"""
Unit and Integration Tests for Desktop Application, Service Layer, and GUI Views
"""

import os
import sys
from pathlib import Path
import pytest

# Ensure headless offscreen platform for Qt testing
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication

from app.application.events import event_bus
from app.application.service_locator import ServiceLocator
from app.services.export_service import ExportService
from app.services.paper_trading_service import PaperTradingService
from app.services.research_service import ResearchService
from app.services.scanner_service import ScannerService
from app.services.settings_service import SettingsService
from app.ui.components.gauge_widget import GaugeWidget
from app.ui.components.stat_card import StatCard
from app.ui.components.status_bar import TerminalStatusBar
from app.ui.main_window import MainWindow
from src.version import FROZEN_VERSION_MANIFEST


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


def test_service_locator_registration_and_retrieval():
    ServiceLocator.clear()
    settings_svc = SettingsService()
    ServiceLocator.register(SettingsService, settings_svc)

    retrieved = ServiceLocator.get(SettingsService)
    assert retrieved is settings_svc


def test_settings_service_credential_masking():
    masked = SettingsService.mask_secret("1234567890abcdef")
    assert masked == "1234****cdef"
    assert "567890ab" not in masked

    empty_masked = SettingsService.mask_secret("")
    assert empty_masked == ""


def test_paper_trading_service_aggregate_stats():
    svc = PaperTradingService()
    stats = svc.calculate_aggregate_stats()
    assert isinstance(stats.total_trades, int)
    assert isinstance(stats.win_rate_pct, float)
    assert stats.status_label == "PAPER / SIMULATION"


def test_research_service_queries():
    svc = ResearchService()
    reg = svc.get_population_registry_summary()
    assert reg.counts.full_universe >= 53
    assert reg.invariants_validated is True
    # Partition Invariant: Full Universe = Captured + Missed + Uncertain
    c = reg.counts
    assert c.full_universe == (c.capture_confirmed + c.discovery_missed + c.discovery_uncertain)

    funnel = svc.get_opportunity_funnel()
    assert len(funnel.stages) == 11

    maturity = svc.get_outcome_maturity_dashboard()
    assert len(maturity.horizon_summary_rows) > 0

    surv = svc.get_survival_analysis("TARGET_3M")
    assert len(surv.intervals) == 6


def test_export_service_generation(tmp_path):
    svc = ExportService(export_dir=tmp_path)
    csv_path = svc.export_shadow_universe_csv()
    assert csv_path.exists()
    assert csv_path.stat().st_size > 0

    report_path = svc.generate_comprehensive_research_report()
    assert report_path.exists()
    content = report_path.read_text(encoding="utf-8")
    assert "Frozen" in content or "FROZEN" in content
    assert "Quantitative Research & Validation Audit Report" in content


def test_pyside6_components_instantiation(qapp):
    card = StatCard("Test Metric", "$1,000", "Subtitle", "#10b981")
    assert card.title_lbl.text() == "TEST METRIC"
    assert card.value_lbl.text() == "$1,000"

    gauge = GaugeWidget("Risk Score", 0.35, 0.0, 1.0, is_risk=True)
    assert gauge.label_lbl.text() == "Risk Score"
    assert gauge.value_lbl.text() == "35.0%"

    status_bar = TerminalStatusBar()
    assert "SCANNER" in status_bar.lbl_status.text()
    assert "SOLANA" in status_bar.lbl_sol.text()


def test_pyside6_main_window_and_views_instantiation(qapp):
    # Setup full services
    ServiceLocator.clear()
    ServiceLocator.register(SettingsService, SettingsService())
    ServiceLocator.register(PaperTradingService, PaperTradingService())
    ServiceLocator.register(ResearchService, ResearchService())
    ServiceLocator.register(ExportService, ExportService())
    ServiceLocator.register(ScannerService, ScannerService())

    window = MainWindow()
    assert window.windowTitle() != ""
    num_tabs = len(MainWindow.NAV_ITEMS)
    assert window.stacked.count() == num_tabs

    # Verify switching across all tabs without exception
    for i in range(num_tabs):
        window.nav_list.setCurrentRow(i)
        assert window.stacked.currentIndex() == i


    # Test detail view token loading
    window.view_detail.load_token("tok_live_1")
    assert "tok_live_1" in window.view_detail.lbl_token_title.text() or "TOKEN NOT FOUND" in window.view_detail.lbl_token_title.text()


def test_event_bus_signals():
    received = []

    def on_status_changed(status, mode):
        received.append((status, mode))

    event_bus.scanner_status_changed.connect(on_status_changed)
    event_bus.scanner_status_changed.emit("RUNNING", "PAPER")

    assert len(received) == 1
    assert received[0] == ("RUNNING", "PAPER")
