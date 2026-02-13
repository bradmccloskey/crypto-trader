"""Stop-loss and trailing stop management."""

from dataclasses import dataclass, field

from src.utils.logger import setup_logger

log = setup_logger("stop-loss")


@dataclass
class StopLossState:
    """Tracks stop-loss state for an open position."""

    product_id: str
    entry_price: float
    stop_loss: float
    take_profit: float
    trailing_activate_pct: float
    trailing_distance_pct: float
    highest_price: float = 0.0
    trailing_active: bool = False
    trailing_stop: float = 0.0

    def __post_init__(self):
        self.highest_price = self.entry_price


class StopLossManager:
    """Manages stop-loss, take-profit, and trailing stops for all positions."""

    def __init__(self, config: dict):
        risk = config.get("risk", {})
        self.stop_loss_pct = risk.get("stop_loss_pct", 0.025)
        self.take_profit_pct = risk.get("take_profit_pct", 0.04)
        self.trailing_activate_pct = risk.get("trailing_stop_activate_pct", 0.03)
        self.trailing_distance_pct = risk.get("trailing_stop_distance_pct", 0.015)

        # product_id → StopLossState
        self._positions: dict[str, StopLossState] = {}

    def register(self, product_id: str, entry_price: float, stop_loss: float, take_profit: float):
        """Register a new position for stop-loss tracking."""
        self._positions[product_id] = StopLossState(
            product_id=product_id,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            trailing_activate_pct=self.trailing_activate_pct,
            trailing_distance_pct=self.trailing_distance_pct,
        )
        log.info(
            f"Registered stop-loss for {product_id}: "
            f"entry=${entry_price:.4f} SL=${stop_loss:.4f} TP=${take_profit:.4f}"
        )

    def unregister(self, product_id: str):
        """Remove a position from tracking."""
        self._positions.pop(product_id, None)

    def check(self, product_id: str, current_price: float) -> str | None:
        """Check if any exit condition is met.

        Returns:
            "stop_loss", "take_profit", "trailing_stop", or None
        """
        state = self._positions.get(product_id)
        if state is None:
            return None

        # Update highest price
        if current_price > state.highest_price:
            state.highest_price = current_price

        # Check take-profit
        if current_price >= state.take_profit:
            log.info(f"{product_id} hit take-profit at ${current_price:.4f} (TP=${state.take_profit:.4f})")
            return "take_profit"

        # Activate trailing stop if gain exceeds threshold
        gain_pct = (current_price - state.entry_price) / state.entry_price
        if not state.trailing_active and gain_pct >= state.trailing_activate_pct:
            state.trailing_active = True
            state.trailing_stop = current_price * (1 - state.trailing_distance_pct)
            log.info(
                f"{product_id} trailing stop activated at ${current_price:.4f} "
                f"(trail=${state.trailing_stop:.4f})"
            )

        # Update trailing stop (ratchet up)
        if state.trailing_active:
            new_trail = state.highest_price * (1 - state.trailing_distance_pct)
            if new_trail > state.trailing_stop:
                state.trailing_stop = new_trail

            if current_price <= state.trailing_stop:
                log.info(
                    f"{product_id} hit trailing stop at ${current_price:.4f} "
                    f"(trail=${state.trailing_stop:.4f})"
                )
                return "trailing_stop"

        # Check fixed stop-loss
        if current_price <= state.stop_loss:
            log.info(f"{product_id} hit stop-loss at ${current_price:.4f} (SL=${state.stop_loss:.4f})")
            return "stop_loss"

        return None

    def get_state(self, product_id: str) -> StopLossState | None:
        return self._positions.get(product_id)

    @property
    def tracked_products(self) -> list[str]:
        return list(self._positions.keys())
