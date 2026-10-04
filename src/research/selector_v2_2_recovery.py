"""
SELECTOR v2.2 — LOW-FREQUENCY WINNER RECOVERY ARCHITECTURE
============================================================
Research-Grade Token Selection After Discovery.

Design Principles:
1. Discovery Range Preserved: Minimum MC >= $8,000, no fixed upper ceiling.
2. Safety Non-Negotiable: Hard filters only for contract risk, liquidity starvation,
   extreme impact/slippage, severe wash/cabal manipulation, or toxic venues.
3. Soft Feature Valuation: Converts non-safety pruners into graduated score penalties.
4. Three Complementary Admission Lanes:
   - Lane A (HIGH_CONVICTION): Mature, multi-axis confirmed setups (Confluence >= 3-4, Score >= 65).
   - Lane B (EMERGING_BREAKOUT): Nascent setups where acceleration signals agree (Confluence >= 2, Score >= 58).
   - Lane C (EXTREME_TAIL): Rare, explosive setups with extreme momentum & buyer velocity (Score >= 65).
5. Dynamic Opportunity Ranking & Slot Competition:
   - Rank score = Primary Score * max(EV, 0.5) * (1 + Confluence * 0.05).
   - Slot-based competition (MAX_ACTIVE_POSITIONS + OPPORTUNITY_QUEUE).
   - Material displacement threshold prevents wasteful trade churn.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import math
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

from src.research.selector_v2_high_conviction import (
    FeatureExtractorV2,
    HighConvictionFeatureBundle,
    ConfluenceEngine,
    ExpectedValueEngine,
    ConfluenceResult,
)


class SelectionLaneV22(str, Enum):
    HIGH_CONVICTION = "HIGH_CONVICTION"
    EMERGING_BREAKOUT = "EMERGING_BREAKOUT"
    EXTREME_TAIL = "EXTREME_TAIL"
    REJECT = "REJECT"


@dataclass
class CandidateEvaluationV22:
    token_address: str
    symbol: str
    lane: SelectionLaneV22
    is_eligible: bool
    opportunity_rank: float
    primary_score: float
    core_score: float
    emerging_score: float
    tail_score: float
    confluence_count: int
    confirmed_axes: List[str]
    ev: float
    soft_penalties: float
    rejection_reasons: List[str]
    features: Dict[str, Any]


class HardSafetyGateV22:
    """
    Enforces strict, non-negotiable safety conditions only.
    Non-safety conditions must NOT trigger hard rejection here.
    """
    MIN_MARKET_CAP: float = 8000.0
    MIN_LIQUIDITY_USD: float = 2000.0
    MAX_PRICE_IMPACT_PCT: float = 5.0
    MAX_SLIPPAGE_PCT: float = 5.0
    MAX_WASH_RISK: float = 0.50
    MAX_CABAL_RISK: float = 0.60
    RESTRICTED_VENUES: Tuple[str, ...] = ("pons-v2", "raydium-cp")

    @classmethod
    def evaluate(cls, token: Dict[str, Any], fb: HighConvictionFeatureBundle) -> Tuple[bool, List[str]]:
        rejections: List[str] = []
        mc = float(token.get("entry_market_cap_usd") or token.get("market_cap_usd") or 0.0)
        liq = float(token.get("entry_liquidity_usd") or token.get("liquidity_usd") or 0.0)

        # 1. Hard Discovery Floor (Enforced: MC >= $8,000, no fixed upper ceiling)
        if mc < cls.MIN_MARKET_CAP:
            rejections.append(f"MC_BELOW_DISCOVERY_FLOOR (${mc:,.0f} < ${cls.MIN_MARKET_CAP:,.0f})")

        # 2. Execution Viability
        if liq < cls.MIN_LIQUIDITY_USD:
            rejections.append(f"INADEQUATE_LIQUIDITY (${liq:,.0f} < ${cls.MIN_LIQUIDITY_USD:,.0f})")

        if fb.price_impact > cls.MAX_PRICE_IMPACT_PCT:
            rejections.append(f"EXTREME_PRICE_IMPACT ({fb.price_impact:.1f}% > {cls.MAX_PRICE_IMPACT_PCT}%)")

        if fb.estimated_slippage > cls.MAX_SLIPPAGE_PCT:
            rejections.append(f"EXTREME_SLIPPAGE ({fb.estimated_slippage:.1f}% > {cls.MAX_SLIPPAGE_PCT}%)")

        # 3. Severe Wash / Circular Activity
        if fb.wash_risk >= cls.MAX_WASH_RISK:
            rejections.append(f"SEVERE_WASH_MANIPULATION ({fb.wash_risk:.2f} >= {cls.MAX_WASH_RISK})")

        if fb.cabal_risk >= cls.MAX_CABAL_RISK:
            rejections.append(f"EXTREME_CABAL_CONCENTRATION ({fb.cabal_risk:.2f} >= {cls.MAX_CABAL_RISK})")

        # 4. Restricted Venues
        venue = str(token.get("venue") or "").lower()
        for rv in cls.RESTRICTED_VENUES:
            if rv in venue:
                rejections.append(f"RESTRICTED_VENUE_{venue.upper()}")
                break

        return (len(rejections) == 0, rejections)


class FalsePositivePenaltyEngineV22:
    """
    Converts historical false-positive patterns from hard rejections to proportional score penalties.
    This prevents anomalous winners exhibiting nascent properties from being discarded.
    """
    PENALTY_WEIGHTS = {
        "FP_HIGH_P3M_LOW_BREADTH": 10.0,
        "FP_WASH_PUMP_LOW_INDEPENDENCE": 15.0,
        "FP_HIGH_MOMENTUM_THIN_LIQUIDITY": 10.0,
        "FP_SMART_MONEY_CABAL_COLLUSION": 10.0,
        "FP_DISTRIBUTION_BID_EXHAUSTION": 10.0,
    }

    @classmethod
    def evaluate(cls, token: Dict[str, Any], fb: HighConvictionFeatureBundle) -> Tuple[float, List[str]]:
        penalty = 0.0
        applied_flags: List[str] = []
        buyers = int(token.get("unique_buyers") or 0)
        vol_mc = fb.vol_to_liq_ratio
        txns = int(token.get("txns_5m_buys") or 0) + int(token.get("txns_5m_sells") or 0)

        # 1. High P3M + Low Breadth
        if fb.p3m >= 0.14 and 0 < buyers <= 20:
            penalty += cls.PENALTY_WEIGHTS["FP_HIGH_P3M_LOW_BREADTH"]
            applied_flags.append("FP_HIGH_P3M_LOW_BREADTH")

        # 2. Wash Pump + Low Trader Independence
        if vol_mc >= 4.0 and (fb.cabal_risk > 0.40 or fb.wash_risk > 0.30):
            penalty += cls.PENALTY_WEIGHTS["FP_WASH_PUMP_LOW_INDEPENDENCE"]
            applied_flags.append("FP_WASH_PUMP_LOW_INDEPENDENCE")

        # 3. Thin Liquidity Spike
        if fb.price_velocity >= 50.0 and fb.liquidity_usd < 8000.0:
            penalty += cls.PENALTY_WEIGHTS["FP_HIGH_MOMENTUM_THIN_LIQUIDITY"]
            applied_flags.append("FP_HIGH_MOMENTUM_THIN_LIQUIDITY")

        # 4. Smart Money Collusion
        if fb.validated_wallet_count >= 1 and fb.cabal_risk > 0.45:
            penalty += cls.PENALTY_WEIGHTS["FP_SMART_MONEY_CABAL_COLLUSION"]
            applied_flags.append("FP_SMART_MONEY_CABAL_COLLUSION")

        # 5. Bid Exhaustion
        if txns >= 80 and fb.two_sided_vol_ratio < 0.45 and fb.mc_velocity <= 0.0:
            penalty += cls.PENALTY_WEIGHTS["FP_DISTRIBUTION_BID_EXHAUSTION"]
            applied_flags.append("FP_DISTRIBUTION_BID_EXHAUSTION")

        return (penalty, applied_flags)


class ThreeLaneSelectorV22:
    """
    Unified Three-Lane Setup Quality & Opportunity Ranking Evaluator.
    """
    @classmethod
    def evaluate(
        cls,
        token: Dict[str, Any],
        min_core_score: float = 65.0,
        min_core_confluence: int = 3,
        min_emerging_score: float = 58.0,
        min_tail_score: float = 65.0,
        min_ev: float = 1.5,
    ) -> CandidateEvaluationV22:
        addr = str(token.get("token_address") or "UNK")
        sym = str(token.get("symbol") or "UNK")

        # Extract normalized 8 feature groups
        fb = FeatureExtractorV2.extract(token)

        # 1. Non-negotiable Hard Safety Gate
        is_safe, hard_rejections = HardSafetyGateV22.evaluate(token, fb)
        if not is_safe:
            return CandidateEvaluationV22(
                token_address=addr,
                symbol=sym,
                lane=SelectionLaneV22.REJECT,
                is_eligible=False,
                opportunity_rank=0.0,
                primary_score=0.0,
                core_score=0.0,
                emerging_score=0.0,
                tail_score=0.0,
                confluence_count=0,
                confirmed_axes=[],
                ev=0.0,
                soft_penalties=0.0,
                rejection_reasons=hard_rejections,
                features={},
            )

        # 2. Confluence Evaluation
        cr = ConfluenceEngine.evaluate(fb, min_count=2)

        # 3. Soft False-Positive Penalties
        soft_penalty, applied_flags = FalsePositivePenaltyEngineV22.evaluate(token, fb)

        # 4. Lane A: Core Setup Quality Score
        score_conf = cr.confluence_score * 0.35
        score_prob = min(100.0, (fb.p3m / 0.16) * 100.0) * fb.probability_stability * 0.25
        score_part = (
            min(100.0, fb.two_sided_vol_ratio * 100.0) * 0.5
            + min(100.0, fb.unique_buyers_to_tx_ratio * 100.0) * 0.5
        ) * 0.20
        score_sm = (fb.wallet_skill * 100.0 if fb.smart_money_consensus == 1 else 60.0) * 0.10
        score_exec = min(100.0, fb.execution_confidence * 100.0) * 0.10
        raw_core = score_conf + score_prob + score_part + score_sm + score_exec
        net_core = max(0.0, raw_core - soft_penalty)

        # 5. Lane B: Emerging Breakout Score
        # Acceleration agreement check
        accel_factors = [
            fb.price_acceleration >= 0.0 or fb.price_velocity >= 2.0,
            fb.volume_acceleration >= 0.0 or fb.volume_velocity >= 1.5,
            fb.buyer_growth >= 2.0,
            fb.trader_growth >= 2.0,
            fb.p3m_acceleration >= 0.0 or fb.p3m_velocity >= 0.0,
            fb.mc_velocity >= 0.0,
        ]
        accel_agreement_count = sum(accel_factors)
        accel_ratio = accel_agreement_count / 6.0

        emerging_raw = (
            accel_ratio * 100.0 * 0.40
            + min(100.0, fb.unique_buyers_to_tx_ratio * 100.0) * 0.30
            + min(100.0, (fb.liquidity_usd / 15000.0) * 100.0) * 0.20
            + min(100.0, (fb.p3m / 0.15) * 100.0) * 0.10
        )
        net_emerging = max(0.0, emerging_raw - (soft_penalty * 0.5))

        # 6. Lane C: Extreme Tail Score
        mom_speed = min(1.0, fb.price_velocity / 50.0)
        vol_acc = min(1.0, max(0.0, fb.volume_velocity / 3.0))
        mom_factor = (mom_speed * 0.5 + vol_acc * 0.5) * 50.0

        buyers = int(token.get("unique_buyers") or 0)
        buyer_rate = min(1.0, buyers / 30.0)
        organic_ratio = fb.unique_buyers_to_tx_ratio
        buyer_factor = (buyer_rate * 0.5 + organic_ratio * 0.5) * 50.0

        raw_tail = mom_factor + buyer_factor
        net_tail = max(0.0, raw_tail - (soft_penalty * 0.5))

        # 7. Expected Value Calculation
        ev = ExpectedValueEngine.calculate_expected_value(
            p3m=fb.p3m,
            setup_score=max(net_core, net_emerging),
            slippage_pct=fb.estimated_slippage,
            price_impact_pct=fb.price_impact,
            regime=fb.regime,
        )

        # 8. Lane Qualification
        lane_a_eligible = (
            cr.confluence_count >= min_core_confluence
            and net_core >= min_core_score
            and ev >= min_ev
        )

        lane_b_eligible = (
            accel_agreement_count >= 4
            and cr.confluence_count >= 2
            and net_emerging >= min_emerging_score
            and ev >= 1.0
            and fb.liquidity_usd >= 4000.0
        )

        lane_c_eligible = (
            net_tail >= min_tail_score
            and (fb.price_velocity >= 20.0 or fb.volume_velocity >= 2.5)
            and buyers >= 15
            and fb.curve_progress >= 0.15
            and ev >= 1.5
        )

        # 9. Lane Priority & Assignment
        rejection_reasons: List[str] = []
        assigned_lane = SelectionLaneV22.REJECT
        is_eligible = False

        if lane_c_eligible and net_tail >= max(net_core, net_emerging):
            assigned_lane = SelectionLaneV22.EXTREME_TAIL
            is_eligible = True
        elif lane_a_eligible and net_core >= net_emerging:
            assigned_lane = SelectionLaneV22.HIGH_CONVICTION
            is_eligible = True
        elif lane_b_eligible:
            assigned_lane = SelectionLaneV22.EMERGING_BREAKOUT
            is_eligible = True
        elif lane_a_eligible:
            assigned_lane = SelectionLaneV22.HIGH_CONVICTION
            is_eligible = True
        elif lane_c_eligible:
            assigned_lane = SelectionLaneV22.EXTREME_TAIL
            is_eligible = True
        else:
            if cr.confluence_count < min_core_confluence and not lane_b_eligible and not lane_c_eligible:
                rejection_reasons.append(f"INSUFFICIENT_CONFLUENCE ({cr.confluence_count} < {min_core_confluence})")
            if net_core < min_core_score and not lane_b_eligible and not lane_c_eligible:
                rejection_reasons.append(f"CORE_SCORE_BELOW_{int(min_core_score)} ({net_core:.1f})")
            if ev < min_ev:
                rejection_reasons.append(f"EV_BELOW_THRESHOLD ({ev:+.1f}% < {min_ev:+.1f}%)")

        primary_score = max(net_core, net_emerging, net_tail)
        # Unified Opportunity Ranking Score incorporates EV and structural confluence multiplier
        opportunity_rank = round(primary_score * max(ev, 0.5) * (1.0 + cr.confluence_count * 0.05), 2)

        return CandidateEvaluationV22(
            token_address=addr,
            symbol=sym,
            lane=assigned_lane,
            is_eligible=is_eligible,
            opportunity_rank=opportunity_rank,
            primary_score=round(primary_score, 1),
            core_score=round(net_core, 1),
            emerging_score=round(net_emerging, 1),
            tail_score=round(net_tail, 1),
            confluence_count=cr.confluence_count,
            confirmed_axes=cr.confirmed_axes,
            ev=round(ev, 2),
            soft_penalties=round(soft_penalty, 1),
            rejection_reasons=rejection_reasons,
            features={
                "price_velocity": fb.price_velocity,
                "price_acceleration": fb.price_acceleration,
                "volume_velocity": fb.volume_velocity,
                "volume_acceleration": fb.volume_acceleration,
                "buyer_growth": fb.buyer_growth,
                "trader_growth": fb.trader_growth,
                "liquidity_usd": fb.liquidity_usd,
                "curve_progress": fb.curve_progress,
                "p3m": fb.p3m,
                "soft_flags": applied_flags,
            },
        )


class OpportunityQueueEngineV22:
    """
    Manages slot-based opportunity competition.
    Replaces fixed hourly caps with dynamic position capacity and material displacement.
    """
    def __init__(self, max_active_positions: int = 8, min_displacement_delta: float = 15.0):
        self.max_active_positions = max_active_positions
        self.min_displacement_delta = min_displacement_delta
        self.active_slots: Dict[str, Dict[str, Any]] = {} # token_address -> slot dict

    def can_admit(
        self,
        token_address: str,
        rank_score: float,
        now_iso: str,
        open_positions: Dict[str, Any],
    ) -> Tuple[bool, str, Optional[str]]:
        """
        Determines whether a new eligible candidate can enter a position slot.
        Returns: (can_admit, reason, displaced_token_address)
        """
        # Synchronize active slots with live open positions
        self.active_slots = {
            a: slot for a, slot in self.active_slots.items() if a in open_positions
        }

        # Guard: Token already has an active position
        if token_address in open_positions or token_address in self.active_slots:
            return (False, "ALREADY_ACTIVE_POSITION", None)

        # Case 1: Open slot available
        if len(self.active_slots) < self.max_active_positions:
            return (True, f"AVAILABLE_SLOT ({len(self.active_slots)}/{self.max_active_positions})", None)

        # Case 2: Full capacity -> Evaluate competitive displacement
        # Positions are protected during their initial 15-minute grace period to prevent immediate churning
        try:
            now_dt = datetime.fromisoformat(now_iso.replace("Z", "+00:00"))
        except Exception:
            now_dt = datetime.now(timezone.utc)

        displaceable_candidates = []
        for a, slot in self.active_slots.items():
            adm_str = slot.get("admitted_time")
            hold_m = 999.0
            if adm_str:
                try:
                    adm_dt = datetime.fromisoformat(adm_str.replace("Z", "+00:00"))
                    hold_m = max(0.0, (now_dt - adm_dt).total_seconds() / 60.0)
                except Exception:
                    hold_m = 999.0

            if hold_m >= 15.0:  # 15-minute minimum hold protection
                displaceable_candidates.append((a, slot))

        if not displaceable_candidates:
            return (
                False,
                f"SLOTS_FULL_ALL_POSITIONS_IN_GRACE_PERIOD ({len(self.active_slots)}/{self.max_active_positions})",
                None,
            )

        weakest_addr, weakest_slot = min(displaceable_candidates, key=lambda x: x[1]["rank_score"])

        # Displacement requires material rank superiority to justify transaction friction
        if rank_score >= weakest_slot["rank_score"] + self.min_displacement_delta:
            return (
                True,
                f"MATERIAL_DISPLACEMENT (+{rank_score - weakest_slot['rank_score']:.1f} pts > {self.min_displacement_delta:.1f})",
                weakest_addr,
            )

        return (
            False,
            f"SLOTS_FULL_DISPLACEMENT_INSUFFICIENT (New {rank_score:.1f} vs Weakest {weakest_slot['rank_score']:.1f} + {self.min_displacement_delta:.1f})",
            None,
        )

    def mark_admitted(self, token_address: str, rank_score: float, now_iso: str, displaced_addr: Optional[str] = None) -> None:
        if displaced_addr and displaced_addr in self.active_slots:
            del self.active_slots[displaced_addr]
        self.active_slots[token_address] = {
            "rank_score": rank_score,
            "admitted_time": now_iso,
        }
