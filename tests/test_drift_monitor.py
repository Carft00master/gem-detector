"""
Unit tests for Calibration Drift and Model Degradation Monitor
"""

import pytest
from src.paper.drift_monitor import CalibrationDriftMonitor
from src.paper.ledger import PaperTradeRecord, PaperTradingLedger


def test_calibration_drift_monitoring(tmp_path):
    db_file = tmp_path / "drift_test.db"
    jsonl_file = tmp_path / "drift_test.jsonl"
    ledger = PaperTradingLedger(db_path=db_file, jsonl_path=jsonl_file)

    # 1. Insert 10 well-calibrated closed trades
    for i in range(10):
        is_winner = (i == 0) # 10% actual
        trade = PaperTradeRecord(
            signal_id=f"sig_{i}",
            token_address=f"Token_{i}",
            symbol=f"T{i}",
            chain="solana",
            venue="raydium",
            timestamp="2026-08-24T12:00:00Z",
            market_cap_usd=15000.0,
            liquidity_usd=4000.0,
            p_reach_100k=0.15,
            p_reach_500k=0.10,
            p_reach_1m=0.08,
            p_reach_3m=0.12, # Predicted 12%
            p_rug=0.10,
            data_confidence=0.90,
            regime="NORMAL",
            position_size_usd=100.0,
            entry_price_usd=0.00015,
            simulated_fill_price_usd=0.000155,
            entry_price_impact_pct=3.3,
            status="CLOSED",
            target_reached_3m=is_winner,
            outcome_label="SUCCESS" if is_winner else "FAILURE",
        )
        ledger.record_entry(trade)
        ledger.record_exit(trade)

    monitor = CalibrationDriftMonitor(ledger=ledger)
    report = monitor.audit_drift(batch_size=10)

    assert report.sample_size == 10
    assert report.unique_tokens == 10
    assert report.empirical_success_rate == 0.10
    assert report.drift_status in ("NORMAL", "CALIBRATED")
    assert abs(report.probability_bias) < 0.05
