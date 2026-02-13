"""Backtest engine — simulate strategy on historical data."""

import time
from dataclasses import dataclass, field

import pandas as pd

from src.strategy.indicators import add_all_indicators
from src.strategy.signal_generator import SignalGenerator, SignalType
from src.utils.logger import setup_logger

log = setup_logger("backtest")


@dataclass
class BacktestPosition:
    product_id: str
    entry_price: float
    size: float
    usd_cost: float
    stop_loss: float
    take_profit: float
    entry_idx: int = 0
    highest_price: float = 0.0
    trailing_active: bool = False
    trailing_stop: float = 0.0


@dataclass
class BacktestTrade:
    product_id: str
    entry_price: float
    exit_price: float
    size: float
    usd_cost: float
    usd_return: float
    pnl: float
    pnl_pct: float
    exit_reason: str
    entry_idx: int
    exit_idx: int


@dataclass
class BacktestResult:
    trades: list[BacktestTrade] = field(default_factory=list)
    starting_capital: float = 0.0
    ending_capital: float = 0.0
    total_return_pct: float = 0.0
    win_count: int = 0
    loss_count: int = 0
    win_rate: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe_ratio: float = 0.0
    profit_factor: float = 0.0
    total_pnl: float = 0.0


class BacktestEngine:
    """Run strategy on historical data and measure performance."""

    def __init__(self, config: dict):
        self.config = config
        self.signal_gen = SignalGenerator(config)
        risk = config.get("risk", {})
        self.max_position_pct = risk.get("max_position_pct", 0.02)
        self.max_open = risk.get("max_open_positions", 3)
        self.stop_loss_pct = risk.get("stop_loss_pct", 0.025)
        self.take_profit_pct = risk.get("take_profit_pct", 0.04)
        self.trailing_activate = risk.get("trailing_stop_activate_pct", 0.03)
        self.trailing_distance = risk.get("trailing_stop_distance_pct", 0.015)

    def run(self, data: dict[str, pd.DataFrame]) -> BacktestResult:
        """Run backtest across multiple products.

        Args:
            data: dict of product_id → DataFrame with OHLCV columns.
                  All DataFrames should cover the same time range.

        Returns:
            BacktestResult with trade list and performance metrics.
        """
        capital = self.config.get("capital", {}).get("initial_usd", 300.0)
        starting_capital = capital
        positions: dict[str, BacktestPosition] = {}
        trades: list[BacktestTrade] = []
        equity_curve = [capital]

        # Add indicators to all datasets
        enriched = {}
        for pid, df in data.items():
            df = df.copy()
            df = add_all_indicators(df, self.config)
            enriched[pid] = df

        # Find common index range
        min_len = min(len(df) for df in enriched.values())
        if min_len < 30:
            log.warning("Insufficient data for backtest")
            return BacktestResult(starting_capital=starting_capital, ending_capital=capital)

        # Walk forward through candles
        for i in range(30, min_len):
            # Check exits first
            for pid in list(positions.keys()):
                pos = positions[pid]
                df = enriched[pid]
                current_price = df.iloc[i]["close"]
                high = df.iloc[i]["high"]
                low = df.iloc[i]["low"]

                # Update highest price
                if high > pos.highest_price:
                    pos.highest_price = high

                exit_reason = None

                # Take-profit
                if high >= pos.take_profit:
                    exit_reason = "take_profit"
                    exit_price = pos.take_profit

                # Trailing stop logic
                gain_pct = (pos.highest_price - pos.entry_price) / pos.entry_price
                if not pos.trailing_active and gain_pct >= self.trailing_activate:
                    pos.trailing_active = True
                    pos.trailing_stop = pos.highest_price * (1 - self.trailing_distance)

                if pos.trailing_active:
                    new_trail = pos.highest_price * (1 - self.trailing_distance)
                    if new_trail > pos.trailing_stop:
                        pos.trailing_stop = new_trail
                    if low <= pos.trailing_stop and exit_reason is None:
                        exit_reason = "trailing_stop"
                        exit_price = pos.trailing_stop

                # Stop-loss
                if low <= pos.stop_loss and exit_reason is None:
                    exit_reason = "stop_loss"
                    exit_price = pos.stop_loss

                if exit_reason:
                    usd_return = pos.size * exit_price
                    pnl = usd_return - pos.usd_cost
                    trade = BacktestTrade(
                        product_id=pid,
                        entry_price=pos.entry_price,
                        exit_price=exit_price,
                        size=pos.size,
                        usd_cost=pos.usd_cost,
                        usd_return=usd_return,
                        pnl=pnl,
                        pnl_pct=pnl / pos.usd_cost if pos.usd_cost else 0,
                        exit_reason=exit_reason,
                        entry_idx=pos.entry_idx,
                        exit_idx=i,
                    )
                    trades.append(trade)
                    capital += usd_return
                    del positions[pid]

            # Check for new entry signals
            for pid, df in enriched.items():
                if pid in positions:
                    continue
                if len(positions) >= self.max_open:
                    break

                window = df.iloc[:i + 1]
                signal = self.signal_gen.generate(window, pid)

                if signal.signal_type == SignalType.BUY:
                    usd_amount = capital * self.max_position_pct
                    if usd_amount < 1.0:
                        continue
                    price = df.iloc[i]["close"]
                    size = usd_amount / price
                    capital -= usd_amount

                    positions[pid] = BacktestPosition(
                        product_id=pid,
                        entry_price=price,
                        size=size,
                        usd_cost=usd_amount,
                        stop_loss=signal.stop_loss,
                        take_profit=signal.take_profit,
                        entry_idx=i,
                        highest_price=price,
                    )

            # Track equity
            unrealized = sum(
                pos.size * enriched[pid].iloc[i]["close"] - pos.usd_cost
                for pid, pos in positions.items()
            )
            equity_curve.append(capital + unrealized +
                                sum(pos.usd_cost for pos in positions.values()))

        # Close remaining positions at last price
        for pid, pos in list(positions.items()):
            last_price = enriched[pid].iloc[min_len - 1]["close"]
            usd_return = pos.size * last_price
            pnl = usd_return - pos.usd_cost
            trades.append(BacktestTrade(
                product_id=pid,
                entry_price=pos.entry_price,
                exit_price=last_price,
                size=pos.size,
                usd_cost=pos.usd_cost,
                usd_return=usd_return,
                pnl=pnl,
                pnl_pct=pnl / pos.usd_cost if pos.usd_cost else 0,
                exit_reason="end_of_data",
                entry_idx=pos.entry_idx,
                exit_idx=min_len - 1,
            ))
            capital += usd_return

        return self._calc_metrics(trades, starting_capital, capital, equity_curve)

    def _calc_metrics(self, trades, starting_capital, ending_capital, equity_curve) -> BacktestResult:
        if not trades:
            return BacktestResult(
                starting_capital=starting_capital,
                ending_capital=ending_capital,
            )

        wins = [t for t in trades if t.pnl > 0]
        losses = [t for t in trades if t.pnl <= 0]

        # Max drawdown
        peak = equity_curve[0]
        max_dd = 0
        for eq in equity_curve:
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd

        # Sharpe ratio (simplified — daily returns)
        returns = []
        for i in range(1, len(equity_curve)):
            r = (equity_curve[i] - equity_curve[i - 1]) / equity_curve[i - 1] if equity_curve[i - 1] else 0
            returns.append(r)

        import numpy as np
        returns_arr = np.array(returns)
        mean_r = returns_arr.mean() if len(returns_arr) else 0
        std_r = returns_arr.std() if len(returns_arr) else 1
        sharpe = (mean_r / std_r * (252 ** 0.5)) if std_r > 0 else 0

        # Profit factor
        gross_profit = sum(t.pnl for t in wins)
        gross_loss = abs(sum(t.pnl for t in losses))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        return BacktestResult(
            trades=trades,
            starting_capital=starting_capital,
            ending_capital=round(ending_capital, 2),
            total_return_pct=round((ending_capital - starting_capital) / starting_capital * 100, 2),
            win_count=len(wins),
            loss_count=len(losses),
            win_rate=round(len(wins) / len(trades), 2) if trades else 0,
            avg_win=round(sum(t.pnl for t in wins) / len(wins), 2) if wins else 0,
            avg_loss=round(sum(t.pnl for t in losses) / len(losses), 2) if losses else 0,
            max_drawdown_pct=round(max_dd * 100, 2),
            sharpe_ratio=round(sharpe, 2),
            profit_factor=round(profit_factor, 2),
            total_pnl=round(sum(t.pnl for t in trades), 2),
        )
