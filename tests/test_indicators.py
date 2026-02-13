"""Tests for technical indicator calculations."""

import numpy as np
import pandas as pd
import pytest

from src.strategy.indicators import (
    add_all_indicators,
    calc_bollinger_bands,
    calc_ema,
    calc_rsi,
    calc_volume_ratio,
)


def _make_df(prices: list[float], volumes: list[float] | None = None) -> pd.DataFrame:
    """Create a minimal OHLCV DataFrame from close prices."""
    n = len(prices)
    return pd.DataFrame({
        "timestamp": range(n),
        "open": prices,
        "high": [p * 1.01 for p in prices],
        "low": [p * 0.99 for p in prices],
        "close": prices,
        "volume": volumes if volumes else [100.0] * n,
    })


class TestRSI:
    def test_rsi_range(self):
        """RSI should be between 0 and 100."""
        np.random.seed(42)
        prices = list(np.cumsum(np.random.randn(100)) + 100)
        df = _make_df(prices)
        rsi = calc_rsi(df, period=14)
        valid = rsi.dropna()
        assert all(0 <= v <= 100 for v in valid)

    def test_rsi_overbought_on_rally(self):
        """Sustained price increase should push RSI above 70."""
        prices = [100 + i * 2 for i in range(50)]
        df = _make_df(prices)
        rsi = calc_rsi(df, period=14)
        assert rsi.iloc[-1] > 70

    def test_rsi_oversold_on_decline(self):
        """Sustained price decline should push RSI below 30."""
        prices = [200 - i * 2 for i in range(50)]
        df = _make_df(prices)
        rsi = calc_rsi(df, period=14)
        assert rsi.iloc[-1] < 30


class TestEMA:
    def test_ema_follows_trend(self):
        """EMA should trend with price."""
        prices = [100 + i for i in range(50)]
        df = _make_df(prices)
        ema = calc_ema(df, period=12)
        valid = ema.dropna()
        # EMA should be increasing
        diffs = valid.diff().dropna()
        assert all(d > 0 for d in diffs)

    def test_fast_ema_responds_faster(self):
        """Fast EMA should be closer to recent price than slow EMA."""
        prices = [100] * 30 + [100 + i * 3 for i in range(20)]
        df = _make_df(prices)
        fast = calc_ema(df, period=12)
        slow = calc_ema(df, period=26)
        # At end of uptrend, fast EMA should be above slow
        assert fast.iloc[-1] > slow.iloc[-1]


class TestBollingerBands:
    def test_bands_contain_price(self):
        """Most prices should be within Bollinger Bands."""
        np.random.seed(42)
        prices = list(np.cumsum(np.random.randn(100) * 0.5) + 100)
        df = _make_df(prices)
        upper, middle, lower = calc_bollinger_bands(df, period=20, std_dev=2.0)
        close = df["close"]
        # Check last 50 candles (after warmup)
        within = sum(
            1 for i in range(50, 100)
            if pd.notna(lower.iloc[i]) and lower.iloc[i] <= close.iloc[i] <= upper.iloc[i]
        )
        assert within >= 40  # at least 80% within bands

    def test_upper_above_lower(self):
        """Upper band should always be above lower band."""
        prices = [100 + i * 0.1 for i in range(50)]
        df = _make_df(prices)
        upper, _, lower = calc_bollinger_bands(df, period=20)
        for i in range(20, 50):
            if pd.notna(upper.iloc[i]):
                assert upper.iloc[i] > lower.iloc[i]


class TestVolumeRatio:
    def test_normal_volume_near_one(self):
        """Constant volume should give ratio ~1.0."""
        prices = [100] * 50
        volumes = [1000] * 50
        df = _make_df(prices, volumes)
        ratio = calc_volume_ratio(df, period=20)
        valid = ratio.dropna()
        assert all(abs(v - 1.0) < 0.01 for v in valid)

    def test_spike_detected(self):
        """Volume spike should produce ratio > 1.5."""
        prices = [100] * 50
        volumes = [1000] * 49 + [3000]  # 3x spike
        df = _make_df(prices, volumes)
        ratio = calc_volume_ratio(df, period=20)
        assert ratio.iloc[-1] > 1.5


class TestAddAllIndicators:
    def test_all_columns_present(self):
        """add_all_indicators should add all expected columns."""
        np.random.seed(42)
        prices = list(np.cumsum(np.random.randn(100)) + 100)
        df = _make_df(prices)
        config = {
            "indicators": {
                "rsi": {"period": 14},
                "ema": {"fast": 12, "slow": 26},
                "bollinger": {"period": 20, "std_dev": 2.0},
                "volume": {"period": 20},
            }
        }
        result = add_all_indicators(df, config)
        expected = {"rsi", "ema_fast", "ema_slow", "bb_upper", "bb_middle", "bb_lower", "volume_ratio"}
        assert expected.issubset(set(result.columns))
