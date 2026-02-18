"""Tests for limit order functionality in OrderExecutor."""

import pytest
from unittest.mock import MagicMock

from src.api.order_executor import OrderExecutor, OrderSide


@pytest.fixture
def paper_executor():
    mock_client = MagicMock()
    return OrderExecutor(mock_client, mode="paper")


class TestPaperLimitOrders:
    def test_limit_buy_creates_unfilled_order(self, paper_executor):
        result = paper_executor.limit_buy("ETH-USD", 0.005, 2000.0)
        assert result.side == OrderSide.BUY
        assert result.price == 2000.0
        assert result.size == 0.005
        assert result.filled is False
        assert result.paper is True

    def test_limit_sell_creates_unfilled_order(self, paper_executor):
        result = paper_executor.limit_sell("ETH-USD", 0.005, 2100.0)
        assert result.side == OrderSide.SELL
        assert result.price == 2100.0
        assert result.size == 0.005
        assert result.filled is False
        assert result.paper is True

    def test_limit_order_has_unique_ids(self, paper_executor):
        r1 = paper_executor.limit_buy("ETH-USD", 0.005, 2000.0)
        r2 = paper_executor.limit_buy("ETH-USD", 0.005, 1990.0)
        assert r1.order_id != r2.order_id

    def test_limit_buy_quote_calculation(self, paper_executor):
        result = paper_executor.limit_buy("ETH-USD", 0.005, 2000.0)
        assert result.quote_spent == pytest.approx(10.0)

    def test_limit_sell_quote_calculation(self, paper_executor):
        result = paper_executor.limit_sell("ETH-USD", 0.005, 2100.0)
        assert result.quote_spent == pytest.approx(10.5)
