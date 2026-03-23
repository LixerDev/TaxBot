from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
from typing import Optional


class TxType(str, Enum):
    BUY            = "BUY"
    SELL           = "SELL"
    SWAP           = "SWAP"
    TRANSFER_IN    = "TRANSFER_IN"
    TRANSFER_OUT   = "TRANSFER_OUT"
    STAKING_REWARD = "STAKING_REWARD"
    NFT_BUY        = "NFT_BUY"
    NFT_SELL       = "NFT_SELL"
    NETWORK_FEE    = "NETWORK_FEE"
    UNKNOWN        = "UNKNOWN"


class GainType(str, Enum):
    SHORT_TERM = "SHORT_TERM"   # Held < 1 year
    LONG_TERM  = "LONG_TERM"    # Held ≥ 1 year


TAXABLE_TYPES = {TxType.SELL, TxType.SWAP, TxType.TRANSFER_OUT, TxType.NFT_SELL}
INCOME_TYPES  = {TxType.STAKING_REWARD}
ACQUIRE_TYPES = {TxType.BUY, TxType.SWAP, TxType.TRANSFER_IN, TxType.NFT_BUY}


@dataclass
class RawTransaction:
    """A raw parsed transaction from Helius API."""
    signature: str
    timestamp: int                  # Unix timestamp
    tx_type_raw: str                # Helius type string
    fee_sol: float                  # Network fee in SOL
    source: str                     # Program/protocol source
    description: str                # Human-readable description
    token_transfers: list[dict]     # SPL token transfers
    native_transfers: list[dict]    # SOL transfers
    account_data: list[dict]        # Account balance changes
    raw: dict = field(default_factory=dict)

    @property
    def dt(self) -> datetime:
        return datetime.utcfromtimestamp(self.timestamp)

    @property
    def date_str(self) -> str:
        return self.dt.strftime("%Y-%m-%d %H:%M:%S UTC")


@dataclass
class TaxLot:
    """
    A unit of acquired tokens (a tax lot).
    Cost basis is tracked per lot for FIFO/LIFO/HIFO.
    """
    lot_id: str
    mint: str
    symbol: str
    amount: float
    cost_basis_usd: float           # Total cost basis in USD
    price_per_unit_usd: float       # Price per token at acquisition
    acquired_at: datetime
    acquisition_tx: str
    acquisition_type: TxType

    @property
    def cost_basis_per_unit(self) -> float:
        return self.price_per_unit_usd

    @property
    def days_held(self) -> int:
        return (datetime.utcnow() - self.acquired_at).days


@dataclass
class TaxEvent:
    """A single taxable disposal or income event."""
    event_id: str
    tx_signature: str
    tx_type: TxType
    date: datetime
    mint: str
    symbol: str

    # Disposal fields
    amount_disposed: float = 0.0
    proceeds_usd: float = 0.0       # USD value at time of disposal
    cost_basis_usd: float = 0.0     # Total cost basis of disposed lots
    gain_loss_usd: float = 0.0      # proceeds - cost_basis
    gain_type: GainType = GainType.SHORT_TERM
    acquisition_date: Optional[datetime] = None

    # Income fields (staking etc.)
    income_usd: float = 0.0

    # Fee fields
    fee_sol: float = 0.0
    fee_usd: float = 0.0

    # Metadata
    protocol: str = ""
    notes: str = ""

    def to_csv_row(self) -> dict:
        return {
            "Date": self.date.strftime("%Y-%m-%d %H:%M:%S"),
            "Type": self.tx_type.value,
            "Token": self.symbol,
            "Amount": round(self.amount_disposed, 8),
            "Proceeds (USD)": round(self.proceeds_usd, 2),
            "Cost Basis (USD)": round(self.cost_basis_usd, 2),
            "Gain/Loss (USD)": round(self.gain_loss_usd, 2),
            "Gain Type": self.gain_type.value if self.amount_disposed else "",
            "Acquisition Date": self.acquisition_date.strftime("%Y-%m-%d") if self.acquisition_date else "",
            "Protocol": self.protocol,
            "TX Signature": self.tx_signature[:20] + "...",
        }


@dataclass
class TaxSummary:
    """Complete tax summary for a fiscal year."""
    wallets: list[str]
    year: int
    method: str

    events: list[TaxEvent] = field(default_factory=list)
    unrealized_lots: list[TaxLot] = field(default_factory=list)

    @property
    def taxable_events(self) -> list[TaxEvent]:
        return [e for e in self.events if e.tx_type in TAXABLE_TYPES]

    @property
    def income_events(self) -> list[TaxEvent]:
        return [e for e in self.events if e.tx_type in INCOME_TYPES]

    @property
    def fee_events(self) -> list[TaxEvent]:
        return [e for e in self.events if e.tx_type == TxType.NETWORK_FEE]

    @property
    def total_proceeds(self) -> float:
        return sum(e.proceeds_usd for e in self.taxable_events)

    @property
    def total_cost_basis(self) -> float:
        return sum(e.cost_basis_usd for e in self.taxable_events)

    @property
    def total_gain_loss(self) -> float:
        return sum(e.gain_loss_usd for e in self.taxable_events)

    @property
    def short_term_gains(self) -> float:
        return sum(
            e.gain_loss_usd for e in self.taxable_events
            if e.gain_type == GainType.SHORT_TERM and e.gain_loss_usd > 0
        )

    @property
    def short_term_losses(self) -> float:
        return sum(
            e.gain_loss_usd for e in self.taxable_events
            if e.gain_type == GainType.SHORT_TERM and e.gain_loss_usd < 0
        )

    @property
    def long_term_gains(self) -> float:
        return sum(
            e.gain_loss_usd for e in self.taxable_events
            if e.gain_type == GainType.LONG_TERM and e.gain_loss_usd > 0
        )

    @property
    def long_term_losses(self) -> float:
        return sum(
            e.gain_loss_usd for e in self.taxable_events
            if e.gain_type == GainType.LONG_TERM and e.gain_loss_usd < 0
        )

    @property
    def total_staking_income(self) -> float:
        return sum(e.income_usd for e in self.income_events)

    @property
    def total_deductible_fees(self) -> float:
        return sum(e.fee_usd for e in self.fee_events)

    def per_token_summary(self) -> dict[str, dict]:
        """Aggregate gains/losses by token symbol."""
        tokens: dict[str, dict] = {}
        for e in self.taxable_events:
            if e.symbol not in tokens:
                tokens[e.symbol] = {
                    "symbol": e.symbol,
                    "proceeds": 0.0,
                    "cost_basis": 0.0,
                    "gain_loss": 0.0,
                    "events": 0,
                }
            tokens[e.symbol]["proceeds"] += e.proceeds_usd
            tokens[e.symbol]["cost_basis"] += e.cost_basis_usd
            tokens[e.symbol]["gain_loss"] += e.gain_loss_usd
            tokens[e.symbol]["events"] += 1
        return tokens
