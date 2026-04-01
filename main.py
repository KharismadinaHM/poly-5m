"""
main.py — Entry point bot trading Polymarket (Crypto, 5 menit)

Alur utama:
  1. Load config dari .env
  2. Init Polymarket CLOB client
  3. Loop: scan market → pantau countdown → BUY 10 detik terakhir
"""

import asyncio
import logging
import signal
import sys
from datetime import datetime, timezone

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds
from py_clob_client.constants import POLYGON

from bot.config import BotConfig
from bot.logger import TradeLogger, setup_logging
from bot.market_scanner import MarketData, MarketScanner
from bot.trade_executor import TradeExecutor

logger = logging.getLogger(__name__)

# ── Konstanta ──────────────────────────────────────────────────────────────
POLYMARKET_HOST = "https://clob.polymarket.com"
CHAIN_ID = POLYGON  # 137


# ── Inisialisasi client ────────────────────────────────────────────────────

def build_client(cfg: BotConfig) -> ClobClient:
    """Buat dan autentikasi ClobClient."""
    creds = ApiCreds(
        api_key=cfg.api_key,
        api_secret=cfg.api_secret,
        api_passphrase=cfg.api_passphrase,
    )
    client = ClobClient(
        host=POLYMARKET_HOST,
        chain_id=CHAIN_ID,
        key=cfg.private_key,
        creds=creds,
        signature_type=2,       # EIP-712
    )
    logger.info("[Init] ClobClient berhasil dibuat.")
    return client


# ── Loop utama ─────────────────────────────────────────────────────────────

class TradingBot:
    def __init__(self, cfg: BotConfig):
        self.cfg = cfg
        self.client = build_client(cfg)
        self.scanner = MarketScanner(self.client, cfg)
        self.executor = TradeExecutor(self.client, cfg)
        self.trade_logger = TradeLogger()
        self._running = False
        self._traded_ids: set[str] = set()   # Hindari double-trade satu market

    # ── Monitor satu market ────────────────────────────────────────────────
    async def _monitor_market(self, market: MarketData) -> None:
        """
        Polling harga market secara real-time.
        Eksekusi BUY saat sisa waktu ≤ trigger_window_sec.
        """
        cid = market.condition_id

        while self._running and cid not in self._traded_ids:
            secs = market.seconds_until_close

            # Market sudah tutup
            if secs < 0:
                logger.info("[Monitor] Market %s sudah tutup.", cid[:8])
                break

            # Refresh harga terbaru dari API
            try:
                fresh_data = self.client.get_market(cid)
                market = MarketData(fresh_data)
            except Exception as exc:
                logger.warning("[Monitor] Gagal refresh market %s: %s", cid[:8], exc)

            outcome, prob = market.best_outcome()
            logger.debug(
                "[Monitor] %s | best=%s %.1f%% | close_in=%.1fs",
                cid[:8], outcome, prob * 100, secs,
            )

            # TRIGGER: masuk window 10 detik terakhir
            if secs <= self.cfg.trigger_window_sec:
                logger.info(
                    "[TRIGGER] %s | %.1fs tersisa — EKSEKUSI BUY %s @ %.1f%%",
                    cid[:8], secs, outcome, prob * 100,
                )
                result = self.executor.execute(market)
                self.trade_logger.log(result)
                self._traded_ids.add(cid)
                logger.info("[Result] %s", result)
                break

            # Tunggu sebelum polling berikutnya
            await asyncio.sleep(self.cfg.poll_interval_sec)

    # ── Loop pemindai ─────────────────────────────────────────────────────
    async def run(self) -> None:
        self._running = True
        logger.info(
            "═══ Bot Polymarket dimulai ═══  [dry_run=%s | max_bet=%.2f USDC]",
            self.cfg.dry_run, self.cfg.max_bet_usdc,
        )

        active_tasks: dict[str, asyncio.Task] = {}

        while self._running:
            try:
                markets = self.scanner.fetch_active_markets()
            except Exception as exc:
                logger.error("[Loop] Error saat scan market: %s", exc)
                await asyncio.sleep(5)
                continue

            for market in markets:
                cid = market.condition_id
                if cid in self._traded_ids:
                    continue  # Sudah ditangani
                if cid in active_tasks and not active_tasks[cid].done():
                    continue  # Sudah dimonitor
                logger.info("[Loop] Memulai monitor: %s", market)
                task = asyncio.create_task(self._monitor_market(market))
                active_tasks[cid] = task

            # Bersihkan task selesai
            active_tasks = {k: v for k, v in active_tasks.items() if not v.done()}

            # Interval antar scan (lebih panjang dari poll individual)
            await asyncio.sleep(self.cfg.poll_interval_sec * 5)

    def stop(self) -> None:
        logger.info("[Bot] Menghentikan bot...")
        self._running = False


# ── Graceful shutdown ──────────────────────────────────────────────────────

def _register_signals(bot: TradingBot, loop: asyncio.AbstractEventLoop) -> None:
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, bot.stop)


# ── Entry point ────────────────────────────────────────────────────────────

def main() -> None:
    setup_logging(logging.INFO)

    try:
        cfg = BotConfig.from_env()
    except ValueError as exc:
        print(f"\n❌  {exc}\n", file=sys.stderr)
        sys.exit(1)

    logger.info("[Config] %s", cfg)

    bot = TradingBot(cfg)
    loop = asyncio.get_event_loop()
    _register_signals(bot, loop)

    try:
        loop.run_until_complete(bot.run())
    except KeyboardInterrupt:
        pass
    finally:
        logger.info("[Bot] Bot berhenti. Sampai jumpa!")
        loop.close()


if __name__ == "__main__":
    main()
