"""
Phase 1d Tests: Fail-Closed Data Engine & Gate Auditor
Tests elimination of defaults (1, 1.0, 0.0795), rejection of synthetic liquidity,
distinct buyer wallet derivation, holder concentration calculations,
and single-wallet curve filler rejection.
"""

import math
import pytest
from src.paper.fail_closed_data import FailClosedDataValidator


@pytest.fixture
def validator():
    return FailClosedDataValidator()


def test_missing_features_and_nan_triggers_rejection(validator):
    cand = {
        "mint": "TestMintNaN",
        "market_cap_usd": float("nan"),
        "liquidity_usd": None,
        "p_reach_3m": float("nan"),
        "unique_buyers": None,
        "buy_sell_ratio": None,
    }
    telemetry = validator.validate_candidate(cand)
    assert not telemetry.is_valid
    assert any("Market Cap is missing or NaN" in g for g in telemetry.failed_gates)
    assert any("Real Liquidity is missing or NaN" in g for g in telemetry.failed_gates)
    assert any("P(3M) prediction is missing or NaN" in g for g in telemetry.failed_gates)
    assert any("Unique buyers is missing or NaN" in g for g in telemetry.failed_gates)
    assert any("Buy/Sell ratio is missing or NaN" in g for g in telemetry.failed_gates)


def test_default_fallbacks_rejected(validator):
    # Unscored candidate with legacy default fallback values
    cand = {
        "mint": "TestMintDefaults",
        "market_cap_usd": 12000.0,
        "liquidity_usd": 8000.0,
        "p_reach_3m": 0.0795, # Unscored baseline model default
        "unique_buyers": 1,      # Default fallback 1
        "buy_sell_ratio": 1.0,  # Unpopulated default 1.0
    }
    telemetry = validator.validate_candidate(cand)
    assert not telemetry.is_valid
    assert any("exact 0.0795 default fallback" in g for g in telemetry.failed_gates)
    assert any("default fallback or <= 1" in g for g in telemetry.failed_gates)
    assert any("unpopulated default 1.0" in g for g in telemetry.failed_gates)


def test_synthetic_liquidity_under_500_rejected(validator):
    cand = {
        "mint": "TestMintLowLiq",
        "market_cap_usd": 10000.0,
        "liquidity_usd": 350.0, # Real liquidity < $500
        "p_reach_3m": 0.15,
        "unique_buyers": 40,
        "buy_sell_ratio": 2.5,
    }
    telemetry = validator.validate_candidate(cand)
    assert not telemetry.is_valid
    assert any("below minimum $500 threshold" in g for g in telemetry.failed_gates)


def test_distinct_buyer_wallets_derivation(validator):
    # Raw wallets list with duplicates (e.g. 5 transactions by 2 wallets)
    wallets = ["wallet_A", "wallet_B", "wallet_A", "wallet_B", "wallet_A"]
    cand = {
        "mint": "TestMintWallets",
        "market_cap_usd": 12000.0,
        "liquidity_usd": 8000.0,
        "p_reach_3m": 0.15,
        "buy_sell_ratio": 2.5,
    }
    telemetry = validator.validate_candidate(cand, onchain_buyer_wallets=wallets)
    # len(set(wallets)) = 2 < 25 -> must reject!
    assert telemetry.unique_buyer_wallets == 2
    assert not telemetry.is_valid
    assert any("below minimum 25" in g for g in telemetry.failed_gates)


def test_single_wallet_curve_filler_rejection(validator):
    # Calibration case: one wallet bought 79.3% of curve in slot 0
    cand = {
        "mint": "qTFyfJiSQhMooT6LzybsWHjMXSGWsdkY3w8C9aXpump",
        "market_cap_usd": 12000.0,
        "liquidity_usd": 8000.0,
        "p_reach_3m": 0.15,
        "unique_buyers": 30,
        "buy_sell_ratio": 2.5,
        "curve_completed_by_single_tx": True,
        "curve_filler_holding_pct": 79.3,
    }
    telemetry = validator.validate_candidate(cand)
    assert not telemetry.is_valid
    assert any("Single-wallet curve filler detected" in g for g in telemetry.failed_gates)


def test_holder_concentration_excluding_system_and_curve_accounts(validator):
    holders = [
        {"address": "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P", "amount": 800_000_000.0, "is_curve_or_pool": True}, # Curve account
        {"address": "1nc1nerator11111111111111111111111111111111", "amount": 50_000_000.0},                              # Burn account
        {"address": "CreatorWallet111", "amount": 30_000_000.0},                                                            # Creator (20% of circulating 150M)
        {"address": "Holder2", "amount": 120_000_000.0},
    ]
    cand = {
        "mint": "TestMintHolders",
        "creator": "CreatorWallet111",
        "market_cap_usd": 12000.0,
        "liquidity_usd": 8000.0,
        "p_reach_3m": 0.15,
        "unique_buyers": 35,
        "buy_sell_ratio": 2.0,
    }
    telemetry = validator.validate_candidate(cand, onchain_holders=holders)
    # Excluded accounts are filtered, so creator holding is 30M / 150M = 20.0% > 3.0%
    assert telemetry.creator_holding_pct == 20.0
    assert not telemetry.is_valid
    assert any("Creator holding 20.0% exceeds limit 3.0%" in g for g in telemetry.failed_gates)
