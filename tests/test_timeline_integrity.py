"""
Tests for Trade Timeline Ordering and Pre-Entry Snapshot Integrity.
"""

import pytest
from src.paper.performance_analytics import PerformanceAnalyticsEngine


def test_trade_timeline_valid_sequencing():
    """Verify detection of valid chronological ordering across trade lifecycle."""
    valid_trades = [
        {
            "discovery_timestamp": "2026-08-01T10:00:00Z",
            "entry_timestamp": "2026-08-01T10:02:00Z",
            "exit_timestamp": "2026-08-01T10:30:00Z",
            "predicted_p3m_at_entry": 0.15,
        },
        {
            "discovery_timestamp": "2026-08-01T11:00:00Z",
            "entry_timestamp": "2026-08-01T11:05:00Z",
            "exit_timestamp": "2026-08-01T11:45:00Z",
            "predicted_p3m_at_entry": 0.22,
        },
    ]

    audit = PerformanceAnalyticsEngine.audit_trade_timelines(valid_trades)
    assert audit.total_trades_audited == 2
    assert audit.chronological_order_valid_count == 2
    assert audit.chronological_order_violation_count == 0
    assert audit.pre_entry_snapshots_preserved_count == 2
    assert audit.is_timeline_integrity_verified is True


def test_trade_timeline_violation_detection():
    """Verify that an inverted exit timestamp is flagged as a violation."""
    invalid_trades = [
        {
            "discovery_timestamp": "2026-08-01T10:00:00Z",
            "entry_timestamp": "2026-08-01T10:30:00Z",
            "exit_timestamp": "2026-08-01T10:15:00Z",  # Exit before entry!
            "predicted_p3m_at_entry": 0.15,
        }
    ]

    audit = PerformanceAnalyticsEngine.audit_trade_timelines(invalid_trades)
    assert audit.chronological_order_violation_count == 1
    assert audit.is_timeline_integrity_verified is False
