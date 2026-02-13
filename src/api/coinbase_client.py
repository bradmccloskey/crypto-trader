"""Coinbase Advanced Trade API wrapper."""

import os
from decimal import Decimal, ROUND_DOWN

from coinbase.rest import RESTClient
from dotenv import load_dotenv

from src.utils.logger import setup_logger

log = setup_logger("coinbase-client")


class CoinbaseClient:
    """Thin wrapper around the Coinbase Advanced Trade REST client."""

    def __init__(self):
        load_dotenv()
        api_key = os.getenv("COINBASE_API_KEY")
        api_secret = os.getenv("COINBASE_API_SECRET")
        if not api_key or not api_secret:
            raise RuntimeError("COINBASE_API_KEY and COINBASE_API_SECRET must be set in .env")
        self.client = RESTClient(api_key=api_key, api_secret=api_secret)
        self._product_cache: dict[str, dict] = {}
        log.info("Coinbase client initialized")

    # ── Account helpers ──────────────────────────────────────────────

    def list_accounts(self) -> list[dict]:
        """Return all accounts with non-zero balances."""
        resp = self.client.get_accounts(limit=250)
        accounts = resp.get("accounts", resp) if isinstance(resp, dict) else resp.accounts
        results = []
        for acct in accounts:
            if isinstance(acct, dict):
                bal = float(acct.get("available_balance", {}).get("value", 0))
                currency = acct.get("available_balance", {}).get("currency", "")
                name = acct.get("name", "")
                uuid = acct.get("uuid", "")
            else:
                bal = float(acct.available_balance.get("value", 0))
                currency = acct.available_balance.get("currency", "")
                name = acct.name
                uuid = acct.uuid
            if bal > 0:
                results.append({
                    "uuid": uuid,
                    "name": name,
                    "currency": currency,
                    "balance": bal,
                })
        return results

    def get_usd_balance(self) -> float:
        """Return available USD balance."""
        for acct in self.list_accounts():
            if acct["currency"] == "USD":
                return acct["balance"]
        return 0.0

    # ── Market data ──────────────────────────────────────────────────

    def get_candles(self, product_id: str, start: int, end: int, granularity: str) -> list[dict]:
        """Fetch OHLCV candles for a product.

        Args:
            product_id: e.g. "ETH-USD"
            start: Unix timestamp (seconds)
            end: Unix timestamp (seconds)
            granularity: e.g. "ONE_HOUR", "ONE_DAY"

        Returns:
            List of dicts with keys: start, low, high, open, close, volume
        """
        resp = self.client.get_candles(
            product_id=product_id,
            start=str(start),
            end=str(end),
            granularity=granularity,
        )
        candles = resp.get("candles", resp) if isinstance(resp, dict) else resp.candles
        return [
            {
                "start": int(c["start"]) if isinstance(c, dict) else int(c.start),
                "low": float(c["low"]) if isinstance(c, dict) else float(c.low),
                "high": float(c["high"]) if isinstance(c, dict) else float(c.high),
                "open": float(c["open"]) if isinstance(c, dict) else float(c.open),
                "close": float(c["close"]) if isinstance(c, dict) else float(c.close),
                "volume": float(c["volume"]) if isinstance(c, dict) else float(c.volume),
            }
            for c in candles
        ]

    def get_product(self, product_id: str) -> dict:
        """Get current price and product info (cached for precision data)."""
        resp = self.client.get_product(product_id=product_id)
        data = resp if isinstance(resp, dict) else resp.__dict__
        self._product_cache[product_id] = data
        return data

    def truncate_base_size(self, product_id: str, size: float) -> str:
        """Truncate a base size to the product's allowed precision.

        Fetches product info if not already cached.
        Returns the size as a correctly-formatted string.
        """
        if product_id not in self._product_cache:
            self.get_product(product_id)
        product = self._product_cache[product_id]
        base_increment = Decimal(str(product.get("base_increment", "0.00000001")))
        size_dec = Decimal(str(size))
        truncated = (size_dec / base_increment).to_integral_value(rounding=ROUND_DOWN) * base_increment
        return str(truncated)

    def truncate_quote_size(self, product_id: str, amount: float) -> str:
        """Truncate a quote (USD) amount to the product's allowed precision."""
        if product_id not in self._product_cache:
            self.get_product(product_id)
        product = self._product_cache[product_id]
        quote_increment = Decimal(str(product.get("quote_increment", "0.01")))
        amount_dec = Decimal(str(amount))
        truncated = (amount_dec / quote_increment).to_integral_value(rounding=ROUND_DOWN) * quote_increment
        return str(truncated)

    # ── Orders ───────────────────────────────────────────────────────

    def place_market_buy(self, product_id: str, quote_size: str) -> dict:
        """Place a market buy order using USD amount.

        Args:
            product_id: e.g. "ETH-USD"
            quote_size: USD amount as string — will be truncated to allowed precision.
        """
        import uuid
        safe_size = self.truncate_quote_size(product_id, float(quote_size))
        client_order_id = str(uuid.uuid4())
        resp = self.client.market_order_buy(
            client_order_id=client_order_id,
            product_id=product_id,
            quote_size=safe_size,
        )
        log.info(f"Market buy {product_id} ${safe_size}: {resp}")
        return resp if isinstance(resp, dict) else resp.__dict__

    def place_market_sell(self, product_id: str, base_size: str) -> dict:
        """Place a market sell order using asset amount.

        Args:
            product_id: e.g. "ETH-USD"
            base_size: Amount of asset as string — will be truncated to allowed precision.
        """
        import uuid
        safe_size = self.truncate_base_size(product_id, float(base_size))
        client_order_id = str(uuid.uuid4())
        resp = self.client.market_order_sell(
            client_order_id=client_order_id,
            product_id=product_id,
            base_size=safe_size,
        )
        log.info(f"Market sell {product_id} {safe_size}: {resp}")
        return resp if isinstance(resp, dict) else resp.__dict__

    def get_order(self, order_id: str) -> dict:
        """Get order details by ID."""
        resp = self.client.get_order(order_id=order_id)
        return resp if isinstance(resp, dict) else resp.__dict__

    def cancel_orders(self, order_ids: list[str]) -> dict:
        """Cancel one or more orders."""
        resp = self.client.cancel_orders(order_ids=order_ids)
        log.info(f"Cancelled orders: {order_ids}")
        return resp if isinstance(resp, dict) else resp.__dict__
