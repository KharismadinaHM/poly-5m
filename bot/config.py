"""
config.py — Pemuatan konfigurasi aman dari .env
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from dotenv import load_dotenv


def _load_env() -> None:
    """Muat .env dari root project, fallback ke env sistem."""
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
    else:
        load_dotenv()  # coba dari cwd


_load_env()


def _require(key: str) -> str:
    """Ambil env variable wajib; lempar ValueError jika tidak ada."""
    val = os.getenv(key, "").strip()
    if not val:
        raise ValueError(
            f"[Config] Environment variable '{key}' wajib diisi. "
            f"Salin .env.example ke .env dan isi nilainya."
        )
    return val


@dataclass(frozen=True)
class BotConfig:
    # Credentials
    api_key: str
    api_secret: str
    api_passphrase: str
    private_key: str
    polygon_rpc_url: str

    # Trading params
    max_bet_usdc: float = 10.0
    min_probability: float = 0.55
    slippage_tolerance: float = 0.02
    dry_run: bool = True

    # Timing
    poll_interval_sec: float = 1.0       # Interval polling normal
    trigger_window_sec: float = 10.0     # Detik terakhir sebelum close
    market_duration_min: int = 5         # Filter durasi market

    # Retry
    max_retries: int = 3
    retry_delay_sec: float = 0.5

    # Notifikasi
    telegram_token: str = ""
    telegram_chat_id: str = ""

    @classmethod
    def from_env(cls) -> "BotConfig":
        return cls(
            api_key=_require("POLY_API_KEY"),
            api_secret=_require("POLY_API_SECRET"),
            api_passphrase=_require("POLY_API_PASSPHRASE"),
            private_key=_require("PRIVATE_KEY"),
            polygon_rpc_url=os.getenv("POLYGON_RPC_URL", "https://polygon-rpc.com"),
            max_bet_usdc=float(os.getenv("MAX_BET_USDC", "10.0")),
            min_probability=float(os.getenv("MIN_PROBABILITY", "0.55")),
            slippage_tolerance=float(os.getenv("SLIPPAGE_TOLERANCE", "0.02")),
            dry_run=os.getenv("DRY_RUN", "true").lower() == "true",
            telegram_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
            telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
        )

    def __repr__(self) -> str:
        """Sembunyikan kredensial sensitif saat print."""
        return (
            f"BotConfig(dry_run={self.dry_run}, max_bet={self.max_bet_usdc} USDC, "
            f"min_prob={self.min_probability:.0%}, api_key=***)"
        )
