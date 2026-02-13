"""Crypto trading bot — main entry point and loop."""

import os
import sys
import time
import traceback
from datetime import date, datetime

import schedule
import yaml
from dotenv import load_dotenv

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.api.coinbase_client import CoinbaseClient
from src.api.market_data import MarketData
from src.api.order_executor import OrderExecutor
from src.database.models import init_db
from src.database.repository import Repository
from src.notifications.sms_notifier import SMSNotifier
from src.portfolio.portfolio_manager import PortfolioManager
from src.portfolio.protected_assets import ProtectedAssets
from src.risk.position_sizer import PositionSizer
from src.risk.risk_manager import RiskManager
from src.risk.stop_loss import StopLossManager
from src.strategy.indicators import add_all_indicators
from src.strategy.signal_generator import SignalGenerator, SignalType
from src.utils.logger import setup_logger

log = setup_logger("main")


class TradingBot:
    """Main trading bot orchestrator."""

    def __init__(self, config_path: str = "config/config.yaml"):
        load_dotenv()

        with open(config_path) as f:
            self.config = yaml.safe_load(f)

        mode = os.getenv("BOT_MODE", self.config["bot"]["mode"])
        self.config["bot"]["mode"] = mode
        log.info(f"Bot mode: {mode}")

        # Core components
        self.client = CoinbaseClient()
        self.market_data = MarketData(self.client, self.config)
        self.executor = OrderExecutor(self.client, mode=mode)
        self.signal_gen = SignalGenerator(self.config)
        self.position_sizer = PositionSizer(self.config)
        self.protected = ProtectedAssets(self.config)
        self.risk_mgr = RiskManager(self.config, self.protected)
        self.stop_loss_mgr = StopLossManager(self.config)
        self.portfolio = PortfolioManager(self.config)
        self.sms = SMSNotifier()

        # Database
        db_path = self.config["data"]["db_path"]
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        _, Session = init_db(db_path)
        self.repo = Repository(Session)

        self.trading_pairs = self.config["trading_pairs"]
        self.running = True

        log.info(f"Trading pairs: {self.trading_pairs}")
        log.info(f"Protected assets: {self.config.get('protected_assets', [])}")

    def run(self):
        """Start the bot loop."""
        log.info("=" * 60)
        log.info("  CRYPTO TRADING BOT STARTING")
        log.info(f"  Mode: {self.config['bot']['mode']}")
        log.info(f"  Capital: ${self.portfolio.capital:.2f}")
        log.info("=" * 60)

        self.sms.send(
            f"Bot started ({self.config['bot']['mode']} mode)\n"
            f"Capital: ${self.portfolio.capital:.2f}\n"
            f"Pairs: {len(self.trading_pairs)}"
        )

        # Schedule daily summary
        summary_hour = self.config["bot"].get("daily_summary_hour", 20)
        schedule.every().day.at(f"{summary_hour:02d}:00").do(self._daily_summary)

        interval = self.config["bot"]["loop_interval_seconds"]
        log.info(f"Loop interval: {interval}s")

        while self.running:
            try:
                self._tick()
                schedule.run_pending()
                time.sleep(interval)
            except KeyboardInterrupt:
                log.info("Shutting down (keyboard interrupt)")
                self.running = False
            except Exception as e:
                log.error(f"Tick error: {e}\n{traceback.format_exc()}")
                self.sms.error(str(e))
                time.sleep(interval * 2)  # back off on errors

        log.info("Bot stopped")

    def _tick(self):
        """One iteration of the main loop."""
        # 1. Check stop-losses on open positions
        self._check_exits()

        # 2. Look for new entry signals
        if not self.risk_mgr.is_paused:
            self._check_entries()

    def _check_exits(self):
        """Check all open positions for exit conditions."""
        for product_id in list(self.portfolio.positions.keys()):
            try:
                price = self.market_data.get_current_price(product_id)
                exit_reason = self.stop_loss_mgr.check(product_id, price)

                if exit_reason:
                    self._close_position(product_id, price, exit_reason)
            except Exception as e:
                log.error(f"Exit check error for {product_id}: {e}")

    def _check_entries(self):
        """Scan trading pairs for entry signals."""
        granularity = self.config["strategy"]["candle_granularity"]
        lookback = self.config["strategy"]["lookback_candles"]

        for product_id in self.trading_pairs:
            if product_id in self.portfolio.positions:
                continue

            try:
                # Risk check
                allowed, reason = self.risk_mgr.can_trade(
                    product_id, self.portfolio.open_position_count
                )
                if not allowed:
                    continue

                # Fetch data and calculate indicators
                df = self.market_data.get_candles(
                    product_id, granularity=granularity, num_candles=lookback
                )
                if len(df) < 30:
                    continue

                df = add_all_indicators(df, self.config)
                signal = self.signal_gen.generate(df, product_id)

                # Log all non-HOLD signals
                if signal.signal_type != SignalType.HOLD:
                    self.repo.save_signal(signal)
                    log.info(
                        f"Signal: {signal.signal_type.value} {product_id} "
                        f"@ ${signal.price:.4f} confidence={signal.confidence:.2f} "
                        f"reasons={signal.reasons}"
                    )

                # Act on BUY signals
                if signal.signal_type == SignalType.BUY:
                    self._open_position(product_id, signal)

            except Exception as e:
                log.error(f"Entry check error for {product_id}: {e}")

    def _open_position(self, product_id, signal):
        """Execute a buy order and register position."""
        sizing = self.position_sizer.calculate(self.portfolio.capital, signal.price)
        usd_amount = sizing["usd_amount"]

        if usd_amount < 1.0:
            log.warning(f"Position too small for {product_id}: ${usd_amount:.2f}")
            return

        result = self.executor.buy(product_id, usd_amount, signal.price)

        if result.filled:
            self.portfolio.open_position(
                product_id=product_id,
                entry_price=result.price,
                size=result.size,
                usd_cost=usd_amount,
                stop_loss=signal.stop_loss,
                take_profit=signal.take_profit,
                order_id=result.order_id,
            )
            self.stop_loss_mgr.register(
                product_id, result.price, signal.stop_loss, signal.take_profit
            )
            self.repo.save_trade_open(
                product_id=product_id,
                entry_price=result.price,
                size=result.size,
                usd_cost=usd_amount,
                stop_loss=signal.stop_loss,
                take_profit=signal.take_profit,
                order_id=result.order_id,
                paper=result.paper,
            )
            self.repo.save_signal(signal, acted_on=True)

            self.sms.trade_opened(
                product_id, result.price, result.size,
                usd_amount, signal.stop_loss, signal.take_profit,
            )

    def _close_position(self, product_id, price, exit_reason):
        """Execute a sell order and record the close."""
        pos = self.portfolio.positions.get(product_id)
        if not pos:
            return

        result = self.executor.sell(product_id, pos.size, price)

        if result.filled:
            closed = self.portfolio.close_position(product_id, price, exit_reason)
            self.stop_loss_mgr.unregister(product_id)

            if closed:
                self.repo.save_trade_close(product_id, closed)

                if closed.pnl < 0:
                    self.risk_mgr.record_loss(abs(closed.pnl))
                    if self.risk_mgr.is_paused:
                        self.sms.daily_limit_hit(self.risk_mgr.daily_loss)

                self.sms.trade_closed(
                    product_id, closed.pnl, closed.pnl_pct, exit_reason
                )

    def _daily_summary(self):
        """Send daily performance summary."""
        prices = {}
        for pid in self.portfolio.positions:
            try:
                prices[pid] = self.market_data.get_current_price(pid)
            except Exception:
                pass

        summary = self.portfolio.summary(prices)
        self.sms.daily_summary(summary)
        self.repo.save_daily_performance(str(date.today()), summary)
        log.info(f"Daily summary: {summary}")


def main():
    bot = TradingBot()
    bot.run()


if __name__ == "__main__":
    main()
