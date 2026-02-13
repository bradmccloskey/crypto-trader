"""Guard against trading protected assets (SHIB, BTC)."""

from src.utils.logger import setup_logger

log = setup_logger("protected-assets")


class ProtectedAssetError(Exception):
    """Raised when an operation would affect a protected asset."""


class ProtectedAssets:
    """Prevents any trading of protected assets."""

    def __init__(self, config: dict):
        self.protected = set(
            s.upper() for s in config.get("protected_assets", ["SHIB", "BTC"])
        )
        log.info(f"Protected assets: {self.protected}")

    def check(self, product_id: str) -> None:
        """Raise ProtectedAssetError if product_id involves a protected asset.

        Args:
            product_id: e.g. "ETH-USD", "SHIB-USD", "BTC-USD"
        """
        base = product_id.split("-")[0].upper()
        if base in self.protected:
            raise ProtectedAssetError(
                f"BLOCKED: {product_id} involves protected asset {base}"
            )

    def is_protected(self, product_id: str) -> bool:
        base = product_id.split("-")[0].upper()
        return base in self.protected
