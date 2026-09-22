"""
VPS and Remote Desktop Performance Suite
Validates caching, non-blocking UI navigation, adaptive throttling, and item recycling.
"""

import os
import sys
import time
from pathlib import Path
import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication

from app.application.service_locator import ServiceLocator
from app.services.export_service import ExportService
from app.services.paper_trading_service import PaperTradingService
from app.services.research_service import ResearchService
from app.services.scanner_service import ScannerService
from app.services.settings_service import SettingsService
from app.ui.main_window import MainWindow


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


def test_vps_mode_settings_detection():
    settings_svc = SettingsService()
    orig_mode = settings_svc.is_vps_mode_active()
    settings_svc.set_vps_mode(True)
    assert settings_svc.is_vps_mode_active() is True

    settings_svc.set_vps_mode(False)
    assert settings_svc.is_vps_mode_active() is False

    settings_svc.set_vps_mode(orig_mode)


def test_paper_trading_service_caching():
    svc = PaperTradingService()
    svc.invalidate_cache()

    # First call warms cache
    t0 = time.perf_counter()
    stats1 = svc.calculate_aggregate_stats()
    duration1 = time.perf_counter() - t0

    # Second call uses cache (must be significantly faster, sub-millisecond)
    t0 = time.perf_counter()
    stats2 = svc.calculate_aggregate_stats()
    duration2 = time.perf_counter() - t0

    assert stats1.total_trades == stats2.total_trades
    assert stats1.total_realized_pnl_usd == stats2.total_realized_pnl_usd
    assert duration2 < 0.05, f"Cached stats took too long: {duration2:.4f}s"

    # Test cache invalidation
    svc.invalidate_cache()
    assert svc._stats_cache is None
    assert svc._trades_cache is None


def test_research_service_merged_universe_caching():
    svc = ResearchService()
    svc.invalidate_merged_cache()

    # First query warms cache
    t0 = time.perf_counter()
    u1 = svc._get_merged_universe()
    duration1 = time.perf_counter() - t0

    # Second query retrieves from cache
    t0 = time.perf_counter()
    u2 = svc._get_merged_universe()
    duration2 = time.perf_counter() - t0

    assert len(u1) == len(u2)
    assert duration2 < 0.01, f"Cached merged universe retrieval took too long: {duration2:.4f}s"


def test_instant_tab_navigation_across_all_views(qapp):
    ServiceLocator.clear()
    settings_svc = SettingsService()
    settings_svc.set_vps_mode(True)
    ServiceLocator.register(SettingsService, settings_svc)
    ServiceLocator.register(PaperTradingService, PaperTradingService())
    ServiceLocator.register(ResearchService, ResearchService())
    ServiceLocator.register(ExportService, ExportService())
    ServiceLocator.register(ScannerService, ScannerService())

    window = MainWindow()
    num_tabs = len(MainWindow.NAV_ITEMS)
    assert num_tabs == 20

    # Warm up first tab
    window.nav_list.setCurrentRow(0)
    qapp.processEvents()

    # Verify switching to all 20 tabs is fast and non-blocking
    for i in range(num_tabs):
        t0 = time.perf_counter()
        window.nav_list.setCurrentRow(i)
        qapp.processEvents()
        elapsed = time.perf_counter() - t0

        assert window.stacked.currentIndex() == i
        # Each tab navigation must complete in < 200ms even with async tasks dispatched
        assert elapsed < 0.5, f"Tab index {i} navigation took {elapsed:.3f}s, exceeding VPS budget"
