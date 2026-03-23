"""
Classifier — labels each raw transaction with a TxType.

Classification logic based on Helius type strings and transfer patterns.
"""

from src.models import RawTransaction, TxType
from src.logger import get_logger

logger = get_logger(__name__)

# Helius type → our TxType mapping
HELIUS_TYPE_MAP = {
    "SWAP":                  TxType.SWAP,
    "TOKEN_SWAP":            TxType.SWAP,
    "JUPITER_SWAP":          TxType.SWAP,
    "TRANSFER":              TxType.TRANSFER_IN,   # Refined below
    "TOKEN_TRANSFER":        TxType.TRANSFER_IN,
    "STAKE_SOL":             TxType.STAKING_REWARD,
    "UNSTAKE_SOL":           TxType.SELL,
    "NFT_SALE":              TxType.NFT_SELL,
    "NFT_BID_CANCELLED":     TxType.UNKNOWN,
    "NFT_LISTING":           TxType.UNKNOWN,
    "NFT_MINT":              TxType.NFT_BUY,
    "NFT_AUCTION_SETTLED":   TxType.NFT_SELL,
    "COMPRESSED_NFT_MINT":   TxType.NFT_BUY,
    "BUY":                   TxType.BUY,
    "SELL":                  TxType.SELL,
    "DEPOSIT":               TxType.TRANSFER_IN,
    "WITHDRAW":              TxType.TRANSFER_OUT,
    "CLAIM_REWARDS":         TxType.STAKING_REWARD,
    "STAKE_TOKEN":           TxType.TRANSFER_OUT,   # Treated as transfer
    "UNKNOWN":               TxType.UNKNOWN,
}

# Source protocols
DEX_SOURCES = {
    "JUPITER", "RAYDIUM", "ORCA", "SERUM", "OPENBOOK",
    "PHOENIX", "METEORA", "LIFINITY", "ALDRIN", "SABER"
}

STAKING_SOURCES = {
    "MARINADE", "JITO", "LIDO", "SOCEAN", "BLAZE",
    "STAKEWIZ", "JPOOL", "SOLBLAZE"
}


class Classifier:
    def classify(self, tx: RawTransaction, wallet: str) -> TxType:
        """
        Classify a transaction based on its type, source, and transfer patterns.

        Parameters:
        - tx: Raw parsed transaction
        - wallet: The wallet we're analyzing (to determine in/out direction)

        Returns:
        - TxType: Classification of this transaction
        """
        helius_type = tx.tx_type_raw.upper()

        # Check staking sources first
        if tx.source.upper() in STAKING_SOURCES:
            if "CLAIM" in helius_type or "REWARD" in helius_type:
                return TxType.STAKING_REWARD

        # Check DEX sources → always a SWAP
        if tx.source.upper() in DEX_SOURCES:
            return TxType.SWAP

        # Map Helius type
        base_type = HELIUS_TYPE_MAP.get(helius_type, TxType.UNKNOWN)

        # Refine TRANSFER direction based on wallet
        if base_type in (TxType.TRANSFER_IN, TxType.TRANSFER_OUT):
            base_type = self._classify_transfer(tx, wallet)

        # Fallback: analyze transfer patterns
        if base_type == TxType.UNKNOWN:
            base_type = self._classify_from_transfers(tx, wallet)

        return base_type

    def _classify_transfer(self, tx: RawTransaction, wallet: str) -> TxType:
        """Determine if a transfer is incoming or outgoing."""
        # Check native SOL transfers
        for transfer in tx.native_transfers:
            from_acc = transfer.get("fromUserAccount", "")
            to_acc = transfer.get("toUserAccount", "")
            if to_acc.lower() == wallet.lower():
                return TxType.TRANSFER_IN
            if from_acc.lower() == wallet.lower():
                return TxType.TRANSFER_OUT

        # Check token transfers
        for transfer in tx.token_transfers:
            from_acc = transfer.get("fromUserAccount", "")
            to_acc = transfer.get("toUserAccount", "")
            if to_acc.lower() == wallet.lower():
                return TxType.TRANSFER_IN
            if from_acc.lower() == wallet.lower():
                return TxType.TRANSFER_OUT

        return TxType.TRANSFER_IN  # Default

    def _classify_from_transfers(self, tx: RawTransaction, wallet: str) -> TxType:
        """Infer transaction type from transfer patterns."""
        wallet_lower = wallet.lower()
        tokens_in = [
            t for t in tx.token_transfers
            if t.get("toUserAccount", "").lower() == wallet_lower
        ]
        tokens_out = [
            t for t in tx.token_transfers
            if t.get("fromUserAccount", "").lower() == wallet_lower
        ]

        if tokens_in and tokens_out:
            return TxType.SWAP  # Got some tokens, sent some → swap
        if tokens_in:
            return TxType.TRANSFER_IN
        if tokens_out:
            return TxType.TRANSFER_OUT

        # Check SOL
        for t in tx.native_transfers:
            if t.get("toUserAccount", "").lower() == wallet_lower:
                return TxType.TRANSFER_IN
            if t.get("fromUserAccount", "").lower() == wallet_lower:
                return TxType.TRANSFER_OUT

        return TxType.UNKNOWN

    def extract_token_flows(
        self, tx: RawTransaction, wallet: str
    ) -> tuple[list[dict], list[dict]]:
        """
        Extract which tokens came in and which went out for this wallet.

        Returns:
        - tuple: (tokens_received, tokens_sent)
          Each is a list of dicts: {mint, symbol, amount}
        """
        wallet_lower = wallet.lower()

        received = []
        for t in tx.token_transfers:
            if t.get("toUserAccount", "").lower() == wallet_lower:
                received.append({
                    "mint": t.get("mint", ""),
                    "symbol": t.get("tokenSymbol", t.get("symbol", "???")),
                    "amount": float(t.get("tokenAmount", 0)),
                })

        sent = []
        for t in tx.token_transfers:
            if t.get("fromUserAccount", "").lower() == wallet_lower:
                sent.append({
                    "mint": t.get("mint", ""),
                    "symbol": t.get("tokenSymbol", t.get("symbol", "???")),
                    "amount": float(t.get("tokenAmount", 0)),
                })

        # Also check native SOL flows
        sol_mint = "So11111111111111111111111111111111111111112"
        for t in tx.native_transfers:
            amount_sol = float(t.get("amount", 0)) / 1e9
            if t.get("toUserAccount", "").lower() == wallet_lower and amount_sol > 0:
                received.append({"mint": sol_mint, "symbol": "SOL", "amount": amount_sol})
            elif t.get("fromUserAccount", "").lower() == wallet_lower and amount_sol > 0:
                sent.append({"mint": sol_mint, "symbol": "SOL", "amount": amount_sol})

        return received, sent
