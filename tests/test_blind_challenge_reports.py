"""
Tests for Blind Wallet Challenge Harness and Periodic Research Reports.
"""

import pytest
from src.learning.smart_money.blind_challenge import BlindWalletChallengeHarness
from src.learning.smart_money.periodic_reports import SmartMoneyPeriodicReportGenerator


def test_blind_wallet_challenge_evaluation():
    """Verify holdout evaluation precision, recall, and verdict assignment."""
    holdout_wallets = [
        # 10 truly skilled wallets discovered
        {"wallet_address": f"Skilled_{i}", "is_classified_smart": True, "true_future_win_rate": 35.0}
        for i in range(10)
    ] + [
        # 2 false positive discoveries
        {"wallet_address": f"FalseSmart_{i}", "is_classified_smart": True, "true_future_win_rate": 10.0}
        for i in range(2)
    ] + [
        # 20 true negative omissions
        {"wallet_address": f"Retail_{i}", "is_classified_smart": False, "true_future_win_rate": 10.0}
        for i in range(20)
    ]

    report = BlindWalletChallengeHarness.evaluate_blind_challenge(holdout_wallets, retail_baseline_win_rate=11.5)

    assert report.total_holdout_population == 32
    assert report.discovered_as_smart_count == 12
    assert report.true_positive_discoveries == 10
    assert report.false_positive_discoveries == 2
    assert report.discovery_precision_pct > 80.0
    assert report.discovery_recall_pct == 100.0
    assert report.challenge_verdict == "STRONG_AUTONOMOUS_DISCOVERY"


def test_periodic_reports_generation():
    """Verify Daily and Weekly Markdown research report formatting."""
    mock_data = {
        "wallets": [{"wallet_address": "W1", "maturity_state": "ELITE"}, {"wallet_address": "W2", "maturity_state": "VALIDATED"}],
        "discovered_wallets": [{"wallet_address": "W1"}],
        "reference_wallets": [{"wallet_address": "W2"}],
        "quarantined_tokens": ["Tok1", "Tok2"],
        "blind_evaluation": {"blind_precision_pct": 82.0, "blind_mean_win_rate_pct": 36.5, "verdict": "STRONG_AUTONOMOUS_DISCOVERY"},
        "independence_report": {"base_pr_auc": 0.42, "augmented_pr_auc": 0.48, "verdict": "SMART_MONEY_INDEPENDENT_EDGE", "controlling_factors": ["regime", "mc"]},
    }

    daily = SmartMoneyPeriodicReportGenerator.generate_daily_report(mock_data)
    weekly = SmartMoneyPeriodicReportGenerator.generate_weekly_report(mock_data)

    assert "# 📅 SMART MONEY DAILY RESEARCH REPORT" in daily
    assert "Elite Tier" in daily
    assert "# 📊 SMART MONEY WEEKLY EXECUTIVE AUDIT" in weekly
    assert "EARLY_SNIPER" in weekly
