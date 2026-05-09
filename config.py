import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

def _require(key):
    val = os.getenv(key)
    if not val:
        raise EnvironmentError(f"Missing required variable: {key} — check your .env file")
    return val

def _optional(key, default):
    return os.getenv(key, default)

@dataclass(frozen=True)
class Config:
    private_key: str
    wallet_address: str
    polygon_rpc: str
    clob_api_url: str
    telegram_bot_token: str
    telegram_chat_id: str
    database_url: str
    redis_url: str
    max_trade_size_usdc: float
    daily_loss_limit_pct: float
    scan_interval_seconds: int
    min_edge_threshold: float
    paper_trading: bool

def load_config():
    return Config(
        private_key=_require("PRIVATE_KEY"),
        wallet_address=_require("WALLET_ADDRESS"),
        polygon_rpc=_require("POLYGON_RPC"),
        clob_api_url=_optional("CLOB_API_URL", "https://clob.polymarket.com"),
        telegram_bot_token=_require("TELEGRAM_BOT_TOKEN"),
        telegram_chat_id=_require("TELEGRAM_CHAT_ID"),
        database_url=_optional("DATABASE_URL", "postgresql://localhost:5432/polybot"),
        redis_url=_optional("REDIS_URL", "redis://localhost:6379"),
        max_trade_size_usdc=float(_optional("MAX_TRADE_SIZE_USDC", "10")),
        daily_loss_limit_pct=float(_optional("DAILY_LOSS_LIMIT_PCT", "0.05")),
        scan_interval_seconds=int(_optional("SCAN_INTERVAL_SECONDS", "30")),
        min_edge_threshold=float(_optional("MIN_EDGE_THRESHOLD", "0.03")),
        paper_trading=_optional("PAPER_TRADING", "true").lower() == "true",
    )