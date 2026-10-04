"""
RESEARCH-ONLY Challenger: SELECTOR_v2.1 — LOW-FREQUENCY / HIGH-P&L RECOVERY
=============================================================================

Architectural Objectives:
1. Increase executable P&L and expectancy while retaining LOW-FREQUENCY trading.
2. Preserve challenger improvements in win rate, Precision@10, Precision@25, and profit factor.
3. Soften rigid confluence and EV gating via ranking and score penalties rather than hard deletion.
4. Introduce a dedicated TAIL OPPORTUNITY LANE for rare explosive momentum/curve breakouts.
5. Deploy Scarcity-Aware Opportunity Displacement ("Capital is Scarce, Opportunities Compete").
6. Provide comprehensive ablation suites: confluence, EV, false-positive pruners, selection density,
   regimes, outlier robustness, and chronological walk-forward validation (Train 60%, Val 20%, Locked Test 20%).
"""

from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import logging
import math
import sqlite3
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np

from src.research.selector_v2_high_conviction import (
    FeatureExtractorV2,
    HighConvictionFeatureBundle,
    TokenSetupStateMachine,
    TokenSetupState,
    WalkForwardValidator,
    ConfluenceEngine,
    ExpectedValueEngine,
)

logger = logging.getLogger(__name__)


# ==============================================================================
# 1. HARD SAFETY & EXECUTION GATES
# ==============================================================================

@dataclass
class HardSafetyCheckResult:
    passes_hard_safety: bool
    rejection_reasons: List[str]


class HardSafetyGate:
    """
    Enforces non-negotiable safety and execution boundaries.
    Only genuinely fatal failure modes trigger hard rejection.
    Non-safety features contribute to ranking and scoring instead.
    """
    MIN_DISCOVERY_MC = 8000.0  # Flexible upper bound, hard $8K floor
    MIN_LIQUIDITY_USD = 1000.0
    MAX_RUG_RISK = 0.50
    MAX_MANIPULATION_RISK = 0.75
    MAX_CABAL_RISK = 0.80
    MAX_SLIPPAGE_PCT = 15.0
    MAX_PRICE_IMPACT_PCT = 15.0

    @classmethod
    def evaluate(cls, token: Dict[str, Any], fb: HighConvictionFeatureBundle) -> HardSafetyCheckResult:
        rejections: List[str] = []
        mc = float(token.get("entry_market_cap_usd") or token.get("market_cap_usd") or 0.0)

        # 1. Discovery Hard Gate
        if mc < cls.MIN_DISCOVERY_MC:
            rejections.append(f"MC_BELOW_DISCOVERY_FLOOR (${mc:,.0f} < ${cls.MIN_DISCOVERY_MC:,.0f})")

        # 2. Extreme Liquidity Deprivation
        if fb.liquidity_usd < cls.MIN_LIQUIDITY_USD:
            rejections.append(f"INADEQUATE_LIQUIDITY (${fb.liquidity_usd:,.0f} < ${cls.MIN_LIQUIDITY_USD:,.0f})")

        # 3. Severe Rug / Fraud Risk
        p_rug = float(token.get("p_rug") or 0.0)
        if p_rug >= cls.MAX_RUG_RISK:
            rejections.append(f"FATAL_RUG_RISK ({p_rug:.2f} >= {cls.MAX_RUG_RISK})")

        # 4. Severe Wash Trading / Circular Collusion
        if fb.wash_risk >= cls.MAX_MANIPULATION_RISK:
            rejections.append(f"SEVERE_WASH_MANIPULATION ({fb.wash_risk:.2f} >= {cls.MAX_MANIPULATION_RISK})")

        if fb.cabal_risk >= cls.MAX_CABAL_RISK:
            rejections.append(f"EXTREME_CABAL_CONCENTRATION ({fb.cabal_risk:.2f} >= {cls.MAX_CABAL_RISK})")

        # 5. Impossible Execution
        if fb.estimated_slippage > cls.MAX_SLIPPAGE_PCT:
            rejections.append(f"EXTREME_SLIPPAGE ({fb.estimated_slippage:.1f}% > {cls.MAX_SLIPPAGE_PCT}%)")

        if fb.price_impact > cls.MAX_PRICE_IMPACT_PCT:
            rejections.append(f"EXTREME_PRICE_IMPACT ({fb.price_impact:.1f}% > {cls.MAX_PRICE_IMPACT_PCT}%)")

        # 6. Restricted/Broken Venues
        venue = str(token.get("venue", "")).lower()
        if "raydium-cp" in venue:
            rejections.append(f"RESTRICTED_VENUE_{venue.upper()}")

        return HardSafetyCheckResult(
            passes_hard_safety=(len(rejections) == 0),
            rejection_reasons=rejections,
        )


# ==============================================================================
# 2. FALSE-POSITIVE PRUNER WITH PENALTY MODE
# ==============================================================================

class FalsePositiveMode(str, Enum):
    ALL_HARD = "ALL_HARD"          # v2.0 baseline: any trigger causes absolute rejection
    PENALTIES_ONLY = "PENALTIES"   # v2.1 innovation: triggers apply score deductions
    REMOVE_PRUNER_1 = "NO_P1"      # Ablation: Remove High P3M + Low Breadth
    REMOVE_PRUNER_2 = "NO_P2"      # Ablation: Remove Wash Pump
    REMOVE_PRUNER_3 = "NO_P3"      # Ablation: Remove Thin Spike
    REMOVE_PRUNER_4 = "NO_P4"      # Ablation: Remove Cabal Collusion
    REMOVE_PRUNER_5 = "NO_P5"      # Ablation: Remove Bid Exhaustion


@dataclass
class FalsePositiveEvaluation:
    triggered_filters: List[str]
    score_penalty: float
    is_hard_rejected: bool
    details: Dict[str, bool]


class PenalizedFalsePositiveEngine:
    """
    Evaluates historical false-positive patterns.
    In v2.1, instead of deleting profitable outliers that exhibit early-stage characteristics,
    pruners apply proportional score penalties, allowing exceptional setups to overcome them.
    """
    PENALTY_WEIGHTS = {
        "FP_HIGH_P3M_LOW_BREADTH": 10.0,
        "FP_WASH_PUMP_LOW_INDEPENDENCE": 15.0,
        "FP_HIGH_MOMENTUM_THIN_LIQUIDITY": 10.0,
        "FP_SMART_MONEY_CABAL_COLLUSION": 10.0,
        "FP_DISTRIBUTION_BID_EXHAUSTION": 10.0,
    }

    @classmethod
    def evaluate(
        cls,
        fb: HighConvictionFeatureBundle,
        token: Dict[str, Any],
        mode: FalsePositiveMode = FalsePositiveMode.PENALTIES_ONLY,
    ) -> FalsePositiveEvaluation:
        triggers: List[str] = []
        details: Dict[str, bool] = {}
        buyers = int(token.get("unique_buyers") or 0)
        vol_mc = fb.vol_to_liq_ratio

        # 1. High P3M + Low Breadth
        p1 = (fb.p3m >= 0.14 and 0 < buyers <= 20)
        details["FP_HIGH_P3M_LOW_BREADTH"] = p1
        if p1 and mode != FalsePositiveMode.REMOVE_PRUNER_1:
            triggers.append("FP_HIGH_P3M_LOW_BREADTH")

        # 2. High Volume + Low Trader Independence (Wash pump)
        p2 = (vol_mc >= 4.0 and (fb.cabal_risk > 0.40 or fb.wash_risk > 0.30))
        details["FP_WASH_PUMP_LOW_INDEPENDENCE"] = p2
        if p2 and mode != FalsePositiveMode.REMOVE_PRUNER_2:
            triggers.append("FP_WASH_PUMP_LOW_INDEPENDENCE")

        # 3. High Momentum + Thin Liquidity
        p3 = (fb.price_velocity >= 50.0 and fb.liquidity_usd < 8000.0)
        details["FP_HIGH_MOMENTUM_THIN_LIQUIDITY"] = p3
        if p3 and mode != FalsePositiveMode.REMOVE_PRUNER_3:
            triggers.append("FP_HIGH_MOMENTUM_THIN_LIQUIDITY")

        # 4. Smart Money + Cabal Collusion
        p4 = (fb.validated_wallet_count >= 1 and fb.cabal_risk > 0.45)
        details["FP_SMART_MONEY_CABAL_COLLUSION"] = p4
        if p4 and mode != FalsePositiveMode.REMOVE_PRUNER_4:
            triggers.append("FP_SMART_MONEY_CABAL_COLLUSION")

        # 5. Distribution / Bid Exhaustion
        txns = int(token.get("txns_5m_buys", 0)) + int(token.get("txns_5m_sells", 0))
        p5 = (txns >= 80 and fb.two_sided_vol_ratio < 0.45 and fb.mc_velocity <= 0.0)
        details["FP_DISTRIBUTION_BID_EXHAUSTION"] = p5
        if p5 and mode != FalsePositiveMode.REMOVE_PRUNER_5:
            triggers.append("FP_DISTRIBUTION_BID_EXHAUSTION")

        total_penalty = sum(cls.PENALTY_WEIGHTS.get(t, 10.0) for t in triggers)
        is_hard_rejected = (len(triggers) > 0) if (mode == FalsePositiveMode.ALL_HARD) else False

        return FalsePositiveEvaluation(
            triggered_filters=triggers,
            score_penalty=total_penalty,
            is_hard_rejected=is_hard_rejected,
            details=details,
        )


# ==============================================================================
# 3. TAIL OPPORTUNITY LANE ENGINE
# ==============================================================================

@dataclass
class TailOpportunityEvaluation:
    tail_score: float
    is_tail_candidate: bool
    acceleration_factors: Dict[str, float]
    breakout_type: str


class TailOpportunityEngine:
    """
    Identifies rare, explosive setups that may lack 4+ simultaneous confirmation axes
    due to nascent structure, but display overwhelming momentum, buyer velocity, or curve traction.
    """
    @classmethod
    def evaluate(
        cls,
        fb: HighConvictionFeatureBundle,
        token: Dict[str, Any],
        threshold: float = 65.0,
    ) -> TailOpportunityEvaluation:
        factors: Dict[str, float] = {}

        # 1. Momentum & Volume Acceleration (0 - 50 pts)
        mom_speed = min(1.0, fb.price_velocity / 50.0)
        vol_acc = min(1.0, max(0.0, fb.volume_velocity / 3.0))
        mom_factor = (mom_speed * 0.5 + vol_acc * 0.5) * 50.0
        factors["MOMENTUM_ACCEL"] = round(mom_factor, 1)

        # 2. Buyer Expansion & Intensity (0 - 50 pts)
        buyers = int(token.get("unique_buyers") or 0)
        buyer_rate = min(1.0, buyers / 30.0)
        organic_ratio = fb.unique_buyers_to_tx_ratio
        buyer_factor = (buyer_rate * 0.5 + organic_ratio * 0.5) * 50.0
        factors["BUYER_EXPANSION"] = round(buyer_factor, 1)

        total_tail_score = round(mom_factor + buyer_factor, 1)

        # Determine breakout archetype
        if mom_factor >= 35.0 and buyer_factor >= 35.0:
            breakout_type = "VELOCITY_EXPLOSION"
        elif mom_factor >= 30.0:
            breakout_type = "MOMENTUM_BREAKOUT"
        elif buyer_factor >= 30.0:
            breakout_type = "BUYER_ACCUMULATION"
        else:
            breakout_type = "GENERAL_ACCELERATION"

        is_candidate = total_tail_score >= threshold

        return TailOpportunityEvaluation(
            tail_score=total_tail_score,
            is_tail_candidate=is_candidate,
            acceleration_factors=factors,
            breakout_type=breakout_type,
        )


# ==============================================================================
# 4. DUAL-LANE SETUP QUALITY & RANKING MODEL
# ==============================================================================

class AdmissionLane(str, Enum):
    CORE_HIGH_CONVICTION = "CORE"
    TAIL_OPPORTUNITY = "TAIL"
    REJECT = "REJECT"


@dataclass
class SelectorV21CandidateEvaluation:
    token_address: str
    symbol: str
    admission_lane: AdmissionLane
    is_eligible: bool
    opportunity_rank_score: float
    core_setup_score: float
    tail_score: float
    expected_value: float
    confluence_count: int
    confluence_score: float
    confirmed_axes: List[str]
    false_positive_penalty: float
    rejection_reasons: List[str]
    feature_bundle: HighConvictionFeatureBundle


class DualLaneSetupQualityModel:
    """
    Evaluates tokens across both the CORE high-conviction lane and the TAIL opportunity lane.
    Calculates unified OPPORTUNITY_RANK_SCORE for competitive trade displacement.
    """
    @classmethod
    def evaluate(
        cls,
        token: Dict[str, Any],
        min_confluence: int = 3,
        min_score: float = 70.0,
        min_ev: float = 1.5,
        tail_threshold: float = 65.0,
        fp_mode: FalsePositiveMode = FalsePositiveMode.PENALTIES_ONLY,
    ) -> SelectorV21CandidateEvaluation:
        addr = str(token.get("token_address", "UNK"))
        sym = str(token.get("symbol", "UNK"))
        rejections: List[str] = []

        # 1. Feature Extraction
        fb = FeatureExtractorV2.extract(token)

        # 2. Hard Safety Gate
        safety = HardSafetyGate.evaluate(token, fb)
        if not safety.passes_hard_safety:
            rejections.extend(safety.rejection_reasons)
            return SelectorV21CandidateEvaluation(
                token_address=addr,
                symbol=sym,
                admission_lane=AdmissionLane.REJECT,
                is_eligible=False,
                opportunity_rank_score=0.0,
                core_setup_score=0.0,
                tail_score=0.0,
                expected_value=0.0,
                confluence_count=0,
                confluence_score=0.0,
                confirmed_axes=[],
                false_positive_penalty=0.0,
                rejection_reasons=rejections,
                feature_bundle=fb,
            )

        # 3. Confluence Evaluation
        cr = ConfluenceEngine.evaluate(fb, min_count=min_confluence)

        # 4. False-Positive Evaluation (Hard or Penalty mode)
        fp_eval = PenalizedFalsePositiveEngine.evaluate(fb, token, mode=fp_mode)
        if fp_eval.is_hard_rejected:
            rejections.append(f"FALSE_POSITIVE_HARD_REJECT ({'; '.join(fp_eval.triggered_filters)})")

        # 5. Core Setup Score Calculation
        score_confluence = cr.confluence_score * 0.35
        score_prob = min(100.0, (fb.p3m / 0.16) * 100.0) * fb.probability_stability * 0.25
        score_part = (
            min(100.0, fb.two_sided_vol_ratio * 100.0) * 0.5
            + min(100.0, fb.unique_buyers_to_tx_ratio * 100.0) * 0.5
        ) * 0.20
        score_sm = (fb.wallet_skill * 100.0 if fb.smart_money_consensus == 1 else 60.0) * 0.10
        score_exec = min(100.0, fb.execution_confidence * 100.0) * 0.10

        raw_core_score = score_confluence + score_prob + score_part + score_sm + score_exec
        # Deduct False-Positive penalty
        net_core_score = max(0.0, raw_core_score - fp_eval.score_penalty)

        # 6. Expected Value Calculation
        ev = ExpectedValueEngine.calculate_expected_value(
            p3m=fb.p3m,
            setup_score=net_core_score,
            slippage_pct=fb.estimated_slippage,
            price_impact_pct=fb.price_impact,
            regime=fb.regime,
        )

        # 7. Tail Opportunity Evaluation
        tail_eval = TailOpportunityEngine.evaluate(fb, token, threshold=tail_threshold)
        net_tail_score = max(0.0, tail_eval.tail_score - (fp_eval.score_penalty * 0.5))

        # 8. Dual-Lane Admission Logic
        # Lane A: CORE High-Conviction (Confluence >= min_confluence, EV >= min_ev, Core Score >= min_score)
        core_eligible = (
            (not fp_eval.is_hard_rejected)
            and (cr.confluence_count >= min_confluence)
            and (ev >= min_ev)
            and (net_core_score >= min_score)
        )

        # Lane B: TAIL Opportunity Lane (Tail Score >= threshold, Confluence >= 2, EV >= 1.0, Curve >= 0.15)
        # Prevents explosive 100x tail winners from being blocked solely by high confluence threshold
        tail_eligible = (
            (not fp_eval.is_hard_rejected)
            and tail_eval.is_tail_candidate
            and (cr.confluence_count >= 2)
            and (ev >= 1.0)
            and (fb.curve_progress >= 0.15)
            and (net_tail_score >= tail_threshold)
        )

        if core_eligible and (net_core_score >= net_tail_score):
            admission_lane = AdmissionLane.CORE_HIGH_CONVICTION
            is_eligible = True
        elif tail_eligible:
            admission_lane = AdmissionLane.TAIL_OPPORTUNITY
            is_eligible = True
        elif core_eligible:
            admission_lane = AdmissionLane.CORE_HIGH_CONVICTION
            is_eligible = True
        else:
            admission_lane = AdmissionLane.REJECT
            is_eligible = False
            if cr.confluence_count < min_confluence:
                rejections.append(f"INSUFFICIENT_CONFLUENCE ({cr.confluence_count} < {min_confluence})")
            if ev < min_ev:
                rejections.append(f"EV_BELOW_THRESHOLD ({ev:+.1f}% < {min_ev:+.1f}%)")
            if net_core_score < min_score:
                rejections.append(f"CORE_SCORE_BELOW_{int(min_score)} ({net_core_score:.1f})")

        # Unified Opportunity Ranking Score
        primary_score = max(net_core_score, net_tail_score)
        opportunity_rank_score = round(primary_score * max(ev, 0.5), 2)

        return SelectorV21CandidateEvaluation(
            token_address=addr,
            symbol=sym,
            admission_lane=admission_lane,
            is_eligible=is_eligible,
            opportunity_rank_score=opportunity_rank_score,
            core_setup_score=round(net_core_score, 1),
            tail_score=round(net_tail_score, 1),
            expected_value=ev,
            confluence_count=cr.confluence_count,
            confluence_score=cr.confluence_score,
            confirmed_axes=cr.confirmed_axes,
            false_positive_penalty=fp_eval.score_penalty,
            rejection_reasons=rejections,
            feature_bundle=fb,
        )


# ==============================================================================
# 5. SCARCITY-AWARE OPPORTUNITY DISPLACEMENT & BUDGET ENGINE
# ==============================================================================

@dataclass
class SelectorV21BudgetConfig:
    max_new_trades_per_hour: int = 4
    max_simultaneous_positions: int = 8
    max_trades_per_token: int = 1
    cooldown_minutes: float = 90.0
    re_entry_consolidation_pct: float = 15.0
    regime_hourly_caps: Dict[str, int] = field(
        default_factory=lambda: {
            "HOT": 4,
            "NORMAL": 4,
            "COLD": 1,
            "PANIC": 0,
        }
    )


class ScarcityDisplacementEngine:
    """
    Operates under the quantitative principle: 'Capital is Scarce, Opportunities Compete.'
    When multiple eligible setups appear in a decision interval:
    1. Ranks them by unified OPPORTUNITY_RANK_SCORE.
    2. Allows superior setups to displace weaker setups within budget caps.
    3. Guarantees token first-alert primacy via state machine.
    """
    def __init__(self, budget_config: Optional[SelectorV21BudgetConfig] = None):
        self.config = budget_config or SelectorV21BudgetConfig()
        self.state_machine = TokenSetupStateMachine(
            cooldown_minutes=self.config.cooldown_minutes,
            re_entry_consolidation_pct=self.config.re_entry_consolidation_pct,
        )
        self.active_positions: Dict[str, str] = {}
        self.hourly_trades: Dict[str, int] = defaultdict(int)

    def process_window(
        self,
        candidates: List[Dict[str, Any]],
        window_hour_key: str,
        top_k_pct: float = 10.0,
        min_confluence: int = 3,
        min_score: float = 70.0,
        min_ev: float = 1.5,
        tail_threshold: float = 65.0,
        fp_mode: FalsePositiveMode = FalsePositiveMode.PENALTIES_ONLY,
    ) -> List[Dict[str, Any]]:
        evaluated: List[Tuple[Dict[str, Any], SelectorV21CandidateEvaluation]] = []

        for cand in candidates:
            res = DualLaneSetupQualityModel.evaluate(
                token=cand,
                min_confluence=min_confluence,
                min_score=min_score,
                min_ev=min_ev,
                tail_threshold=tail_threshold,
                fp_mode=fp_mode,
            )
            if res.is_eligible:
                evaluated.append((cand, res))

        if not evaluated:
            return []

        # Rank candidates by Unified Opportunity Score
        evaluated.sort(key=lambda x: x[1].opportunity_rank_score, reverse=True)

        selected_trades: List[Dict[str, Any]] = []

        for cand, res in evaluated:
            addr = res.token_address
            sym = res.symbol
            ts = cand.get("entry_signal_timestamp") or cand.get("timestamp") or ""
            mc = float(cand.get("entry_market_cap_usd") or cand.get("market_cap_usd") or 0.0)
            regime = res.feature_bundle.regime

            # Evict expired positions
            if ts:
                self.active_positions = {
                    a: ext for a, ext in self.active_positions.items()
                    if ext and ext > ts
                }

            # State Machine Check (First-Alert Primacy & Consolidation Check)
            state, can_trade, _ = self.state_machine.evaluate_transition(
                token_address=addr,
                symbol=sym,
                timestamp=ts,
                current_mc=mc,
                is_qualifying_setup=True,
                setup_score=res.opportunity_rank_score,
            )

            if not can_trade:
                continue

            # Hourly & Regime Budget Gate
            hourly_cap = self.config.regime_hourly_caps.get(regime, self.config.max_new_trades_per_hour)
            if self.hourly_trades[window_hour_key] >= hourly_cap:
                # Opportunity displaced by higher-ranking competitor
                continue

            # Simultaneous Active Positions Gate
            if len(self.active_positions) >= self.config.max_simultaneous_positions:
                continue

            # Trade Admitted!
            self.state_machine.mark_traded(addr, ts)
            self.hourly_trades[window_hour_key] += 1
            exit_ts = str(cand.get("exit_timestamp") or cand.get("exit_execution_timestamp") or "")
            self.active_positions[addr] = exit_ts

            rec = dict(cand)
            rec["challenger_version"] = "SELECTOR_v2.1"
            rec["admission_lane"] = res.admission_lane.value
            rec["opportunity_rank_score"] = res.opportunity_rank_score
            rec["core_setup_score"] = res.core_setup_score
            rec["tail_score"] = res.tail_score
            rec["challenger_ev"] = res.expected_value
            rec["confluence_count"] = res.confluence_count
            rec["confirmed_axes"] = res.confirmed_axes
            rec["false_positive_penalty"] = res.false_positive_penalty
            selected_trades.append(rec)

        return selected_trades


# ==============================================================================
# 6. WINNER CAPTURE & OUTLIER ROBUSTNESS EVALUATOR
# ==============================================================================

class WinnerCaptureEvaluator:
    """
    Computes comprehensive winner capture rates, tail percentiles, frequency metrics,
    and outlier sensitivity across any candidate selector's trades vs total universe.
    """
    @staticmethod
    def evaluate_capture_and_robustness(
        selected_trades: List[Dict[str, Any]],
        universe_trades: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        n_selected = len(selected_trades)
        n_universe = len(universe_trades)

        if n_universe == 0:
            return {}

        # 1. Total Universe Winners & Runners
        all_winners = [t for t in universe_trades if float(t.get("net_realized_return_pct") or 0.0) > 0]
        all_3m = [t for t in universe_trades if int(t.get("target_reached_3m") or 0) == 1]
        all_pnl = sum(float(t.get("net_realized_pnl_usd") or 0.0) for t in universe_trades)
        all_mfe = sum(float(t.get("mfe_ratio") or 1.0) for t in universe_trades)

        # 2. Selected Totals
        sel_winners = [t for t in selected_trades if float(t.get("net_realized_return_pct") or 0.0) > 0]
        sel_3m = [t for t in selected_trades if int(t.get("target_reached_3m") or 0) == 1]
        sel_pnl = sum(float(t.get("net_realized_pnl_usd") or 0.0) for t in selected_trades)
        sel_mfe = sum(float(t.get("mfe_ratio") or 1.0) for t in selected_trades)

        # Capture Rates
        winner_capture_rate = (len(sel_winners) / max(len(all_winners), 1)) * 100.0
        runners_3m_capture_rate = (len(sel_3m) / max(len(all_3m), 1)) * 100.0
        pnl_capture_rate = (sel_pnl / max(all_pnl, 1.0)) * 100.0
        mfe_capture_rate = (sel_mfe / max(all_mfe, 1.0)) * 100.0

        # 3. Tail Percentile Winner Capture (Top 0.5%, 1%, 2%, 5%, 10% of P&L)
        sorted_by_pnl = sorted(universe_trades, key=lambda x: float(x.get("net_realized_pnl_usd") or 0.0), reverse=True)
        top_pct_capture = {}
        for pct in [0.5, 1.0, 2.0, 5.0, 10.0]:
            k = max(1, int(n_universe * (pct / 100.0)))
            target_ids = {t["trade_id"] for t in sorted_by_pnl[:k]}
            captured_k = sum(1 for t in selected_trades if t["trade_id"] in target_ids)
            pct_captured = (captured_k / k) * 100.0
            top_pct_capture[f"top_{str(pct).replace('.', '_')}_pct"] = {
                "target_count": k,
                "captured_count": captured_k,
                "capture_rate_pct": round(pct_captured, 2),
            }

        # 4. Outlier Robustness Analysis
        sel_sorted_pnl = sorted(selected_trades, key=lambda x: float(x.get("net_realized_pnl_usd") or 0.0), reverse=True)
        pnl_excl_1 = sum(float(t.get("net_realized_pnl_usd") or 0.0) for t in sel_sorted_pnl[1:]) if len(sel_sorted_pnl) > 1 else 0.0
        pnl_excl_5 = sum(float(t.get("net_realized_pnl_usd") or 0.0) for t in sel_sorted_pnl[5:]) if len(sel_sorted_pnl) > 5 else 0.0
        pnl_excl_10 = sum(float(t.get("net_realized_pnl_usd") or 0.0) for t in sel_sorted_pnl[10:]) if len(sel_sorted_pnl) > 10 else 0.0
        pnl_excl_20 = sum(float(t.get("net_realized_pnl_usd") or 0.0) for t in sel_sorted_pnl[20:]) if len(sel_sorted_pnl) > 20 else 0.0

        is_broad_edge = (pnl_excl_10 > 0.0) and (len(sel_winners) >= 25)

        # 5. Low-Frequency Constraint Metrics
        trades_per_1000_opps = (n_selected / max(n_universe, 1)) * 1000.0
        
        timestamps = sorted([
            datetime.fromisoformat(str(t.get("entry_signal_timestamp") or t.get("timestamp") or "").replace("Z", "+00:00"))
            for t in selected_trades if (t.get("entry_signal_timestamp") or t.get("timestamp"))
        ])
        
        if len(timestamps) >= 2:
            time_span_days = max(1.0, (timestamps[-1] - timestamps[0]).total_seconds() / 86400.0)
            trades_per_day = n_selected / time_span_days
            trades_per_week = trades_per_day * 7.0
            diffs_hours = [(timestamps[i] - timestamps[i-1]).total_seconds() / 3600.0 for i in range(1, len(timestamps))]
            avg_spacing_hours = float(np.mean(diffs_hours))
        else:
            time_span_days = 1.0
            trades_per_day = float(n_selected)
            trades_per_week = trades_per_day * 7.0
            avg_spacing_hours = 0.0

        pnl_per_trade = sel_pnl / max(n_selected, 1)
        pnl_per_1000_opps = (sel_pnl / max(n_universe, 1)) * 1000.0

        core_trades = [t for t in selected_trades if t.get("admission_lane") == "CORE"]
        tail_trades = [t for t in selected_trades if t.get("admission_lane") == "TAIL"]
        core_pnl = sum(float(t.get("net_realized_pnl_usd") or 0.0) for t in core_trades)
        tail_pnl = sum(float(t.get("net_realized_pnl_usd") or 0.0) for t in tail_trades)

        return {
            "winner_capture_rate_pct": round(winner_capture_rate, 2),
            "runners_3m_capture_rate_pct": round(runners_3m_capture_rate, 2),
            "pnl_capture_rate_pct": round(pnl_capture_rate, 2),
            "mfe_capture_rate_pct": round(mfe_capture_rate, 2),
            "tail_percentile_capture": top_pct_capture,
            "outlier_robustness": {
                "total_executable_pnl": round(sel_pnl, 2),
                "pnl_excluding_top_1": round(pnl_excl_1, 2),
                "pnl_excluding_top_5": round(pnl_excl_5, 2),
                "pnl_excluding_top_10": round(pnl_excl_10, 2),
                "pnl_excluding_top_20": round(pnl_excl_20, 2),
                "is_broad_edge": is_broad_edge,
            },
            "frequency_metrics": {
                "trades_per_1000_opportunities": round(trades_per_1000_opps, 2),
                "trades_per_day": round(trades_per_day, 2),
                "trades_per_week": round(trades_per_week, 2),
                "average_spacing_hours": round(avg_spacing_hours, 2),
                "pnl_per_trade": round(pnl_per_trade, 2),
                "pnl_per_1000_opportunities": round(pnl_per_1000_opps, 2),
            },
            "lane_breakdown": {
                "core_trade_count": len(core_trades),
                "core_pnl": round(core_pnl, 2),
                "tail_trade_count": len(tail_trades),
                "tail_pnl": round(tail_pnl, 2),
            },
        }


# ==============================================================================
# 7. MAIN ENGINE: SELECTOR_v2_1_RECOVERY
# ==============================================================================

class SelectorV21RecoveryEngine:
    """
    Complete RESEARCH_ONLY Selector v2.1 Engine.
    Executes Low-Frequency / High-P&L Recovery opportunity selection.
    """
    VERSION = "SELECTOR_v2.1_RECOVERY"

    def __init__(self, budget_config: Optional[SelectorV21BudgetConfig] = None):
        self.budget_config = budget_config or SelectorV21BudgetConfig()

    def evaluate_dataset(
        self,
        trades: List[Dict[str, Any]],
        top_k_pct: float = 10.0,
        min_confluence: int = 3,
        min_score: float = 70.0,
        min_ev: float = 1.5,
        tail_threshold: float = 65.0,
        fp_mode: FalsePositiveMode = FalsePositiveMode.PENALTIES_ONLY,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any], Dict[str, Any]]:
        """
        Runs the full selector engine over trade candidates grouped by hourly windows.
        Returns: (selected_trades, performance_metrics, winner_capture_metrics)
        """
        hourly_buckets: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for t in trades:
            ts = str(t.get("entry_signal_timestamp") or t.get("timestamp") or "")
            hr_key = ts[:13] if len(ts) >= 13 else "unknown"
            hourly_buckets[hr_key].append(t)

        displacement_engine = ScarcityDisplacementEngine(self.budget_config)
        all_selected: List[Dict[str, Any]] = []

        for hr_key in sorted(hourly_buckets.keys()):
            batch = hourly_buckets[hr_key]
            selected = displacement_engine.process_window(
                candidates=batch,
                window_hour_key=hr_key,
                top_k_pct=top_k_pct,
                min_confluence=min_confluence,
                min_score=min_score,
                min_ev=min_ev,
                tail_threshold=tail_threshold,
                fp_mode=fp_mode,
            )
            all_selected.extend(selected)

        perf_metrics = WalkForwardValidator.compute_performance_metrics(
            all_selected,
            label=f"SELECTOR_v2.1 (C>={min_confluence}, Score>={min_score}, EV>={min_ev})",
        )
        capture_metrics = WinnerCaptureEvaluator.evaluate_capture_and_robustness(
            selected_trades=all_selected,
            universe_trades=trades,
        )

        return all_selected, perf_metrics, capture_metrics
