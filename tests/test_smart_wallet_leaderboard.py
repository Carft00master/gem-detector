"""
Tests for Smart Wallet Leaderboard, Elite State Transitions & Statistical Rankings.
"""

import pytest
from src.learning.smart_money.leaderboard import SmartWalletLeaderboardEngine
from src.learning.smart_money.maturity import WalletMaturityClassifier, WalletMaturityState


def test_elite_wallet_maturity_transition():
    """Verify criteria for promotion to ELITE tier (N >= 30, Lift >= 20%, Conf >= 85%, Stable trend)."""
    elite_wallet = {
        "wallet_address": "EliteMasterTrader1",
        "mature_trades": 35,
        "matched_lift_pct": 24.5,
        "skill_confidence": 0.88,
        "skill_trend": "STABLE",
        "rug_rate_pct": 0.0,
        "primary_role": "TRADER",
    }
    state = WalletMaturityClassifier.classify(elite_wallet)
    assert state == WalletMaturityState.ELITE


def test_validated_vs_declining_transition():
    """Verify validated wallet state vs declining state."""
    val_wallet = {
        "wallet_address": "ValidatedTraderAlpha",
        "mature_trades": 22,
        "matched_lift_pct": 14.0,
        "skill_confidence": 0.75,
        "skill_trend": "STABLE",
        "rug_rate_pct": 0.0,
        "primary_role": "TRADER",
    }
    assert WalletMaturityClassifier.classify(val_wallet) == WalletMaturityState.VALIDATED

    dec_wallet = {
        "wallet_address": "DecayingTraderBeta",
        "mature_trades": 22,
        "matched_lift_pct": 14.0,
        "skill_confidence": 0.75,
        "skill_trend": "DECLINING",
        "rug_rate_pct": 0.0,
        "primary_role": "TRADER",
    }
    assert WalletMaturityClassifier.classify(dec_wallet) == WalletMaturityState.DECLINING


def test_leaderboard_compilation_and_sorting():
    """Verify leaderboard compilation across elite, validated, and candidate wallets."""
    wallets = [
        {
            "wallet_address": "Cand1",
            "mature_trades": 2,
            "matched_lift_pct": 0.0,
            "skill_confidence": 0.20,
            "raw_win_rate": 10.0,
            "shrunk_win_rate": 10.0,
            "wallet_category": "DISCOVERED_WALLETS",
        },
        {
            "wallet_address": "Elite1",
            "mature_trades": 35,
            "matched_lift_pct": 25.0,
            "skill_confidence": 0.90,
            "raw_win_rate": 45.0,
            "shrunk_win_rate": 42.0,
            "skill_trend": "IMPROVING",
            "wallet_category": "DISCOVERED_WALLETS",
        },
        {
            "wallet_address": "Val1",
            "mature_trades": 22,
            "matched_lift_pct": 15.0,
            "skill_confidence": 0.75,
            "raw_win_rate": 30.0,
            "shrunk_win_rate": 28.0,
            "skill_trend": "STABLE",
            "wallet_category": "DISCOVERED_WALLETS",
        },
    ]

    report = SmartWalletLeaderboardEngine.compile_leaderboard(wallets)
    assert report.total_wallets_tracked == 3
    assert report.elite_count == 1
    assert report.validated_count == 1
    assert report.candidate_count == 1

    # Top ranked wallet must be Elite1
    assert report.leaderboard_entries[0].wallet_address == "Elite1"
    assert report.leaderboard_entries[0].maturity_state == "ELITE"
    assert report.leaderboard_entries[1].wallet_address == "Val1"
    assert report.leaderboard_entries[2].wallet_address == "Cand1"
