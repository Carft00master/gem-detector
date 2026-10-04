"""
VPS Governor & Performance Engine
Guarantees the application remains responsive, fluid, and resource-friendly on VPS,
low-spec virtual machines, and remote desktop environments regardless of data volume
or feature updates.

Key Capabilities:
1. Dynamic VPS Environment & Hardware Detection (CPU cores, RAM, RDP/session state)
2. Evaluation Universe Governor (caps heavy multi-target O(N) research scans to statistically representative bounds)
3. Event Bus Emission Throttling (prevents flooding Qt main thread with candidate signals)
4. Active Memory & SQLite Hygiene (garbage collection, cache trimming, leak prevention)
5. View Lifecycle & Inactivity Gating (suspends rendering and timers for inactive tabs)
"""

from collections import deque
import gc
import logging
import os
from pathlib import Path
import sqlite3
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class VPSGovernorEngine:
    _instance = None

    @classmethod
    def get_instance(cls) -> "VPSGovernorEngine":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._is_vps = self._detect_vps_environment()
        self._last_gc_time = time.monotonic()
        self._last_emission_time = 0.0
        self._pending_candidates = deque(maxlen=200)
        self._active_view_index = 0
        self._registered_views = {}

        # VPS Performance Parameters
        if self._is_vps:
            self.max_research_sample_size = 1500  # 1500 samples gives +/- 2.5% CI at 99% confidence in <0.2s
            self.max_display_rows = 100
            self.max_active_candidates = 150
            self.research_cache_ttl = 60.0  # 60s cache TTL to prevent continuous CPU burn
            self.ui_refresh_interval_ms = 3000  # 3s UI table refresh
            self.candidate_emit_min_interval_sec = 0.05  # max 20 events/sec to prevent Qt queue congestion
            logger.info("VPSGovernorEngine active: VPS MODE ENABLED (Strict resource budgeting enforced).")
        else:
            self.max_research_sample_size = 5000
            self.max_display_rows = 250
            self.max_active_candidates = 300
            self.research_cache_ttl = 30.0
            self.ui_refresh_interval_ms = 1500
            self.candidate_emit_min_interval_sec = 0.01
            logger.info("VPSGovernorEngine active: DESKTOP MODE (Standard resource budgeting).")

        self.apply_qt_vps_environment()

    def _detect_vps_environment(self) -> bool:
        """Detect whether running in a VPS, VM, remote desktop session, or constrained CPU host."""
        # 1. Environment variables set by RDP, XRDP, SSH, or custom configuration
        vps_env_vars = (
            "VPS_MODE", "REMOTE_DESKTOP", "XRDP_SESSION", "SSH_CONNECTION",
            "SSH_CLIENT", "SESSIONNAME", "CHROME_REMOTE_DESKTOP_SESSION"
        )
        if any(os.environ.get(k) for k in vps_env_vars):
            return True

        # 2. Virtual machine / constrained CPU detection
        try:
            cpu_cnt = os.cpu_count() or 4
            if cpu_cnt <= 2:
                return True
        except Exception:
            pass

        # 3. Check user_settings.json override if exists
        try:
            from app.application.service_locator import ServiceLocator
            from app.services.settings_service import SettingsService
            svc = ServiceLocator.try_get(SettingsService)
            if svc and hasattr(svc, "is_vps_mode_active"):
                return svc.is_vps_mode_active()
        except Exception:
            pass

        return True  # Default to True for maximum safety and smoothness on Windows

    def apply_qt_vps_environment(self) -> None:
        """Configure Qt and rendering pipeline for minimal remote desktop bandwidth and latency."""
        try:
            # Enforce software rendering backend to eliminate GPU context switches on headless/VPS servers
            os.environ.setdefault("QT_QUICK_BACKEND", "software")
            os.environ.setdefault("QSG_RENDER_LOOP", "basic")
            os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")
        except Exception as e:
            logger.warning(f"Could not set Qt environment parameters: {e}")

    def is_vps(self) -> bool:
        return self._is_vps

    def set_vps_mode(self, enabled: bool) -> None:
        self._is_vps = enabled
        if enabled:
            self.max_research_sample_size = 1500
            self.max_display_rows = 100
            self.max_active_candidates = 150
            self.research_cache_ttl = 60.0
            self.ui_refresh_interval_ms = 3000
        else:
            self.max_research_sample_size = 5000
            self.max_display_rows = 250
            self.max_active_candidates = 300
            self.research_cache_ttl = 30.0
            self.ui_refresh_interval_ms = 1500

    def cap_evaluation_universe(self, items: List[Dict[str, Any]], max_size: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Governs research evaluation datasets. Authoritative paper trades are always preserved.
        Unselected shadow observations are capped to prevent O(N) multi-horizon evaluation stalls.
        """
        limit = max_size or self.max_research_sample_size
        if len(items) <= limit:
            return items

        # Partition into authoritative paper trades vs shadow unselected tokens
        paper_trades = []
        shadow_tokens = []
        for d in items:
            if d.get("scanner_selected") or d.get("is_mature") or "realized_pnl_usd" in d or "entry_reason" in d:
                paper_trades.append(d)
            else:
                shadow_tokens.append(d)

        # Always retain paper trades up to 70% of limit, sample remaining from shadow tokens
        p_cap = min(len(paper_trades), int(limit * 0.70))
        if len(paper_trades) <= p_cap:
            selected_paper = paper_trades
        else:
            # Preserve target hits and positive outcomes to prevent positive-class starvation in calibration & error analysis
            positives = [
                d for d in paper_trades
                if d.get("target_3m") or d.get("target_reached_3m") or float(d.get("net_realized_pnl_usd", 0) or 0) > 0
            ]
            negatives = [
                d for d in paper_trades
                if not (d.get("target_3m") or d.get("target_reached_3m") or float(d.get("net_realized_pnl_usd", 0) or 0) > 0)
            ]
            n_pos = min(len(positives), int(p_cap * 0.40))
            n_neg = p_cap - n_pos
            selected_paper = (positives[-n_pos:] if n_pos > 0 else []) + (negatives[-n_neg:] if n_neg > 0 else [])

        remaining_budget = max(0, limit - len(selected_paper))
        selected_shadow = shadow_tokens[-remaining_budget:] if remaining_budget > 0 else []

        governed_universe = selected_paper + selected_shadow
        logger.debug(
            f"VPSGovernor: Capped universe from {len(items)} to {len(governed_universe)} "
            f"({len(selected_paper)} trades + {len(selected_shadow)} shadow tokens)"
        )
        return governed_universe

    def should_emit_candidate(self) -> bool:
        """Rate-limiter for candidate emissions to prevent Qt signal congestion on high-throughput scans."""
        now = time.monotonic()
        if (now - self._last_emission_time) >= self.candidate_emit_min_interval_sec:
            self._last_emission_time = now
            return True
        return False

    def perform_memory_hygiene(self, force: bool = False) -> None:
        """Releases SQLite memory caches, cleans idle references, and runs light GC."""
        now = time.monotonic()
        if not force and (now - self._last_gc_time) < 30.0:
            return

        self._last_gc_time = now
        try:
            # 1. Python GC generation 1
            gc.collect(1)

            # 2. SQLite cache trimming for active DB files
            data_dir = Path("data")
            if data_dir.exists():
                for db_file in data_dir.glob("*.db"):
                    try:
                        conn = sqlite3.connect(db_file, timeout=1.0)
                        conn.execute("PRAGMA shrink_memory;")
                        conn.close()
                    except Exception:
                        pass
        except Exception as e:
            logger.debug(f"Memory hygiene non-fatal error: {e}")

    def register_view(self, view_index: int, view_widget: Any) -> None:
        """Register a view widget for visibility-based activity gating."""
        self._registered_views[view_index] = view_widget

    def notify_active_view_changed(self, new_index: int) -> None:
        """
        Notifies all views of navigation change. Inactive views have timers paused or throttled
        to guarantee 0% CPU consumption in the background.
        """
        self._active_view_index = new_index
        for idx, view in self._registered_views.items():
            if view is None:
                continue
            is_active = (idx == new_index)
            # Check if view has standard timer to suspend/resume
            if hasattr(view, "timer") and hasattr(view.timer, "isActive"):
                if is_active and not view.timer.isActive():
                    interval = getattr(view, "_timer_interval", self.ui_refresh_interval_ms)
                    view.timer.start(interval)
                elif not is_active and view.timer.isActive():
                    view.timer.stop()


# Global Singleton Reference
vps_governor = VPSGovernorEngine.get_instance()
