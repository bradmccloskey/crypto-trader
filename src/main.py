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
from src.strategy.grid_strategy import GridStrategy
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

        # Grid strategy
        self.strategy_mode = self.config["bot"].get("strategy", "signal")
        self.grid_strategy = None
        self.grid_capital = 0.0
        self.grid_pnl_total = 0.0

        grid_cfg = self.config.get("grid", {})
        if self.strategy_mode in ("grid", "both") and grid_cfg.get("enabled", False):
            self.grid_strategy = GridStrategy(self.config)
            self.grid_capital = grid_cfg.get("grid_capital_usd", 150.0)
            # Reduce signal capital if running both strategies
            if self.strategy_mode == "both":
                self.portfolio.capital -= self.grid_capital
                self.portfolio.initial_capital -= self.grid_capital
            log.info(f"Grid trading enabled: ${self.grid_capital:.2f} across {grid_cfg.get('pairs', [])}")

        self.trading_pairs = self.config["trading_pairs"]
        self.running = True

        log.info(f"Strategy mode: {self.strategy_mode}")
        log.info(f"Trading pairs: {self.trading_pairs}")
        log.info(f"Protected assets: {self.config.get('protected_assets', [])}")

    def run(self):
        """Start the bot loop."""
        log.info("=" * 60)
        log.info("  CRYPTO TRADING BOT STARTING")
        log.info(f"  Mode: {self.config['bot']['mode']}")
        log.info(f"  Capital: ${self.portfolio.capital:.2f}")
        log.info("=" * 60)

        grid_info = ""
        if self.grid_strategy:
            grid_info = f"\nGrid: ${self.grid_capital:.2f} on {len(self.grid_strategy.pairs)} pairs"
        self.sms.send(
            f"Bot started ({self.config['bot']['mode']} mode, {self.strategy_mode})\n"
            f"Signal capital: ${self.portfolio.capital:.2f}\n"
            f"Pairs: {len(self.trading_pairs)}{grid_info}"
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
        # 1. Signal strategy: check exits and entries
        if self.strategy_mode in ("signal", "both"):
            self._check_exits()
            if not self.risk_mgr.is_paused:
                self._check_entries()

        # 2. Grid strategy: check fills and manage grid
        if self.grid_strategy:
            self._grid_tick()

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

    # ── Grid trading ────────────────────────────────────────────────

    def _grid_tick(self):
        """One iteration of the grid strategy loop."""
        for product_id in self.grid_strategy.pairs:
            try:
                # Check protected assets
                if self.protected.is_protected(product_id):
                    continue

                price = self.market_data.get_current_price(product_id)

                # Initialize grid if not yet created or needs rebalance
                if self.grid_strategy.needs_rebalance(product_id, price):
                    self._grid_rebalance(product_id, price)

                # Place any pending orders
                pending = self.grid_strategy.get_pending_levels(product_id)
                for level in pending:
                    self._grid_place_order(product_id, level)

                # In paper mode, check for simulated fills using recent candle range
                if self.config["bot"]["mode"] == "paper":
                    self._grid_check_paper_fills(product_id, price)

                # In live mode, check order status via API
                else:
                    self._grid_check_live_fills(product_id)

            except Exception as e:
                log.error(f"Grid tick error for {product_id}: {e}")

    def _grid_rebalance(self, product_id: str, current_price: float):
        """Re-center the grid around the current price."""
        preserved_pnl = self.grid_strategy.clear_grid(product_id)
        self.grid_pnl_total += preserved_pnl

        # Cancel existing exchange orders for this pair
        if self.config["bot"]["mode"] != "paper":
            open_orders = self.repo.get_open_grid_orders(product_id)
            order_ids = [o.order_id for o in open_orders if o.order_id]
            if order_ids:
                try:
                    self.client.cancel_orders(order_ids)
                except Exception as e:
                    log.error(f"Failed to cancel grid orders for {product_id}: {e}")
        self.repo.cancel_grid_orders(product_id)

        # Create new grid
        self.grid_strategy.initialize_grid(product_id, current_price)
        log.info(f"Grid rebalanced for {product_id} at ${current_price:.4f}")

    def _grid_place_order(self, product_id: str, level):
        """Place a single grid order."""
        result = None
        if level.side == "BUY":
            result = self.executor.limit_buy(product_id, level.base_size, level.price)
        else:
            result = self.executor.limit_sell(product_id, level.base_size, level.price)

        if result:
            self.grid_strategy.mark_level_open(product_id, level.index, result.order_id)
            self.repo.save_grid_order(
                product_id=product_id,
                side=level.side,
                level_price=level.price,
                base_size=level.base_size,
                order_id=result.order_id,
                grid_center=self.grid_strategy.grids[product_id].center_price,
                level_index=level.index,
                paper=result.paper,
            )

    def _grid_check_paper_fills(self, product_id: str, current_price: float):
        """Check for paper fills using current price as both high and low approximation."""
        # Use current tick price — fills if price crosses a level
        filled = self.grid_strategy.check_fills_paper(
            product_id, current_price, low=current_price, high=current_price
        )

        for level in filled:
            pnl = 0.0
            if level.side == "SELL":
                buy_price = level.price * (1 - self.grid_strategy.spacing_pct)
                pnl = level.base_size * (level.price - buy_price)

            self.repo.fill_grid_order(level.order_id, current_price, pnl)

            # Create the opposite order
            new_level = self.grid_strategy.handle_fill(product_id, level)
            if new_level:
                self._grid_place_order(product_id, new_level)

            # SMS for fills
            self.sms.send(
                f"GRID {level.side} FILLED {product_id}\n"
                f"Price: ${level.price:,.4f}\n"
                f"Size: {level.base_size:.8f}" +
                (f"\nP&L: +${pnl:.4f}" if pnl > 0 else "")
            )

    def _grid_check_live_fills(self, product_id: str):
        """Check live order fills via the Coinbase API."""
        state = self.grid_strategy.grids.get(product_id)
        if not state:
            return

        for idx, level in list(state.levels.items()):
            if level.status != "open" or not level.order_id:
                continue

            try:
                order_info = self.client.get_order(level.order_id)
                status = order_info.get("status", "")

                if status in ("FILLED", "COMPLETED"):
                    level.status = "filled"
                    fill_price = float(order_info.get("average_filled_price", level.price))
                    pnl = 0.0

                    if level.side == "SELL":
                        buy_price = level.price * (1 - self.grid_strategy.spacing_pct)
                        pnl = level.base_size * (fill_price - buy_price)
                        state.total_sells_filled += 1
                    else:
                        state.total_buys_filled += 1

                    self.repo.fill_grid_order(level.order_id, fill_price, pnl)

                    new_level = self.grid_strategy.handle_fill(product_id, level)
                    if new_level:
                        self._grid_place_order(product_id, new_level)

                    self.sms.send(
                        f"GRID {level.side} FILLED {product_id}\n"
                        f"Price: ${fill_price:,.4f}\n"
                        f"Size: {level.base_size:.8f}" +
                        (f"\nP&L: +${pnl:.4f}" if pnl > 0 else "")
                    )

            except Exception as e:
                log.error(f"Grid order check failed for {level.order_id}: {e}")

    def _daily_summary(self):
        """Send daily performance summary."""
        try:
            prices = {}
            for pid in self.portfolio.positions:
                try:
                    prices[pid] = self.market_data.get_current_price(pid)
                except Exception:
                    pass

            summary = self.portfolio.summary(prices)

            # Add grid stats if grid trading is active
            if self.grid_strategy:
                grid_pnl = self.grid_pnl_total
                for pid in self.grid_strategy.pairs:
                    gs = self.grid_strategy.get_grid_summary(pid)
                    if gs:
                        grid_pnl += gs.get("realized_pnl", 0)
                summary["grid_pnl"] = round(grid_pnl, 4)
                summary["grid_pairs"] = len(self.grid_strategy.pairs)

            self.sms.daily_summary(summary)
            self.repo.save_daily_performance(str(date.today()), summary)
            log.info(f"Daily summary: {summary}")
        except Exception as e:
            log.error(f"Daily summary failed: {e}")
            self.sms.error(f"Daily summary save failed: {e}")


def main():
    bot = TradingBot()
    bot.run()


if __name__ == "__main__":
    main()
