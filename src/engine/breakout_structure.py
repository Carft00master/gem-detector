"""
Price Structure & Breakout Classifier Engine
Classifies price-action regimes into:
HEALTHY_STAIRCASE | VERTICAL_PUMP | DISTRIBUTION | CAPITULATION
and outputs BREAKOUT_STRUCTURE_SCORE.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class BreakoutStructureReport:
    regime: str = "NEUTRAL"               # HEALTHY_STAIRCASE, VERTICAL_PUMP, DISTRIBUTION, CAPITULATION
    breakout_structure_score: float = 50.0 # 0.0 to 100.0
    higher_highs_count: int = 0
    higher_lows_count: int = 0
    max_pullback_pct: float = 0.0
    is_controlled_staircase: bool = False
    is_vertical_pump_trap: bool = False
    signals: List[str] = field(default_factory=list)


class BreakoutStructureClassifier:
    @classmethod
    def classify(
        cls,
        return_5m: float,
        return_1h: float,
        volume_mc_ratio_5m: float,
        liquidity_mc_ratio: float,
        buy_sell_volume_ratio: float,
        unique_buyers_count: int,
        cabal_risk_score: float = 0.0,
        higher_highs: int = 0,
        higher_lows: int = 0,
        max_pullback_pct: float = 0.0,
    ) -> BreakoutStructureReport:
        """
        Classify the microcap price-action structure and score breakout sustainability.
        """
        rep = BreakoutStructureReport()
        rep.higher_highs_count = higher_highs
        rep.higher_lows_count = higher_lows
        rep.max_pullback_pct = max_pullback_pct

        score = 50.0
        signals = []

        # 1. Healthy Staircase Pattern
        # Characterized by positive 1h return with controlled pullbacks, healthy LP, and good buyer counts
        if (
            return_1h > 0.30
            and liquidity_mc_ratio >= 0.18
            and buy_sell_volume_ratio >= 1.4
            and unique_buyers_count >= 25
            and max_pullback_pct <= 35.0
            and cabal_risk_score < 0.35
        ):
            rep.regime = "HEALTHY_STAIRCASE"
            rep.is_controlled_staircase = True
            score = 85.0 + min(15.0, (buy_sell_volume_ratio - 1.4) * 10.0)
            signals.append("CONFIRMED_HEALTHY_STAIRCASE")

        # 2. Vertical Pump Trap
        # Extreme short-duration pump with low liquidity, low unique buyers, or cabal bundling
        elif (
            return_5m > 2.0
            and (liquidity_mc_ratio < 0.12 or unique_buyers_count < 15 or cabal_risk_score > 0.50)
        ):
            rep.regime = "VERTICAL_PUMP"
            rep.is_vertical_pump_trap = True
            score = 25.0
            signals.append("VERTICAL_PUMP_LOW_LIQUIDITY_TRAP")

        # 3. Capitulation
        elif return_5m < -0.40 or return_1h < -0.60:
            rep.regime = "CAPITULATION"
            score = 10.0
            signals.append("SEVERE_CAPITULATION_DUMP")

        # 4. Distribution
        elif buy_sell_volume_ratio < 0.70 or (return_1h < 0.0 and volume_mc_ratio_5m > 1.5):
            rep.regime = "DISTRIBUTION"
            score = 20.0
            signals.append("ACTIVE_INSIDER_DISTRIBUTION")

        else:
            rep.regime = "NEUTRAL"
            score = 50.0

        rep.breakout_structure_score = round(min(100.0, max(0.0, score)), 1)
        rep.signals = signals
        return rep
