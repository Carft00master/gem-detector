"""
Behavioral Wallet Archetypes Classification Engine
Automatically clusters on-chain smart wallets into 7 distinct behavioral archetypes:
- EARLY_SNIPER: Sub-2min entries, sub-$10K MC, aggressive curve velocity targeting
- TRACTION_TRADER: 2-15min entries, high buyer pressure, activity density > 70%
- CURVE_TRADER: 20%-60% bonding curve progress, accumulation pacing
- BREAKOUT_TRADER: $25K-$50K MC entries at structural velocity inflection points
- PULLBACK_TRADER: Local dip buyers post-launch, low MAE (< 0.8)
- MOMENTUM_TRADER: High 5m volume/MC acceleration, fast turnover
- OTHER: Unclassified / hybrid behavioral style
"""

from dataclasses import asdict, dataclass, field
from enum import Enum
import math
from typing import Any, Dict, List, Optional, Tuple
import numpy as np


class WalletArchetype(str, Enum):
    EARLY_SNIPER = "EARLY_SNIPER"
    TRACTION_TRADER = "TRACTION_TRADER"
    CURVE_TRADER = "CURVE_TRADER"
    BREAKOUT_TRADER = "BREAKOUT_TRADER"
    PULLBACK_TRADER = "PULLBACK_TRADER"
    MOMENTUM_TRADER = "MOMENTUM_TRADER"
    OTHER = "OTHER"


@dataclass
class ArchetypeProfile:
    archetype: str
    confidence: float
    secondary_archetype: str
    optimal_mc_range: Tuple[float, float]
    optimal_token_age_range: Tuple[float, float]
    optimal_curve_progress_range: Tuple[float, float]
    preferred_regimes: List[str]
    description: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "archetype": self.archetype,
            "confidence": round(self.confidence, 3),
            "secondary_archetype": self.secondary_archetype,
            "optimal_mc_range": [round(self.optimal_mc_range[0], 2), round(self.optimal_mc_range[1], 2)],
            "optimal_token_age_range": [round(self.optimal_token_age_range[0], 2), round(self.optimal_token_age_range[1], 2)],
            "optimal_curve_progress_range": [round(self.optimal_curve_progress_range[0], 2), round(self.optimal_curve_progress_range[1], 2)],
            "preferred_regimes": self.preferred_regimes,
            "description": self.description,
        }


class WalletArchetypeClassifier:
    """Classifies wallets into behavioral archetypes using observable point-in-time entry patterns."""

    @classmethod
    def classify_interactions(
        cls,
        interactions: List[Dict[str, Any]],
        wallet_summary: Optional[Dict[str, Any]] = None,
    ) -> ArchetypeProfile:
        if not interactions:
            return ArchetypeProfile(
                archetype=WalletArchetype.OTHER.value,
                confidence=0.50,
                secondary_archetype=WalletArchetype.OTHER.value,
                optimal_mc_range=(5000.0, 30000.0),
                optimal_token_age_range=(1.0, 30.0),
                optimal_curve_progress_range=(10.0, 70.0),
                preferred_regimes=["NORMAL"],
                description="Insufficient historical interactions for behavioral archetype clustering.",
            )

        # Extract features across interactions
        token_ages = [float(i.get("token_age_minutes", 5.0) or 5.0) for i in interactions]
        entry_mcs = [float(i.get("entry_market_cap_usd", 12000.0) or 12000.0) for i in interactions]
        curves = [float(i.get("curve_progress_pct", 25.0) or 25.0) for i in interactions]
        maes = [float(i.get("mae_ratio", 1.0) or 1.0) for i in interactions]
        regimes = [str(i.get("market_regime", "NORMAL")) for i in interactions]

        med_age = float(np.median(token_ages))
        med_mc = float(np.median(entry_mcs))
        med_curve = float(np.median(curves))
        med_mae = float(np.median(maes))

        # Score candidates
        scores: Dict[str, float] = {
            WalletArchetype.EARLY_SNIPER.value: 0.0,
            WalletArchetype.TRACTION_TRADER.value: 0.0,
            WalletArchetype.CURVE_TRADER.value: 0.0,
            WalletArchetype.BREAKOUT_TRADER.value: 0.0,
            WalletArchetype.PULLBACK_TRADER.value: 0.0,
            WalletArchetype.MOMENTUM_TRADER.value: 0.0,
        }

        # 1. Early Sniper: med_age < 2.0, med_mc < 10000
        if med_age < 2.0 and med_mc < 10000.0:
            scores[WalletArchetype.EARLY_SNIPER.value] += 0.85
        elif med_age < 3.0:
            scores[WalletArchetype.EARLY_SNIPER.value] += 0.40

        # 2. Traction Trader: 2.0 <= med_age <= 15.0, high activity
        if 2.0 <= med_age <= 15.0 and 8000.0 <= med_mc <= 30000.0:
            scores[WalletArchetype.TRACTION_TRADER.value] += 0.80

        # 3. Curve Trader: 20.0 <= med_curve <= 65.0
        if 20.0 <= med_curve <= 65.0:
            scores[WalletArchetype.CURVE_TRADER.value] += 0.75

        # 4. Breakout Trader: 25000.0 <= med_mc <= 60000.0
        if 25000.0 <= med_mc <= 60000.0:
            scores[WalletArchetype.BREAKOUT_TRADER.value] += 0.85

        # 5. Pullback Trader: med_mae < 0.80 and med_age > 3.0
        if med_mae < 0.80 and med_age >= 3.0:
            scores[WalletArchetype.PULLBACK_TRADER.value] += 0.75

        # 6. Momentum Trader: Fast turnover, high MC velocity
        if med_curve > 50.0 and med_mc > 20000.0:
            scores[WalletArchetype.MOMENTUM_TRADER.value] += 0.70

        sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        best_archetype, best_score = sorted_scores[0]
        second_archetype, _ = sorted_scores[1]

        if best_score < 0.35:
            best_archetype = WalletArchetype.OTHER.value
            conf = 0.50
        else:
            conf = min(0.95, max(0.55, best_score))

        # Preferred regimes
        reg_counts: Dict[str, int] = {}
        for r in regimes:
            reg_counts[r] = reg_counts.get(r, 0) + 1
        pref_regimes = sorted(reg_counts.keys(), key=lambda k: reg_counts[k], reverse=True)[:2] or ["NORMAL"]

        # Descriptions
        desc_map = {
            WalletArchetype.EARLY_SNIPER.value: "Specializes in ultra-early sub-2min entries with minimal initial market cap exposure.",
            WalletArchetype.TRACTION_TRADER.value: "Enters during early traction verification window (2–15 min) with confirmed organic volume.",
            WalletArchetype.CURVE_TRADER.value: "Systematically accumulates during bonding curve progress (20%–60%) prior to migration.",
            WalletArchetype.BREAKOUT_TRADER.value: "Enters at major structural resistance inflection points ($25K–$50K MC).",
            WalletArchetype.PULLBACK_TRADER.value: "Identifies and enters high-conviction runners on healthy initial retracements (low MAE).",
            WalletArchetype.MOMENTUM_TRADER.value: "Captures rapid price and volume acceleration on high-velocity trending runners.",
            WalletArchetype.OTHER.value: "Broad multi-setup participant without a concentrated behavioral signature.",
        }

        # Parameter sweet spots
        p25_mc, p75_mc = float(np.percentile(entry_mcs, 25)), float(np.percentile(entry_mcs, 75))
        p25_age, p75_age = float(np.percentile(token_ages, 25)), float(np.percentile(token_ages, 75))
        p25_curve, p75_curve = float(np.percentile(curves, 25)), float(np.percentile(curves, 75))

        return ArchetypeProfile(
            archetype=best_archetype,
            confidence=conf,
            secondary_archetype=second_archetype,
            optimal_mc_range=(max(1000.0, p25_mc * 0.8), min(150000.0, p75_mc * 1.2)),
            optimal_token_age_range=(max(0.5, p25_age * 0.8), min(120.0, p75_age * 1.2)),
            optimal_curve_progress_range=(max(0.0, p25_curve * 0.8), min(100.0, p75_curve * 1.2)),
            preferred_regimes=pref_regimes,
            description=desc_map.get(best_archetype, ""),
        )
