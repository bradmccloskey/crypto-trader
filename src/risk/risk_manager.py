"""Pre-trade safety checks and daily loss limits."""

from datetime import date

from src.portfolio.protected_assets import ProtectedAssets
from src.utils.logger import setup_logger

log = setup_logger("risk-manager")


class RiskManager:
    """Enforces all risk rules before any trade is placed."""

    def __init__(self, config: dict, protected_assets: ProtectedAssets):
        risk = config.get("risk", {})
        self.max_open_positions = risk.get("max_open_positions", 3)
        self.daily_loss_limit_pct = risk.get("daily_loss_limit_pct", 0.05)
        self.daily_loss_limit_usd = risk.get("daily_loss_limit_usd", 15.0)
        self.protected = protected_assets
        self.capital = config.get("capital", {}).get("initial_usd", 300.0)

        # Daily tracking
        self._today = date.today()
        self._daily_loss = 0.0
        self._trading_paused = False

    def _reset_if_new_day(self):
        today = date.today()
        if today != self._today:
            log.info(f"New trading day: resetting daily loss (was ${self._daily_loss:.2f})")
            self._today = today
            self._daily_loss = 0.0
            self._trading_paused = False

    def record_loss(self, loss_usd: float):
        """Record a realized loss. Positive number = loss amount."""
        self._reset_if_new_day()
        self._daily_loss += abs(loss_usd)
        pct_loss = self._daily_loss / self.capital if self.capital > 0 else 0

        if self._daily_loss >= self.daily_loss_limit_usd or pct_loss >= self.daily_loss_limit_pct:
            self._trading_paused = True
            log.warning(
                f"DAILY LOSS LIMIT HIT: ${self._daily_loss:.2f} "
                f"({pct_loss:.1%}) — trading paused"
            )

    def can_trade(self, product_id: str, open_position_count: int) -> tuple[bool, str]:
        """Check if a new trade is allowed.

        Returns:
            (allowed, reason) — reason is empty string if allowed
        """
        self._reset_if_new_day()

        # Protected asset check
        if self.protected.is_protected(product_id):
            return False, f"{product_id} is a protected asset"

        # Daily loss check
        if self._trading_paused:
            return False, f"Trading paused: daily loss ${self._daily_loss:.2f}"

        # Position limit
        if open_position_count >= self.max_open_positions:
            return False, f"Max positions reached ({self.max_open_positions})"

        return True, ""

    @property
    def daily_loss(self) -> float:
        self._reset_if_new_day()
        return self._daily_loss

    @property
    def is_paused(self) -> bool:
        self._reset_if_new_day()
        return self._trading_paused
