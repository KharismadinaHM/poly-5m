"""
trade_executor.py — Eksekusi order dengan retry, dry-run, dan manajemen error
"""

import logging
import time
from dataclasses import dataclass
from typing import Optional

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import MarketOrderArgs, OrderType

from .config import BotConfig
from .market_scanner import MarketData

logger = logging.getLogger(__name__)


@dataclass
class TradeResult:
    success: bool
    market_id: str
    outcome: str
    probability: float
    amount_usdc: float
    order_id: Optional[str] = None
    error: Optional[str] = None
    dry_run: bool = False

    def __repr__(self) -> str:
        status = "DRY-RUN" if self.dry_run else ("OK" if self.success else "GAGAL")
        return (
            f"[{status}] {self.outcome}@{self.probability:.1%} "
            f"| {self.amount_usdc} USDC "
            f"| order={self.order_id or self.error}"
        )


class RiskManager:
    """Validasi parameter sebelum eksekusi."""

    def __init__(self, config: BotConfig):
        self.config = config

    def validate(self, market: MarketData, outcome: str, probability: float) -> tuple[bool, str]:
        """
        Kembalikan (ok, alasan_penolakan).
        """
        if probability < self.config.min_probability:
            return False, (
                f"Probabilitas {probability:.1%} < minimum "
                f"{self.config.min_probability:.1%}"
            )
        token_id = market.token_id_for(outcome)
        if not token_id:
            return False, f"Token ID untuk '{outcome}' tidak ditemukan"
        secs = market.seconds_until_close
        if secs > self.config.trigger_window_sec:
            return False, f"Sisa waktu {secs:.1f}s > window {self.config.trigger_window_sec}s"
        return True, ""


class TradeExecutor:
    """
    Mengirim order ke Polymarket CLOB API.
    Mendukung:
    - Dry-run (simulasi tanpa kirim)
    - Retry otomatis dengan exponential backoff
    - Validasi risiko sebelum eksekusi
    """

    def __init__(self, client: ClobClient, config: BotConfig):
        self.client = client
        self.config = config
        self.risk = RiskManager(config)

    def execute(self, market: MarketData) -> TradeResult:
        """
        Titik masuk utama. Pilih outcome terbaik, validasi, lalu kirim order.
        """
        outcome, probability = market.best_outcome()
        amount = self.config.max_bet_usdc

        # Validasi risiko
        ok, reason = self.risk.validate(market, outcome, probability)
        if not ok:
            logger.warning("[Executor] Trade ditolak — %s", reason)
            return TradeResult(
                success=False,
                market_id=market.condition_id,
                outcome=outcome,
                probability=probability,
                amount_usdc=amount,
                error=reason,
            )

        logger.info(
            "[Executor] Bersiap BUY %s | market=%s | prob=%.1f%% | amount=%.2f USDC",
            outcome, market.condition_id[:8], probability * 100, amount,
        )

        if self.config.dry_run:
            return self._dry_run_result(market, outcome, probability, amount)

        return self._send_with_retry(market, outcome, probability, amount)

    # ------------------------------------------------------------------
    def _send_with_retry(
        self,
        market: MarketData,
        outcome: str,
        probability: float,
        amount: float,
    ) -> TradeResult:
        """Kirim order dengan retry hingga max_retries kali."""
        token_id = market.token_id_for(outcome)
        last_error: Optional[str] = None

        for attempt in range(1, self.config.max_retries + 1):
            try:
                order_args = MarketOrderArgs(
                    token_id=token_id,
                    amount=amount,
                )
                signed_order = self.client.create_market_order(order_args)
                resp = self.client.post_order(signed_order, OrderType.FOK)

                order_id = resp.get("orderID") or resp.get("order_id", "N/A")
                logger.info("[Executor] Order berhasil: %s", order_id)
                return TradeResult(
                    success=True,
                    market_id=market.condition_id,
                    outcome=outcome,
                    probability=probability,
                    amount_usdc=amount,
                    order_id=order_id,
                )

            except Exception as exc:
                last_error = str(exc)
                logger.warning(
                    "[Executor] Percobaan %d/%d gagal: %s",
                    attempt, self.config.max_retries, exc,
                )
                if attempt < self.config.max_retries:
                    delay = self.config.retry_delay_sec * (2 ** (attempt - 1))
                    time.sleep(delay)

        return TradeResult(
            success=False,
            market_id=market.condition_id,
            outcome=outcome,
            probability=probability,
            amount_usdc=amount,
            error=f"Gagal setelah {self.config.max_retries} percobaan: {last_error}",
        )

    def _dry_run_result(
        self,
        market: MarketData,
        outcome: str,
        probability: float,
        amount: float,
    ) -> TradeResult:
        logger.info(
            "[DRY-RUN] SKIP eksekusi nyata — BUY %s %.2f USDC @ %.1f%%",
            outcome, amount, probability * 100,
        )
        return TradeResult(
            success=True,
            market_id=market.condition_id,
            outcome=outcome,
            probability=probability,
            amount_usdc=amount,
            order_id="DRY_RUN_ORDER",
            dry_run=True,
        )
