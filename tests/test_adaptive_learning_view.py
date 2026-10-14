"""
Test for AdaptiveLearningView UI and Live Challenger Monitor
"""

import pytest
from PySide6.QtWidgets import QApplication
from app.ui.views.adaptive_learning_view import AdaptiveLearningView
from app.application.events import event_bus


from app.application.service_locator import ServiceLocator
from app.services.research_service import ResearchService


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    if ServiceLocator.try_get(ResearchService) is None:
        ServiceLocator.register(ResearchService, ResearchService())
    return app


def test_adaptive_learning_view_init(qapp):
    view = AdaptiveLearningView()
    assert view is not None
    assert hasattr(view, "monitor_frame")
    assert hasattr(view, "lbl_mon_badge")
    assert hasattr(view, "lbl_mon_last_trade")
    assert hasattr(view, "btn_sync_monitor")
    assert hasattr(view, "lbl_mon_stat_trades")
    assert hasattr(view, "lbl_mon_stat_challengers")

    # Verify switching active challenger
    view._set_active_challenger("SELECTOR_v2_1")
    assert view._active_challenger == "SELECTOR_v2_1"

    view._set_active_challenger("SELECTOR_v2")
    assert view._active_challenger == "SELECTOR_v2"

    view._set_active_challenger("CHALLENGER_v1")
    assert view._active_challenger == "CHALLENGER_v1"

    view._set_active_challenger("SELECTOR_v2_2")
    assert view._active_challenger == "SELECTOR_v2_2"


def test_adaptive_learning_view_trade_signals(qapp):
    view = AdaptiveLearningView()
    
    # Simulate trade open signal
    open_trade = {
        "trade_id": "PT-UI-OPEN-1",
        "symbol": "MONITOR_TOKEN",
        "entry_market_cap_usd": 12500.0,
        "entry_liquidity_usd": 15000.0,
        "entry_reason": "SELECTOR_V2_2_EMERGING_BREAKOUT",
    }
    view._on_trade_opened(open_trade)
    assert "MONITOR_TOKEN" in view.lbl_mon_last_trade.text()

    # Simulate trade close signal
    closed_trade = {
        "trade_id": "PT-UI-CLOSE-1",
        "symbol": "MONITOR_TOKEN",
        "entry_market_cap_usd": 12500.0,
        "entry_liquidity_usd": 15000.0,
        "entry_reason": "SELECTOR_V2_2_EMERGING_BREAKOUT",
        "net_realized_pnl_usd": 180.50,
        "exit_timestamp": "2026-10-09T09:20:00Z",
    }
    view._on_trade_closed(closed_trade)
    assert "MONITOR_TOKEN" in view.lbl_mon_last_trade.text()
    assert "+$180.50" in view.lbl_mon_last_trade.text()
