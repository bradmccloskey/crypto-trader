#!/usr/bin/env python3
"""Run grid strategy backtest on historical data."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import yaml

from src.backtesting.grid_backtest import GridBacktestEngine
from src.utils.logger import setup_logger

log = setup_logger("run-grid-backtest")


def main():
    with open("config/config.yaml") as f:
        config = yaml.safe_load(f)

    granularity = config["strategy"]["candle_granularity"]
    data_dir = "data/historical"
    grid_pairs = config.get("grid", {}).get("pairs", [])

    if not os.path.isdir(data_dir):
        print("No historical data found. Run scripts/download_historical.py first.")
        sys.exit(1)

    # Load historical data for grid pairs
    data = {}
    for pair in grid_pairs:
        filename = f"{pair.replace('-', '_')}_{granularity}.parquet"
        path = os.path.join(data_dir, filename)
        if os.path.exists(path):
            df = pd.read_parquet(path)
            data[pair] = df
            print(f"Loaded {pair}: {len(df)} candles")
        else:
            print(f"Skipping {pair} — no data file")

    if not data:
        print("No data files found for grid pairs. Run scripts/download_historical.py first.")
        sys.exit(1)

    print(f"\nRunning grid backtest on {len(data)} pairs...")
    print(f"Grid config: {config.get('grid', {}).get('num_levels', 5)} levels, "
          f"{config.get('grid', {}).get('grid_spacing_pct', 0.01):.1%} spacing, "
          f"${config.get('grid', {}).get('order_size_usd', 10):.0f}/order")
    print()

    engine = GridBacktestEngine(config)
    result = engine.run(data)

    # Print report
    print("=" * 50)
    print("  GRID BACKTEST RESULTS")
    print("=" * 50)
    print(f"  Grid Capital:    ${result.grid_capital:.2f}")
    print(f"  Total P&L:       ${result.total_pnl:.4f}")
    print(f"  Return:          {result.return_pct:.2f}%")
    print(f"  Max Deployed:    ${result.max_deployed:.2f}")
    print(f"  Total Buys:      {result.total_buys}")
    print(f"  Total Sells:     {result.total_sells}")
    print(f"  Rebalances:      {result.num_rebalances}")
    print(f"  Total Fills:     {result.total_buys + result.total_sells}")
    print("=" * 50)

    # Show last 20 trades
    if result.trades:
        print(f"\nLast 20 trades (of {len(result.trades)}):")
        print(f"  {'#':>4}  {'Product':12}  {'Side':4}  {'Price':>10}  {'P&L':>8}")
        print("  " + "-" * 45)
        for t in result.trades[-20:]:
            pnl_str = f"${t.pnl:>+7.4f}" if t.pnl else "       -"
            print(f"  {t.candle_idx:4d}  {t.product_id:12}  {t.side:4}  ${t.price:>9.4f}  {pnl_str}")


if __name__ == "__main__":
    main()
