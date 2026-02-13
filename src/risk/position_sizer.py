"""Position sizing — enforces 2% max risk per trade."""

from src.utils.logger import setup_logger

log = setup_logger("position-sizer")


class PositionSizer:
    """Calculate position sizes based on risk parameters."""

    def __init__(self, config: dict):
        risk = config.get("risk", {})
        self.max_position_pct = risk.get("max_position_pct", 0.02)

    def calculate(self, capital: float, price: float) -> dict:
        """Determine position size for a trade.

        Args:
            capital: Available trading capital in USD
            price: Current asset price

        Returns:
            dict with usd_amount and base_size
        """
        usd_amount = round(capital * self.max_position_pct, 2)
        base_size = usd_amount / price if price > 0 else 0

        log.debug(
            f"Position size: ${usd_amount:.2f} / ${price:.4f} = {base_size:.8f} "
            f"({self.max_position_pct:.0%} of ${capital:.2f})"
        )
        return {
            "usd_amount": usd_amount,
            "base_size": base_size,
        }
