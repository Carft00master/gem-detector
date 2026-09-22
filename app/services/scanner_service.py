"""
Scanner Execution Service & Background Thread Manager
Spawns and monitors the GemDetectorEngine in a non-blocking background QThread.

Design:
- ScannerWorker runs an asyncio loop in a dedicated QThread.
- On start: calls engine.initialize() once, then loops calling engine.scan_cycle().
- On stop: sets _running=False and calls engine.cleanup() gracefully.
- Errors are surfaced via event_bus.scanner_error and logged — never silently swallowed.
- Candidate data is emitted to event_bus.candidate_updated after each scan_cycle().
"""

import asyncio
from datetime import datetime, timezone
import logging
import time
import traceback
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QThread

from app.application.events import event_bus
from src.main import GemDetectorEngine
from src.config import AppConfig, load_config
from src.version import FROZEN_VERSION_MANIFEST

logger = logging.getLogger(__name__)


def _candidate_to_dict(cand: Any, pred: Any) -> Dict[str, Any]:
    """Convert a (TokenCandidate, BreakoutPredictionOutput) pair into a UI-ready dict."""
    p3m = 0.05
    p_rug = 0.10
    cabal_risk = 0.12
    data_conf = 0.95
    dqs = 85.0
    alert_state = "WATCH"

    try:
        if pred is not None:
            p3m = float(getattr(pred, "prob_3m", None) or
                        getattr(pred, "p_reach_3m", None) or
                        getattr(pred, "predicted_prob_3m", None) or 0.05)
            p_rug = float(getattr(pred, "p_rug", None) or
                          getattr(pred, "predicted_prob_rug", None) or 0.10)
            cabal_risk = float(getattr(pred, "cabal_risk_score", None) or 0.12)
            data_conf = float(getattr(pred, "data_confidence_score", None) or
                              getattr(pred, "data_confidence", None) or 0.95)
            alert_state = str(getattr(pred, "alert_state", None) or
                              getattr(pred, "signal_state", None) or "WATCH")
    except Exception:
        pass

    try:
        liq = float(cand.liquidity_usd or 0.0)
        max_pos_2pct = liq * 0.02
    except Exception:
        max_pos_2pct = 0.0

    return {
        "token_address": getattr(cand, "address", "Unknown"),
        "symbol": getattr(cand, "symbol", "SYM"),
        "name": getattr(cand, "name", ""),
        "chain": getattr(cand, "chain", "solana"),
        "venue": getattr(cand, "dex_id", "pumpfun"),
        "market_cap_usd": float(getattr(cand, "market_cap_usd", 0.0) or 0.0),
        "price_usd": float(getattr(cand, "price_usd", 0.0) or 0.0),
        "liquidity_usd": float(getattr(cand, "liquidity_usd", 0.0) or 0.0),
        "volume_5m_usd": float(getattr(cand, "volume_5m_usd", 0.0) or 0.0),
        "volume_1h_usd": float(getattr(cand, "volume_1h_usd", 0.0) or 0.0),
        "txns_5m_buys": int(getattr(cand, "txns_5m_buys", 0) or 0),
        "txns_5m_sells": int(getattr(cand, "txns_5m_sells", 0) or 0),
        "unique_buyers": int(getattr(cand, "unique_buyers_1h", 0) or 0),
        "unique_sellers": int(getattr(cand, "unique_sellers_1h", 0) or 0),
        "token_age_minutes": float(getattr(cand, "age_minutes", 0.0) or 0.0),
        "p_reach_3m": p3m,
        "p_rug": p_rug,
        "cabal_risk": cabal_risk,
        "data_confidence": data_conf,
        "discovery_quality": dqs,
        "signal_state": alert_state,
        "max_position_2pct_usd": max_pos_2pct,
        "discovery_timestamp": datetime.now(timezone.utc).isoformat(),
    }


class ScannerWorker(QThread):
    """
    Background QThread that wraps GemDetectorEngine in a dedicated asyncio event loop.
    Initializes the engine once, then loops calling scan_cycle() until stopped.
    Includes automatic session reinitialization after hibernation/network interruption.
    """

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self._running = False
        self._engine: Optional[GemDetectorEngine] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def run(self):
        """QThread entry point — creates a dedicated asyncio loop and runs the engine."""
        self._running = True
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._async_main())
        except Exception as e:
            err_msg = f"Scanner worker fatal error: {e}\n{traceback.format_exc()}"
            logger.error(err_msg)
            event_bus.scanner_error.emit(str(e))
        finally:
            self._running = False
            try:
                if self._loop and not self._loop.is_closed():
                    self._loop.close()
            except Exception:
                pass
            event_bus.scanner_status_changed.emit("STOPPED", "PAPER")
            logger.info("Scanner worker thread exited.")

    async def _async_main(self):
        """Initialize engine once, then scan in a loop until stopped."""
        logger.info("Initializing scanner engine...")
        self._engine = GemDetectorEngine(self.config, use_calibrated_ml=True)

        try:
            await self._engine.initialize()
        except Exception as e:
            logger.error(f"Engine initialization failed: {e}")
            event_bus.scanner_error.emit(f"Engine init failed: {e}")
            return

        logger.info(f"Scanner engine initialized. Starting scan loop on chains: {self.config.scanner.active_chains}")

        consecutive_errors = 0
        consecutive_empty_cycles = 0  # Track silent empty-feed failures
        MAX_CONSECUTIVE_ERRORS = 5
        MAX_EMPTY_CYCLES = 2  # Fast failover: after 2 cycles of zero raw API results, recycle immediately

        while self._running:
            self._last_cycle_time = time.monotonic()
            try:
                results = await self._engine.scan_cycle()
                consecutive_errors = 0  # Reset error counter on success

                # Detect silently dead session via empty feed (post-hibernation / stale TCP)
                raw_count = getattr(self._engine, "_last_raw_candidate_count", None)
                if raw_count is not None:
                    if raw_count == 0:
                        consecutive_empty_cycles += 1
                    else:
                        consecutive_empty_cycles = 0  # API is alive — reset
                else:
                    if len(results) == 0:
                        consecutive_empty_cycles += 1
                    else:
                        consecutive_empty_cycles = 0

                if consecutive_empty_cycles >= MAX_EMPTY_CYCLES:
                    logger.warning(
                        f"Empty feed detected for {consecutive_empty_cycles} consecutive cycles "
                        f"— recycling network sessions immediately..."
                    )
                    event_bus.log_emitted.emit(
                        datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                        "WARNING", "ScannerWorker",
                        f"Empty feed for {consecutive_empty_cycles} cycles — recycling network connections..."
                    )
                    try:
                        if hasattr(self._engine, "recycle_sessions"):
                            await self._engine.recycle_sessions()
                        else:
                            await self._engine.cleanup()
                            self._engine = GemDetectorEngine(self.config, use_calibrated_ml=True)
                            await self._engine.initialize()
                        consecutive_empty_cycles = 0
                        consecutive_errors = 0
                        logger.info("Engine session recycled successfully.")
                        event_bus.log_emitted.emit(
                            datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                            "INFO", "ScannerWorker",
                            "Network sessions recycled — scan loop active."
                        )
                    except Exception as reinit_err:
                        logger.error(f"Engine session recycle failed: {reinit_err}")
                        event_bus.scanner_error.emit(f"Engine session recycle failed: {reinit_err}")
                        break

                # Emit each evaluated candidate to the UI
                for item in results:
                    try:
                        if isinstance(item, (list, tuple)) and len(item) >= 2:
                            cand, pred = item[0], item[1]
                        else:
                            continue
                        cand_dict = _candidate_to_dict(cand, pred)
                        event_bus.candidate_updated.emit(cand_dict)
                    except Exception as emit_err:
                        logger.debug(f"Candidate emit error: {emit_err}")

                # Emit newly opened paper trades
                for trade in getattr(self._engine, "_newly_opened_trades", []):
                    try:
                        from dataclasses import asdict
                        trade_dict = asdict(trade) if hasattr(trade, "__dataclass_fields__") else (trade.to_dict() if hasattr(trade, "to_dict") else vars(trade))
                        event_bus.paper_trade_opened.emit(trade_dict)
                        event_bus.log_emitted.emit(
                            datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                            "INFO", "ScannerWorker",
                            f"Paper Trade Opened: {trade.symbol} (${trade.position_size_usd:.0f} at MC ${trade.market_cap_usd:,.0f})"
                        )
                    except Exception as pt_err:
                        logger.debug(f"Trade open emit error: {pt_err}")

                # Emit newly closed paper trades
                for trade in getattr(self._engine, "_newly_closed_trades", []):
                    try:
                        from dataclasses import asdict
                        trade_dict = asdict(trade) if hasattr(trade, "__dataclass_fields__") else (trade.to_dict() if hasattr(trade, "to_dict") else vars(trade))
                        event_bus.paper_trade_closed.emit(trade_dict)
                        pnl_val = getattr(trade, "net_realized_pnl_usd", 0.0)
                        pnl_str = f"+${pnl_val:.2f}" if pnl_val >= 0 else f"-${abs(pnl_val):.2f}"
                        event_bus.log_emitted.emit(
                            datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                            "INFO", "ScannerWorker",
                            f"Paper Trade Closed: {trade.symbol} (Reason: {trade.exit_reason}, P&L: {pnl_str})"
                        )
                    except Exception as pt_err:
                        logger.debug(f"Trade close emit error: {pt_err}")

                event_bus.log_emitted.emit(
                    datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                    "INFO", "ScannerWorker",
                    f"Scan cycle complete — {len(results)} candidates evaluated."
                )

            except asyncio.CancelledError:
                break
            except Exception as e:
                consecutive_errors += 1
                consecutive_empty_cycles = 0  # Hard error resets the empty counter
                logger.error(f"Scan cycle error ({consecutive_errors}/{MAX_CONSECUTIVE_ERRORS}): {e}")
                event_bus.log_emitted.emit(
                    datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                    "ERROR", "ScannerWorker", f"Scan cycle error: {e}"
                )

                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    logger.warning("Too many consecutive errors — reinitializing engine session...")
                    event_bus.log_emitted.emit(
                        datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                        "WARNING", "ScannerWorker",
                        "Network session stale (possible hibernation). Reinitializing engine..."
                    )
                    try:
                        await self._engine.cleanup()
                    except Exception:
                        pass
                    try:
                        self._engine = GemDetectorEngine(self.config, use_calibrated_ml=True)
                        await self._engine.initialize()
                        consecutive_errors = 0
                        consecutive_empty_cycles = 0
                        logger.info("Engine reinitialized successfully after error recovery.")
                        event_bus.log_emitted.emit(
                            datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                            "INFO", "ScannerWorker", "Engine session reinitialized — resuming scan loop."
                        )
                    except Exception as reinit_err:
                        logger.error(f"Engine reinitialization failed: {reinit_err}")
                        event_bus.scanner_error.emit(f"Engine reinitialization failed: {reinit_err}")
                        break

                # Exponential back-off on repeated errors (max 60s)
                backoff_sec = min(5 * consecutive_errors, 60)
                try:
                    await asyncio.sleep(backoff_sec)
                except asyncio.CancelledError:
                    break
                continue

            # Wait for next poll interval, but respect stop signal
            # Monotonic sleep/wake watchdog: if time elapsed during sleep significantly exceeds
            # poll_interval_sec, the machine was suspended/hibernated.
            sleep_start = time.monotonic()
            poll_interval = self.config.scanner.poll_interval_sec
            try:
                await asyncio.sleep(poll_interval)
            except asyncio.CancelledError:
                break

            sleep_elapsed = time.monotonic() - sleep_start
            if sleep_elapsed > (poll_interval * 2.0):
                logger.warning(
                    f"System wake-from-sleep detected! (slept {sleep_elapsed:.1f}s vs expected {poll_interval:.1f}s). "
                    f"Immediately recycling network sessions..."
                )
                event_bus.log_emitted.emit(
                    datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                    "WARNING", "ScannerWorker",
                    f"System wake-from-sleep detected ({sleep_elapsed:.1f}s pause) — recycling stale network connections..."
                )
                try:
                    if hasattr(self._engine, "recycle_sessions"):
                        await self._engine.recycle_sessions()
                    consecutive_empty_cycles = 0
                    consecutive_errors = 0
                    logger.info("Post-sleep network session recycle completed.")
                except Exception as wake_err:
                    logger.error(f"Post-sleep session recycle error: {wake_err}")

        # Graceful cleanup
        logger.info("Scanner worker stopping — cleaning up engine...")
        try:
            await self._engine.cleanup()
        except Exception as e:
            logger.warning(f"Engine cleanup error (non-fatal): {e}")

    def request_stop(self):
        """Signal the async loop to stop gracefully."""
        self._running = False
        # Cancel all pending tasks in the event loop
        if self._loop and not self._loop.is_closed():
            try:
                for task in asyncio.all_tasks(self._loop):
                    task.cancel()
            except Exception:
                pass

    def is_truly_alive(self) -> bool:
        """Returns True only if the thread is alive AND the asyncio event loop is healthy.
        A thread can pass isRunning() after hibernation even though its asyncio
        loop is stalled or closed — this method detects that zombie state.
        """
        if not self.isRunning():
            return False
        if self._loop is None or self._loop.is_closed():
            return False
        if not self._running:
            return False
        # Check if the cycle watchdog has stalled for more than 45s
        if hasattr(self, "_last_cycle_time"):
            if time.monotonic() - self._last_cycle_time > 45.0:
                logger.warning("ScannerWorker cycle stalled for >45s — considered zombie.")
                return False
        return True


class ScannerService:
    """Application service layer wrapping the background ScannerWorker."""

    def __init__(self, config: Optional[AppConfig] = None):
        self.config = config or load_config(
            settings_path="config/settings.yaml",
            presets_path="config/presets.yaml",
        )
        self.worker: Optional[ScannerWorker] = None
        self.status = "STOPPED"
        self.mode = "PAPER"
        self.cached_candidates: Dict[str, Dict[str, Any]] = {}
        self._init_cached_candidates()

        # Wire candidate updates to local cache
        event_bus.candidate_updated.connect(self._on_candidate_updated)

    def _init_cached_candidates(self):
        """Pre-populate cache from stored shadow tokens for immediate UI responsiveness."""
        try:
            from src.research.shadow import ShadowUniverseLogger
            tokens = ShadowUniverseLogger().load_recent_shadow_tokens(limit=100)
            for t in tokens:
                addr = t.get("token_address", "Unknown")
                self.cached_candidates[addr] = t
        except Exception as e:
            logger.warning(f"Could not pre-populate candidates: {e}")

    def _on_candidate_updated(self, cand_dict: Dict[str, Any]):
        """Keep local cache updated so get_active_candidates() is always fresh."""
        addr = cand_dict.get("token_address", "Unknown")
        self.cached_candidates[addr] = cand_dict
        # Prune older candidates if dictionary exceeds 300 items to prevent unbounded memory growth
        if len(self.cached_candidates) > 300:
            excess = len(self.cached_candidates) - 300
            for k in list(self.cached_candidates.keys())[:excess]:
                del self.cached_candidates[k]

    def _force_stop_stale_worker(self):
        """Terminate any stale/zombie worker thread before starting a new one.
        Called automatically on start() after hibernation or crash recovery.
        """
        if self.worker is None:
            return
        try:
            self.worker.request_stop()
        except Exception:
            pass
        # Give it 3s to exit gracefully, then forcibly terminate
        if not self.worker.wait(3000):
            logger.warning("Stale worker did not exit in 3s — force terminating.")
            try:
                self.worker.terminate()
                self.worker.wait(2000)
            except Exception:
                pass
        self.worker = None

    def start(self, mode: str = "PAPER") -> bool:
        # Always check for zombie/stale worker first (key fix for post-hibernation)
        if self.worker is not None:
            if not self.worker.is_truly_alive():
                logger.warning("Detected stale/zombie scanner worker — force-killing before restart.")
                event_bus.log_emitted.emit(
                    datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                    "WARNING", "ScannerService",
                    "Stale scanner session detected (wake from hibernation). Restarting cleanly..."
                )
                self._force_stop_stale_worker()
            else:
                logger.warning("Scanner is already running.")
                return False

        self.mode = mode
        self.status = "RUNNING"
        self.worker = ScannerWorker(self.config)
        self.worker.start()

        event_bus.scanner_status_changed.emit("RUNNING", self.mode)
        event_bus.log_emitted.emit(
            datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "INFO", "ScannerService",
            f"Scanner started in {self.mode} mode on chains: {self.config.scanner.active_chains}"
        )
        logger.info(f"ScannerService started in {self.mode} mode.")
        return True

    def stop(self) -> bool:
        if not self.worker or not self.worker.isRunning():
            logger.warning("Scanner is not running — nothing to stop.")
            # Reset UI state anyway
            self.status = "STOPPED"
            event_bus.scanner_status_changed.emit("STOPPED", self.mode)
            return False

        self.status = "STOPPED"
        # Signal the worker to stop — non-blocking.
        # The worker emits scanner_status_changed("STOPPED") when it fully exits,
        # which updates the UI buttons via the event bus.
        self.worker.request_stop()
        event_bus.log_emitted.emit(
            datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "INFO", "ScannerService", "Stop requested — waiting for scanner to finish current cycle..."
        )
        logger.info("Stop requested — worker will finish current cycle and exit.")
        return True

    def get_status(self) -> str:
        if self.worker and self.worker.is_truly_alive():
            return "RUNNING"
        return self.status

    def get_mode(self) -> str:
        return self.mode

    def get_active_candidates(self) -> List[Dict[str, Any]]:
        return list(self.cached_candidates.values())
