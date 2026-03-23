"""
Fetcher — retrieves full transaction history from Helius Enhanced API.

Uses Helius's parsed transaction endpoint which gives us:
- Transaction type (SWAP, TRANSFER, etc.)
- Token amounts in/out
- Protocol source
- Human-readable descriptions
- Fee amounts
"""

import aiohttp
import asyncio
import json
import os
from src.models import RawTransaction
from src.logger import get_logger
from config import config

logger = get_logger(__name__)

HELIUS_API = config.HELIUS_BASE
MAX_PAGES = 50           # Max 50 pages × 100 tx = 5000 transactions
TX_PER_PAGE = 100


class Fetcher:
    def __init__(self):
        self.api_key = config.HELIUS_API_KEY

    async def fetch_transactions(
        self,
        wallet: str,
        year: int,
        before_sig: str = None,
    ) -> list[RawTransaction]:
        """
        Fetch full transaction history for a wallet, filtered to a specific year.
        Paginates through Helius API until all transactions are fetched or year boundary crossed.

        Parameters:
        - wallet: Solana wallet address
        - year: Fiscal year to filter (only returns txs from this year)
        - before_sig: Pagination cursor (signature)

        Returns:
        - list[RawTransaction]: All transactions for the given year
        """
        from datetime import datetime

        year_start = int(datetime(year, config.TAX_YEAR_START_MONTH, 1).timestamp())
        year_end = int(datetime(year + 1, config.TAX_YEAR_START_MONTH, 1).timestamp())

        all_txs: list[RawTransaction] = []
        cursor = before_sig
        page = 0

        logger.info(f"Fetching transactions for {wallet[:12]}... (year {year})")

        while page < MAX_PAGES:
            batch = await self._fetch_batch(wallet, cursor)
            if not batch:
                break

            for tx_raw in batch:
                ts = tx_raw.get("timestamp", 0)

                # Skip future transactions
                if ts > year_end:
                    continue

                # Stop if we've gone past the year
                if ts < year_start:
                    logger.info(f"Reached year boundary at page {page + 1}")
                    return all_txs

                parsed = self._parse_raw(tx_raw)
                if parsed:
                    all_txs.append(parsed)

            # Set next cursor
            cursor = batch[-1].get("signature")
            page += 1

            if len(batch) < TX_PER_PAGE:
                break

            # Small delay to respect rate limits
            await asyncio.sleep(0.2)

        logger.info(f"Fetched {len(all_txs)} transactions for year {year}")
        return all_txs

    async def _fetch_batch(self, wallet: str, before: str = None) -> list[dict]:
        """Fetch one page of transactions from Helius."""
        url = f"{HELIUS_API}/addresses/{wallet}/transactions"
        params = {
            "api-key": self.api_key,
            "limit": TX_PER_PAGE,
        }
        if before:
            params["before"] = before

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=20)
                ) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    elif resp.status == 429:
                        logger.warning("Helius rate limit hit. Waiting 2s...")
                        await asyncio.sleep(2)
                        return await self._fetch_batch(wallet, before)
                    else:
                        text = await resp.text()
                        logger.error(f"Helius API {resp.status}: {text[:200]}")
                        return []
        except Exception as e:
            logger.error(f"Helius fetch error: {e}")
            return []

    def _parse_raw(self, raw: dict) -> RawTransaction | None:
        """Parse a Helius API response into a RawTransaction."""
        try:
            return RawTransaction(
                signature=raw.get("signature", ""),
                timestamp=raw.get("timestamp", 0),
                tx_type_raw=raw.get("type", "UNKNOWN"),
                fee_sol=raw.get("fee", 0) / 1e9,
                source=raw.get("source", ""),
                description=raw.get("description", ""),
                token_transfers=raw.get("tokenTransfers", []),
                native_transfers=raw.get("nativeTransfers", []),
                account_data=raw.get("accountData", []),
                raw=raw,
            )
        except Exception as e:
            logger.debug(f"Failed to parse tx: {e}")
            return None
