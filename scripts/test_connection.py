#!/usr/bin/env python3
"""Phase 1 verification — test Coinbase API connection and show balances."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.api.coinbase_client import CoinbaseClient
from src.utils.logger import setup_logger

log = setup_logger("test-connection")


def main():
    print("=" * 50)
    print("  Coinbase Connection Test")
    print("=" * 50)

    try:
        client = CoinbaseClient()
        accounts = client.list_accounts()
    except Exception as e:
        print(f"\nFAILED to connect: {e}")
        sys.exit(1)

    print(f"\nFound {len(accounts)} accounts with balances:\n")
    total_usd = 0

    for acct in sorted(accounts, key=lambda a: a["balance"], reverse=True):
        currency = acct["currency"]
        balance = acct["balance"]
        print(f"  {currency:8s}  {balance:>18.8f}")

        if currency == "USD":
            total_usd += balance

    # Check for protected assets
    print("\n" + "-" * 50)
    protected = {"SHIB", "BTC"}
    found = {a["currency"] for a in accounts} & protected
    missing = protected - found

    if found:
        print(f"  Protected assets found: {', '.join(sorted(found))}")
    if missing:
        print(f"  Protected assets NOT found: {', '.join(sorted(missing))}")

    print(f"\n  USD balance: ${total_usd:.2f}")
    print("=" * 50)
    print("  Connection: OK")
    print("=" * 50)


if __name__ == "__main__":
    main()
