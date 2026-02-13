#!/usr/bin/env python3
"""Run backtest on historical data and print performance report."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import yaml

from src.backtesting.backtest_engine import BacktestEngine
from src.backtesting.performance import print_report
from src.utils.logger import setup_logger

log = setup_logger("run-backtest")


def main():
    with open("config/config.yaml") as f:
        config = yaml.safe_load(f)

    granularity = config["strategy"]["candle_granularity"]
    data_dir = "data/historical"

    if not os.path.isdir(data_dir):
        print("No historical data found. Run scripts/download_historical.py first.")
        sys.exit(1)

    # Load all available historical data
    data = {}
    for pair in config["trading_pairs"]:
        filename = f"{pair.replace('-', '_')}_{granularity}.parquet"
        path = os.path.join(data_dir, filename)
        if os.path.exists(path):
            df = pd.read_parquet(path)
            data[pair] = df
            print(f"Loaded {pair}: {len(df)} candles")
        else:
            print(f"Skipping {pair} — no data file")

    if not data:
        print("No data files found. Run scripts/download_historical.py first.")
        sys.exit(1)

    print(f"\nRunning backtest on {len(data)} pairs...")
    engine = BacktestEngine(config)
    result = engine.run(data)
    print_report(result)

    # Also print individual trades if few enough
    if len(result.trades) <= 50:
        print("\nTrade Log:")
        print(f"  {'#':>3}  {'Product':12}  {'Entry':>10}  {'Exit':>10}  "
              f"{'P&L':>8}  {'%':>7}  {'Reason'}")
        print("  " + "-" * 70)
        for i, t in enumerate(result.trades, 1):
            print(f"  {i:3d}  {t.product_id:12}  ${t.entry_price:>9.4f}  "
                  f"${t.exit_price:>9.4f}  ${t.pnl:>+7.2f}  "
                  f"{t.pnl_pct:>+6.1%}  {t.exit_reason}")


if __name__ == "__main__":
    main()
