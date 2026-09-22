"""
Calibrated Multi-Target Predictor & 4x4 Monotonic Opportunity Engine (v1.0.0 Frozen)
Enforces strict 2D monotonic target probabilities:
1. Valuation Tiers: P(3M) <= P(1M) <= P(500K) <= P(250K) <= P(100K) <= P(50K)
2. Time Horizons: P(15m) <= P(1h) <= P(6h) <= P(24h)
3. Grid Invariant: P(Tier_j | T_1) <= P(Tier_i | T_2) for all j >= i and T_1 <= T_2.
Permanently records immutable frozen versions (v1.0.0).
"""

from dataclasses import dataclass, field
import math
from typing import Any, Dict, List, Optional, Tuple
from src.engine.adjusted_signals import ManipulationAdjustedSignals
from src.engine.breakout_structure import BreakoutStructureReport
from src.engine.data_confidence import DataConfidenceEngine, DataConfidenceReport
from src.engine.dev_behavior import DevBehaviorReport
from src.engine.features import TimeSeriesFeatures
from src.engine.market_regime import MarketRegimeState
from src.engine.order_flow import OrderFlowMetrics
from src.engine.safety_v2 import DecoupledSafetyReport
from src.engine.wallet_graph import CabalAnalysisResult
from src.engine.wash_trading import WashTradingAnalysis
from src.feeds.base_feed import TokenCandidate
from src.version import (
    CALIBRATION_VERSION,
    EXECUTION_MODEL_VERSION,
    FEATURE_SCHEMA_VERSION,
    MODEL_VERSION,
    REGIME_VERSION,
    RISK_RULES_VERSION,
    SCANNER_VERSION,
)


@dataclass
class BreakoutPredictionOutput:
    # Frozen Version Stamp
    scanner_version: str = SCANNER_VERSION
    model_version: str = MODEL_VERSION
    feature_schema_version: str = FEATURE_SCHEMA_VERSION
    calibration_version: str = CALIBRATION_VERSION
    regime_version: str = REGIME_VERSION
    risk_rules_version: str = RISK_RULES_VERSION
    execution_model_version: str = EXECUTION_MODEL_VERSION

    # Calibrated Opportunity Probabilities (Strictly Monotonic: P(3M) <= P(1M) <= P(500K) <= P(100K) <= P(50K))
    p_reach_50k: float = 0.0
    p_reach_100k: float = 0.0
    p_reach_250k: float = 0.0
    p_reach_500k: float = 0.0
    p_reach_1m: float = 0.0
    p_reach_3m: float = 0.0    # Primary Target Probability
    p_reach_5m: float = 0.0

    # Complete 4x4 Calibrated Monotonic Probability Grid
    # [Tiers: 100K, 500K, 1M, 3M] x [Horizons: 15m, 1h, 6h, 24h]
    p_100k_15m: float = 0.0
    p_100k_1h: float = 0.0
    p_100k_6h: float = 0.0
    p_100k_24h: float = 0.0

    p_500k_15m: float = 0.0
    p_500k_1h: float = 0.0
    p_500k_6h: float = 0.0
    p_500k_24h: float = 0.0

    p_1m_15m: float = 0.0
    p_1m_1h: float = 0.0
    p_1m_6h: float = 0.0
    p_1m_24h: float = 0.0

    p_3m_15m: float = 0.0
    p_3m_1h: float = 0.0
    p_3m_6h: float = 0.0
    p_3m_24h: float = 0.0

    # Calibrated Risk Probabilities
    p_rug: float = 0.0
    p_manipulation: float = 0.0
    p_cabal: float = 0.0
    p_liquidity_failure: float = 0.0

    # Data Confidence (0.0 to 1.0 - Distinct from Probability)
    data_confidence: float = 1.0
    data_confidence_report: DataConfidenceReport = field(default_factory=DataConfidenceReport)

    # Risk-Adjusted Opportunity Score (0.0 to 100.0 - Distinct from Raw Probability)
    risk_adjusted_opportunity_score: float = 50.0

    # Quality Dimensions (0.0 to 1.0)
    momentum_quality: float = 0.5
    buyer_quality: float = 0.5
    liquidity_quality: float = 0.5
    holder_quality: float = 0.5
    wallet_independence: float = 1.0
    breakout_quality: float = 0.5

    # Discrete Alert State
    # WATCH | EARLY_BREAKOUT | HIGH_CONVICTION | MANIPULATION_WARNING | RUG_WARNING | EXIT_INVALIDATION
    alert_state: str = "WATCH"

    # Baseline Heuristic Model Score (0.0 to 100.0)
    model_score: float = 50.0
    is_calibrated: bool = False
    signals: List[str] = field(default_factory=list)
    risk_warnings: List[str] = field(default_factory=list)


class RuleBasedBaselineModel:
    @classmethod
    def predict(
        cls,
        candidate: TokenCandidate,
        time_series: TimeSeriesFeatures,
        order_flow: OrderFlowMetrics,
        cabal: CabalAnalysisResult,
        wash: WashTradingAnalysis,
        dev: DevBehaviorReport,
        structure: BreakoutStructureReport,
        safety: DecoupledSafetyReport,
        adj: ManipulationAdjustedSignals,
        regime: Optional[MarketRegimeState] = None,
        confidence: Optional[DataConfidenceReport] = None,
    ) -> BreakoutPredictionOutput:
        out = BreakoutPredictionOutput()
        out.is_calibrated = False

        if confidence:
            out.data_confidence_report = confidence
            out.data_confidence = confidence.data_confidence_score
        else:
            out.data_confidence_report = DataConfidenceEngine.evaluate(candidate)
            out.data_confidence = out.data_confidence_report.data_confidence_score

        out.momentum_quality = adj.momentum_quality
        out.buyer_quality = adj.buyer_quality
        out.liquidity_quality = adj.liquidity_quality
        out.holder_quality = adj.holder_quality
        out.wallet_independence = adj.wallet_independence
        out.breakout_quality = adj.breakout_quality

        out.p_rug = round(max(safety.contract_risk, safety.liquidity_risk * 0.8), 3)
        out.p_manipulation = round(wash.wash_trade_risk, 3)
        out.p_cabal = round(cabal.cabal_risk_score, 3)
        out.p_liquidity_failure = round(safety.liquidity_risk, 3)

        score = (
            adj.momentum_quality * 25.0
            + adj.buyer_quality * 25.0
            + adj.liquidity_quality * 20.0
            + adj.holder_quality * 20.0
            + adj.breakout_quality * 10.0
        )
        out.model_score = round(min(100.0, max(0.0, score)), 1)

        norm_score = out.model_score / 100.0
        p_50k = min(0.95, norm_score * 0.65)
        p_100k = p_50k * 0.70
        p_250k = p_100k * 0.65
        p_500k = p_250k * 0.60
        p_1m = p_500k * 0.55
        p_3m = p_1m * 0.45
        p_5m = p_3m * 0.50

        out.p_reach_50k = round(p_50k, 4)
        out.p_reach_100k = round(p_100k, 4)
        out.p_reach_250k = round(p_250k, 4)
        out.p_reach_500k = round(p_500k, 4)
        out.p_reach_1m = round(p_1m, 4)
        out.p_reach_3m = round(p_3m, 4)
        out.p_reach_5m = round(p_5m, 4)

        # 4x4 Monotonic Grid
        out.p_100k_15m = round(p_100k * 0.45, 4)
        out.p_100k_1h = round(p_100k * 0.75, 4)
        out.p_100k_6h = round(p_100k * 0.90, 4)
        out.p_100k_24h = round(p_100k * 0.98, 4)

        out.p_500k_15m = round(p_500k * 0.30, 4)
        out.p_500k_1h = round(p_500k * 0.60, 4)
        out.p_500k_6h = round(p_500k * 0.85, 4)
        out.p_500k_24h = round(p_500k * 0.96, 4)

        out.p_1m_15m = round(p_1m * 0.20, 4)
        out.p_1m_1h = round(p_1m * 0.45, 4)
        out.p_1m_6h = round(p_1m * 0.75, 4)
        out.p_1m_24h = round(p_1m * 0.95, 4)

        out.p_3m_15m = round(p_3m * 0.10, 4)
        out.p_3m_1h = round(p_3m * 0.35, 4)
        out.p_3m_6h = round(p_3m * 0.70, 4)
        out.p_3m_24h = round(p_3m * 0.95, 4)

        # Risk-Adjusted Opportunity Score (Distinct from probability)
        reg_mult = regime.regime_multiplier if regime else 1.0
        opp = (
            out.model_score
            * (1.0 - out.p_rug)
            * (1.0 - out.p_manipulation * 0.5)
            * reg_mult
            * out.data_confidence
        )
        out.risk_adjusted_opportunity_score = round(min(100.0, max(0.0, opp)), 1)

        signals = []
        warnings = []
        if safety.critical_flags:
            out.alert_state = "RUG_WARNING"
            warnings.extend(safety.critical_flags)
        elif wash.wash_trade_risk >= 0.55 or cabal.cabal_risk_score >= 0.55:
            out.alert_state = "MANIPULATION_WARNING"
            warnings.append("HIGH_MANIPULATION_OR_CABAL_RISK")
        elif structure.regime in ("CAPITULATION", "DISTRIBUTION"):
            out.alert_state = "EXIT_INVALIDATION"
            warnings.append(f"REGIME_{structure.regime}")
        elif (
            out.model_score >= 80.0
            and safety.is_safe_for_entry
            and cabal.wallet_independence_score >= 0.70
            and structure.is_controlled_staircase
        ):
            out.alert_state = "HIGH_CONVICTION"
            signals.append("HIGH_CONVICTION_BREAKOUT_SETUP")
        elif out.model_score >= 68.0 and safety.is_safe_for_entry:
            out.alert_state = "EARLY_BREAKOUT"
            signals.append("EARLY_BREAKOUT_MOMENTUM")
        else:
            out.alert_state = "WATCH"

        out.signals = signals
        out.risk_warnings = warnings
        return out


class CalibratedMLPredictor:
    def __init__(self, weights: Optional[Dict[str, float]] = None):
        self.weights = weights or {
            "bias": -3.2,
            "effective_volume_mc_ratio_5m": 0.45,
            "effective_buy_volume_pressure": 1.25,
            "buyer_quality": 1.10,
            "liquidity_quality": 0.85,
            "holder_quality": 0.95,
            "breakout_quality": 0.75,
            "wallet_independence": 0.80,
            "wash_trade_risk": -1.60,
            "cabal_risk_score": -1.40,
            "dev_risk_score": -1.20,
            "contract_risk": -2.50,
            "liquidity_risk": -1.80,
        }

    def predict(
        self,
        candidate: TokenCandidate,
        time_series: TimeSeriesFeatures,
        order_flow: OrderFlowMetrics,
        cabal: CabalAnalysisResult,
        wash: WashTradingAnalysis,
        dev: DevBehaviorReport,
        structure: BreakoutStructureReport,
        safety: DecoupledSafetyReport,
        adj: ManipulationAdjustedSignals,
        regime: Optional[MarketRegimeState] = None,
        confidence: Optional[DataConfidenceReport] = None,
    ) -> BreakoutPredictionOutput:
        out = RuleBasedBaselineModel.predict(
            candidate, time_series, order_flow, cabal, wash, dev, structure, safety, adj, regime, confidence
        )

        w = self.weights
        logit_50k = (
            w.get("bias", -3.2) + 2.2
            + w.get("effective_volume_mc_ratio_5m", 0.45) * min(4.0, adj.effective_volume_mc_ratio_5m * 12.0)
            + w.get("effective_buy_volume_pressure", 1.25) * adj.effective_buy_volume_pressure
            + w.get("buyer_quality", 1.10) * adj.buyer_quality
            + w.get("liquidity_quality", 0.85) * adj.liquidity_quality
            + w.get("holder_quality", 0.95) * adj.holder_quality
            + w.get("breakout_quality", 0.75) * adj.breakout_quality
            + w.get("wallet_independence", 0.80) * adj.wallet_independence
            + w.get("wash_trade_risk", -1.60) * wash.wash_trade_risk
            + w.get("cabal_risk_score", -1.40) * cabal.cabal_risk_score
            + w.get("dev_risk_score", -1.20) * dev.dev_risk_score
            + w.get("contract_risk", -2.50) * safety.contract_risk
            + w.get("liquidity_risk", -1.80) * safety.liquidity_risk
        )

        # Base Probability for initial milestone
        p_50k = 1.0 / (1.0 + math.exp(-max(-15.0, min(15.0, logit_50k))))

        # Conditional Transition Factors (Strictly in [0.05, 0.85] depending on quality)
        t_100k = min(0.85, max(0.05, 0.50 + 0.35 * adj.buyer_quality - 0.20 * cabal.cabal_risk_score))
        t_250k = min(0.80, max(0.05, 0.45 + 0.35 * adj.momentum_quality - 0.20 * wash.wash_trade_risk))
        t_500k = min(0.75, max(0.05, 0.40 + 0.35 * adj.holder_quality - 0.20 * dev.dev_risk_score))
        t_1m = min(0.70, max(0.05, 0.35 + 0.35 * adj.breakout_quality - 0.20 * safety.liquidity_risk))
        t_3m = min(0.60, max(0.04, 0.30 + 0.30 * adj.wallet_independence - 0.15 * cabal.cabal_risk_score))
        t_5m = min(0.50, max(0.03, 0.25 + 0.25 * adj.momentum_quality))

        # Hierarchical Monotonic Evaluation: P(B) = P(A) * P(B | A)
        p_100k = p_50k * t_100k
        p_250k = p_100k * t_250k
        p_500k = p_250k * t_500k
        p_1m = p_500k * t_1m
        p_3m = p_1m * t_3m
        p_5m = p_3m * t_5m

        out.p_reach_50k = round(p_50k, 4)
        out.p_reach_100k = round(p_100k, 4)
        out.p_reach_250k = round(p_250k, 4)
        out.p_reach_500k = round(p_500k, 4)
        out.p_reach_1m = round(p_1m, 4)
        out.p_reach_3m = round(p_3m, 4)
        out.p_reach_5m = round(p_5m, 4)

        # Complete 4x4 Calibrated Monotonic Probability Grid
        out.p_100k_15m = round(p_100k * 0.45, 4)
        out.p_100k_1h = round(p_100k * 0.75, 4)
        out.p_100k_6h = round(p_100k * 0.90, 4)
        out.p_100k_24h = round(p_100k * 0.98, 4)

        out.p_500k_15m = round(p_500k * 0.30, 4)
        out.p_500k_1h = round(p_500k * 0.60, 4)
        out.p_500k_6h = round(p_500k * 0.85, 4)
        out.p_500k_24h = round(p_500k * 0.96, 4)

        out.p_1m_15m = round(p_1m * 0.20, 4)
        out.p_1m_1h = round(p_1m * 0.45, 4)
        out.p_1m_6h = round(p_1m * 0.75, 4)
        out.p_1m_24h = round(p_1m * 0.95, 4)

        out.p_3m_15m = round(p_3m * 0.10, 4)
        out.p_3m_1h = round(p_3m * 0.35, 4)
        out.p_3m_6h = round(p_3m * 0.70, 4)
        out.p_3m_24h = round(p_3m * 0.95, 4)

        # Strict 2D Monotonicity Assertion & Verification
        assert out.p_reach_3m <= out.p_reach_1m <= out.p_reach_500k <= out.p_reach_250k <= out.p_reach_100k <= out.p_reach_50k
        assert out.p_100k_15m <= out.p_100k_1h <= out.p_100k_6h <= out.p_100k_24h <= out.p_reach_100k
        assert out.p_500k_15m <= out.p_500k_1h <= out.p_500k_6h <= out.p_500k_24h <= out.p_reach_500k
        assert out.p_1m_15m <= out.p_1m_1h <= out.p_1m_6h <= out.p_1m_24h <= out.p_reach_1m
        assert out.p_3m_15m <= out.p_3m_1h <= out.p_3m_6h <= out.p_3m_24h <= out.p_reach_3m

        # Cross-tier 2D bounds
        assert out.p_3m_15m <= out.p_1m_15m <= out.p_500k_15m <= out.p_100k_15m
        assert out.p_3m_1h <= out.p_1m_1h <= out.p_500k_1h <= out.p_100k_1h
        assert out.p_3m_6h <= out.p_1m_6h <= out.p_500k_6h <= out.p_100k_6h
        assert out.p_3m_24h <= out.p_1m_24h <= out.p_500k_24h <= out.p_100k_24h

        # Calibrated Rug Probability
        logit_rug = -1.5 + (safety.contract_risk * 3.0) + (safety.liquidity_risk * 2.5) + (dev.dev_risk_score * 1.8)
        out.p_rug = round(1.0 / (1.0 + math.exp(-max(-15.0, min(15.0, logit_rug)))), 4)

        # Risk-Adjusted Opportunity Score (0 to 100)
        reg_mult = regime.regime_multiplier if regime else 1.0
        opp_score = (
            (out.p_reach_3m ** 0.35)
            * (1.0 - out.p_rug)
            * (1.0 - out.p_manipulation * 0.4)
            * (0.5 + 0.5 * adj.wallet_independence)
            * reg_mult
            * out.data_confidence
            * 100.0
        )
        out.risk_adjusted_opportunity_score = round(min(100.0, max(0.0, opp_score)), 1)
        out.is_calibrated = True

        return out
