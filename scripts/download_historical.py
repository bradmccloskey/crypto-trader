#!/usr/bin/env python3
"""Download historical data for backtesting."""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import yaml

from src.api.coinbase_client import CoinbaseClient
from src.utils.logger import setup_logger

log = setup_logger("download-historical")

# Coinbase API limits ~300 candles per request
MAX_PER_REQUEST = 300
GRANULARITY_SECONDS = {
    "ONE_HOUR": 3600,
    "ONE_DAY": 86400,
}


def download(product_id: str, client: CoinbaseClient, granularity: str = "ONE_HOUR",
             days: int = 180) -> pd.DataFrame:
    """Download historical candles, paginating as needed."""
    seconds_per = GRANULARITY_SECONDS[granularity]
    end = int(time.time())
    start = end - (days * 86400)

    all_candles = []
    chunk_start = start

    while chunk_start < end:
        chunk_end = min(chunk_start + MAX_PER_REQUEST * seconds_per, end)
        try:
            candles = client.get_candles(product_id, chunk_start, chunk_end, granularity)
            all_candles.extend(candles)
            log.info(f"  {product_id}: fetched {len(candles)} candles "
                     f"({len(all_candles)} total)")
        except Exception as e:
            log.error(f"  {product_id}: error at chunk {chunk_start}: {e}")

        chunk_start = chunk_end
        time.sleep(0.3)  # rate limit

    if not all_candles:
        return pd.DataFrame()

    df = pd.DataFrame(all_candles)
    df.rename(columns={"start": "timestamp"}, inplace=True)
    df = df[["timestamp", "open", "high", "low", "close", "volume"]]
    df = df.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    return df


def main():
    with open("config/config.yaml") as f:
        config = yaml.safe_load(f)

    pairs = config["trading_pairs"]
    granularity = config["strategy"]["candle_granularity"]
    days = 180  # 6 months

    os.makedirs("data/historical", exist_ok=True)
    client = CoinbaseClient()

    print(f"Downloading {days} days of {granularity} data for {len(pairs)} pairs...\n")

    for pair in pairs:
        print(f"Downloading {pair}...")
        df = download(pair, client, granularity=granularity, days=days)
        if not df.empty:
            path = f"data/historical/{pair.replace('-', '_')}_{granularity}.parquet"
            df.to_parquet(path)
            print(f"  Saved {len(df)} candles → {path}")
        else:
            print(f"  WARNING: No data for {pair}")
        print()

    print("Done!")


if __name__ == "__main__":
    main()
