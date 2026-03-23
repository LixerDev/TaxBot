import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    HELIUS_API_KEY: str = os.getenv("HELIUS_API_KEY", "")
    BIRDEYE_API_KEY: str = os.getenv("BIRDEYE_API_KEY", "")

    COST_BASIS_METHOD: str = os.getenv("COST_BASIS_METHOD", "fifo").lower()
    BASE_CURRENCY: str = os.getenv("BASE_CURRENCY", "USD")
    TAX_YEAR_START_MONTH: int = int(os.getenv("TAX_YEAR_START_MONTH", "1"))
    DE_MINIMIS_USD: float = float(os.getenv("DE_MINIMIS_USD", "0"))

    USE_CACHE: bool = os.getenv("USE_CACHE", "true").lower() == "true"
    CACHE_DB: str = os.getenv("CACHE_DB", "taxbot_cache.db")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    HELIUS_BASE = "https://api.helius.xyz/v0"
    BIRDEYE_BASE = "https://public-api.birdeye.so"
    COINGECKO_BASE = "https://api.coingecko.com/api/v3"

    def validate(self) -> list[str]:
        errors = []
        if not self.HELIUS_API_KEY:
            errors.append("HELIUS_API_KEY is required. Get one free at https://helius.dev")
        if self.COST_BASIS_METHOD not in ("fifo", "lifo", "hifo"):
            errors.append("COST_BASIS_METHOD must be fifo, lifo, or hifo")
        return errors

config = Config()
