"""
Tests for Incremental Predictive Independence Testing and Blind Wallet Evaluation.
"""

import pytest
from src.learning.smart_money.independence_test import SmartMoneyIndependenceTester
from src.learning.smart_money.blind_evaluation import BlindWalletEvaluator


def test_incremental_independence_evaluation():
    """Verify incremental lift calculation beyond base features."""
    samples = [
        {"p_reach_3m": 0.15, "wallet_consensus": 0.9, "smart_wallet_match_score": 0.85, "target_3m": True},
        {"p_reach_3m": 0.05, "wallet_consensus": 0.1, "smart_wallet_match_score": 0.40, "target_3m": False},
    ] * 20

    report = SmartMoneyIndependenceTester.test_incremental_independence(samples)
    assert report.is_statistically_independent is True
    assert report.verdict == "SMART_MONEY_INDEPENDENT_EDGE"
    assert report.delta_pr_auc_pct > 0.0
    assert report.delta_precision_10_pct >= 0.0
    assert len(report.controlling_factors) >= 5



def test_blind_wallet_evaluation_and_research_flags():
    """Verify blind evaluation flags small sample, decaying wallets, and computes holdout lift."""
    discovered = [
        {"wallet_address": "SmallSampleWallet", "mature_trades": 3, "role_confidence": 0.40, "shrunk_win_rate": 20.0, "skill_trend": "STABLE"},
        {"wallet_address": "DecayingWallet", "mature_trades": 35, "role_confidence": 0.85, "shrunk_win_rate": 30.0, "skill_trend": "DECLINING"},
    ]
    blind_trades = [
        {"token_address": "BlindTok1", "target_100k": True, "realized_return": 100.0} for _ in range(25)
    ]

    report = BlindWalletEvaluator.evaluate_blind_holdout(discovered, blind_trades)
    assert report.total_blind_wallets == 2
    assert report.is_algorithm_empirically_valid is True

    flag_types = [f.flag_type for f in report.research_flags]
    assert "WALLET_SAMPLE_TOO_SMALL" in flag_types
    assert "WALLET_SKILL_DECAY" in flag_types
