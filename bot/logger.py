"""
logger.py — Logging terstruktur ke console dan file JSON
"""

import json
import logging
import logging.handlers
from datetime import datetime, timezone
from pathlib import Path

from .trade_executor import TradeResult


def setup_logging(level: int = logging.INFO) -> None:
    """Inisialisasi root logger dengan handler console + file rotating."""
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    fmt = logging.Formatter(
        "[%(asctime)s] %(levelname)-8s %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler
    console = logging.StreamHandler()
    console.setFormatter(fmt)

    # Rotating file handler (maks 5 MB × 3 backup)
    file_handler = logging.handlers.RotatingFileHandler(
        log_dir / "bot.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(console)
    root.addHandler(file_handler)


class TradeLogger:
    """Menyimpan riwayat trade ke JSONL (satu record per baris)."""

    def __init__(self, path: str = "logs/trades.jsonl"):
        self._path = Path(path)
        self._path.parent.mkdir(exist_ok=True)

    def log(self, result: TradeResult) -> None:
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "market_id": result.market_id,
            "outcome": result.outcome,
            "probability": round(result.probability, 4),
            "amount_usdc": result.amount_usdc,
            "success": result.success,
            "order_id": result.order_id,
            "error": result.error,
            "dry_run": result.dry_run,
        }
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
