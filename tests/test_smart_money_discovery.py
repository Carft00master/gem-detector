"""
Tests for Autonomous Smart Money Discovery, Bayesian Shrinkage, Matched Controls,
Role Intelligence, Entry Fingerprints & Look-Ahead Guardrails.
"""

from datetime import datetime, timezone
import pytest

from src.learning.smart_money.maturity import DEFAULT_MATURITY_THRESHOLDS, WalletMaturityState
from src.learning.smart_money.point_in_time import PointInTimeGuardrail
from src.learning.smart_money.wallet_discovery import AutonomousWalletDiscoveryEngine
from src.learning.smart_money.wallet_roles import WalletRoleClassifier
from src.learning.smart_money.wallet_performance import WalletPerformanceCalculator
from src.learning.smart_money.wallet_controls import MatchedControlEvaluator
from src.learning.smart_money.wallet_clusters import WalletClusterDetector
from src.learning.smart_money.wallet_fingerprint import WalletFingerprintLearner
from src.learning.smart_money.wallet_similarity import WalletSimilarityEngine
from src.learning.smart_money.wallet_signal import SmartMoneySignalEngine, WalletActivityEvent
from src.learning.smart_money.wallet_registry import SmartMoneyRegistry, SEED_REFERENCE_WALLETS
from src.learning.smart_money.ab_testing import SmartMoneyABTester
from src.learning.smart_money.error_learning import SmartMoneyErrorLearner


def test_autonomous_wallet_discovery_pre_milestone_cutoff():
    """Verify only transactions occurring BEFORE milestone timestamp/market cap are extracted."""
    txs = [
        {"wallet_address": "WalletEarly1", "timestamp": "2026-08-26T10:05:00Z", "market_cap_usd": 12000.0, "amount_usd": 200.0},
        {"wallet_address": "WalletEarly2", "timestamp": "2026-08-26T10:15:00Z", "market_cap_usd": 28000.0, "amount_usd": 150.0},
        {"wallet_address": "WalletLate", "timestamp": "2026-08-26T10:45:00Z", "market_cap_usd": 120000.0, "amount_usd": 500.0},
    ]

    discovered = AutonomousWalletDiscoveryEngine.discover_wallets_from_winning_token(
        token_address="TokenWin100k",
        symbol="WIN",
        chain="solana",
        venue="pumpfun",
        milestone="TARGET_100K",
        milestone_timestamp="2026-08-26T10:30:00Z",
        milestone_market_cap=100000.0,
        transaction_history=txs,
    )

    addresses = [d.wallet_address for d in discovered]
    assert "WalletEarly1" in addresses
    assert "WalletEarly2" in addresses
    assert "WalletLate" not in addresses  # Entered after milestone cutoff


def test_bayesian_shrinkage_prevents_small_sample_bias():
    """Verify that a 3 wins / 3 trades wallet does NOT outrank an 80 wins / 200 trades wallet in skill confidence."""
    # Wallet 1: 3 wins out of 3 trades (100% raw win rate)
    trades_small = [
        {"realized_return": 200.0, "realized_pnl": 300.0, "is_mature": True, "target_3m": True, "mfe": 2.5, "mae": 0.9}
        for _ in range(3)
    ]
    perf_small = WalletPerformanceCalculator.calculate_performance("WalletSmall", trades_small)

    # Wallet 2: 80 wins out of 200 trades (40% raw win rate, solid sample)
    trades_large = [
        {"realized_return": 150.0 if i < 80 else -40.0, "realized_pnl": 200.0 if i < 80 else -50.0, "is_mature": True, "target_3m": (i < 40), "mfe": 2.2 if i < 80 else 1.1, "mae": 0.8}
        for i in range(200)
    ]
    perf_large = WalletPerformanceCalculator.calculate_performance("WalletLarge", trades_large)

    # Statistical properties
    assert perf_small.raw_win_rate == 100.0
    assert perf_large.raw_win_rate == 40.0

    # Shrunk win rate pulls small sample towards population prior (~10-20%)
    assert perf_small.shrunk_win_rate < 25.0
    assert perf_large.shrunk_win_rate > 35.0

    # Skill confidence must be much higher for the large sample
    assert perf_large.skill_confidence > 0.95
    assert perf_small.skill_confidence < 0.20

    # Risk-adjusted score properly favors validated sample over 3/3 noise
    assert perf_large.risk_adjusted_score > perf_small.risk_adjusted_score


def test_matched_control_group_evaluation():
    """Verify matched control group lift calculation."""
    # Wallet with 60% win rate on Pump.fun (where baseline is ~10%)
    trades = [
        {"venue": "pumpfun", "entry_market_cap": 12000.0, "target_100k": (i % 2 == 0), "realized_return": 50.0 if (i % 2 == 0) else -20.0}
        for i in range(30)
    ]
    lift_eval = MatchedControlEvaluator.evaluate_wallet_lift("SkilledTrader", trades)

    assert lift_eval.total_entries_matched == 30
    assert lift_eval.wallet_success_rate_pct == 50.0
    assert lift_eval.matched_lift_pct > 30.0  # Significant lift over ~10% base rate
    assert lift_eval.is_statistically_significant is True


def test_wallet_role_classification_and_filtering():
    """Verify non-trader roles (deployer, exchange, router) are excluded from smart money signals."""
    cls_deployer = WalletRoleClassifier.classify_wallet("DeployerAddr", [], creation_count=5)
    assert cls_deployer.primary_role == "DEPLOYER"
    assert cls_deployer.is_smart_money_eligible is False

    cls_exchange = WalletRoleClassifier.classify_wallet("BinanceHotWallet", [], is_known_exchange=True)
    assert cls_exchange.primary_role == "EXCHANGE"
    assert cls_exchange.is_smart_money_eligible is False

    organic_trades = [
        {"token_age_minutes": 8.0, "holding_time": 600.0, "position_size_usd": 250.0}
        for _ in range(15)
    ]
    cls_trader = WalletRoleClassifier.classify_wallet("OrganicTrader", organic_trades)
    assert cls_trader.primary_role == "TRADER"
    assert cls_trader.is_smart_money_eligible is True


def test_wallet_cluster_sybil_discounting():
    """Verify sybil rings are discounted rather than multiplying independent counts."""
    # 5 wallets all funded by common private coordinator
    wallets = ["W1", "W2", "W3", "W4", "W5"]
    funding = {w: "PrivateCoordinatorFunder" for w in wallets}

    clusters, eff_count = WalletClusterDetector.analyze_wallet_set(wallets, funding_map=funding)
    assert len(clusters) == 1
    assert clusters[0].is_sybil_ring is True
    assert clusters[0].cluster_size == 5
    # Effective count should be discounted (~5^0.35 = 1.76), NOT 5.0
    assert eff_count < 2.0


def test_12d_entry_fingerprint_and_similarity_scoring():
    """Verify entry setup fingerprint extraction and token match similarity scoring."""
    trades = [
        {"entry_market_cap": 10000.0, "token_age_minutes": 5.0, "entry_liquidity": 4000.0, "market_regime": "NORMAL", "target_100k": True, "realized_return": 100.0}
        for _ in range(20)
    ]
    fp = WalletFingerprintLearner.extract_fingerprint("ValidatedAlpha", trades)
    assert fp.optimal_mc_range_usd[0] <= 10000.0 <= fp.optimal_mc_range_usd[1]

    # Evaluate candidate matching optimal setup
    candidate_good = {
        "token_address": "GoodSetupToken",
        "market_cap_usd": 10000.0,
        "token_age_minutes": 5.0,
        "liquidity_usd": 4000.0,
        "market_regime": "NORMAL",
    }
    match_good = WalletSimilarityEngine.calculate_match_score(candidate_good, [fp])
    assert match_good.smart_wallet_match_score >= 0.85
    assert match_good.setup_classification == "STRONG_SMART_MATCH"

    # Evaluate candidate far outside optimal setup
    candidate_bad = {
        "token_address": "BadSetupToken",
        "market_cap_usd": 450000.0,
        "token_age_minutes": 180.0,
        "liquidity_usd": 120000.0,
        "market_regime": "COLD",
    }
    match_bad = WalletSimilarityEngine.calculate_match_score(candidate_bad, [fp])
    assert match_bad.smart_wallet_match_score < 0.50


def test_point_in_time_look_ahead_guardrails():
    """Verify zero look-ahead bias: trades occurring after cutoff T are strictly excluded."""
    trades = [
        {"timestamp": "2026-08-01T12:00:00Z", "entry_timestamp": "2026-08-01T12:00:00Z", "token": "T1"},
        {"timestamp": "2026-08-10T12:00:00Z", "entry_timestamp": "2026-08-10T12:00:00Z", "token": "T2"},
        {"timestamp": "2026-08-20T12:00:00Z", "entry_timestamp": "2026-08-20T12:00:00Z", "token": "T3"},
    ]

    filtered = PointInTimeGuardrail.filter_trades_before_timestamp(trades, "2026-08-15T00:00:00Z")
    assert len(filtered) == 2
    assert filtered[0]["token"] == "T1"
    assert filtered[1]["token"] == "T2"


def test_smart_money_registry_initialization_and_seeds(tmp_path):
    """Verify SmartMoneyRegistry seeds default user reference wallets."""
    db_path = tmp_path / "smart_money.db"
    reg = SmartMoneyRegistry(db_path=db_path)
    wallets = reg.get_all_wallets()

    addresses = [w["wallet_address"] for w in wallets]
    for seed in SEED_REFERENCE_WALLETS:
        assert seed["address"] in addresses


def test_smart_money_ab_challenger_harness():
    """Verify A/B/C model comparison harness runs and evaluates lift."""
    samples = [
        {"target_3m": (i % 5 == 0), "p_reach_3m": 0.15, "wallet_consensus": 0.8, "smart_wallet_match_score": 0.85}
        for i in range(50)
    ]
    report = SmartMoneyABTester.evaluate_ab_harness(samples)
    assert report.control_a.model_name == "v1.0.0 (Control)"
    assert report.challenger_b.model_name == "v1.0.0 + Wallets (Challenger A)"
    assert report.challenger_c.model_name == "v1.0.0 + Wallets + Fingerprints (Challenger B)"
    assert report.is_challenger_statistically_superior is True


def test_smart_money_error_learning_classification():
    """Verify TP, FP, FN, TN classification of token outcomes."""
    outcomes = [
        {"token_address": "T_TP", "p_reach_3m": 0.25, "target_reached_3m": True, "smart_wallets_count": 2},
        {"token_address": "T_FP", "p_reach_3m": 0.25, "target_reached_3m": False, "smart_wallets_count": 0},
        {"token_address": "T_FN", "p_reach_3m": 0.05, "target_reached_3m": True, "smart_wallets_count": 3},
        {"token_address": "T_TN", "p_reach_3m": 0.02, "target_reached_3m": False, "smart_wallets_count": 0},
    ]
    diagnostics = SmartMoneyErrorLearner.analyze_token_outcomes(outcomes)
    classes = [d.error_class for d in diagnostics]
    assert classes == ["TRUE_POSITIVE", "FALSE_POSITIVE", "FALSE_NEGATIVE", "TRUE_NEGATIVE"]
    assert diagnostics[1].primary_failure_reason == "ABSENT_SMART_MONEY_CONFIRMATION"
    assert diagnostics[2].primary_failure_reason == "EARLY_SMART_WALLET_LEAD"
