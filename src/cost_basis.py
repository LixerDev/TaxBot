"""
CostBasis — FIFO / LIFO / HIFO cost basis engine.

Manages a portfolio of tax lots per token.
When a disposal occurs, selects which lots to use
based on the chosen method to compute cost basis.
"""

import uuid
from datetime import datetime
from collections import defaultdict
from src.models import TaxLot, TaxEvent, GainType, TxType
from src.logger import get_logger
from config import config

logger = get_logger(__name__)

ONE_YEAR_SECONDS = 365.25 * 24 * 3600


class CostBasisEngine:
    def __init__(self, method: str = None):
        self.method = (method or config.COST_BASIS_METHOD).lower()
        # Inventory: mint → list of TaxLots
        self._lots: dict[str, list[TaxLot]] = defaultdict(list)

    def acquire(
        self,
        mint: str,
        symbol: str,
        amount: float,
        price_per_unit_usd: float,
        acquired_at: datetime,
        tx_sig: str,
        acquisition_type: TxType,
    ) -> TaxLot:
        """
        Record an acquisition (buy/transfer-in/swap receive).
        Creates a new tax lot and adds it to the inventory.
        """
        lot = TaxLot(
            lot_id=str(uuid.uuid4())[:8],
            mint=mint,
            symbol=symbol,
            amount=amount,
            cost_basis_usd=amount * price_per_unit_usd,
            price_per_unit_usd=price_per_unit_usd,
            acquired_at=acquired_at,
            acquisition_tx=tx_sig,
            acquisition_type=acquisition_type,
        )
        self._lots[mint].append(lot)
        logger.debug(
            f"Acquired {amount:.6f} {symbol} @ ${price_per_unit_usd:.4f} "
            f"(lot {lot.lot_id}, method {self.method})"
        )
        return lot

    def dispose(
        self,
        mint: str,
        symbol: str,
        amount: float,
        proceeds_usd: float,
        disposed_at: datetime,
        tx_sig: str,
        tx_type: TxType,
        protocol: str = "",
    ) -> TaxEvent | None:
        """
        Process a disposal (sell/swap-out/transfer-out).
        Selects lots using FIFO/LIFO/HIFO and computes gain/loss.

        Returns:
        - TaxEvent with computed gain/loss, or None if insufficient inventory
        """
        available = self._lots.get(mint, [])
        available = [lot for lot in available if lot.amount > 0]

        if not available:
            logger.warning(
                f"No lots found for {symbol} ({mint[:12]}...) during disposal. "
                "This may indicate a transaction before the tracked period."
            )
            # Create an event with unknown cost basis (cost = 0)
            event = TaxEvent(
                event_id=str(uuid.uuid4())[:8],
                tx_signature=tx_sig,
                tx_type=tx_type,
                date=disposed_at,
                mint=mint,
                symbol=symbol,
                amount_disposed=amount,
                proceeds_usd=proceeds_usd,
                cost_basis_usd=0.0,
                gain_loss_usd=proceeds_usd,
                gain_type=GainType.SHORT_TERM,
                protocol=protocol,
                notes="⚠️ Unknown cost basis — no acquisition found",
            )
            return event

        # Sort lots by method
        sorted_lots = self._sort_lots(available)

        # Consume lots until amount is satisfied
        amount_remaining = amount
        total_cost_basis = 0.0
        earliest_acquisition = sorted_lots[0].acquired_at

        for lot in sorted_lots:
            if amount_remaining <= 0:
                break

            use_amount = min(lot.amount, amount_remaining)
            use_cost = use_amount * lot.cost_basis_per_unit

            total_cost_basis += use_cost
            lot.amount -= use_amount
            amount_remaining -= use_amount

            if lot.acquired_at < earliest_acquisition:
                earliest_acquisition = lot.acquired_at

        # Determine short/long term based on earliest acquired lot used
        hold_seconds = (disposed_at - earliest_acquisition).total_seconds()
        gain_type = (
            GainType.LONG_TERM
            if hold_seconds >= ONE_YEAR_SECONDS
            else GainType.SHORT_TERM
        )

        gain_loss = proceeds_usd - total_cost_basis

        event = TaxEvent(
            event_id=str(uuid.uuid4())[:8],
            tx_signature=tx_sig,
            tx_type=tx_type,
            date=disposed_at,
            mint=mint,
            symbol=symbol,
            amount_disposed=amount - amount_remaining,
            proceeds_usd=proceeds_usd,
            cost_basis_usd=total_cost_basis,
            gain_loss_usd=gain_loss,
            gain_type=gain_type,
            acquisition_date=earliest_acquisition,
            protocol=protocol,
        )

        logger.debug(
            f"Disposed {amount:.6f} {symbol}: proceeds=${proceeds_usd:.2f} "
            f"basis=${total_cost_basis:.2f} gain=${gain_loss:.2f} [{gain_type.value}]"
        )
        return event

    def _sort_lots(self, lots: list[TaxLot]) -> list[TaxLot]:
        """Sort lots according to the chosen method."""
        if self.method == "fifo":
            return sorted(lots, key=lambda l: l.acquired_at)
        elif self.method == "lifo":
            return sorted(lots, key=lambda l: l.acquired_at, reverse=True)
        elif self.method == "hifo":
            return sorted(lots, key=lambda l: l.cost_basis_per_unit, reverse=True)
        return lots

    def get_remaining_lots(self) -> list[TaxLot]:
        """Return all remaining (unrealized) lots across all tokens."""
        all_lots = []
        for lots in self._lots.values():
            all_lots.extend(lot for lot in lots if lot.amount > 0.000001)
        return all_lots
