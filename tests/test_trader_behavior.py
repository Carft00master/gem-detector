"""
Unit and Integration Tests for TRADER_BEHAVIOR_ENGINE v1.0.0 (Research Layer)
Tests Activity Density, Cohort Normalization, Participation Breadth, Two-Sided Market Quality,
Pump.fun Curve Traction, Smart-Wallet Role Intelligence, Bayesian Edge Shrinkage,
Point-in-Time Zero-Leakage, and Chronological A/B Model Validation.
"""

from pathlib import Path
import pytest

from src.trader_behavior.activity_density import (
    ActivityDensityEngine,
    ActivityDensityMetrics,
    get_age_bucket,
    get_liquidity_bucket,
    get_mc_bucket,
)
from src.trader_behavior.participation import (
    ParticipationBreadthEngine,
    ParticipationBreadthMetrics,
)
from src.trader_behavior.two_sided import (
    TwoSidedMarketQualityEngine,
    TwoSidedMarketQualityMetrics,
)
from src.trader_behavior.curve_traction import (
    CurveTractionEngine,
    CurveTractionMetrics,
)
from src.trader_behavior.composite import (
    EarlyTractionBundle,
    TraderStyleEarlyTractionEngine,
)
from src.trader_behavior.wallet_intelligence import (
    REFERENCE_WALLET_A,
    REFERENCE_WALLET_B,
    SmartWalletEngine,
    WalletBehaviorProfile,
)
from src.trader_behavior.ab_validation import (
    ABValidationHarness,
    ABValidationReport,
)
from src.trader_behavior.report import TraderBehaviorReportGenerator


# ---------------------------------------------------------------------------
# 1. Activity Density & Cohort Normalization Tests
# ---------------------------------------------------------------------------

def test_activity_density_calculation():
    # $150K volume on $8K MC (extreme density)
    res = ActivityDensityEngine.compute(
        market_cap_usd=8000.0,
        liquidity_usd=3000.0,
        token_age_minutes=5.0,
        volume_5m_usd=150000.0,
        volume_1h_usd=300000.0,
        txns_5m=250,
        txns_1h=1200,
        unique_buyers_1h=180,
        unique_sellers_1h=70,
        chain="solana",
        venue="pumpfun",
        prev_volume_5m=80000.0,
        prev_txns_5m=120,
    )

    assert isinstance(res, ActivityDensityMetrics)
    assert res.volume_mc_ratio == pytest.approx(150000.0 / 8000.0, rel=1e-3)
    assert res.transactions_mc_ratio == pytest.approx(250.0 / 8000.0, rel=1e-3)
    assert res.volume_velocity == pytest.approx(70000.0, rel=1e-3)
    assert res.volume_acceleration > 0.0
    assert res.activity_density_score >= 85.0


def test_activity_density_relative_differentiation():
    # Same $150K volume on $8K MC vs $800K MC
    dense = ActivityDensityEngine.compute(
        market_cap_usd=8000.0,
        liquidity_usd=3000.0,
        token_age_minutes=5.0,
        volume_5m_usd=150000.0,
        volume_1h_usd=200000.0,
        txns_5m=300,
        txns_1h=1000,
        unique_buyers_1h=150,
        unique_sellers_1h=50,
    )

    diluted = ActivityDensityEngine.compute(
        market_cap_usd=800000.0,
        liquidity_usd=150000.0,
        token_age_minutes=120.0,
        volume_5m_usd=150000.0,
        volume_1h_usd=500000.0,
        txns_5m=300,
        txns_1h=1000,
        unique_buyers_1h=150,
        unique_sellers_1h=50,
    )

    # Extreme activity density on micro-cap MUST dramatically outscore the same volume on high-cap
    assert dense.activity_density_score > diluted.activity_density_score + 25.0


def test_cohort_normalization_bucket_keys():
    assert get_mc_bucket(7500.0) == "MC_SUB_10K"
    assert get_mc_bucket(18000.0) == "MC_10K_25K"
    assert get_mc_bucket(35000.0) == "MC_25K_50K"
    assert get_mc_bucket(75000.0) == "MC_50K_100K"
    assert get_mc_bucket(250000.0) == "MC_100K_PLUS"

    assert get_age_bucket(2.0) == "AGE_0_5M"
    assert get_age_bucket(10.0) == "AGE_5_15M"
    assert get_age_bucket(25.0) == "AGE_15_30M"
    assert get_age_bucket(45.0) == "AGE_30_60M"
    assert get_age_bucket(120.0) == "AGE_60M_PLUS"

    assert get_liquidity_bucket(1500.0) == "LIQ_SUB_2K"
    assert get_liquidity_bucket(3500.0) == "LIQ_2K_5K"
    assert get_liquidity_bucket(8000.0) == "LIQ_5K_15K"
    assert get_liquidity_bucket(50000.0) == "LIQ_15K_PLUS"


# ---------------------------------------------------------------------------
# 2. Participation Breadth Tests
# ---------------------------------------------------------------------------

def test_participation_breadth_organic_vs_sybil():
    # Organic broad retail: 50 buys from 45 unique buyers
    organic = ParticipationBreadthEngine.compute(
        txns_5m_buys=50,
        txns_5m_sells=20,
        unique_buyers_1h=45,
        unique_sellers_1h=18,
        prev_unique_buyers=30,
        prev_unique_sellers=10,
    )

    # Sybil / Wash loop: 50 buys from only 2 wallets
    sybil = ParticipationBreadthEngine.compute(
        txns_5m_buys=50,
        txns_5m_sells=20,
        unique_buyers_1h=2,
        unique_sellers_1h=1,
        prev_unique_buyers=2,
        prev_unique_sellers=1,
    )

    assert organic.buyer_to_buy_txn_ratio == pytest.approx(45.0 / 50.0, rel=1e-2)
    assert sybil.buyer_to_buy_txn_ratio == pytest.approx(2.0 / 50.0, rel=1e-2)
    assert sybil.repeat_buyer_penalty > 0.0
    assert organic.participation_breadth_score > sybil.participation_breadth_score + 40.0


# ---------------------------------------------------------------------------
# 3. Two-Sided Market Quality Tests
# ---------------------------------------------------------------------------

def test_two_sided_market_quality_calculation():
    # Healthy two-sided trading ($15K buys, $10K sells, +8% price gain)
    healthy = TwoSidedMarketQualityEngine.compute(
        volume_5m_usd=25000.0,
        txns_5m_buys=30,
        txns_5m_sells=20,
        unique_buyers_1h=25,
        unique_sellers_1h=15,
        price_return_5m_pct=0.08,
        estimated_buy_volume_usd=15000.0,
        estimated_sell_volume_usd=10000.0,
    )

    # Balanced flow but dumping price (-15%)
    dumping = TwoSidedMarketQualityEngine.compute(
        volume_5m_usd=25000.0,
        txns_5m_buys=25,
        txns_5m_sells=25,
        unique_buyers_1h=20,
        unique_sellers_1h=20,
        price_return_5m_pct=-0.15,
        estimated_buy_volume_usd=12500.0,
        estimated_sell_volume_usd=12500.0,
    )

    assert healthy.two_sided_volume_ratio == pytest.approx(10000.0 / 15000.0, rel=1e-3)
    assert healthy.two_sided_market_quality > dumping.two_sided_market_quality + 20.0


# ---------------------------------------------------------------------------
# 4. Pump.fun Curve Traction Tests
# ---------------------------------------------------------------------------

def test_curve_progress_and_velocity():
    history = [
        {"time_sec": 60, "progress": 0.10},
        {"time_sec": 180, "progress": 0.22},
        {"time_sec": 300, "progress": 0.40},
        {"time_sec": 360, "progress": 0.48},
    ]

    res = CurveTractionEngine.compute(
        venue="pumpfun",
        curve_progress=0.48,
        token_age_minutes=6.0,
        volume_5m_usd=12000.0,
        txns_5m=45,
        progress_history=history,
    )

    assert res.status == "AVAILABLE"
    assert res.curve_progress == 0.48
    assert res.curve_progress_velocity > 0.0
    assert res.is_accelerating is True
    assert res.curve_traction_score >= 70.0


def test_curve_missing_state_handling():
    # Missing curve progress on Pump.fun
    missing = CurveTractionEngine.compute(
        venue="pumpfun",
        curve_progress=None,
        token_age_minutes=5.0,
        volume_5m_usd=5000.0,
        txns_5m=20,
    )
    assert missing.status == "MISSING"
    assert missing.curve_progress is None
    assert missing.curve_traction_score == 50.0

    # Raydium / Uniswap (not applicable)
    ray = CurveTractionEngine.compute(
        venue="raydium",
        curve_progress=None,
        token_age_minutes=50.0,
        volume_5m_usd=25000.0,
        txns_5m=100,
    )
    assert ray.status == "NOT_APPLICABLE"
    assert ray.curve_traction_score == 50.0


# ---------------------------------------------------------------------------
# 5. Composite Early Traction & Similarity Matching Tests
# ---------------------------------------------------------------------------

def test_composite_early_traction_and_style_match():
    act = ActivityDensityEngine.compute(
        market_cap_usd=14000.0,
        liquidity_usd=4000.0,
        token_age_minutes=8.0,
        volume_5m_usd=20000.0,
        volume_1h_usd=60000.0,
        txns_5m=80,
        txns_1h=350,
        unique_buyers_1h=60,
        unique_sellers_1h=25,
    )
    part = ParticipationBreadthEngine.compute(
        txns_5m_buys=60,
        txns_5m_sells=20,
        unique_buyers_1h=50,
        unique_sellers_1h=20,
    )
    two = TwoSidedMarketQualityEngine.compute(
        volume_5m_usd=20000.0,
        txns_5m_buys=60,
        txns_5m_sells=20,
        unique_buyers_1h=50,
        unique_sellers_1h=20,
        price_return_5m_pct=0.12,
    )
    curv = CurveTractionEngine.compute(
        venue="pumpfun",
        curve_progress=0.55,
        token_age_minutes=8.0,
        volume_5m_usd=20000.0,
        txns_5m=80,
    )

    bundle = TraderStyleEarlyTractionEngine.evaluate(
        token_address="tok_test_123",
        symbol="TRACTION",
        market_cap_usd=14000.0,
        liquidity_usd=4000.0,
        token_age_minutes=8.0,
        activity=act,
        participation=part,
        two_sided=two,
        curve=curv,
        momentum_return_5m_pct=0.12,
    )

    assert isinstance(bundle, EarlyTractionBundle)
    assert 0.0 <= bundle.early_traction_score <= 100.0
    assert 0.0 <= bundle.trader_style_match_score <= 100.0
    assert bundle.early_traction_score >= 70.0
    assert bundle.trader_style_match_score >= 70.0


# ---------------------------------------------------------------------------
# 6. Smart-Wallet Behavioral Intelligence & Bayesian Edge Tests
# ---------------------------------------------------------------------------

def test_smart_wallet_role_classification_and_bayesian_shrinkage():
    engine = SmartWalletEngine()
    test_wallet = "TestSmartWallet111111111111111111111111111111"

    # Record 20 trades with high win rate
    for i in range(20):
        engine.record_entry(
            wallet_address=test_wallet,
            token_address=f"tok_w_{i}",
            symbol=f"W_{i}",
            market_cap_usd=12000.0 + (i * 1000.0),
            liquidity_usd=3500.0,
            token_age_minutes=7.0,
            curve_progress=0.40,
            volume_mc_ratio=0.8,
            activity_density_score=85.0,
            buy_pressure=0.65,
            two_sided_ratio=0.70,
        )
        # 16 wins, 4 losses
        is_win = (i % 5 != 0)
        engine.record_exit(
            wallet_address=test_wallet,
            token_address=f"tok_w_{i}",
            exit_market_cap_usd=30000.0 if is_win else 6000.0,
            realized_return_pct=150.0 if is_win else -50.0,
            mfe_pct=200.0 if is_win else 10.0,
            mae_pct=-5.0 if is_win else -60.0,
        )

    profile = engine.wallets[test_wallet]
    assert profile.role == "TRADER"
    assert profile.total_trades_observed == 20
    assert profile.mature_trades_count == 20
    assert profile.winning_trades_count == 16
    assert profile.raw_win_rate == 0.80

    # Bayesian shrinkage test:
    # \hat{p} = (16 + 10 * 0.25) / (20 + 10) = 18.5 / 30 = 0.6167
    assert profile.bayesian_shrunk_win_rate < profile.raw_win_rate
    assert profile.bayesian_shrunk_win_rate == pytest.approx(18.5 / 30.0, rel=1e-3)
    assert profile.sample_confidence in ("MEDIUM", "HIGH")
    assert profile.wallet_edge_score > 60.0


def test_small_sample_bayesian_penalty():
    engine = SmartWalletEngine()
    lucky_wallet = "LuckyWallet222222222222222222222222222222"
    pro_wallet = "ProWallet333333333333333333333333333333333"

    # Lucky wallet: 2 wins / 2 trades (raw 100%)
    for i in range(2):
        engine.record_entry(lucky_wallet, f"tok_l_{i}", "L", 10000, 3000, 5, 0.3, 0.8, 80, 0.6, 0.7)
        engine.record_exit(lucky_wallet, f"tok_l_{i}", 25000, 150.0, 200.0, -5.0)

    # Pro wallet: 35 wins / 50 trades (raw 70%)
    for i in range(50):
        engine.record_entry(pro_wallet, f"tok_p_{i}", "P", 10000, 3000, 5, 0.3, 0.8, 80, 0.6, 0.7)
        is_win = (i < 35)
        engine.record_exit(pro_wallet, f"tok_p_{i}", 25000 if is_win else 6000, 150.0 if is_win else -50.0, 200.0 if is_win else 5.0, -5.0 if is_win else -50.0)

    p_lucky = engine.wallets[lucky_wallet]
    p_pro = engine.wallets[pro_wallet]

    # Small sample (N=2) MUST have INSUFFICIENT_WALLET_EVIDENCE and lower edge score than N=50
    assert p_lucky.sample_confidence == "INSUFFICIENT_WALLET_EVIDENCE"
    assert p_pro.sample_confidence == "HIGH"
    assert p_pro.wallet_edge_score > p_lucky.wallet_edge_score


def test_sniper_role_classification():
    engine = SmartWalletEngine()
    sniper_wallet = "SniperWallet44444444444444444444444444444"
    for i in range(6):
        # Entry at age 0.1 minutes (< 6 seconds from launch)
        engine.record_entry(sniper_wallet, f"tok_s_{i}", "S", 8000, 2500, 0.1, 0.05, 1.2, 90, 0.7, 0.5)
        engine.record_exit(sniper_wallet, f"tok_s_{i}", 15000, 80.0, 100.0, -5.0)

    assert engine.wallets[sniper_wallet].role == "SNIPER"


# ---------------------------------------------------------------------------
# 7. A/B Model Validation & Report Tests
# ---------------------------------------------------------------------------

def test_ab_validation_harness_execution():
    sample_tokens = [
        {
            "token_address": f"tok_{i}",
            "p_reach_3m": 0.06 + (i * 0.01),
            "early_traction_score": 40.0 + (i * 4.0),
            "wallet_boost": 10.0 if i >= 8 else 0.0,
            "target_3m_eventual": 1 if i in (8, 9) else 0,
            "p_rug": 0.05 if i >= 5 else 0.40,
        }
        for i in range(12)
    ]

    report = ABValidationHarness.evaluate(sample_tokens)
    assert isinstance(report, ABValidationReport)
    assert report.model_a_baseline.model_name == "Model A (v1.0.0 Control)"
    assert report.model_b_early_traction.model_name == "Model B (v1.0.0 + Early Traction)"
    assert report.model_c_full_behavioral.model_name == "Model C (v1.0.0 + Early Traction + Smart Wallet)"
    assert len(report.answers_to_research_questions) == 8


def test_trader_behavior_report_generation(tmp_path):
    engine = SmartWalletEngine()
    sample_tokens = [
        {
            "token_address": f"tok_rep_{i}",
            "symbol": f"REP_{i}",
            "market_cap_usd": 15000.0,
            "p_reach_3m": 0.08,
            "activity_density_score": 82.0,
            "participation_breadth_score": 78.0,
            "two_sided_market_quality": 75.0,
            "early_traction_score": 80.0,
            "target_3m_eventual": 1 if i == 0 else 0,
        }
        for i in range(5)
    ]

    path = TraderBehaviorReportGenerator.generate_markdown_report(sample_tokens, engine, output_dir=tmp_path)
    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert "TRADER_BEHAVIOR_ENGINE v1.0.0" in content
    assert "Strict v1.0.0 Model Freeze" in content
    assert "Reference Smart-Wallet Role Classifications" in content
    assert "Answers to Primary Research Questions" in content
