"""
Trader-Style Early Traction & Profile Matcher Engine (Trader Behavior v1.0.0)
Synthesizes Activity Density, Participation Breadth, Two-Sided Market Quality, Curve Traction,
Momentum, and Liquidity into the composite EARLY_TRACTION_SCORE (0–100).
Calculates TRADER_STYLE_MATCH_SCORE (0–100) via multi-dimensional standardized similarity.
"""

from dataclasses import dataclass
import math
from typing import Any, Dict, List, Optional

from src.trader_behavior.activity_density import ActivityDensityMetrics
from src.trader_behavior.curve_traction import CurveTractionMetrics
from src.trader_behavior.participation import ParticipationBreadthMetrics
from src.trader_behavior.two_sided import TwoSidedMarketQualityMetrics


@dataclass
class EarlyTractionBundle:
    token_address: str
    symbol: str

    # Component Scores (0–100)
    activity_density_score: float = 50.0
    participation_breadth_score: float = 50.0
    two_sided_market_quality: float = 50.0
    curve_traction_score: float = 50.0
    momentum_quality_score: float = 50.0
    liquidity_quality_score: float = 50.0

    # Composite Scores (0–100)
    early_traction_score: float = 50.0
    trader_style_match_score: float = 50.0

    # Underlying Detail Metrics
    activity: Optional[ActivityDensityMetrics] = None
    participation: Optional[ParticipationBreadthMetrics] = None
    two_sided: Optional[TwoSidedMarketQualityMetrics] = None
    curve: Optional[CurveTractionMetrics] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "token_address": self.token_address,
            "symbol": self.symbol,
            "activity_density_score": self.activity_density_score,
            "participation_breadth_score": self.participation_breadth_score,
            "two_sided_market_quality": self.two_sided_market_quality,
            "curve_traction_score": self.curve_traction_score,
            "momentum_quality_score": self.momentum_quality_score,
            "liquidity_quality_score": self.liquidity_quality_score,
            "early_traction_score": self.early_traction_score,
            "trader_style_match_score": self.trader_style_match_score,
            "activity_metrics": self.activity.to_dict() if self.activity else {},
            "participation_metrics": self.participation.to_dict() if self.participation else {},
            "two_sided_metrics": self.two_sided.to_dict() if self.two_sided else {},
            "curve_metrics": self.curve.to_dict() if self.curve else {},
        }


class TraderStyleEarlyTractionEngine:
    """
    Computes early traction composite metrics and profile similarity matches.
    """

    # Idealized Target Profile Vector for early-stage breakout traction:
    # [MC_norm, Age_norm, ActDensity, PartBreadth, TwoSided, CurveTraction, BuyPressure, VolLiqRatio]
    TARGET_TRACTION_PROFILE = {
        "mc_target": 15000.0,       # $15K ideal sweet spot
        "age_target_min": 8.0,      # 8m ideal discovery age
        "act_density": 85.0,
        "part_breadth": 80.0,
        "two_sided": 75.0,
        "curve_traction": 75.0,
        "buy_pressure": 0.65,
    }

    @classmethod
    def evaluate(
        cls,
        token_address: str,
        symbol: str,
        market_cap_usd: float,
        liquidity_usd: float,
        token_age_minutes: float,
        activity: ActivityDensityMetrics,
        participation: ParticipationBreadthMetrics,
        two_sided: TwoSidedMarketQualityMetrics,
        curve: CurveTractionMetrics,
        momentum_return_5m_pct: float = 0.0,
    ) -> EarlyTractionBundle:
        mc = max(100.0, float(market_cap_usd))
        liq = max(100.0, float(liquidity_usd))
        age = max(0.5, float(token_age_minutes))

        # 1. Momentum Quality (0–100)
        ret5 = float(momentum_return_5m_pct)
        if ret5 >= 0.20:
            mom_score = 95.0
        elif ret5 >= 0.10:
            mom_score = 80.0
        elif ret5 >= 0.03:
            mom_score = 65.0
        elif ret5 >= -0.05:
            mom_score = 50.0
        else:
            mom_score = max(10.0, 50.0 + ret5 * 200.0)

        # 2. Liquidity Quality (0–100)
        liq_mc = liq / mc
        if 0.15 <= liq_mc <= 0.45:
            liq_score = 85.0
        elif liq_mc > 0.45:
            liq_score = 70.0
        else:
            liq_score = max(15.0, (liq_mc / 0.15) * 85.0)

        # 3. Composite Early Traction Score (0–100)
        # Weights:
        # 30% Activity Density
        # 20% Participation Breadth
        # 20% Two-Sided Market Quality
        # 15% Curve Traction (or distributed if NOT_APPLICABLE)
        # 10% Momentum Quality
        # 5% Liquidity Quality
        if curve.status in ("NOT_APPLICABLE", "MISSING"):
            w_act = 0.35
            w_part = 0.25
            w_two = 0.25
            w_curv = 0.0
            w_mom = 0.10
            w_liq = 0.05
        else:
            w_act = 0.30
            w_part = 0.20
            w_two = 0.20
            w_curv = 0.15
            w_mom = 0.10
            w_liq = 0.05

        early_traction_score = (
            activity.activity_density_score * w_act +
            participation.participation_breadth_score * w_part +
            two_sided.two_sided_market_quality * w_two +
            (curve.curve_traction_score if w_curv > 0 else 0.0) * w_curv +
            mom_score * w_mom +
            liq_score * w_liq
        )
        early_traction_score = max(0.0, min(100.0, early_traction_score))

        # 4. Trader-Style Match Score (0–100)
        # Mahalanobis / Normalized Euclidean distance from reference trading profile
        match_score = cls._compute_style_match(
            mc=mc,
            age=age,
            act_score=activity.activity_density_score,
            part_score=participation.participation_breadth_score,
            two_sided_score=two_sided.two_sided_market_quality,
            curve_score=curve.curve_traction_score if curve.status == "AVAILABLE" else 50.0,
            buy_pressure=two_sided.buy_pressure_index,
        )

        return EarlyTractionBundle(
            token_address=token_address,
            symbol=symbol,
            activity_density_score=activity.activity_density_score,
            participation_breadth_score=participation.participation_breadth_score,
            two_sided_market_quality=two_sided.two_sided_market_quality,
            curve_traction_score=curve.curve_traction_score,
            momentum_quality_score=mom_score,
            liquidity_quality_score=liq_score,
            early_traction_score=early_traction_score,
            trader_style_match_score=match_score,
            activity=activity,
            participation=participation,
            two_sided=two_sided,
            curve=curve,
        )

    @classmethod
    def _compute_style_match(
        cls,
        mc: float,
        age: float,
        act_score: float,
        part_score: float,
        two_sided_score: float,
        curve_score: float,
        buy_pressure: float,
    ) -> float:
        """
        Calculates similarity percentage [0, 100] against reference traction profile.
        """
        p = cls.TARGET_TRACTION_PROFILE

        # Normalized feature errors [0, 1]
        mc_diff = abs(math.log10(mc) - math.log10(p["mc_target"])) / 1.5
        age_diff = abs(math.log10(max(1.0, age)) - math.log10(p["age_target_min"])) / 1.2
        act_diff = abs(act_score - p["act_density"]) / 100.0
        part_diff = abs(part_score - p["part_breadth"]) / 100.0
        two_diff = abs(two_sided_score - p["two_sided"]) / 100.0
        curv_diff = abs(curve_score - p["curve_traction"]) / 100.0
        bp_diff = abs(buy_pressure - p["buy_pressure"]) / 0.5

        # Weighted squared Euclidean distance
        weighted_sq_dist = (
            (mc_diff ** 2) * 0.25 +
            (age_diff ** 2) * 0.15 +
            (act_diff ** 2) * 0.25 +
            (part_diff ** 2) * 0.15 +
            (two_diff ** 2) * 0.10 +
            (curv_diff ** 2) * 0.05 +
            (bp_diff ** 2) * 0.05
        )

        dist = math.sqrt(weighted_sq_dist)
        # Convert distance to similarity score
        sim = math.exp(-1.8 * dist) * 100.0
        return max(0.0, min(100.0, sim))
