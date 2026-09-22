"""
Tests for Behavioral Wallet Archetypes Classification and Confidence Scoring.
"""

import pytest
from src.learning.smart_money.archetypes import WalletArchetype, WalletArchetypeClassifier


def test_early_sniper_archetype_classification():
    """Verify classification of early sniper setups (<2 min age, sub-10K MC)."""
    interactions = [
        {"token_age_minutes": 0.8, "entry_market_cap_usd": 7500.0, "curve_progress_pct": 12.0, "mae_ratio": 0.95, "market_regime": "HOT"},
        {"token_age_minutes": 1.2, "entry_market_cap_usd": 8200.0, "curve_progress_pct": 15.0, "mae_ratio": 0.90, "market_regime": "HOT"},
        {"token_age_minutes": 1.5, "entry_market_cap_usd": 6800.0, "curve_progress_pct": 10.0, "mae_ratio": 0.92, "market_regime": "NORMAL"},
    ]
    profile = WalletArchetypeClassifier.classify_interactions(interactions)
    assert profile.archetype == WalletArchetype.EARLY_SNIPER.value
    assert profile.confidence >= 0.70
    assert "HOT" in profile.preferred_regimes


def test_traction_trader_archetype_classification():
    """Verify classification of traction trader setups (2-15 min age, verified volume)."""
    interactions = [
        {"token_age_minutes": 6.0, "entry_market_cap_usd": 15000.0, "curve_progress_pct": 30.0, "mae_ratio": 0.85, "market_regime": "NORMAL"},
        {"token_age_minutes": 8.5, "entry_market_cap_usd": 18000.0, "curve_progress_pct": 35.0, "mae_ratio": 0.88, "market_regime": "NORMAL"},
        {"token_age_minutes": 11.0, "entry_market_cap_usd": 22000.0, "curve_progress_pct": 40.0, "mae_ratio": 0.82, "market_regime": "HOT"},
    ]
    profile = WalletArchetypeClassifier.classify_interactions(interactions)
    assert profile.archetype == WalletArchetype.TRACTION_TRADER.value
    assert profile.confidence >= 0.65


def test_breakout_trader_archetype_classification():
    """Verify classification of breakout trader setups ($25K-$50K MC)."""
    interactions = [
        {"token_age_minutes": 25.0, "entry_market_cap_usd": 35000.0, "curve_progress_pct": 65.0, "mae_ratio": 0.85, "market_regime": "NORMAL"},
        {"token_age_minutes": 35.0, "entry_market_cap_usd": 42000.0, "curve_progress_pct": 75.0, "mae_ratio": 0.90, "market_regime": "HOT"},
    ]
    profile = WalletArchetypeClassifier.classify_interactions(interactions)
    assert profile.archetype == WalletArchetype.BREAKOUT_TRADER.value


def test_empty_interactions_defaults_to_other():
    """Verify handling of empty interactions gracefully."""
    profile = WalletArchetypeClassifier.classify_interactions([])
    assert profile.archetype == WalletArchetype.OTHER.value
    assert profile.confidence == 0.50
