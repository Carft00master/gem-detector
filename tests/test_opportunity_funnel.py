"""
Unit tests for Canonical 11-Stage Opportunity Funnel and Multi-Tier Winner Recall
"""

import pytest
from src.research.opportunity_funnel import OpportunityFunnelAuditor


def test_opportunity_funnel_and_winner_recall():
    # 20 sample candidates, 2 winners
    records = []
    for i in range(20):
        is_win = (i < 2)
        records.append({
            "token_address": f"tok_{i}",
            "discovery_status": "CAPTURE_CONFIRMED" if i < 15 else "DISCOVERY_MISSED",
            "liquidity_usd": 3000.0 if i < 12 else 200.0,
            "is_alert_candidate": (i < 6),
            "p_rug": 0.10 if i < 10 else 0.80,
            "target_3m": int(is_win),
            "target_survivable_3m": bool(is_win),
            "is_valid_3m_runner": int(is_win),
        })

    report = OpportunityFunnelAuditor.audit_funnel(records)

    assert report.total_initial_candidates == 20
    assert len(report.stages) == 11

    s_all = next(s for s in report.stages if "FULL_UNIVERSE" in s.stage_name)
    s_cap = next(s for s in report.stages if "CAPTURE_CONFIRMED" in s.stage_name)
    s_elig = next(s for s in report.stages if "MODEL_ELIGIBLE" in s.stage_name)
    s_alert = next(s for s in report.stages if "ALERTED" in s.stage_name)

    assert s_all.token_count == 20
    assert s_cap.token_count == 20
    assert s_elig.token_count == 12

    # Winner recall checks
    rec = report.recall
    assert rec.total_ground_truth_winners == 2
    assert rec.discovery_recall_pct == 100.0
    assert rec.end_to_end_recall_pct == 100.0
