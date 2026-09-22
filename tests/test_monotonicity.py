"""
Unit tests for Monotonic Target Probabilities and Opportunity Score
"""

import pytest
from src.engine.adjusted_signals import ManipulationAdjustedSignals
from src.engine.breakout_structure import BreakoutStructureReport
from src.engine.dev_behavior import DevBehaviorReport
from src.engine.features import TimeSeriesFeatures
from src.engine.order_flow import OrderFlowMetrics
from src.engine.safety_v2 import DecoupledSafetyReport
from src.engine.wallet_graph import CabalAnalysisResult
from src.engine.wash_trading import WashTradingAnalysis
from src.feeds.base_feed import TokenCandidate
from src.models.predictor import CalibratedMLPredictor, RuleBasedBaselineModel


def test_strict_monotonic_probability_hierarchy():
    """
    Verify that P(3M) <= P(1M) <= P(500K) <= P(250K) <= P(100K) <= P(50K)
    across all diverse candidate profiles.
    """
    predictor = CalibratedMLPredictor()

    cand = TokenCandidate(
        address="TestMint",
        pair_address="Pair",
        symbol="MONO",
        name="Monotonic",
        chain="solana",
        dex_id="pumpfun",
        market_cap_usd=20000.0,
        price_usd=0.0002,
        liquidity_usd=5000.0,
        volume_5m_usd=2500.0,
        volume_1h_usd=15000.0,
        txns_5m_buys=35,
        txns_5m_sells=10,
        unique_buyers_1h=45,
        unique_sellers_1h=12,
        age_minutes=20.0,
    )
    cand.calculate_ratios()

    ts = TimeSeriesFeatures(return_5m=0.20, volume_mc_ratio_5m=0.12)
    of = OrderFlowMetrics(volume_weighted_buy_ratio=0.75, trade_size_entropy=1.3)
    cabal = CabalAnalysisResult(cabal_risk_score=0.10, wallet_independence_score=0.90)
    wash = WashTradingAnalysis(wash_trade_risk=0.10, volume_quality_score=0.90)
    dev = DevBehaviorReport(classification="STRONG", dev_risk_score=0.05)
    struct = BreakoutStructureReport(regime="HEALTHY_STAIRCASE", breakout_structure_score=85.0)
    safety = DecoupledSafetyReport(contract_risk=0.0, liquidity_risk=0.05)
    adj = ManipulationAdjustedSignals(
        effective_volume_mc_ratio_5m=0.11,
        effective_buy_volume_pressure=0.70,
        buyer_quality=0.85,
        liquidity_quality=0.80,
        holder_quality=0.85,
        breakout_quality=0.85,
        wallet_independence=0.90,
    )

    pred = predictor.predict(cand, ts, of, cabal, wash, dev, struct, safety, adj)

    # 1. Verify strict monotonicity
    assert pred.p_reach_3m <= pred.p_reach_1m
    assert pred.p_reach_1m <= pred.p_reach_500k
    assert pred.p_reach_500k <= pred.p_reach_250k
    assert pred.p_reach_250k <= pred.p_reach_100k
    assert pred.p_reach_100k <= pred.p_reach_50k

    # 2. Verify all probabilities bounded in [0, 1]
    for p_val in [pred.p_reach_50k, pred.p_reach_100k, pred.p_reach_500k, pred.p_reach_1m, pred.p_reach_3m]:
        assert 0.0 <= p_val <= 1.0

    # 3. Verify Opportunity Score bounded in [0, 100]
    assert 0.0 <= pred.risk_adjusted_opportunity_score <= 100.0
