"""
Tests for Real-Time Smart Wallet Entry Detector & Entry Timeline Tracker.
"""

import pytest
from src.learning.smart_money.entry_detector import SmartWalletEntryDetector
from src.learning.smart_money.wallet_timeline import WalletEntryTimelineTracker


def test_entry_match_score_calculation():
    """Verify WALLET_ENTRY_MATCH_SCORE matches optimal setup parameters without look-ahead bias."""
    wallet_profile = {
        "optimal_mc_range": [5000.0, 25000.0],
        "optimal_token_age_range": [2.0, 15.0],
        "optimal_curve_progress_range": [15.0, 50.0],
    }

    # Ideal setup
    ideal_token = {
        "market_cap_usd": 12000.0,
        "token_age_minutes": 5.0,
        "curve_progress_pct": 30.0,
        "activity_density_percentile": 80.0,
    }
    score_ideal = SmartWalletEntryDetector.calculate_entry_match_score(ideal_token, wallet_profile)
    assert score_ideal >= 0.90

    # Poor setup
    poor_token = {
        "market_cap_usd": 180000.0,
        "token_age_minutes": 120.0,
        "curve_progress_pct": 95.0,
        "activity_density_percentile": 15.0,
    }
    score_poor = SmartWalletEntryDetector.calculate_entry_match_score(poor_token, wallet_profile)
    assert score_poor < 0.40


def test_wallet_entry_event_creation():
    """Verify SMART_WALLET_ENTRY_EVENT generation."""
    wallet = {
        "wallet_address": "TestWalletAlpha",
        "primary_role": "TRADER",
        "archetype": "TRACTION_TRADER",
        "maturity_state": "VALIDATED",
        "skill_confidence": 0.80,
        "shrunk_win_rate": 35.0,
    }
    token = {
        "token_address": "So1TokenBeta",
        "symbol": "BETA",
        "market_cap_usd": 10000.0,
        "liquidity_usd": 4000.0,
        "token_age_minutes": 4.0,
        "curve_progress_pct": 25.0,
    }
    event = SmartWalletEntryDetector.record_entry_event(wallet, token)
    assert event.wallet_address == "TestWalletAlpha"
    assert event.token_address == "So1TokenBeta"
    assert event.wallet_entry_match_score > 0.0
    assert event.is_research_only is True


def test_wallet_entry_timeline_tracking():
    """Verify step-by-step price trajectory and early entry validation in timeline tracker."""
    interaction = {
        "interaction_id": "tx_12345",
        "wallet_address": "TestWalletAlpha",
        "token_address": "So1TokenBeta",
        "symbol": "BETA",
        "entry_market_cap_usd": 10000.0,
        "entry_liquidity_usd": 4000.0,
        "entry_price_usd": 0.0001,
        "mfe_ratio": 4.5,
        "mae_ratio": 0.85,
        "realized_pnl_usd": 350.0,
        "realized_return_pct": 350.0,
        "target_100k": 1,
        "target_500k": 1,
        "target_1m": 0,
        "target_3m": 0,
    }

    tl = WalletEntryTimelineTracker.build_timeline_record(interaction)
    assert tl.wallet_address == "TestWalletAlpha"
    assert tl.is_proven_early_entry is True
    assert "TARGET_100K" in tl.milestones_reached
    assert len(tl.price_trajectory) >= 3
