"""SMS notifications via macOS iMessage.

Uses a message queue file that a helper script sends from a terminal context
(which has Automation permissions for Messages.app). Falls back to direct
osascript if running interactively.
"""

import os
import subprocess
import threading
import time
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

from src.utils.logger import setup_logger

log = setup_logger("sms-notifier")

MSG_QUEUE = "/Users/claude/projects/investment/crypto-trader/data/sms_queue.txt"

ET = timezone(timedelta(hours=-5))


def _is_quiet_hours() -> bool:
    """Check if current time is within quiet hours (10 PM - 7 AM ET)."""
    now_et = datetime.now(ET)
    hour = now_et.hour
    return hour >= 22 or hour < 7


class SMSNotifier:
    """Send SMS/iMessage notifications."""

    def __init__(self):
        load_dotenv()
        self.phone = os.getenv("SMS_PHONE_NUMBER", "")
        os.makedirs(os.path.dirname(MSG_QUEUE), exist_ok=True)
        if not self.phone:
            log.warning("SMS_PHONE_NUMBER not set — notifications disabled")

    def send(self, message: str):
        """Queue an SMS for delivery. Non-blocking. Suppressed during quiet hours (10PM-7AM ET)."""
        if not self.phone:
            log.debug(f"SMS skipped (no phone): {message[:80]}")
            return

        if _is_quiet_hours():
            log.info(f"SMS suppressed (quiet hours): {message[:80]}")
            return

        # Write to queue file for the helper to pick up
        clean = message.replace("\n", " | ")
        try:
            with open(MSG_QUEUE, "a") as f:
                f.write(clean + "\n")
            log.info(f"SMS queued: {message[:80]}...")
        except Exception as e:
            log.warning(f"SMS queue failed: {e}")

    # ── Convenience methods ──────────────────────────────────────────

    def trade_opened(self, product_id: str, price: float, size: float,
                     usd_amount: float, stop_loss: float, take_profit: float):
        self.send(
            f"BUY {product_id}\n"
            f"Price: ${price:,.4f}\n"
            f"Size: {size:.8f} (${usd_amount:.2f})\n"
            f"SL: ${stop_loss:,.4f} | TP: ${take_profit:,.4f}"
        )

    def trade_closed(self, product_id: str, pnl: float, pnl_pct: float,
                     exit_reason: str):
        emoji = "+" if pnl >= 0 else ""
        self.send(
            f"CLOSED {product_id} ({exit_reason})\n"
            f"P&L: {emoji}${pnl:.2f} ({pnl_pct:+.1%})"
        )

    def daily_limit_hit(self, daily_loss: float):
        self.send(
            f"DAILY LOSS LIMIT HIT\n"
            f"Loss today: ${daily_loss:.2f}\n"
            f"Trading paused until tomorrow"
        )

    def daily_summary(self, summary: dict):
        msg = (
            f"DAILY SUMMARY\n"
            f"Capital: ${summary.get('capital', 0):.2f}\n"
            f"Trades: {summary.get('total_trades', 0)} "
            f"(W:{summary.get('wins', 0)} L:{summary.get('losses', 0)})\n"
            f"P&L: ${summary.get('realized_pnl', 0):.2f}\n"
            f"Win rate: {summary.get('win_rate', 0):.0%}"
        )
        if "grid_pnl" in summary:
            msg += f"\nGrid P&L: ${summary['grid_pnl']:.4f} ({summary.get('grid_pairs', 0)} pairs)"
        self.send(msg)

    def error(self, message: str):
        self.send(f"BOT ERROR: {message}")
