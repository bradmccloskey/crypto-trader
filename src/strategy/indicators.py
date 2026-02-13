"""Technical indicator calculations using pandas + ta-lib."""

import pandas as pd
import ta


def calc_rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Relative Strength Index."""
    return ta.momentum.RSIIndicator(close=df["close"], window=period).rsi()


def calc_ema(df: pd.DataFrame, period: int = 12) -> pd.Series:
    """Exponential Moving Average."""
    return ta.trend.EMAIndicator(close=df["close"], window=period).ema_indicator()


def calc_bollinger_bands(
    df: pd.DataFrame, period: int = 20, std_dev: float = 2.0
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Bollinger Bands — returns (upper, middle, lower)."""
    bb = ta.volatility.BollingerBands(
        close=df["close"], window=period, window_dev=std_dev
    )
    return bb.bollinger_hband(), bb.bollinger_mavg(), bb.bollinger_lband()


def calc_volume_ratio(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """Current volume / rolling average volume."""
    avg_vol = df["volume"].rolling(window=period).mean()
    return df["volume"] / avg_vol


def add_all_indicators(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Add all indicator columns to the DataFrame in-place and return it.

    Added columns:
        rsi, ema_fast, ema_slow, bb_upper, bb_middle, bb_lower, volume_ratio
    """
    ind = config.get("indicators", {})

    rsi_cfg = ind.get("rsi", {})
    df["rsi"] = calc_rsi(df, period=rsi_cfg.get("period", 14))

    ema_cfg = ind.get("ema", {})
    df["ema_fast"] = calc_ema(df, period=ema_cfg.get("fast", 12))
    df["ema_slow"] = calc_ema(df, period=ema_cfg.get("slow", 26))

    bb_cfg = ind.get("bollinger", {})
    df["bb_upper"], df["bb_middle"], df["bb_lower"] = calc_bollinger_bands(
        df, period=bb_cfg.get("period", 20), std_dev=bb_cfg.get("std_dev", 2.0)
    )

    vol_cfg = ind.get("volume", {})
    df["volume_ratio"] = calc_volume_ratio(df, period=vol_cfg.get("period", 20))

    return df
