"""OHLCV data fetching with disk caching."""

import hashlib
import json
import os
import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import yaml

from src.api.coinbase_client import CoinbaseClient
from src.utils.logger import setup_logger

log = setup_logger("market-data")

# Granularity → seconds per candle
GRANULARITY_SECONDS = {
    "ONE_MINUTE": 60,
    "FIVE_MINUTE": 300,
    "FIFTEEN_MINUTE": 900,
    "THIRTY_MINUTE": 1800,
    "ONE_HOUR": 3600,
    "TWO_HOUR": 7200,
    "SIX_HOUR": 21600,
    "ONE_DAY": 86400,
}


class MarketData:
    """Fetches and caches OHLCV candle data from Coinbase."""

    def __init__(self, client: CoinbaseClient, config: dict):
        self.client = client
        self.config = config
        self.cache_dir = config["data"]["cache_dir"]
        os.makedirs(self.cache_dir, exist_ok=True)

    def _cache_key(self, product_id: str, granularity: str, start: int, end: int) -> str:
        raw = f"{product_id}_{granularity}_{start}_{end}"
        return hashlib.md5(raw.encode()).hexdigest()

    def _load_cache(self, key: str) -> pd.DataFrame | None:
        path = os.path.join(self.cache_dir, f"{key}.parquet")
        if os.path.exists(path):
            age_minutes = (time.time() - os.path.getmtime(path)) / 60
            if age_minutes < 30:  # cache valid for 30 min
                return pd.read_parquet(path)
        return None

    def _save_cache(self, key: str, df: pd.DataFrame):
        path = os.path.join(self.cache_dir, f"{key}.parquet")
        df.to_parquet(path)

    def get_candles(
        self,
        product_id: str,
        granularity: str = "ONE_HOUR",
        num_candles: int = 100,
    ) -> pd.DataFrame:
        """Fetch recent OHLCV candles as a DataFrame.

        Returns DataFrame with columns: timestamp, open, high, low, close, volume
        sorted by timestamp ascending.
        """
        seconds_per = GRANULARITY_SECONDS[granularity]
        end = int(time.time())
        start = end - (num_candles * seconds_per)

        cache_key = self._cache_key(product_id, granularity, start, end)
        cached = self._load_cache(cache_key)
        if cached is not None:
            log.debug(f"Cache hit for {product_id} {granularity}")
            return cached

        # Coinbase limits ~300 candles per request; paginate if needed
        all_candles = []
        chunk_start = start
        max_per_request = 300

        while chunk_start < end:
            chunk_end = min(chunk_start + max_per_request * seconds_per, end)
            candles = self.client.get_candles(
                product_id=product_id,
                start=chunk_start,
                end=chunk_end,
                granularity=granularity,
            )
            all_candles.extend(candles)
            chunk_start = chunk_end
            if len(candles) < max_per_request:
                break

        if not all_candles:
            log.warning(f"No candles returned for {product_id}")
            return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

        df = pd.DataFrame(all_candles)
        df.rename(columns={"start": "timestamp"}, inplace=True)
        df = df[["timestamp", "open", "high", "low", "close", "volume"]]
        df = df.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)

        self._save_cache(cache_key, df)
        log.info(f"Fetched {len(df)} candles for {product_id} ({granularity})")
        return df

    def get_current_price(self, product_id: str) -> float:
        """Get the latest price for a product."""
        product = self.client.get_product(product_id)
        return float(product.get("price", 0))
