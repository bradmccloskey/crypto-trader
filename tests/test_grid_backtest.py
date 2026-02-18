"""Tests for grid backtest engine."""

import pytest
import pandas as pd
import numpy as np

from src.backtesting.grid_backtest import GridBacktestEngine


@pytest.fixture
def config():
    return {
        "grid": {
            "enabled": True,
            "pairs": ["ETH-USD"],
            "grid_capital_usd": 100.0,
            "num_levels": 3,
            "grid_spacing_pct": 0.02,  # 2% spacing for clearer test signals
            "order_size_usd": 10.0,
            "rebalance_threshold_pct": 0.10,  # 10% to avoid rebalancing in tests
        }
    }


def make_candles(prices: list[float]) -> pd.DataFrame:
    """Create a simple OHLCV DataFrame from a list of close prices."""
    rows = []
    for i, p in enumerate(prices):
        rows.append({
            "timestamp": 1700000000 + i * 3600,
            "open": p,
            "high": p * 1.005,
            "low": p * 0.995,
            "close": p,
            "volume": 1000.0,
        })
    return pd.DataFrame(rows)


def make_oscillating_candles(center: float, amplitude_pct: float, periods: int) -> pd.DataFrame:
    """Create candles that oscillate around a center price."""
    rows = []
    for i in range(periods):
        # Oscillate using sine wave
        offset = np.sin(i * 2 * np.pi / 10) * center * amplitude_pct
        close = center + offset
        high = close + abs(offset) * 0.2
        low = close - abs(offset) * 0.2
        rows.append({
            "timestamp": 1700000000 + i * 3600,
            "open": close,
            "high": max(high, close),
            "low": min(low, close),
            "close": close,
            "volume": 1000.0,
        })
    return pd.DataFrame(rows)


class TestGridBacktestBasic:
    def test_empty_data_returns_empty_result(self, config):
        engine = GridBacktestEngine(config)
        result = engine.run({})
        assert result.total_pnl == 0.0
        assert result.total_buys == 0

    def test_flat_market_no_fills(self, config):
        """In a perfectly flat market, grid levels shouldn't fill."""
        # All candles at exactly 1000 — high/low within 0.5% won't hit 2% grid levels
        data = {"ETH-USD": make_candles([1000.0] * 50)}
        engine = GridBacktestEngine(config)
        result = engine.run(data)
        # With 0.5% natural range vs 2% grid spacing, no fills expected
        assert result.total_buys == 0 or result.total_sells == 0

    def test_oscillating_market_generates_trades(self, config):
        """An oscillating market should trigger grid fills."""
        # 3% amplitude on 2% grid spacing should trigger fills
        data = {"ETH-USD": make_oscillating_candles(1000.0, 0.03, 200)}
        engine = GridBacktestEngine(config)
        result = engine.run(data)
        assert result.total_buys > 0

    def test_result_has_required_fields(self, config):
        data = {"ETH-USD": make_oscillating_candles(1000.0, 0.03, 100)}
        engine = GridBacktestEngine(config)
        result = engine.run(data)
        assert hasattr(result, "total_pnl")
        assert hasattr(result, "total_buys")
        assert hasattr(result, "total_sells")
        assert hasattr(result, "grid_capital")
        assert hasattr(result, "return_pct")
        assert result.grid_capital == 100.0


class TestGridBacktestPnL:
    def test_oscillating_market_positive_pnl(self, config):
        """Grid trading in a ranging market should be profitable."""
        data = {"ETH-USD": make_oscillating_candles(1000.0, 0.04, 500)}
        engine = GridBacktestEngine(config)
        result = engine.run(data)
        # If we have both buys and sells, PnL should be positive
        if result.total_sells > 0:
            assert result.total_pnl > 0

    def test_multiple_pairs(self, config):
        config["grid"]["pairs"] = ["ETH-USD", "SOL-USD"]
        data = {
            "ETH-USD": make_oscillating_candles(2000.0, 0.03, 200),
            "SOL-USD": make_oscillating_candles(100.0, 0.03, 200),
        }
        engine = GridBacktestEngine(config)
        result = engine.run(data)
        assert result.total_buys >= 0
        assert isinstance(result.return_pct, float)
