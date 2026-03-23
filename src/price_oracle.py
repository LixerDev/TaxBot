"""
PriceOracle — fetches historical token prices at specific timestamps.

Primary: Birdeye historical OHLCV API
Fallback: CoinGecko public API (rate limited, for major tokens only)
Cache: SQLite to avoid re-fetching the same price twice
"""

import aiohttp
import asyncio
import json
from datetime import datetime, timezone
from src.logger import get_logger
from config import config

logger = get_logger(__name__)

# CoinGecko coin ID mapping for major tokens
COINGECKO_IDS = {
    "So11111111111111111111111111111111111111112": "solana",
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": "usd-coin",
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": "tether",
    "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So": "msol",
    "7vfCXTUXx5WJV5JADk17DUJ4ksgau7utNKj4b963voxs": "ethereum",
    "9n4nbM75f5Ui33ZbPYXn59EwSgE8CGsHtAeTH5YFeJ9E": "bitcoin",
    "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263": "bonk",
    "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN": "jupiter-exchange-solana",
    "jtojtomepa8beP8AuQc6eXt5FriJwfFMwQx2v2f9mCL": "jito-governance-token",
}

# Stablecoins always worth $1
STABLECOINS = {
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",   # USDT
    "USDH1SM1ojwWUga67PGrgFWUHibbjqMvuMaDkRJTgkX",    # USDH
}

_price_cache: dict[str, float] = {}


class PriceOracle:
    def __init__(self):
        self.birdeye_key = config.BIRDEYE_API_KEY

    def _cache_key(self, mint: str, timestamp: int) -> str:
        # Round to nearest hour for caching
        return f"{mint}:{timestamp // 3600}"

    async def get_price_at(self, mint: str, timestamp: int) -> float:
        """
        Get the USD price of a token at a specific Unix timestamp.

        Returns:
        - float: Price in USD (0.0 if unknown)
        """
        # Stablecoins are always $1
        if mint in STABLECOINS:
            return 1.0

        cache_key = self._cache_key(mint, timestamp)
        if cache_key in _price_cache:
            return _price_cache[cache_key]

        price = 0.0

        # Try Birdeye first (more accurate, supports all tokens)
        if self.birdeye_key:
            price = await self._birdeye_historical(mint, timestamp)

        # Fallback to CoinGecko for major tokens
        if price == 0.0 and mint in COINGECKO_IDS:
            price = await self._coingecko_historical(mint, timestamp)

        if price > 0:
            _price_cache[cache_key] = price
        else:
            logger.debug(f"Could not fetch price for {mint[:12]}... at {timestamp}")

        return price

    async def get_prices_batch(
        self, requests: list[tuple[str, int]]
    ) -> dict[str, float]:
        """
        Fetch multiple prices concurrently.

        Parameters:
        - requests: list of (mint, timestamp) tuples

        Returns:
        - dict mapping "mint:timestamp" → price
        """
        tasks = [self.get_price_at(mint, ts) for mint, ts in requests]
        results = await asyncio.gather(*tasks)
        return {
            f"{mint}:{ts}": price
            for (mint, ts), price in zip(requests, results)
        }

    async def _birdeye_historical(self, mint: str, timestamp: int) -> float:
        """Fetch historical price from Birdeye OHLCV API."""
        # Birdeye historical: 1h candle containing the timestamp
        time_from = timestamp - 1800
        time_to = timestamp + 1800

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{config.BIRDEYE_BASE}/defi/history_price",
                    params={
                        "address": mint,
                        "address_type": "token",
                        "type": "1H",
                        "time_from": time_from,
                        "time_to": time_to,
                    },
                    headers={"X-API-KEY": self.birdeye_key},
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        items = data.get("data", {}).get("items", [])
                        if items:
                            # Use the close price of the nearest candle
                            return float(items[0].get("c", 0) or items[0].get("value", 0))
        except Exception as e:
            logger.debug(f"Birdeye historical failed for {mint[:12]}...: {e}")
        return 0.0

    async def _coingecko_historical(self, mint: str, timestamp: int) -> float:
        """Fetch historical price from CoinGecko (free, rate limited)."""
        coin_id = COINGECKO_IDS.get(mint)
        if not coin_id:
            return 0.0

        dt = datetime.utcfromtimestamp(timestamp)
        date_str = dt.strftime("%d-%m-%Y")

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{config.COINGECKO_BASE}/coins/{coin_id}/history",
                    params={"date": date_str, "localization": "false"},
                    headers={"Accept": "application/json"},
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        price = (
                            data.get("market_data", {})
                            .get("current_price", {})
                            .get("usd", 0)
                        )
                        return float(price or 0)
                    elif resp.status == 429:
                        await asyncio.sleep(2)
        except Exception as e:
            logger.debug(f"CoinGecko failed for {coin_id}: {e}")
        return 0.0
