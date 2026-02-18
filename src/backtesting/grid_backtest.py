"""Grid strategy backtester — simulate grid trading on historical OHLCV data."""

from dataclasses import dataclass, field

import pandas as pd

from src.strategy.grid_strategy import GridStrategy
from src.utils.logger import setup_logger

log = setup_logger("grid-backtest")


@dataclass
class GridBacktestTrade:
    product_id: str
    side: str
    price: float
    size: float
    pnl: float
    candle_idx: int


@dataclass
class GridBacktestResult:
    trades: list[GridBacktestTrade] = field(default_factory=list)
    total_pnl: float = 0.0
    total_buys: int = 0
    total_sells: int = 0
    grid_capital: float = 0.0
    return_pct: float = 0.0
    max_deployed: float = 0.0
    num_rebalances: int = 0


class GridBacktestEngine:
    """Simulate grid trading on historical candle data."""

    def __init__(self, config: dict):
        self.config = config
        self.grid = GridStrategy(config)

    def run(self, data: dict[str, pd.DataFrame]) -> GridBacktestResult:
        """Run grid backtest across multiple products.

        Args:
            data: dict of product_id → DataFrame with OHLCV columns.

        Returns:
            GridBacktestResult with trade list and stats.
        """
        grid_cfg = self.config.get("grid", {})
        grid_capital = grid_cfg.get("grid_capital_usd", 150.0)
        pairs = grid_cfg.get("pairs", list(data.keys()))

        # Filter to pairs we have data for
        pairs = [p for p in pairs if p in data]
        if not pairs:
            log.warning("No grid pairs have historical data")
            return GridBacktestResult(grid_capital=grid_capital)

        trades: list[GridBacktestTrade] = []
        total_pnl = 0.0
        total_buys = 0
        total_sells = 0
        max_deployed = 0.0
        deployed = 0.0
        num_rebalances = 0

        min_len = min(len(data[p]) for p in pairs)
        if min_len < 2:
            return GridBacktestResult(grid_capital=grid_capital)

        for i in range(min_len):
            for pid in pairs:
                df = data[pid]
                close = df.iloc[i]["close"]
                high = df.iloc[i]["high"]
                low = df.iloc[i]["low"]

                # Initialize or rebalance grid
                if self.grid.needs_rebalance(pid, close):
                    preserved = self.grid.clear_grid(pid)
                    total_pnl += preserved
                    self.grid.initialize_grid(pid, close)
                    num_rebalances += 1

                    # Mark all levels as open
                    for level in self.grid.get_pending_levels(pid):
                        self.grid.mark_level_open(pid, level.index, f"bt-{i}-{level.index}")

                # Check for fills using candle high/low
                filled = self.grid.check_fills_paper(pid, close, low, high)

                for level in filled:
                    pnl = 0.0
                    if level.side == "BUY":
                        deployed += level.base_size * level.price
                        total_buys += 1
                    elif level.side == "SELL":
                        buy_price = level.price * (1 - self.grid.spacing_pct)
                        pnl = level.base_size * (level.price - buy_price)
                        total_pnl += pnl
                        deployed -= level.base_size * buy_price
                        total_sells += 1

                    trades.append(GridBacktestTrade(
                        product_id=pid,
                        side=level.side,
                        price=level.price,
                        size=level.base_size,
                        pnl=pnl,
                        candle_idx=i,
                    ))

                    # Place the opposite order
                    new_level = self.grid.handle_fill(pid, level)
                    if new_level:
                        self.grid.mark_level_open(pid, new_level.index, f"bt-{i}-{new_level.index}")

                if deployed > max_deployed:
                    max_deployed = deployed

        return_pct = (total_pnl / grid_capital * 100) if grid_capital > 0 else 0

        return GridBacktestResult(
            trades=trades,
            total_pnl=round(total_pnl, 4),
            total_buys=total_buys,
            total_sells=total_sells,
            grid_capital=grid_capital,
            return_pct=round(return_pct, 2),
            max_deployed=round(max_deployed, 2),
            num_rebalances=num_rebalances,
        )
