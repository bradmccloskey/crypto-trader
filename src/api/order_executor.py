"""Order execution — supports paper and live modes."""

import time
from dataclasses import dataclass, field
from enum import Enum

from src.api.coinbase_client import CoinbaseClient
from src.utils.logger import setup_logger

log = setup_logger("order-executor")


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass
class OrderResult:
    order_id: str
    product_id: str
    side: OrderSide
    price: float
    size: float  # base asset amount
    quote_spent: float  # USD amount
    filled: bool
    timestamp: float = field(default_factory=time.time)
    paper: bool = True


class OrderExecutor:
    """Execute trades in paper or live mode."""

    def __init__(self, client: CoinbaseClient, mode: str = "paper"):
        self.client = client
        self.mode = mode
        self._paper_id_counter = 0
        log.info(f"OrderExecutor initialized in {mode} mode")

    def buy(self, product_id: str, usd_amount: float, current_price: float) -> OrderResult:
        """Buy asset using a USD amount."""
        if self.mode == "paper":
            return self._paper_buy(product_id, usd_amount, current_price)
        return self._live_buy(product_id, usd_amount, current_price)

    def sell(self, product_id: str, base_size: float, current_price: float) -> OrderResult:
        """Sell a specific amount of the base asset."""
        if self.mode == "paper":
            return self._paper_sell(product_id, base_size, current_price)
        return self._live_sell(product_id, base_size, current_price)

    # ── Paper trading ────────────────────────────────────────────────

    def _next_paper_id(self) -> str:
        self._paper_id_counter += 1
        return f"paper-{self._paper_id_counter:06d}"

    def _paper_buy(self, product_id: str, usd_amount: float, price: float) -> OrderResult:
        size = usd_amount / price
        result = OrderResult(
            order_id=self._next_paper_id(),
            product_id=product_id,
            side=OrderSide.BUY,
            price=price,
            size=size,
            quote_spent=usd_amount,
            filled=True,
            paper=True,
        )
        log.info(f"[PAPER] BUY {product_id}: {size:.8f} @ ${price:.4f} (${usd_amount:.2f})")
        return result

    def _paper_sell(self, product_id: str, base_size: float, price: float) -> OrderResult:
        quote = base_size * price
        result = OrderResult(
            order_id=self._next_paper_id(),
            product_id=product_id,
            side=OrderSide.SELL,
            price=price,
            size=base_size,
            quote_spent=quote,
            filled=True,
            paper=True,
        )
        log.info(f"[PAPER] SELL {product_id}: {base_size:.8f} @ ${price:.4f} (${quote:.2f})")
        return result

    # ── Live trading ─────────────────────────────────────────────────

    def _live_buy(self, product_id: str, usd_amount: float, price: float) -> OrderResult:
        resp = self.client.place_market_buy(product_id, f"{usd_amount:.2f}")
        order_id = resp.get("order_id", resp.get("success_response", {}).get("order_id", ""))
        log.info(f"[LIVE] BUY {product_id} ${usd_amount:.2f} → order {order_id}")
        size = usd_amount / price  # approximate; real fill may differ slightly
        return OrderResult(
            order_id=order_id,
            product_id=product_id,
            side=OrderSide.BUY,
            price=price,
            size=size,
            quote_spent=usd_amount,
            filled=True,
            paper=False,
        )

    def _live_sell(self, product_id: str, base_size: float, price: float) -> OrderResult:
        # Precision truncation handled by coinbase_client.place_market_sell
        resp = self.client.place_market_sell(product_id, str(base_size))
        order_id = resp.get("order_id", resp.get("success_response", {}).get("order_id", ""))
        quote = base_size * price
        log.info(f"[LIVE] SELL {product_id} {base_size} → order {order_id}")
        return OrderResult(
            order_id=order_id,
            product_id=product_id,
            side=OrderSide.SELL,
            price=price,
            size=base_size,
            quote_spent=quote,
            filled=True,
            paper=False,
        )
