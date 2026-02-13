"""Position tracking and P&L management."""

import time
from dataclasses import dataclass, field

from src.utils.logger import setup_logger

log = setup_logger("portfolio")


@dataclass
class Position:
    product_id: str
    side: str  # "BUY"
    entry_price: float
    size: float  # base asset amount
    usd_cost: float
    stop_loss: float
    take_profit: float
    entry_time: float = field(default_factory=time.time)
    order_id: str = ""


@dataclass
class ClosedTrade:
    product_id: str
    entry_price: float
    exit_price: float
    size: float
    usd_cost: float
    usd_return: float
    pnl: float
    pnl_pct: float
    exit_reason: str  # stop_loss, take_profit, trailing_stop, signal
    entry_time: float = 0
    exit_time: float = field(default_factory=time.time)


class PortfolioManager:
    """Track open positions and closed trade history."""

    def __init__(self, config: dict):
        self.initial_capital = config.get("capital", {}).get("initial_usd", 300.0)
        self.capital = self.initial_capital
        self.positions: dict[str, Position] = {}  # product_id → Position
        self.closed_trades: list[ClosedTrade] = []

    def open_position(
        self,
        product_id: str,
        entry_price: float,
        size: float,
        usd_cost: float,
        stop_loss: float,
        take_profit: float,
        order_id: str = "",
    ) -> Position:
        """Record a new open position."""
        pos = Position(
            product_id=product_id,
            side="BUY",
            entry_price=entry_price,
            size=size,
            usd_cost=usd_cost,
            stop_loss=stop_loss,
            take_profit=take_profit,
            order_id=order_id,
        )
        self.positions[product_id] = pos
        self.capital -= usd_cost
        log.info(
            f"Opened {product_id}: {size:.8f} @ ${entry_price:.4f} "
            f"(${usd_cost:.2f}) Capital: ${self.capital:.2f}"
        )
        return pos

    def close_position(self, product_id: str, exit_price: float, exit_reason: str) -> ClosedTrade | None:
        """Close a position and record P&L."""
        pos = self.positions.pop(product_id, None)
        if pos is None:
            log.warning(f"No open position for {product_id}")
            return None

        usd_return = pos.size * exit_price
        pnl = usd_return - pos.usd_cost
        pnl_pct = pnl / pos.usd_cost if pos.usd_cost > 0 else 0

        trade = ClosedTrade(
            product_id=product_id,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            size=pos.size,
            usd_cost=pos.usd_cost,
            usd_return=usd_return,
            pnl=pnl,
            pnl_pct=pnl_pct,
            exit_reason=exit_reason,
            entry_time=pos.entry_time,
        )
        self.closed_trades.append(trade)
        self.capital += usd_return

        emoji = "+" if pnl >= 0 else ""
        log.info(
            f"Closed {product_id} ({exit_reason}): "
            f"${pos.entry_price:.4f} → ${exit_price:.4f} "
            f"P&L: {emoji}${pnl:.2f} ({pnl_pct:+.1%}) Capital: ${self.capital:.2f}"
        )
        return trade

    @property
    def open_position_count(self) -> int:
        return len(self.positions)

    @property
    def total_pnl(self) -> float:
        return sum(t.pnl for t in self.closed_trades)

    @property
    def win_count(self) -> int:
        return sum(1 for t in self.closed_trades if t.pnl > 0)

    @property
    def loss_count(self) -> int:
        return sum(1 for t in self.closed_trades if t.pnl <= 0)

    def unrealized_pnl(self, prices: dict[str, float]) -> float:
        """Calculate unrealized P&L across all open positions."""
        total = 0.0
        for pid, pos in self.positions.items():
            price = prices.get(pid, pos.entry_price)
            total += (price * pos.size) - pos.usd_cost
        return total

    def summary(self, prices: dict[str, float] | None = None) -> dict:
        """Return a portfolio summary dict."""
        return {
            "capital": round(self.capital, 2),
            "open_positions": self.open_position_count,
            "total_trades": len(self.closed_trades),
            "wins": self.win_count,
            "losses": self.loss_count,
            "realized_pnl": round(self.total_pnl, 2),
            "unrealized_pnl": round(self.unrealized_pnl(prices or {}), 2),
            "win_rate": round(self.win_count / max(len(self.closed_trades), 1), 2),
        }
