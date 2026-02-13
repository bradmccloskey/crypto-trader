"""Multi-indicator signal generation."""

from dataclasses import dataclass
from enum import Enum

import pandas as pd

from src.utils.logger import setup_logger

log = setup_logger("signal-gen")


class SignalType(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class Signal:
    signal_type: SignalType
    product_id: str
    price: float
    stop_loss: float
    take_profit: float
    confidence: float  # 0.0-1.0
    reasons: list[str]


class SignalGenerator:
    """Generate trading signals from indicator data."""

    def __init__(self, config: dict):
        self.config = config
        ind = config.get("indicators", {})
        self.rsi_oversold = ind.get("rsi", {}).get("oversold", 30)
        self.rsi_overbought = ind.get("rsi", {}).get("overbought", 70)
        self.volume_multiplier = ind.get("volume", {}).get("multiplier", 1.5)
        risk = config.get("risk", {})
        self.stop_loss_pct = risk.get("stop_loss_pct", 0.025)
        self.take_profit_pct = risk.get("take_profit_pct", 0.04)
        self.min_confirmations = config.get("strategy", {}).get("min_confirmations", 3)

    def generate(self, df: pd.DataFrame, product_id: str) -> Signal:
        """Evaluate the latest candle and return a signal.

        Expects df to already have indicator columns from add_all_indicators().
        """
        if len(df) < 2:
            return Signal(SignalType.HOLD, product_id, 0, 0, 0, 0, ["insufficient data"])

        latest = df.iloc[-1]
        prev = df.iloc[-2]
        price = latest["close"]

        buy_reasons = []
        sell_reasons = []

        # 1. RSI
        rsi = latest.get("rsi")
        if pd.notna(rsi):
            if rsi < self.rsi_oversold:
                buy_reasons.append(f"RSI oversold ({rsi:.1f})")
            elif rsi > self.rsi_overbought:
                sell_reasons.append(f"RSI overbought ({rsi:.1f})")

        # 2. EMA crossover
        ema_fast = latest.get("ema_fast")
        ema_slow = latest.get("ema_slow")
        prev_ema_fast = prev.get("ema_fast")
        prev_ema_slow = prev.get("ema_slow")
        if all(pd.notna(v) for v in [ema_fast, ema_slow, prev_ema_fast, prev_ema_slow]):
            if ema_fast > ema_slow and prev_ema_fast <= prev_ema_slow:
                buy_reasons.append("EMA bullish crossover")
            elif ema_fast > ema_slow:
                buy_reasons.append("EMA bullish trend")
            if ema_fast < ema_slow and prev_ema_fast >= prev_ema_slow:
                sell_reasons.append("EMA bearish crossover")
            elif ema_fast < ema_slow:
                sell_reasons.append("EMA bearish trend")

        # 3. Bollinger Bands
        bb_lower = latest.get("bb_lower")
        bb_upper = latest.get("bb_upper")
        if pd.notna(bb_lower) and pd.notna(bb_upper):
            bb_range = bb_upper - bb_lower
            if bb_range > 0:
                bb_pct = (price - bb_lower) / bb_range
                if bb_pct < 0.15:
                    buy_reasons.append(f"Price near lower BB ({bb_pct:.0%})")
                elif bb_pct > 0.85:
                    sell_reasons.append(f"Price near upper BB ({bb_pct:.0%})")

        # 4. Volume confirmation
        volume_ratio = latest.get("volume_ratio")
        volume_ok = pd.notna(volume_ratio) and volume_ratio >= self.volume_multiplier
        if volume_ok:
            buy_reasons.append(f"Volume confirmed ({volume_ratio:.1f}x)")
            sell_reasons.append(f"Volume confirmed ({volume_ratio:.1f}x)")

        # Decide signal
        buy_score = len(buy_reasons)
        sell_score = len(sell_reasons)

        if buy_score >= self.min_confirmations and buy_score > sell_score:
            confidence = min(buy_score / 4.0, 1.0)
            return Signal(
                signal_type=SignalType.BUY,
                product_id=product_id,
                price=price,
                stop_loss=round(price * (1 - self.stop_loss_pct), 6),
                take_profit=round(price * (1 + self.take_profit_pct), 6),
                confidence=confidence,
                reasons=buy_reasons,
            )

        if sell_score >= self.min_confirmations and sell_score > buy_score:
            confidence = min(sell_score / 4.0, 1.0)
            return Signal(
                signal_type=SignalType.SELL,
                product_id=product_id,
                price=price,
                stop_loss=round(price * (1 + self.stop_loss_pct), 6),
                take_profit=round(price * (1 - self.take_profit_pct), 6),
                confidence=confidence,
                reasons=sell_reasons,
            )

        return Signal(
            signal_type=SignalType.HOLD,
            product_id=product_id,
            price=price,
            stop_loss=0,
            take_profit=0,
            confidence=0,
            reasons=[f"Buy({buy_score}) Sell({sell_score}) < min({self.min_confirmations})"],
        )
