"""
Unit tests for Discovery-Capture and Ingestion Latency Auditing
"""

import pytest
from src.research.discovery_audit import DiscoveryCaptureAuditor


def test_discovery_classification_rules():
    # 1. Normal Discovery Captured
    s1, c1, tl1, n1 = DiscoveryCaptureAuditor.classify_token_discovery(
        first_mc=15000.0, lowest_mc=12000.0, highest_mc=45000.0,
        observation_count=5, time_in_range_sec=120.0
    )
    assert s1 == "DISCOVERY_CAPTURED"

    # 2. Discovery Late (Seen at 45K, but low was 20K)
    s2, c2, tl2, n2 = DiscoveryCaptureAuditor.classify_token_discovery(
        first_mc=45000.0, lowest_mc=20000.0, highest_mc=80000.0,
        observation_count=4, time_in_range_sec=30.0
    )
    assert s2 == "DISCOVERY_LATE"

    # 3. Discovery Missed (Seen at 50K, lowest was 45K)
    s3, c3, tl3, n3 = DiscoveryCaptureAuditor.classify_token_discovery(
        first_mc=50000.0, lowest_mc=45000.0, highest_mc=150000.0,
        observation_count=3, time_in_range_sec=10.0
    )
    assert s3 == "DISCOVERY_MISSED"

    # 4. Discovery Uncertain (Excessive Latency)
    s4, c4, tl4, n4 = DiscoveryCaptureAuditor.classify_token_discovery(
        first_mc=15000.0, lowest_mc=12000.0, highest_mc=25000.0,
        observation_count=5, time_in_range_sec=60.0,
        rpc_latency_ms=6500.0
    )
    assert s4 == "DISCOVERY_UNCERTAIN"


def test_discovery_audit_population(tmp_path):
    db_file = tmp_path / "test_discovery.db"
    auditor = DiscoveryCaptureAuditor(db_path=db_file)

    sample_records = [
        {"token_address": "tok1", "symbol": "T1", "market_cap_usd": 15000.0, "trade_count": 8, "token_age_minutes": 5.0, "rpc_delay_ms": 100.0},
        {"token_address": "tok2", "symbol": "T2", "market_cap_usd": 45000.0, "trough_market_cap_usd": 20000.0, "trade_count": 4, "token_age_minutes": 2.0, "rpc_delay_ms": 110.0},
        {"token_address": "tok3", "symbol": "T3", "market_cap_usd": 18000.0, "trade_count": 10, "token_age_minutes": 8.0, "rpc_delay_ms": 90.0},
    ]

    summary = auditor.audit_ingestion_population(sample_records)
    assert summary.total_tokens_evaluated == 3
    assert summary.discovery_captured_count == 2
    assert summary.discovery_late_count == 1
    assert summary.universe_capture_rate_pct == pytest.approx(66.67, 0.1)
