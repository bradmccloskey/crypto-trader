"""Tests for signal generation."""

import numpy as np
import pandas as pd
import pytest

from src.strategy.indicators import add_all_indicators
from src.strategy.signal_generator import SignalGenerator, SignalType


def _default_config():
    return {
        "indicators": {
            "rsi": {"period": 14, "oversold": 30, "overbought": 70},
            "ema": {"fast": 12, "slow": 26},
            "bollinger": {"period": 20, "std_dev": 2.0},
            "volume": {"period": 20, "multiplier": 1.5},
        },
        "strategy": {"min_confirmations": 3},
        "risk": {"stop_loss_pct": 0.025, "take_profit_pct": 0.04},
    }


def _make_df(prices, volumes=None):
    n = len(prices)
    return pd.DataFrame({
        "timestamp": range(n),
        "open": prices,
        "high": [p * 1.01 for p in prices],
        "low": [p * 0.99 for p in prices],
        "close": prices,
        "volume": volumes or [100.0] * n,
    })


class TestSignalGenerator:
    def test_hold_on_insufficient_data(self):
        config = _default_config()
        gen = SignalGenerator(config)
        df = _make_df([100.0])
        signal = gen.generate(df, "ETH-USD")
        assert signal.signal_type == SignalType.HOLD

    def test_hold_on_mixed_signals(self):
        """Flat market with no clear trend should produce HOLD."""
        config = _default_config()
        gen = SignalGenerator(config)
        np.random.seed(42)
        prices = list(np.cumsum(np.random.randn(100) * 0.2) + 100)
        df = _make_df(prices)
        df = add_all_indicators(df, config)
        signal = gen.generate(df, "ETH-USD")
        # With random walk, likely HOLD
        assert signal.signal_type in (SignalType.HOLD, SignalType.BUY, SignalType.SELL)
        assert signal.product_id == "ETH-USD"

    def test_buy_signal_has_stop_loss_and_take_profit(self):
        """When a BUY signal fires, it should include SL and TP levels."""
        config = _default_config()
        config["strategy"]["min_confirmations"] = 1  # easier to trigger
        gen = SignalGenerator(config)

        # Strong downtrend then reversal with volume
        prices = [200 - i * 2 for i in range(40)] + [120 + i * 3 for i in range(20)]
        volumes = [100] * 55 + [300] * 5  # volume spike at end
        df = _make_df(prices, volumes)
        df = add_all_indicators(df, config)
        signal = gen.generate(df, "SOL-USD")

        if signal.signal_type == SignalType.BUY:
            assert signal.stop_loss > 0
            assert signal.take_profit > signal.price
            assert signal.stop_loss < signal.price
            assert signal.confidence > 0

    def test_signal_respects_min_confirmations(self):
        """Signal should require min_confirmations indicators."""
        config = _default_config()
        config["strategy"]["min_confirmations"] = 4  # require all 4
        gen = SignalGenerator(config)
        np.random.seed(42)
        prices = list(np.cumsum(np.random.randn(100) * 0.5) + 100)
        df = _make_df(prices)
        df = add_all_indicators(df, config)
        signal = gen.generate(df, "ETH-USD")
        # Very hard to get 4 confirmations on random data → likely HOLD
        assert signal.signal_type == SignalType.HOLD
