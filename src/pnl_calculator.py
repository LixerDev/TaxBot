"""
PnLCalculator — processes classified transactions into taxable events.

Orchestrates: Classifier → PriceOracle → CostBasisEngine
for each transaction in the fiscal year.
"""

import asyncio
from datetime import datetime
from src.models import (
    RawTransaction, TxType, TaxEvent, TaxSummary,
    TAXABLE_TYPES, ACQUIRE_TYPES, INCOME_TYPES
)
from src.classifier import Classifier
from src.price_oracle import PriceOracle
from src.cost_basis import CostBasisEngine
from src.logger import get_logger
from config import config

logger = get_logger(__name__)

SOL_MINT = "So11111111111111111111111111111111111111112"


class PnLCalculator:
    def __init__(self, method: str = None):
        self.classifier = Classifier()
        self.oracle = PriceOracle()
        self.engine = CostBasisEngine(method or config.COST_BASIS_METHOD)

    async def process(
        self,
        wallets: list[str],
        transactions: list[RawTransaction],
        year: int,
    ) -> TaxSummary:
        """
        Process all transactions and compute the full tax summary.

        Parameters:
        - wallets: List of wallet addresses (for direction determination)
        - transactions: All raw transactions for the year
        - year: Fiscal year

        Returns:
        - TaxSummary with all events and unrealized lots
        """
        summary = TaxSummary(
            wallets=wallets,
            year=year,
            method=config.COST_BASIS_METHOD
        )

        # Sort chronologically (oldest first) for correct lot matching
        sorted_txs = sorted(transactions, key=lambda t: t.timestamp)
        logger.info(f"Processing {len(sorted_txs)} transactions...")

        for tx in sorted_txs:
            # Use first wallet as primary (for direction)
            wallet = wallets[0]
            tx_type = self.classifier.classify(tx, wallet)
            received, sent = self.classifier.extract_token_flows(tx, wallet)
            dt = tx.dt

            # --- NETWORK FEE ---
            if tx.fee_sol > 0:
                sol_price = await self.oracle.get_price_at(SOL_MINT, tx.timestamp)
                fee_usd = tx.fee_sol * sol_price
                fee_event = TaxEvent(
                    event_id=f"fee_{tx.signature[:12]}",
                    tx_signature=tx.signature,
                    tx_type=TxType.NETWORK_FEE,
                    date=dt,
                    mint=SOL_MINT,
                    symbol="SOL",
                    fee_sol=tx.fee_sol,
                    fee_usd=fee_usd,
                    protocol=tx.source,
                )
                summary.events.append(fee_event)

            # --- ACQUISITIONS ---
            if tx_type in ACQUIRE_TYPES:
                for flow in received:
                    if not flow["mint"] or flow["amount"] <= 0:
                        continue
                    price = await self.oracle.get_price_at(flow["mint"], tx.timestamp)
                    self.engine.acquire(
                        mint=flow["mint"],
                        symbol=flow["symbol"],
                        amount=flow["amount"],
                        price_per_unit_usd=price,
                        acquired_at=dt,
                        tx_sig=tx.signature,
                        acquisition_type=tx_type,
                    )

            # --- DISPOSALS ---
            if tx_type in TAXABLE_TYPES:
                for flow in sent:
                    if not flow["mint"] or flow["amount"] <= 0:
                        continue
                    # Get proceeds: what did we receive for this?
                    proceeds_usd = 0.0
                    if tx_type == TxType.SWAP:
                        # Proceeds = value of tokens received
                        for rec in received:
                            price = await self.oracle.get_price_at(rec["mint"], tx.timestamp)
                            proceeds_usd += rec["amount"] * price
                    else:
                        price = await self.oracle.get_price_at(flow["mint"], tx.timestamp)
                        proceeds_usd = flow["amount"] * price

                    # De minimis check
                    if config.DE_MINIMIS_USD > 0 and proceeds_usd < config.DE_MINIMIS_USD:
                        continue

                    event = self.engine.dispose(
                        mint=flow["mint"],
                        symbol=flow["symbol"],
                        amount=flow["amount"],
                        proceeds_usd=proceeds_usd,
                        disposed_at=dt,
                        tx_sig=tx.signature,
                        tx_type=tx_type,
                        protocol=tx.source,
                    )
                    if event:
                        summary.events.append(event)

            # --- STAKING INCOME ---
            elif tx_type in INCOME_TYPES:
                for flow in received:
                    if not flow["mint"] or flow["amount"] <= 0:
                        continue
                    price = await self.oracle.get_price_at(flow["mint"], tx.timestamp)
                    income_usd = flow["amount"] * price
                    income_event = TaxEvent(
                        event_id=f"income_{tx.signature[:12]}",
                        tx_signature=tx.signature,
                        tx_type=TxType.STAKING_REWARD,
                        date=dt,
                        mint=flow["mint"],
                        symbol=flow["symbol"],
                        amount_disposed=flow["amount"],
                        proceeds_usd=income_usd,
                        income_usd=income_usd,
                        protocol=tx.source,
                    )
                    summary.events.append(income_event)

                    # Staking rewards are also acquired at FMV
                    self.engine.acquire(
                        mint=flow["mint"],
                        symbol=flow["symbol"],
                        amount=flow["amount"],
                        price_per_unit_usd=price,
                        acquired_at=dt,
                        tx_sig=tx.signature,
                        acquisition_type=TxType.STAKING_REWARD,
                    )

        summary.unrealized_lots = self.engine.get_remaining_lots()
        logger.info(
            f"Processing complete: {len(summary.taxable_events)} taxable events, "
            f"{len(summary.income_events)} income events, "
            f"{len(summary.fee_events)} fee deductions"
        )
        return summary
