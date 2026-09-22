"""
Unit tests for Ranking Power, Selection Lift and Decile Analysis
"""

import pytest
from src.research.ranking_power import RankingPowerAuditor


def test_ranking_power_selection_lift():
    records = []
    # 100 mature tokens, 10 winners total (10% base rate)
    for i in range(100):
        is_win = (i < 10)
        records.append({
            "token_address": f"Token_{i}",
            "elapsed_minutes": 1500.0,
            "target_3m": int(is_win),
            "is_valid_3m_runner": int(is_win),
            "time_to_3m_min": 10.0 if is_win else None,
        })

    # High predicted probabilities for the 10 true winners
    ml_probs = [0.85] * 10 + [0.05] * 90

    report = RankingPowerAuditor.audit_ranking_power(records, ml_probs=ml_probs)

    assert report.total_population_n == 100
    assert report.n_mature == 100
    assert report.total_positives_3m == 10
    assert report.population_base_rate == 0.10

    # Top 10% should capture all 10 winners -> Hit Rate = 100%, Lift = 10.0x
    top_10pct = next(t for t in report.tiers if t.tier_label == "Top 10%")
    assert top_10pct.selected_count == 10
    assert top_10pct.hit_count_3m == 10
    assert top_10pct.empirical_hit_rate == 1.00
    assert top_10pct.lift_over_base_rate == 10.0
