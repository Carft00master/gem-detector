"""
Unit tests for 11 Discovery Failure Cause Codes and Discovery Quality Score
"""

import pytest
from src.research.discovery_audit import DiscoveryCaptureAuditor, DiscoveryFailureCause


def test_discovery_failure_cause_diagnostics():
    # 1. Excessive RPC Latency
    st1, c1, tl1, _ = DiscoveryCaptureAuditor.classify_token_discovery(
        first_mc=15000.0, lowest_mc=12000.0, highest_mc=25000.0,
        observation_count=5, time_in_range_sec=60.0,
        rpc_latency_ms=6000.0
    )
    assert c1 == DiscoveryFailureCause.RPC_LATENCY

    # 2. Pool Discovery Delay (Bypassed $35K directly)
    st2, c2, tl2, _ = DiscoveryCaptureAuditor.classify_token_discovery(
        first_mc=55000.0, lowest_mc=45000.0, highest_mc=120000.0,
        observation_count=3, time_in_range_sec=15.0
    )
    assert c2 == DiscoveryFailureCause.POOL_DISCOVERY_DELAY

    # 3. Polling Gap (Seen at $45K, but low was $20K)
    st3, c3, tl3, _ = DiscoveryCaptureAuditor.classify_token_discovery(
        first_mc=45000.0, lowest_mc=20000.0, highest_mc=90000.0,
        observation_count=4, time_in_range_sec=30.0
    )
    assert c3 == DiscoveryFailureCause.POLLING_GAP


def test_discovery_quality_score_calculation():
    # Optimal conditions -> DQS near 100
    dqs_perfect = DiscoveryCaptureAuditor.calculate_discovery_quality_score(
        observation_count=10,
        time_in_range_sec=300.0,
        rpc_latency_ms=80.0,
        websocket_latency_ms=40.0,
        has_complete_features=True,
    )
    assert dqs_perfect >= 95.0

    # Poor continuity & high latency -> DQS degraded
    dqs_poor = DiscoveryCaptureAuditor.calculate_discovery_quality_score(
        observation_count=1,
        time_in_range_sec=5.0,
        rpc_latency_ms=1500.0,
        websocket_latency_ms=1200.0,
        has_complete_features=False,
    )
    assert dqs_poor <= 25.0
