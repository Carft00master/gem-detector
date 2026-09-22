"""
Unit tests for 4x4 Calibrated Monotonic Probability Grid
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
from src.models.predictor import CalibratedMLPredictor


def test_4x4_grid_monotonicity_invariants():
    cand = TokenCandidate(
        address="TestToken",
        pair_address="Pair",
        symbol="TEST",
        name="Test",
        chain="solana",
        dex_id="raydium",
        market_cap_usd=15000.0,
        price_usd=0.00015,
        liquidity_usd=5000.0,
    )
    predictor = CalibratedMLPredictor()

    ts = TimeSeriesFeatures()
    order_flow = OrderFlowMetrics()
    cabal = CabalAnalysisResult()
    wash = WashTradingAnalysis()
    dev = DevBehaviorReport()
    structure = BreakoutStructureReport()
    safety = DecoupledSafetyReport()
    adj = ManipulationAdjustedSignals()

    pred = predictor.predict(cand, ts, order_flow, cabal, wash, dev, structure, safety, adj)

    # 1. Valuation Tier Monotonicity
    assert pred.p_reach_3m <= pred.p_reach_1m <= pred.p_reach_500k <= pred.p_reach_250k <= pred.p_reach_100k <= pred.p_reach_50k

    # 2. Time Horizon Monotonicity for each tier
    assert pred.p_100k_15m <= pred.p_100k_1h <= pred.p_100k_6h <= pred.p_100k_24h
    assert pred.p_500k_15m <= pred.p_500k_1h <= pred.p_500k_6h <= pred.p_500k_24h
    assert pred.p_1m_15m <= pred.p_1m_1h <= pred.p_1m_6h <= pred.p_1m_24h
    assert pred.p_3m_15m <= pred.p_3m_1h <= pred.p_3m_6h <= pred.p_3m_24h

    # 3. Cross-Tier Invariants for each horizon
    assert pred.p_3m_15m <= pred.p_1m_15m <= pred.p_500k_15m <= pred.p_100k_15m
    assert pred.p_3m_1h <= pred.p_1m_1h <= pred.p_500k_1h <= pred.p_100k_1h
    assert pred.p_3m_6h <= pred.p_1m_6h <= pred.p_500k_6h <= pred.p_100k_6h
    assert pred.p_3m_24h <= pred.p_1m_24h <= pred.p_500k_24h <= pred.p_100k_24h
