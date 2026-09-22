"""
Unit tests for Probability Calibration, Precision@K, and Base-Rate Lift Metrics
"""

import pytest
from src.models.predictor import CalibratedMLPredictor
from src.research.evaluation import ResearchEvaluator
from src.feeds.base_feed import TokenCandidate, TokenSecurityReport
from src.engine.features import TimeSeriesFeatures
from src.engine.order_flow import OrderFlowMetrics
from src.engine.wallet_graph import CabalAnalysisResult
from src.engine.wash_trading import WashTradingAnalysis
from src.engine.dev_behavior import DevBehaviorReport
from src.engine.breakout_structure import BreakoutStructureReport
from src.engine.safety_v2 import DecoupledSafetyReport
from src.engine.adjusted_signals import ManipulationAdjustedSignals


def test_calibrated_ml_predictor_bounds_and_ranking():
    predictor = CalibratedMLPredictor()

    cand = TokenCandidate(
        address="TestMint",
        pair_address="Pair",
        symbol="WINNER",
        name="Winner",
        chain="solana",
        dex_id="pumpfun",
        market_cap_usd=25000.0,
        price_usd=0.00025,
        liquidity_usd=6500.0,
        volume_5m_usd=3000.0,
        volume_1h_usd=20000.0,
        txns_5m_buys=40,
        txns_5m_sells=10,
        unique_buyers_1h=50,
        unique_sellers_1h=12,
        age_minutes=25.0,
    )
    cand.calculate_ratios()

    ts = TimeSeriesFeatures(return_5m=0.25, volume_mc_ratio_5m=0.12)
    of = OrderFlowMetrics(volume_weighted_buy_ratio=0.80, trade_size_entropy=1.4, order_flow_quality_score=0.90)
    cabal = CabalAnalysisResult(cabal_risk_score=0.05, wallet_independence_score=0.95)
    wash = WashTradingAnalysis(wash_trade_risk=0.05, volume_quality_score=0.95)
    dev = DevBehaviorReport(classification="STRONG", dev_risk_score=0.05)
    struct = BreakoutStructureReport(regime="HEALTHY_STAIRCASE", breakout_structure_score=90.0, is_controlled_staircase=True)
    safety = DecoupledSafetyReport(contract_risk=0.0, liquidity_risk=0.05, distribution_risk=0.10)
    adj = ManipulationAdjustedSignals(
        effective_volume_mc_ratio_5m=0.11,
        effective_buy_volume_pressure=0.76,
        buyer_quality=0.92,
        liquidity_quality=0.88,
        holder_quality=0.90,
        breakout_quality=0.90,
        wallet_independence=0.95,
    )

    pred = predictor.predict(cand, ts, of, cabal, wash, dev, struct, safety, adj)

    assert 0.0 <= pred.p_reach_3m <= 1.0
    assert 0.0 <= pred.p_reach_100k <= 1.0
    assert 0.0 <= pred.p_rug <= 1.0
    assert pred.p_reach_3m > 0.05  # High-conviction winner setup
    assert pred.alert_state == "HIGH_CONVICTION"
    assert pred.is_calibrated is True


def test_research_evaluator_metrics():
    y_true = [1, 1, 0, 1, 0, 0, 0, 0, 0, 0]  # 30% base rate
    y_prob = [0.9, 0.8, 0.7, 0.6, 0.4, 0.3, 0.2, 0.1, 0.1, 0.05]

    report = ResearchEvaluator.evaluate_model(
        y_true=y_true,
        y_prob=y_prob,
        model_name="TestModel",
        threshold=0.5,
    )

    assert report.precision_at_10 == 0.30
    assert report.precision == 0.75  # 3 TP out of 4 predictions above 0.5
    assert report.recall == 1.0     # 3 TP out of 3 total true positives
    assert report.roc_auc >= 0.85
    assert report.base_rate_lift_3m > 2.0  # 75% precision / 30% base rate = 2.5x lift
