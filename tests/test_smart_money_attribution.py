"""
Tests for Live Smart-Money Trade Attribution, Comparative Analysis & 6-Tier Verdicts.
"""

import pytest
from src.learning.smart_money.attribution import SmartMoneyAttributionEngine


def test_smart_money_present_vs_absent_attribution():
    """Verify smart-money present vs absent comparative analysis and confidence intervals."""
    trades = []
    # 20 Smart money present trades (high win rate)
    for i in range(20):
        trades.append({
            "status": "CLOSED",
            "smart_money_present": True,
            "validated_wallet_count": 2,
            "smart_money_consensus": 0.85,
            "smart_wallet_match_score": 0.90,
            "net_realized_pnl_usd": 150.0 if (i % 4 != 0) else -40.0,
            "net_realized_return_pct": 60.0 if (i % 4 != 0) else -15.0,
            "target_3m_reached": (i % 3 == 0),
            "mfe_ratio": 2.5,
            "mae_ratio": 0.8,
            "regime": "HOT" if (i % 2 == 0) else "NORMAL",
            "token_age_at_entry_sec": 120.0,
            "entry_market_cap_usd": 8500.0,
        })

    # 20 Smart money absent trades (lower win rate)
    for i in range(20):
        trades.append({
            "status": "CLOSED",
            "smart_money_present": False,
            "validated_wallet_count": 0,
            "smart_money_consensus": 0.0,
            "smart_wallet_match_score": 0.30,
            "net_realized_pnl_usd": 50.0 if (i % 3 == 0) else -50.0,
            "net_realized_return_pct": 20.0 if (i % 3 == 0) else -20.0,
            "target_3m_reached": (i % 6 == 0),
            "mfe_ratio": 1.2,
            "mae_ratio": 0.6,
            "regime": "HOT" if (i % 2 == 0) else "NORMAL",
            "token_age_at_entry_sec": 120.0,
            "entry_market_cap_usd": 8500.0,
        })

    report = SmartMoneyAttributionEngine.evaluate_live_attribution(trades)

    assert report.total_trades_analyzed == 40
    assert report.present_cohort.sample_size == 20
    assert report.absent_cohort.sample_size == 20
    assert report.present_cohort.win_rate_pct == 75.0
    assert report.absent_cohort.win_rate_pct < 40.0
    assert report.win_rate_lift_pct > 35.0
    assert report.profit_factor_lift > 0.0
    assert report.pnl_lift_usd > 0.0
    assert report.verdict == "STRONG_INDEPENDENT_EDGE"

    # Wilson CI tests
    ci_pres = report.present_cohort.win_rate_ci_95
    assert ci_pres[0] < report.present_cohort.win_rate_pct < ci_pres[1]


def test_smart_money_attribution_sub_slices():
    """Verify attribution breakdown by regime, token age, and market cap."""
    trades = [
        {
            "status": "CLOSED",
            "smart_money_present": True,
            "validated_wallet_count": 1,
            "net_realized_pnl_usd": 100.0,
            "regime": "HOT",
            "token_age_at_entry_sec": 45.0,     # <1m
            "entry_market_cap_usd": 4000.0,     # <5K
        },
        {
            "status": "CLOSED",
            "smart_money_present": False,
            "validated_wallet_count": 0,
            "net_realized_pnl_usd": -30.0,
            "regime": "COLD",
            "token_age_at_entry_sec": 600.0,    # 5-15m
            "entry_market_cap_usd": 30000.0,    # 25-50K
        },
    ]

    report = SmartMoneyAttributionEngine.evaluate_live_attribution(trades)
    assert "HOT" in report.by_regime
    assert "COLD" in report.by_regime
    assert "<1m" in report.by_token_age
    assert "5–15m" in report.by_token_age
    assert "<5K" in report.by_market_cap
    assert "25–50K" in report.by_market_cap


def test_future_wallet_attribution_exclusion():
    """Verify future-only validated wallet attribution."""
    val_wallets = [
        {"wallet_address": "ValWalletAlpha", "mature_trades": 15, "shrunk_win_rate": 40.0, "shrunk_target_3m_rate": 8.0, "matched_lift_pct": 18.5, "skill_confidence": 0.82}
    ]
    report = SmartMoneyAttributionEngine.evaluate_live_attribution([], validated_wallets=val_wallets)
    assert len(report.future_wallets) == 1
    assert report.future_wallets[0].wallet_address == "ValWalletAlpha"
    assert report.future_wallets[0].matched_lift_pct == 18.5
