"""
Unit tests for 7-Model Baseline Tournament and Stability Statistics
"""

import pytest
from src.research.tournament import BaselineTournamentEngine


def test_baseline_tournament_execution():
    records = []
    for i in range(50):
        records.append({
            "token_address": f"Tok_{i}",
            "market_cap_usd": 15000.0,
            "volume_5m_usd": 2000.0 if i % 10 == 0 else 200.0,
            "txns_5m_buys": 30 if i % 10 == 0 else 5,
            "txns_5m_sells": 10 if i % 10 == 0 else 8,
            "liquidity_usd": 4000.0,
            "unique_buyers": 40 if i % 10 == 0 else 10,
            "elapsed_minutes": 15.0,
            "target_3m": int(i % 10 == 0),
        })

    ml_probs = [0.85 if i % 10 == 0 else 0.05 for i in range(50)]
    res = BaselineTournamentEngine.run_tournament(records, ml_probs=ml_probs)

    assert len(res.leaderboard) == 7
    # Top model should have highest PR-AUC
    top_model = res.leaderboard[0]
    assert top_model.pr_auc > 0.0
    assert len(res.stability_stats) == 7
