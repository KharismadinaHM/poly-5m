"""
market_scanner.py — Pemindai market Crypto dengan filter durasi 5 menit
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds

from .config import BotConfig

logger = logging.getLogger(__name__)


class MarketData:
    """DTO: data market yang sudah diproses."""

    def __init__(self, raw: dict):
        self.condition_id: str = raw.get("condition_id", "")
        self.question: str = raw.get("question", "N/A")
        self.category: str = raw.get("tags", [{}])[0].get("label", "") if raw.get("tags") else ""
        self.end_date_iso: str = raw.get("end_date_iso", "")
        self.tokens: list[dict] = raw.get("tokens", [])
        self._raw = raw

    @property
    def close_time(self) -> Optional[datetime]:
        """Waktu penutupan market sebagai datetime UTC-aware."""
        if not self.end_date_iso:
            return None
        try:
            dt = datetime.fromisoformat(self.end_date_iso.replace("Z", "+00:00"))
            return dt.astimezone(timezone.utc)
        except ValueError:
            return None

    @property
    def seconds_until_close(self) -> float:
        """Sisa detik hingga market tutup; -1 jika tidak diketahui."""
        ct = self.close_time
        if ct is None:
            return -1.0
        now = datetime.now(timezone.utc)
        return (ct - now).total_seconds()

    @property
    def duration_minutes(self) -> float:
        """Perkiraan durasi market berdasarkan metadata (jika ada)."""
        return float(self._raw.get("minimum_order_size", 0))  # placeholder field

    def yes_probability(self) -> float:
        """Probabilitas token 'YES' (0.0–1.0)."""
        for tok in self.tokens:
            if tok.get("outcome", "").upper() == "YES":
                return float(tok.get("price", 0.5))
        return 0.5

    def no_probability(self) -> float:
        """Probabilitas token 'NO'."""
        return 1.0 - self.yes_probability()

    def best_outcome(self) -> tuple[str, float]:
        """Kembalikan ('YES'/'NO', probabilitas) untuk outcome tertinggi."""
        yes_p = self.yes_probability()
        no_p = self.no_probability()
        if yes_p >= no_p:
            return "YES", yes_p
        return "NO", no_p

    def token_id_for(self, outcome: str) -> Optional[str]:
        """Ambil token_id untuk outcome tertentu."""
        for tok in self.tokens:
            if tok.get("outcome", "").upper() == outcome.upper():
                return tok.get("token_id")
        return None

    def __repr__(self) -> str:
        outcome, prob = self.best_outcome()
        secs = self.seconds_until_close
        return (
            f"<Market '{self.question[:40]}' | "
            f"best={outcome}@{prob:.1%} | "
            f"close_in={secs:.0f}s>"
        )


class MarketScanner:
    """
    Memindai semua market aktif Polymarket dan memfilter:
    - Kategori: Crypto
    - Durasi: ~5 menit (berdasarkan waktu tutup)
    - Status: aktif & belum tutup
    """

    CRYPTO_KEYWORDS = {"crypto", "bitcoin", "ethereum", "btc", "eth", "solana", "sol"}

    def __init__(self, client: ClobClient, config: BotConfig):
        self.client = client
        self.config = config

    def _is_crypto_market(self, market: MarketData) -> bool:
        """Cek apakah market termasuk kategori Crypto."""
        cat = market.category.lower()
        question = market.question.lower()
        if "crypto" in cat:
            return True
        return any(kw in question or kw in cat for kw in self.CRYPTO_KEYWORDS)

    def _is_target_duration(self, market: MarketData) -> bool:
        """
        Filter market yang memiliki sisa waktu dalam rentang yang relevan.
        Untuk bot 5 menit: market baru dibuka s.d. maksimum 10 menit tersisa.
        """
        secs = market.seconds_until_close
        if secs < 0:
            return False
        target_secs = self.config.market_duration_min * 60  # 300 detik
        # Terima market yang sisa waktunya antara 10s s.d. 2× durasi target
        return self.config.trigger_window_sec <= secs <= (target_secs * 2)

    def fetch_active_markets(self) -> list[MarketData]:
        """
        Ambil dan filter semua market aktif.
        Returns: list[MarketData] yang lolos filter Crypto + durasi.
        """
        try:
            raw_markets = self.client.get_markets()  # returns list[dict]
        except Exception as exc:
            logger.error("[Scanner] Gagal mengambil daftar market: %s", exc)
            return []

        results: list[MarketData] = []
        for raw in raw_markets:
            if not raw.get("active") or raw.get("closed"):
                continue
            market = MarketData(raw)
            if self._is_crypto_market(market) and self._is_target_duration(market):
                results.append(market)

        logger.info("[Scanner] Ditemukan %d market Crypto aktif.", len(results))
        return results
