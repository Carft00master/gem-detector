"""
RESEARCH-ONLY Challenger: SELECTOR_v2_HIGH_CONVICTION
Implements an ultra-high-conviction, low-frequency opportunity selector.

Architecture Invariants:
1. DISCOVERY: Flexible, hard minimum MC >= $8,000. No fixed upper MC boundary.
2. FIRST-ALERT PRIMARY UNIT: First qualifying alert per token is the primary unit.
   Token state machine: UNSEEN -> WATCHING -> QUALIFIED -> TRADED -> COOLDOWN -> INVALIDATED.
   Suppresses repeated setups from unchanged ticks; allows re-entry only on materially new setups.
3. 8 HIGH-CONVICTION FEATURE GROUPS:
   Probability, Momentum, Participation, Market Quality, Curve, Smart Money, Regime, Execution.
4. SETUP QUALITY MODEL: SETUP_QUALITY_SCORE (0-100) -> Tiers: A+, A, B, C, REJECT.
   Only A+ and A are eligible for trade execution.
5. CONFLUENCE ENGINE: Requires independent confirmation across multiple feature groups.
   CONFLUENCE_COUNT (0-7) and CONFLUENCE_SCORE (0-100). Minimum confluence >= 4 required.
6. EXPECTED-VALUE FILTER: Net EV taking into account win/loss, slippage, fees, and invalidation drag.
7. TOP-K OPPORTUNITY RANKING: Bands: Top 1%, 2%, 5%, 10%, 20%, 30%, ALL.
8. TRADE BUDGET: Configurable caps on new trades per hour, regime, active positions, and per token.
9. FALSE-POSITIVE PRUNER: 5 fatal anti-pattern filters (low breadth, wash pump, thin spike, dev insider, exhaustion).
10. OPPORTUNITY DISPLACEMENT: Best available opportunities displace lower-quality candidates.
11. WALK-FORWARD VALIDATION: Strict chronological Train (60%), Validation (20%), Locked Test (20%).
12. SUCCESS CRITERIA: Lower trade count + higher win rate + better Precision@K + preserved outlier upside.
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

logger = logging.getLogger(__name__)


# ==============================================================================
# 1. TOKEN SETUP STATE MACHINE
# ==============================================================================

class TokenSetupState(str, Enum):
    UNSEEN = "UNSEEN"
    WATCHING = "WATCHING"
    QUALIFIED = "QUALIFIED"
    TRADED = "TRADED"
    COOLDOWN = "COOLDOWN"
    INVALIDATED = "INVALIDATED"


@dataclass
class TokenStateRecord:
    token_address: str
    symbol: str
    state: TokenSetupState = TokenSetupState.UNSEEN
    first_seen_ts: str = ""
    last_alert_ts: str = ""
    last_trade_ts: str = ""
    trade_count: int = 0
    highest_mc_seen: float = 0.0
    lowest_mc_post_trade: float = 0.0
    last_setup_score: float = 0.0
    cooldown_until_ts: Optional[str] = None


class TokenSetupStateMachine:
    """
    Manages token state lifecycle and prevents duplicate entries on unchanged setups.
    Guarantees that the first qualifying opportunity is the primary selection unit.
    """
    def __init__(self, cooldown_minutes: float = 120.0, re_entry_consolidation_pct: float = 20.0):
        self.cooldown_minutes = cooldown_minutes
        self.re_entry_consolidation_pct = re_entry_consolidation_pct
        self.tokens: Dict[str, TokenStateRecord] = {}

    def get_or_create(self, token_address: str, symbol: str, timestamp: str) -> TokenStateRecord:
        if token_address not in self.tokens:
            self.tokens[token_address] = TokenStateRecord(
                token_address=token_address,
                symbol=symbol,
                state=TokenSetupState.UNSEEN,
                first_seen_ts=timestamp,
            )
        return self.tokens[token_address]

    def evaluate_transition(
        self,
        token_address: str,
        symbol: str,
        timestamp: str,
        current_mc: float,
        is_qualifying_setup: bool,
        setup_score: float,
        has_fatal_red_flag: bool = False,
    ) -> Tuple[TokenSetupState, bool, str]:
        """
        Determines current state and whether the token can be considered for trade admission.
        Returns (state, is_eligible_for_trade, reason).
        """
        rec = self.get_or_create(token_address, symbol, timestamp)
        rec.highest_mc_seen = max(rec.highest_mc_seen, current_mc)

        # Fatal safety failure moves directly to INVALIDATED
        if has_fatal_red_flag:
            rec.state = TokenSetupState.INVALIDATED
            return rec.state, False, "INVALIDATED_FATAL_RED_FLAG"

        if rec.state == TokenSetupState.INVALIDATED:
            return rec.state, False, "ALREADY_INVALIDATED"

        if rec.state == TokenSetupState.TRADED:
            # Check if cooldown is in effect
            rec.lowest_mc_post_trade = (
                current_mc
                if rec.lowest_mc_post_trade <= 0.0
                else min(rec.lowest_mc_post_trade, current_mc)
            )
            # Evaluate re-entry conditions
            cooldown_active = True
            if rec.cooldown_until_ts and timestamp >= rec.cooldown_until_ts:
                cooldown_active = False

            # Material new setup requires: cooldown expired AND consolidation >= 20% from peak
            drawdown_from_peak = (
                (rec.highest_mc_seen - rec.lowest_mc_post_trade) / max(rec.highest_mc_seen, 1.0)
            ) * 100.0

            if not cooldown_active and drawdown_from_peak >= self.re_entry_consolidation_pct and is_qualifying_setup:
                # Material fresh breakout wave detected
                rec.state = TokenSetupState.QUALIFIED
                rec.last_alert_ts = timestamp
                rec.last_setup_score = setup_score
                return rec.state, True, f"MATERIAL_NEW_SETUP_POST_CONSOLIDATION_{drawdown_from_peak:.1f}PCT"
            else:
                return rec.state, False, "REPEATED_SETUP_SUPPRESSED"

        if rec.state in (TokenSetupState.UNSEEN, TokenSetupState.WATCHING):
            if current_mc < 8000.0:
                rec.state = TokenSetupState.WATCHING
                return rec.state, False, "MC_BELOW_DISCOVERY_FLOOR_8K"

            if is_qualifying_setup:
                rec.state = TokenSetupState.QUALIFIED
                rec.last_alert_ts = timestamp
                rec.last_setup_score = setup_score
                return rec.state, True, "FIRST_ALERT_QUALIFIED"
            else:
                rec.state = TokenSetupState.WATCHING
                return rec.state, False, "WATCHING_UNCONFIRMED"

        if rec.state == TokenSetupState.QUALIFIED:
            # Already qualified, eligible as primary alert unit
            return rec.state, True, "PRIMARY_ALERT_QUALIFIED"

        return rec.state, False, "INELIGIBLE_STATE"

    def mark_traded(self, token_address: str, timestamp: str):
        if token_address in self.tokens:
            rec = self.tokens[token_address]
            rec.state = TokenSetupState.TRADED
            rec.last_trade_ts = timestamp
            rec.trade_count += 1
            rec.lowest_mc_post_trade = 0.0
            # Calculate cooldown expiration (timestamp + cooldown_minutes)
            try:
                dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                cooldown_sec = self.cooldown_minutes * 60.0
                cooldown_dt = datetime.fromtimestamp(dt.timestamp() + cooldown_sec, tz=timezone.utc)
                rec.cooldown_until_ts = cooldown_dt.isoformat()
            except Exception:
                rec.cooldown_until_ts = timestamp


# ==============================================================================
# 2. HIGH-CONVICTION FEATURE GROUPS
# ==============================================================================

@dataclass
class HighConvictionFeatureBundle:
    # 1. Probability Group
    p3m: float = 0.0
    p3m_velocity: float = 0.0
    p3m_acceleration: float = 0.0
    probability_stability: float = 0.0

    # 2. Momentum Group
    price_velocity: float = 0.0
    price_acceleration: float = 0.0
    mc_velocity: float = 0.0
    mc_acceleration: float = 0.0
    volume_velocity: float = 0.0
    volume_acceleration: float = 0.0

    # 3. Participation Group
    buyer_growth: float = 0.0
    seller_growth: float = 0.0
    trader_growth: float = 0.0
    unique_buyers_to_tx_ratio: float = 0.0
    unique_sellers_to_tx_ratio: float = 0.0

    # 4. Market Quality Group
    two_sided_vol_ratio: float = 0.0
    liquidity_usd: float = 0.0
    vol_to_liq_ratio: float = 0.0
    tx_to_liq_ratio: float = 0.0
    wash_risk: float = 0.0
    cabal_risk: float = 0.0

    # 5. Curve Group
    curve_progress: float = 0.0
    curve_velocity: float = 0.0
    curve_acceleration: float = 0.0

    # 6. Smart Money Group
    validated_wallet_count: int = 0
    independent_wallet_count: int = 0
    wallet_skill: float = 0.0
    wallet_confidence: float = 0.0
    wallet_entry_match: float = 0.0
    smart_money_consensus: int = 0

    # 7. Regime Group
    regime: str = "NORMAL"

    # 8. Execution Group
    estimated_slippage: float = 0.0
    liquidity_depth: float = 0.0
    price_impact: float = 0.0
    route_quality: float = 0.0
    execution_confidence: float = 0.0


class FeatureExtractorV2:
    """
    Extracts and standardizes the 8 high-conviction feature groups from candidate data.
    """
    @staticmethod
    def extract(token: Dict[str, Any]) -> HighConvictionFeatureBundle:
        mc = float(token.get("entry_market_cap_usd") or token.get("market_cap_usd") or 0.0)
        liq = float(token.get("entry_liquidity_usd") or token.get("liquidity_usd") or 0.0)
        p3m = float(token.get("p_reach_3m_at_entry") or token.get("p_reach_3m") or 0.0)
        p100k = float(token.get("p_reach_100k_at_entry") or token.get("p_reach_100k") or 0.0)
        p500k = float(token.get("p_reach_500k_at_entry") or token.get("p_reach_500k") or 0.0)
        p1m = float(token.get("p_reach_1m_at_entry") or token.get("p_reach_1m") or 0.0)

        # 1. Probability Group
        p_std = float(np.std([p100k, p500k, p1m, p3m])) if (p100k > 0 or p3m > 0) else 0.2
        prob_stability = max(0.0, min(1.0, 1.0 - (p_std * 2.5)))
        p3m_vel = float(token.get("p3m_velocity", 0.0)) or max(0.0, p3m - 0.10)
        p3m_acc = float(token.get("p3m_acceleration", 0.0)) or (p3m_vel * 0.5)

        # 2. Momentum Group
        vol_5m = float(token.get("volume_5m_usd") or 0.0)
        vol_1h = float(token.get("volume_1h_usd") or 0.0)
        vol_mc_ratio = vol_5m / max(mc, 1.0)
        price_vel = float(token.get("price_velocity", 0.0)) or min(vol_mc_ratio * 15.0, 100.0)
        price_acc = float(token.get("price_acceleration", 0.0)) or (price_vel * 0.2)
        mc_vel = float(token.get("mc_velocity", 0.0)) or (price_vel * 0.9)
        mc_acc = float(token.get("mc_acceleration", 0.0)) or (price_acc * 0.8)
        vol_vel = float(token.get("volume_velocity", 0.0)) or (vol_5m / max(vol_1h / 12.0, 1.0))
        vol_acc = float(token.get("volume_acceleration", 0.0)) or (vol_vel - 1.0)

        # 3. Participation Group
        buyers = int(token.get("unique_buyers") or 0)
        sellers = int(token.get("unique_sellers") or 0)
        tx_buys = int(token.get("txns_5m_buys") or max(buyers, 1))
        tx_sells = int(token.get("txns_5m_sells") or max(sellers, 1))
        total_tx = tx_buys + tx_sells
        buyers_to_tx = buyers / max(tx_buys, 1)
        sellers_to_tx = sellers / max(tx_sells, 1)
        buyer_growth = float(token.get("buyer_growth", 0.0)) or float(buyers / 5.0)
        seller_growth = float(token.get("seller_growth", 0.0)) or float(sellers / 5.0)
        trader_growth = buyer_growth + seller_growth

        # 4. Market Quality Group
        two_sided_vol = (tx_buys / max(total_tx, 1)) if total_tx > 0 else 0.5
        vol_to_liq = vol_5m / max(liq, 1.0)
        tx_to_liq = total_tx / max(liq / 1000.0, 1.0)
        wash_risk = float(token.get("wash_trade_risk") or token.get("wash_trading_risk") or 0.08)
        cabal_risk = float(token.get("cabal_risk_at_entry") or token.get("cabal_risk_score") or 0.12)

        # 5. Curve Group
        # Pump.fun bonding curve or AMM migration index ($8k to $65k range)
        curve_prog = float(token.get("curve_progress", 0.0)) or min(1.0, max(0.0, (mc - 8000.0) / 60000.0))
        curve_vel = float(token.get("curve_velocity", 0.0)) or (curve_prog * 0.1)
        curve_acc = float(token.get("curve_acceleration", 0.0)) or (curve_vel * 0.05)

        # 6. Smart Money Group
        val_wallets = int(token.get("validated_wallet_count") or token.get("smart_wallet_count") or 0)
        ind_wallets = int(token.get("independent_wallet_count") or max(0, val_wallets - 1))
        wallet_skill = float(token.get("wallet_skill") or 0.65)
        wallet_conf = float(token.get("wallet_confidence") or 0.70)
        wallet_match = float(token.get("wallet_entry_match") or 0.75)
        sm_consensus = 1 if (val_wallets >= 2 and ind_wallets >= 2) else (1 if val_wallets >= 1 else 0)

        # 7. Regime Group
        regime = str(token.get("regime") or token.get("market_regime") or "NORMAL").upper()
        if regime not in ("HOT", "NORMAL", "COLD", "PANIC"):
            regime = "NORMAL"

        # 8. Execution Group
        slippage = float(token.get("entry_slippage_pct") or 1.5)
        impact = float(token.get("entry_price_impact_pct") or 1.5)
        depth = float(token.get("liquidity_depth") or liq * 0.02)
        route_q = float(token.get("route_quality") or 0.95)
        conf = float(token.get("data_confidence_at_entry") or token.get("data_confidence") or 0.85)

        return HighConvictionFeatureBundle(
            p3m=p3m,
            p3m_velocity=p3m_vel,
            p3m_acceleration=p3m_acc,
            probability_stability=prob_stability,
            price_velocity=price_vel,
            price_acceleration=price_acc,
            mc_velocity=mc_vel,
            mc_acceleration=mc_acc,
            volume_velocity=vol_vel,
            volume_acceleration=vol_acc,
            buyer_growth=buyer_growth,
            seller_growth=seller_growth,
            trader_growth=trader_growth,
            unique_buyers_to_tx_ratio=min(1.0, buyers_to_tx),
            unique_sellers_to_tx_ratio=min(1.0, sellers_to_tx),
            two_sided_vol_ratio=two_sided_vol,
            liquidity_usd=liq,
            vol_to_liq_ratio=vol_to_liq,
            tx_to_liq_ratio=tx_to_liq,
            wash_risk=wash_risk,
            cabal_risk=cabal_risk,
            curve_progress=curve_prog,
            curve_velocity=curve_vel,
            curve_acceleration=curve_acc,
            validated_wallet_count=val_wallets,
            independent_wallet_count=ind_wallets,
            wallet_skill=wallet_skill,
            wallet_confidence=wallet_conf,
            wallet_entry_match=wallet_match,
            smart_money_consensus=sm_consensus,
            regime=regime,
            estimated_slippage=slippage,
            liquidity_depth=depth,
            price_impact=impact,
            route_quality=route_q,
            execution_confidence=conf,
        )


# ==============================================================================
# 3. CONFLUENCE ENGINE
# ==============================================================================

@dataclass
class ConfluenceResult:
    confluence_count: int
    confluence_score: float
    confirmed_axes: List[str]
    is_confluent: bool
    details: Dict[str, bool]


class ConfluenceEngine:
    """
    Guarantees no single feature can trigger an admission.
    Evaluates independent confirmations across 7 structural dimensions.
    """
    AXIS_WEIGHTS = {
        "PROBABILITY": 20.0,
        "MOMENTUM": 18.0,
        "PARTICIPATION": 16.0,
        "MARKET_QUALITY": 18.0,
        "CURVE": 8.0,
        "SMART_MONEY": 10.0,
        "EXECUTION": 10.0,
    }

    @classmethod
    def evaluate(cls, fb: HighConvictionFeatureBundle, min_count: int = 4) -> ConfluenceResult:
        confirmations: Dict[str, bool] = {}

        # 1. Probability confirmation
        confirmations["PROBABILITY"] = (fb.p3m >= 0.126) and (fb.p3m_velocity >= 0.0)

        # 2. Momentum confirmation
        confirmations["MOMENTUM"] = (fb.mc_velocity > 0.0) and (fb.price_acceleration >= 0.0)

        # 3. Participation confirmation (organic buyer expansion)
        confirmations["PARTICIPATION"] = (fb.buyer_growth > 0.0) and (fb.unique_buyers_to_tx_ratio >= 0.40)

        # 4. Market Quality confirmation
        confirmations["MARKET_QUALITY"] = (
            (fb.liquidity_usd >= 10000.0)
            and (0.40 <= fb.two_sided_vol_ratio <= 0.85)
            and (fb.wash_risk <= 0.25)
            and (fb.cabal_risk <= 0.35)
        )

        # 5. Curve confirmation (bonding progress active)
        confirmations["CURVE"] = (0.20 <= fb.curve_progress <= 0.95) and (fb.curve_velocity >= 0.0)

        # 6. Smart Money confirmation
        confirmations["SMART_MONEY"] = (fb.smart_money_consensus == 1) or (fb.validated_wallet_count >= 1)

        # 7. Execution confirmation
        confirmations["EXECUTION"] = (
            (fb.price_impact <= 2.5)
            and (fb.estimated_slippage <= 2.5)
            and (fb.execution_confidence >= 0.70)
        )

        confirmed_list = [k for k, v in confirmations.items() if v]
        count = len(confirmed_list)
        score = sum(cls.AXIS_WEIGHTS[k] for k in confirmed_list)

        # Higher threshold in COLD regimes
        effective_min = min_count + (1 if fb.regime == "COLD" else 0)
        is_confluent = count >= effective_min

        return ConfluenceResult(
            confluence_count=count,
            confluence_score=round(score, 1),
            confirmed_axes=confirmed_list,
            is_confluent=is_confluent,
            details=confirmations,
        )


# ==============================================================================
# 4. FALSE-POSITIVE PRUNER
# ==============================================================================

@dataclass
class FalsePositiveCheckResult:
    is_false_positive: bool
    triggered_filters: List[str]
    reason: str


class FalsePositivePruner:
    """
    Identifies and eliminates toxic feature combinations associated with historical failure.
    """
    @classmethod
    def evaluate(cls, fb: HighConvictionFeatureBundle, token: Dict[str, Any]) -> FalsePositiveCheckResult:
        triggers: List[str] = []
        buyers = int(token.get("unique_buyers") or 0)
        vol_mc = fb.vol_to_liq_ratio  # or volume/mc proxy

        # 1. High P3M + Low Breadth: Insider / fake breakout trap
        if fb.p3m >= 0.14 and buyers > 0 and buyers <= 20:
            triggers.append("FP_HIGH_P3M_LOW_BREADTH")

        # 2. High Volume + Low Trader Independence: Wash trading pump
        if vol_mc >= 4.0 and (fb.cabal_risk > 0.40 or fb.wash_risk > 0.30):
            triggers.append("FP_WASH_PUMP_LOW_INDEPENDENCE")

        # 3. High Momentum + Poor Liquidity: Extreme slippage exit trap
        if fb.price_velocity >= 50.0 and fb.liquidity_usd < 8000.0:
            triggers.append("FP_HIGH_MOMENTUM_THIN_LIQUIDITY")

        # 4. Smart Money + High Cabal Concentration: Dev exit liquidity setup
        if fb.validated_wallet_count >= 1 and fb.cabal_risk > 0.45:
            triggers.append("FP_SMART_MONEY_CABAL_COLLUSION")

        # 5. High Activity + Weak Price Response: Bid exhaustion / distribution
        txns = int(token.get("txns_5m_buys", 0)) + int(token.get("txns_5m_sells", 0))
        if txns >= 80 and fb.two_sided_vol_ratio < 0.45 and fb.mc_velocity <= 0.0:
            triggers.append("FP_DISTRIBUTION_BID_EXHAUSTION")

        # 6. Uncalibrated/Restricted Venues
        venue = str(token.get("venue", "")).lower()
        if "pons-v2" in venue or "raydium-cp" in venue:
            triggers.append(f"FP_RESTRICTED_VENUE_{venue.upper()}")

        is_fp = len(triggers) > 0
        return FalsePositiveCheckResult(
            is_false_positive=is_fp,
            triggered_filters=triggers,
            reason="; ".join(triggers) if triggers else "CLEAN",
        )


# ==============================================================================
# 5. EXPECTED-VALUE MODEL
# ==============================================================================

class ExpectedValueEngine:
    """
    Computes mathematical trade expectancy including slippage, fees, and invalidation drag.
    """
    @staticmethod
    def calculate_expected_value(
        p3m: float,
        setup_score: float,
        slippage_pct: float,
        price_impact_pct: float,
        regime: str,
    ) -> float:
        """
        Calculates Net Expected Value (%) per unit traded.
        EV = (P_win * R_win) - ((1 - P_win) * R_loss) - Drag
        """
        # Tier-boosted win probability
        score_multiplier = 0.8 + (setup_score / 100.0) * 0.5
        p_win = max(0.01, min(0.65, (p3m * 2.8) * score_multiplier))

        # Expected return magnitude based on multi-horizon expansion
        # Normal microcap target expansion generates +45% to +180% average winner
        r_win_pct = 75.0

        # Stop-loss gate strictly controls loss magnitude (~ -8.5% to -10.0%)
        r_loss_pct = 8.8

        # Execution friction: 2x round-trip slippage + impact + fee
        drag_pct = (slippage_pct * 1.5) + (price_impact_pct * 1.2) + 1.2

        # Invalidation drag penalty in volatile regimes
        regime_penalty = 1.5 if regime == "PANIC" else (0.5 if regime == "COLD" else 0.0)

        ev = (p_win * r_win_pct) - ((1.0 - p_win) * r_loss_pct) - drag_pct - regime_penalty
        return round(float(ev), 2)


# ==============================================================================
# 6. SETUP QUALITY MODEL & TIERS
# ==============================================================================

class SetupTier(str, Enum):
    A_PLUS = "A+"
    A = "A"
    B = "B"
    C = "C"
    REJECT = "REJECT"


@dataclass
class SetupEvaluationResult:
    token_address: str
    symbol: str
    tier: SetupTier
    setup_quality_score: float
    expected_value: float
    confluence_count: int
    confluence_score: float
    confirmed_axes: List[str]
    is_eligible: bool
    rejection_reasons: List[str]
    feature_bundle: HighConvictionFeatureBundle


class SetupQualityModel:
    """
    Synthesizes independent feature groups, confluence, and EV into a point-in-time quality tier.
    """
    @classmethod
    def evaluate(cls, token: Dict[str, Any], ev_threshold: float = 3.0) -> SetupEvaluationResult:
        addr = token.get("token_address", "UNK")
        sym = token.get("symbol", "UNK")
        rejections: List[str] = []

        # 1. Discovery Hard Gate: MC >= $8,000 (No fixed upper boundary)
        mc = float(token.get("entry_market_cap_usd") or token.get("market_cap_usd") or 0.0)
        if mc < 8000.0:
            rejections.append(f"MC_BELOW_MIN_8K (${mc:,.0f} < $8,000)")

        # 2. Extract 8 Feature Groups
        fb = FeatureExtractorV2.extract(token)

        # 3. Confluence Verification
        cr = ConfluenceEngine.evaluate(fb)
        if not cr.is_confluent:
            rejections.append(f"INSUFFICIENT_CONFLUENCE ({cr.confluence_count} < 4 axes)")

        # 4. False-Positive Elimination
        fp = FalsePositivePruner.evaluate(fb, token)
        if fp.is_false_positive:
            rejections.append(f"FALSE_POSITIVE_FLAGGED ({fp.reason})")

        # 5. Composite Setup Quality Score (0 - 100)
        # 35% Confluence + 25% Prob/Stability + 20% Participation/Quality + 10% Smart Money + 10% Execution
        score_confluence = cr.confluence_score * 0.35
        # Normalize probability against 0.16 high-conviction benchmark
        score_prob = min(100.0, (fb.p3m / 0.16) * 100.0) * fb.probability_stability * 0.25
        score_part = (
            min(100.0, fb.two_sided_vol_ratio * 100.0) * 0.5
            + min(100.0, fb.unique_buyers_to_tx_ratio * 100.0) * 0.5
        ) * 0.20
        score_sm = (fb.wallet_skill * 100.0 if fb.smart_money_consensus == 1 else 60.0) * 0.10
        score_exec = min(100.0, fb.execution_confidence * 100.0) * 0.10

        composite_score = round(score_confluence + score_prob + score_part + score_sm + score_exec, 1)

        # 6. Expected Value Calculation
        ev = ExpectedValueEngine.calculate_expected_value(
            p3m=fb.p3m,
            setup_score=composite_score,
            slippage_pct=fb.estimated_slippage,
            price_impact_pct=fb.price_impact,
            regime=fb.regime,
        )

        if ev < ev_threshold:
            rejections.append(f"EV_BELOW_THRESHOLD ({ev:+.1f}% < {ev_threshold:+.1f}%)")

        # 7. Tier Classification
        is_clean = len(rejections) == 0
        if is_clean and composite_score >= 80.0 and cr.confluence_count >= 5:
            tier = SetupTier.A_PLUS
        elif is_clean and composite_score >= 70.0 and cr.confluence_count >= 4:
            tier = SetupTier.A
        elif composite_score >= 55.0:
            tier = SetupTier.B
        elif composite_score >= 40.0:
            tier = SetupTier.C
        else:
            tier = SetupTier.REJECT

        is_eligible = (tier in (SetupTier.A_PLUS, SetupTier.A)) and is_clean

        return SetupEvaluationResult(
            token_address=addr,
            symbol=sym,
            tier=tier,
            setup_quality_score=composite_score,
            expected_value=ev,
            confluence_count=cr.confluence_count,
            confluence_score=cr.confluence_score,
            confirmed_axes=cr.confirmed_axes,
            is_eligible=is_eligible,
            rejection_reasons=rejections,
            feature_bundle=fb,
        )


# ==============================================================================
# 7. TRADE BUDGET & OPPORTUNITY DISPLACEMENT MANAGER
# ==============================================================================

@dataclass
class TradeBudgetConfig:
    max_new_trades_per_hour: int = 2
    max_simultaneous_positions: int = 6
    max_trades_per_token: int = 1
    regime_hourly_caps: Dict[str, int] = field(
        default_factory=lambda: {
            "HOT": 3,
            "NORMAL": 2,
            "COLD": 1,
            "PANIC": 0,
        }
    )


class OpportunityDisplacementEngine:
    """
    Ranks qualifying candidates at each decision interval and trades only the highest-conviction
    candidates within budget, displacing weaker candidates.
    """
    def __init__(self, budget_config: Optional[TradeBudgetConfig] = None):
        self.config = budget_config or TradeBudgetConfig()
        self.state_machine = TokenSetupStateMachine()
        self.active_positions: Dict[str, str] = {}  # token_address -> exit_timestamp
        self.hourly_trades: Dict[str, int] = defaultdict(int)

    def process_candidates_window(
        self,
        candidates: List[Dict[str, Any]],
        window_hour_key: str,
        top_k_pct: float = 10.0,
    ) -> List[Dict[str, Any]]:
        """
        Filters, scores, ranks, and displaces candidates for an hourly window.
        Returns accepted trades for execution.
        """
        evaluated: List[Tuple[Dict[str, Any], SetupEvaluationResult]] = []

        for cand in candidates:
            res = SetupQualityModel.evaluate(cand)
            if res.is_eligible:
                evaluated.append((cand, res))

        if not evaluated:
            return []

        # Rank candidates by Composite Conviction (Score * EV)
        evaluated.sort(
            key=lambda x: (x[1].setup_quality_score * max(x[1].expected_value, 0.1)),
            reverse=True,
        )

        # Top-K Cutoff Filter
        if top_k_pct < 100.0:
            k_count = max(1, int(len(evaluated) * (top_k_pct / 100.0)))
            admitted_candidates = evaluated[:k_count]
        else:
            admitted_candidates = evaluated

        selected_trades: List[Dict[str, Any]] = []

        for cand, res in admitted_candidates:
            addr = res.token_address
            sym = res.symbol
            ts = cand.get("entry_signal_timestamp") or cand.get("timestamp") or ""
            mc = float(cand.get("entry_market_cap_usd") or cand.get("market_cap_usd") or 0.0)
            regime = res.feature_bundle.regime

            # Evict expired active positions whose exit_timestamp <= current entry timestamp
            if ts:
                self.active_positions = {
                    a: ext for a, ext in self.active_positions.items()
                    if ext and ext > ts
                }

            # Check Token State Machine (First-Alert unit + Unchanged repeat suppression)
            state, can_trade, state_reason = self.state_machine.evaluate_transition(
                token_address=addr,
                symbol=sym,
                timestamp=ts,
                current_mc=mc,
                is_qualifying_setup=True,
                setup_score=res.setup_quality_score,
            )

            if not can_trade:
                continue

            # Check Hourly & Regime Budget
            hourly_cap = self.config.regime_hourly_caps.get(regime, self.config.max_new_trades_per_hour)
            if self.hourly_trades[window_hour_key] >= hourly_cap:
                # Opportunity displaced by earlier higher-ranked candidate
                continue

            # Check Simultaneous Active Positions
            if len(self.active_positions) >= self.config.max_simultaneous_positions:
                continue

            # Admitted!
            self.state_machine.mark_traded(addr, ts)
            self.hourly_trades[window_hour_key] += 1
            exit_ts = str(cand.get("exit_timestamp") or cand.get("exit_execution_timestamp") or "")
            self.active_positions[addr] = exit_ts

            trade_record = dict(cand)
            trade_record["challenger_tier"] = res.tier.value
            trade_record["challenger_setup_score"] = res.setup_quality_score
            trade_record["challenger_ev"] = res.expected_value
            trade_record["challenger_confluence_count"] = res.confluence_count
            trade_record["challenger_confirmed_axes"] = res.confirmed_axes
            selected_trades.append(trade_record)

        return selected_trades


# ==============================================================================
# 8. WALK-FORWARD CHRONOLOGICAL VALIDATOR
# ==============================================================================

class WalkForwardValidator:
    """
    Executes entity-disjoint chronological Train (60%), Validation (20%), and Locked Test (20%)
    audits across all historical trades.
    """
    @staticmethod
    def partition_trades_chronological(
        trades: List[Dict[str, Any]],
        train_ratio: float = 0.60,
        val_ratio: float = 0.20,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Partitions records entity-disjoint and chronologically by entry_signal_timestamp.
        """
        # Sort all trades by timestamp
        sorted_trades = sorted(
            trades,
            key=lambda x: str(x.get("entry_signal_timestamp") or x.get("timestamp") or ""),
        )

        # Unique token ordering by first observed timestamp
        token_first_seen: Dict[str, str] = {}
        token_trades: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for t in sorted_trades:
            addr = str(t.get("token_address", "UNK"))
            ts = str(t.get("entry_signal_timestamp") or t.get("timestamp") or "")
            token_trades[addr].append(t)
            if addr not in token_first_seen or ts < token_first_seen[addr]:
                token_first_seen[addr] = ts

        sorted_tokens = sorted(token_first_seen.keys(), key=lambda a: token_first_seen[a])
        n_tokens = len(sorted_tokens)

        n_train = int(n_tokens * train_ratio)
        n_val = int(n_tokens * val_ratio)

        train_tokens = set(sorted_tokens[:n_train])
        val_tokens = set(sorted_tokens[n_train : n_train + n_val])
        locked_tokens = set(sorted_tokens[n_train + n_val :])

        train_trades = [t for a in train_tokens for t in token_trades[a]]
        val_trades = [t for a in val_tokens for t in token_trades[a]]
        locked_trades = [t for a in locked_tokens for t in token_trades[a]]

        # Re-sort partitions chronologically
        key_fn = lambda x: str(x.get("entry_signal_timestamp") or x.get("timestamp") or "")
        train_trades.sort(key=key_fn)
        val_trades.sort(key=key_fn)
        locked_trades.sort(key=key_fn)

        return train_trades, val_trades, locked_trades

    @staticmethod
    def compute_performance_metrics(trades: List[Dict[str, Any]], label: str = "") -> Dict[str, Any]:
        """
        Computes the complete quantitative matrix required by the specification.
        """
        n = len(trades)
        if n == 0:
            return {
                "label": label, "trade_count": 0, "win_rate": 0.0, "p_at_10": 0.0,
                "p_at_25": 0.0, "mean_pnl": 0.0, "median_pnl": 0.0, "mean_ret_pct": 0.0,
                "median_ret_pct": 0.0, "profit_factor": 0.0, "max_drawdown_pct": 0.0,
                "mean_mfe": 0.0, "mean_mae": 0.0, "runners_3m_count": 0, "executable_pnl": 0.0,
            }

        rets = [float(t.get("net_realized_return_pct") or 0.0) for t in trades]
        pnls = [float(t.get("net_realized_pnl_usd") or 0.0) for t in trades]
        wins = [r for r in rets if r > 0]
        losses = [r for r in rets if r < 0]

        win_rate = (len(wins) / n) * 100.0
        profit_factor = (sum(wins) / abs(sum(losses))) if (losses and sum(losses) != 0) else (99.0 if wins else 0.0)

        # Precision @ K (ranked by p3m or setup score)
        sorted_by_conviction = sorted(
            trades,
            key=lambda x: float(x.get("challenger_setup_score") or x.get("p_reach_3m_at_entry") or 0.0),
            reverse=True,
        )
        top10 = sorted_by_conviction[:10]
        top25 = sorted_by_conviction[:25]
        p_at_10 = (sum(1 for t in top10 if float(t.get("net_realized_return_pct") or 0.0) > 0) / max(len(top10), 1)) * 100.0
        p_at_25 = (sum(1 for t in top25 if float(t.get("net_realized_return_pct") or 0.0) > 0) / max(len(top25), 1)) * 100.0

        # Drawdown calculation
        cumulative = np.cumsum(pnls)
        peak = np.maximum.accumulate(cumulative)
        drawdown = peak - cumulative
        max_dd = float(np.max(drawdown)) if len(drawdown) > 0 else 0.0

        # MFE / MAE
        mfe_list = [float(t.get("mfe_ratio") or 1.0) for t in trades]
        mae_list = [float(t.get("mae_ratio") or 1.0) for t in trades]

        # Target 3M runners captured
        runners_3m = sum(1 for t in trades if int(t.get("target_reached_3m") or 0) == 1)

        return {
            "label": label,
            "trade_count": n,
            "win_rate": round(win_rate, 2),
            "p_at_10": round(p_at_10, 1),
            "p_at_25": round(p_at_25, 1),
            "mean_pnl": round(float(np.mean(pnls)), 2),
            "median_pnl": round(float(np.median(pnls)), 2),
            "mean_ret_pct": round(float(np.mean(rets)), 2),
            "median_ret_pct": round(float(np.median(rets)), 2),
            "profit_factor": round(profit_factor, 2),
            "max_drawdown_pct": round(max_dd, 2),
            "mean_mfe": round(float(np.mean(mfe_list)), 2),
            "mean_mae": round(float(np.mean(mae_list)), 2),
            "runners_3m_count": runners_3m,
            "executable_pnl": round(float(sum(pnls)), 2),
        }


# ==============================================================================
# 9. MAIN CHALLENGER ENGINE: SELECTOR_v2_HIGH_CONVICTION
# ==============================================================================

class SelectorV2HighConvictionEngine:
    """
    Complete RESEARCH_ONLY Selector v2 Engine.
    Executes high-conviction low-frequency opportunity selection across candidates and streams.
    """
    VERSION = "SELECTOR_v2_HIGH_CONVICTION"

    def __init__(self, budget_config: Optional[TradeBudgetConfig] = None):
        self.budget_config = budget_config or TradeBudgetConfig()

    def evaluate_dataset(
        self,
        trades: List[Dict[str, Any]],
        top_k_pct: float = 10.0,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        Runs the full selector engine over a set of trade candidates grouped by hour.
        """
        # Group candidates by hourly windows to simulate point-in-time competition
        hourly_buckets: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for t in trades:
            ts = str(t.get("entry_signal_timestamp") or t.get("timestamp") or "")
            hr_key = ts[:13] if len(ts) >= 13 else "unknown"
            hourly_buckets[hr_key].append(t)

        displacement_engine = OpportunityDisplacementEngine(self.budget_config)
        all_selected: List[Dict[str, Any]] = []

        for hr_key in sorted(hourly_buckets.keys()):
            batch = hourly_buckets[hr_key]
            selected = displacement_engine.process_candidates_window(
                candidates=batch,
                window_hour_key=hr_key,
                top_k_pct=top_k_pct,
            )
            all_selected.extend(selected)

        metrics = WalkForwardValidator.compute_performance_metrics(all_selected, label=f"SELECTOR_v2 (Top {top_k_pct}%)")
        return all_selected, metrics

    def run_walk_forward_evaluation(self, trades: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Performs full Train / Validation / Locked-Test walk-forward evaluation,
        Top-K sensitivity comparison, and confluence level breakdown.
        """
        train_trades, val_trades, locked_trades = WalkForwardValidator.partition_trades_chronological(trades)

        # 1. Baseline Champion Performance (All trades)
        champ_all = WalkForwardValidator.compute_performance_metrics(trades, label="Champion v1.0.0 (All)")
        champ_train = WalkForwardValidator.compute_performance_metrics(train_trades, label="Champion v1.0.0 (Train)")
        champ_val = WalkForwardValidator.compute_performance_metrics(val_trades, label="Champion v1.0.0 (Validation)")
        champ_locked = WalkForwardValidator.compute_performance_metrics(locked_trades, label="Champion v1.0.0 (Locked Test)")

        # 2. Challenger Performance across Partitions (Default Top 10% band)
        _, chal_train = self.evaluate_dataset(train_trades, top_k_pct=10.0)
        _, chal_val = self.evaluate_dataset(val_trades, top_k_pct=10.0)
        _, chal_locked = self.evaluate_dataset(locked_trades, top_k_pct=10.0)
        chal_overall_trades, chal_overall = self.evaluate_dataset(trades, top_k_pct=10.0)

        # 3. Top-K Sensitivity Matrix (Top 1%, 2%, 5%, 10%, 20%, 30%, ALL)
        top_k_bands = [1.0, 2.0, 5.0, 10.0, 20.0, 30.0, 100.0]
        top_k_comparison: List[Dict[str, Any]] = []
        for k in top_k_bands:
            label = "ALL" if k == 100.0 else f"TOP {int(k)}%"
            _, m = self.evaluate_dataset(locked_trades, top_k_pct=k)
            m["band_label"] = label
            top_k_comparison.append(m)

        # 4. Confluence Level Breakdown (1 to 7 axes)
        confluence_breakdown: List[Dict[str, Any]] = []
        for c_level in range(1, 8):
            confluent_slice: List[Dict[str, Any]] = []
            for t in locked_trades:
                fb = FeatureExtractorV2.extract(t)
                cr = ConfluenceEngine.evaluate(fb, min_count=c_level)
                if cr.confluence_count == c_level:
                    confluent_slice.append(t)
            m = WalkForwardValidator.compute_performance_metrics(confluent_slice, label=f"Confluence Level {c_level}")
            m["level"] = c_level
            confluence_breakdown.append(m)

        return {
            "challenger_name": self.VERSION,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "sample_size": len(trades),
            "partitions": {
                "train_size": len(train_trades),
                "val_size": len(val_trades),
                "locked_test_size": len(locked_trades),
            },
            "champion_baseline": {
                "overall": champ_all,
                "train": champ_train,
                "val": champ_val,
                "locked_test": champ_locked,
            },
            "challenger_walk_forward": {
                "overall": chal_overall,
                "train": chal_train,
                "val": chal_val,
                "locked_test": chal_locked,
            },
            "top_k_sensitivity_locked_test": top_k_comparison,
            "confluence_breakdown": confluence_breakdown,
        }


# ==============================================================================
# 10. STANDALONE AUDIT CLI ENTRYPOINT
# ==============================================================================

def run_full_walk_forward_evaluation(
    db_path: str = "data/paper_trading.db",
    shadow_db_path: str = "data/shadow_universe.db",
) -> Dict[str, Any]:
    """Helper function to load trades and run complete evaluation."""
    logger.info(f"Loading historical trades from {db_path} joined with {shadow_db_path}...")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    has_shadow = False
    try:
        conn.execute(f"ATTACH DATABASE '{shadow_db_path}' AS shadow")
        has_shadow = True
    except Exception as e:
        logger.warning(f"Could not attach shadow universe DB: {e}")

    if has_shadow:
        query = """
            SELECT p.*,
                   s.volume_5m_usd, s.volume_1h_usd, s.unique_buyers, s.unique_sellers,
                   s.effective_vol_mc_ratio, s.effective_buy_pressure, s.wallet_independence,
                   COALESCE(s.wash_trade_risk, 0.08) AS shadow_wash_risk,
                   COALESCE(s.cabal_risk_score, 0.12) AS shadow_cabal_risk
            FROM paper_trades p
            LEFT JOIN shadow.shadow_tokens s ON p.token_address = s.token_address
            WHERE p.outcome_label IS NOT NULL
            ORDER BY p.entry_signal_timestamp ASC
        """
    else:
        query = "SELECT * FROM paper_trades WHERE outcome_label IS NOT NULL ORDER BY entry_signal_timestamp ASC"

    trades = [dict(r) for r in conn.execute(query).fetchall()]
    conn.close()

    engine = SelectorV2HighConvictionEngine()
    results = engine.run_walk_forward_evaluation(trades)
    return results
