"""
Tests for Challenger Live Monitor & Adaptive Learning Real-Time Updates
"""

import pytest
from src.learning.challenger_monitor import ChallengerLiveMonitor, ChallengerLiveMetrics, ChallengerMonitorStatus
from app.services.research_service import ResearchService


def test_challenger_monitor_initialization():
    monitor = ChallengerLiveMonitor.get_instance()
    assert monitor is not None
    status = monitor.get_status()
    assert status["is_active"] is True
    assert "STREAMING" in status["status_label"]
    assert status["total_trades_evaluated"] >= 0
    assert status["active_challengers_count"] == 4


def test_challenger_monitor_all_challengers_present():
    monitor = ChallengerLiveMonitor.get_instance()
    all_data = monitor.get_all_metrics()
    challengers = all_data["challengers"]
    
    assert "SELECTOR_v2_2" in challengers
    assert "SELECTOR_v2_1" in challengers
    assert "SELECTOR_v2" in challengers
    assert "CHALLENGER_v1" in challengers

    v22 = challengers["SELECTOR_v2_2"]
    assert v22["trade_count"] >= 0
    assert v22["executable_pnl"] >= 0
    assert v22["win_rate"] >= 0
    assert v22["profit_factor"] >= 0

    v1 = challengers["CHALLENGER_v1"]
    assert v1["trade_count"] >= 0
    assert v1["executable_pnl"] >= 0
    assert v1["win_rate"] >= 0


def test_challenger_monitor_on_trade_events():
    monitor = ChallengerLiveMonitor.get_instance()
    
    v22_before = monitor.get_challenger_metrics("SELECTOR_v2_2")
    v1_before = monitor.get_challenger_metrics("CHALLENGER_v1")
    initial_v22_count = v22_before["trade_count"]
    initial_v1_count = v1_before["trade_count"]
    initial_v22_pnl = v22_before["executable_pnl"]

    # 1. Test Trade Open
    open_trade = {
        "trade_id": "PT-TEST-OPEN-1",
        "symbol": "LIVEGEM",
        "entry_market_cap_usd": 10500.0,
        "entry_liquidity_usd": 12000.0,
        "entry_reason": "SELECTOR_V2_2_EMERGING_BREAKOUT",
    }
    monitor.on_trade_opened(open_trade)
    status_after_open = monitor.get_status()
    assert status_after_open["last_ingested_trade_id"] == "PT-TEST-OPEN-1"
    assert status_after_open["last_ingested_symbol"] == "LIVEGEM"

    # 2. Test Trade Close
    closed_trade = {
        "trade_id": "PT-TEST-CLOSE-1",
        "symbol": "LIVEGEM",
        "entry_market_cap_usd": 10500.0,
        "entry_liquidity_usd": 12000.0,
        "entry_reason": "SELECTOR_V2_2_EMERGING_BREAKOUT",
        "p_reach_3m_at_entry": 0.14,
        "net_realized_pnl_usd": 250.0,
        "venue": "pumpfun",
        "exit_timestamp": "2026-10-09T09:15:00Z",
    }
    monitor.on_trade_closed(closed_trade)

    v22_after = monitor.get_challenger_metrics("SELECTOR_v2_2")
    v1_after = monitor.get_challenger_metrics("CHALLENGER_v1")

    # V2.2 should have incremented
    assert v22_after["trade_count"] == initial_v22_count + 1
    assert v22_after["executable_pnl"] == round(initial_v22_pnl + 250.0, 2)
    assert v22_after["last_trade_symbol"] == "LIVEGEM"

    # V1 satisfies MC between 8k-15k, Liq >= 10k, P(3M) >= 0.126 -> should have incremented too!
    assert v1_after["trade_count"] == initial_v1_count + 1
    assert v1_after["last_trade_symbol"] == "LIVEGEM"


def test_research_service_integration():
    svc = ResearchService()
    assert hasattr(svc, "challenger_monitor")
    assert svc.challenger_monitor is not None

    snapshot = svc.get_challenger_monitor_snapshot()
    assert "status" in snapshot
    assert "challengers" in snapshot
    assert snapshot["status"]["is_active"] is True

    # Live adaptive learning data
    live_data = svc.get_live_adaptive_learning_data()
    assert "status" in live_data
    assert "live_champion" in live_data
    assert "live_challengers" in live_data
    assert "live_selector_v2_2" in live_data
    assert "live_challenger_v1" in live_data

    # Selector evaluations enriched with live data
    v22_eval = svc.get_selector_v2_2_evaluation()
    assert "live" in v22_eval or "selector_v2_2" in v22_eval
    if "selector_v2_2" in v22_eval:
        assert "live" in v22_eval["selector_v2_2"]
        assert v22_eval["selector_v2_2"]["overall"].get("live_trade_count") is not None
