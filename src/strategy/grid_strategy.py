"""Grid trading strategy — profits from price oscillation in ranging markets.

Places buy orders at fixed intervals below the current price and sell orders above.
When a buy fills, a corresponding sell is placed one level up. When a sell fills,
a corresponding buy is placed one level down. Profits accumulate from the spread
between grid levels.
"""

import time
from dataclasses import dataclass, field

from src.utils.logger import setup_logger

log = setup_logger("grid-strategy")


@dataclass
class GridLevel:
    """A single price level in the grid."""
    index: int          # -N to +N (negative = below center, positive = above)
    price: float        # price at this level
    side: str           # "BUY" or "SELL"
    order_id: str = ""  # exchange/paper order ID
    base_size: float = 0.0
    status: str = "pending"  # pending, open, filled


@dataclass
class GridState:
    """State of a grid for one trading pair."""
    product_id: str
    center_price: float
    levels: dict[int, GridLevel] = field(default_factory=dict)  # index → GridLevel
    total_buys_filled: int = 0
    total_sells_filled: int = 0
    realized_pnl: float = 0.0
    capital_deployed: float = 0.0


class GridStrategy:
    """Manages grid trading across one or more pairs."""

    def __init__(self, config: dict):
        grid_cfg = config.get("grid", {})
        self.num_levels = grid_cfg.get("num_levels", 5)
        self.spacing_pct = grid_cfg.get("grid_spacing_pct", 0.01)
        self.order_size_usd = grid_cfg.get("order_size_usd", 10.0)
        self.rebalance_threshold = grid_cfg.get("rebalance_threshold_pct", 0.05)
        self.grid_capital = grid_cfg.get("grid_capital_usd", 150.0)
        self.pairs = grid_cfg.get("pairs", [])

        self.grids: dict[str, GridState] = {}  # product_id → GridState

    def calculate_grid_levels(self, center_price: float) -> list[tuple[int, float, str]]:
        """Calculate grid levels around a center price.

        Returns:
            List of (index, price, side) tuples.
            Negative indices = buy levels below center.
            Positive indices = sell levels above center.
        """
        levels = []
        for i in range(1, self.num_levels + 1):
            buy_price = center_price * (1 - i * self.spacing_pct)
            sell_price = center_price * (1 + i * self.spacing_pct)
            levels.append((-i, round(buy_price, 6), "BUY"))
            levels.append((i, round(sell_price, 6), "SELL"))
        return sorted(levels, key=lambda x: x[0])

    def initialize_grid(self, product_id: str, current_price: float) -> GridState:
        """Create a new grid centered on the current price."""
        state = GridState(product_id=product_id, center_price=current_price)
        level_list = self.calculate_grid_levels(current_price)

        for idx, price, side in level_list:
            base_size = self.order_size_usd / price
            state.levels[idx] = GridLevel(
                index=idx,
                price=price,
                side=side,
                base_size=base_size,
            )

        self.grids[product_id] = state
        log.info(
            f"Grid initialized for {product_id}: center=${current_price:.4f}, "
            f"{len(state.levels)} levels, spacing={self.spacing_pct:.1%}"
        )
        return state

    def needs_rebalance(self, product_id: str, current_price: float) -> bool:
        """Check if the grid needs to be re-centered around the current price."""
        state = self.grids.get(product_id)
        if not state:
            return True
        drift = abs(current_price - state.center_price) / state.center_price
        return drift >= self.rebalance_threshold

    def check_fills_paper(self, product_id: str, current_price: float,
                          low: float, high: float) -> list[GridLevel]:
        """Check which grid orders would have filled given the price range (paper mode).

        In paper mode, a buy fills if low <= level_price, a sell fills if high >= level_price.

        Returns:
            List of GridLevels that filled.
        """
        state = self.grids.get(product_id)
        if not state:
            return []

        filled = []
        for idx, level in list(state.levels.items()):
            if level.status != "open":
                continue

            if level.side == "BUY" and low <= level.price:
                level.status = "filled"
                state.total_buys_filled += 1
                filled.append(level)

            elif level.side == "SELL" and high >= level.price:
                level.status = "filled"
                state.total_sells_filled += 1
                filled.append(level)

        return filled

    def handle_fill(self, product_id: str, filled_level: GridLevel) -> GridLevel | None:
        """After a fill, create the corresponding opposite order.

        Buy fill → place sell one level up (at buy_price * (1 + spacing))
        Sell fill → place buy one level down (at sell_price * (1 - spacing))

        Returns:
            The new GridLevel to place, or None if out of bounds.
        """
        state = self.grids.get(product_id)
        if not state:
            return None

        if filled_level.side == "BUY":
            # Buy filled → place sell at the next level up
            sell_price = filled_level.price * (1 + self.spacing_pct)
            pnl = filled_level.base_size * (sell_price - filled_level.price)
            new_level = GridLevel(
                index=filled_level.index,
                price=round(sell_price, 6),
                side="SELL",
                base_size=filled_level.base_size,
            )
            state.levels[filled_level.index] = new_level
            log.info(
                f"Grid {product_id}: BUY filled @ ${filled_level.price:.4f} → "
                f"placing SELL @ ${sell_price:.4f} (potential P&L: ${pnl:.4f})"
            )
            return new_level

        elif filled_level.side == "SELL":
            # Sell filled → calculate P&L and place buy back at original level
            buy_price = filled_level.price * (1 - self.spacing_pct)
            pnl = filled_level.base_size * (filled_level.price - buy_price)
            state.realized_pnl += pnl
            new_level = GridLevel(
                index=filled_level.index,
                price=round(buy_price, 6),
                side="BUY",
                base_size=self.order_size_usd / buy_price,
            )
            state.levels[filled_level.index] = new_level
            log.info(
                f"Grid {product_id}: SELL filled @ ${filled_level.price:.4f} → "
                f"placing BUY @ ${buy_price:.4f} (P&L: +${pnl:.4f})"
            )
            return new_level

        return None

    def get_pending_levels(self, product_id: str) -> list[GridLevel]:
        """Get all levels that need orders placed."""
        state = self.grids.get(product_id)
        if not state:
            return []
        return [l for l in state.levels.values() if l.status == "pending"]

    def mark_level_open(self, product_id: str, level_index: int, order_id: str):
        """Mark a level as having an active order."""
        state = self.grids.get(product_id)
        if state and level_index in state.levels:
            state.levels[level_index].order_id = order_id
            state.levels[level_index].status = "open"

    def get_grid_summary(self, product_id: str) -> dict:
        """Return a summary of grid state for a pair."""
        state = self.grids.get(product_id)
        if not state:
            return {}

        open_buys = sum(1 for l in state.levels.values() if l.side == "BUY" and l.status == "open")
        open_sells = sum(1 for l in state.levels.values() if l.side == "SELL" and l.status == "open")

        return {
            "product_id": product_id,
            "center_price": state.center_price,
            "open_buys": open_buys,
            "open_sells": open_sells,
            "total_buys_filled": state.total_buys_filled,
            "total_sells_filled": state.total_sells_filled,
            "realized_pnl": round(state.realized_pnl, 4),
        }

    def clear_grid(self, product_id: str):
        """Remove a grid (e.g. before rebalancing)."""
        if product_id in self.grids:
            state = self.grids[product_id]
            log.info(
                f"Clearing grid for {product_id}: "
                f"P&L=${state.realized_pnl:.4f}, "
                f"fills={state.total_buys_filled}B/{state.total_sells_filled}S"
            )
            # Preserve P&L across rebalances
            return state.realized_pnl
        return 0.0

    def max_capital_required(self) -> float:
        """Calculate maximum capital needed if all buy levels fill."""
        return self.num_levels * self.order_size_usd * len(self.pairs)
