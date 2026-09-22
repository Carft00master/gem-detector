"""
Non-Anticipative 8-State Signal State Machine (v1.0.0 Frozen)
Tracks discrete opportunity lifecycles strictly using point-in-time market information:
States:
1. NEW: Token first discovered in $8K-$35K window
2. WATCH: Baseline monitoring, not yet meeting breakout threshold
3. EARLY_BREAKOUT: Initial breakout alert triggered (First Alert)
4. STRENGTHENING: Follow-through momentum, buyer acceleration
5. WEAKENING: Volume contraction, momentum stalling
6. INVALIDATED: Risk condition triggered (dev dump, LP drain, cabal collapse)
7. TARGET_PROGRESS: Surpassed intermediate milestones ($100K, $500K, $1M)
8. EXIT: Target achieved or position stopped out
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional
from src.feeds.base_feed import TokenCandidate
from src.models.predictor import BreakoutPredictionOutput

logger = logging.getLogger(__name__)


class SignalState:
    NEW = "NEW"
    WATCH = "WATCH"
    EARLY_BREAKOUT = "EARLY_BREAKOUT"
    STRENGTHENING = "STRENGTHENING"
    WEAKENING = "WEAKENING"
    INVALIDATED = "INVALIDATED"
    TARGET_PROGRESS = "TARGET_PROGRESS"
    EXIT = "EXIT"


@dataclass
class SignalStateMachineRecord:
    token_address: str
    current_state: str = SignalState.NEW
    previous_state: Optional[str] = None
    state_history: List[Dict[str, Any]] = field(default_factory=list)
    first_eligible_timestamp: Optional[str] = None
    first_signal_timestamp: Optional[str] = None
    first_alert_price_usd: Optional[float] = None
    first_alert_mc_usd: Optional[float] = None
    first_alert_liquidity_usd: Optional[float] = None


class SignalStateMachine:
    def __init__(self):
        self.states: Dict[str, SignalStateMachineRecord] = {}

    def get_or_create(self, token_address: str, current_ts: Optional[str] = None) -> SignalStateMachineRecord:
        if token_address not in self.states:
            ts = current_ts or datetime.now(timezone.utc).isoformat()
            rec = SignalStateMachineRecord(
                token_address=token_address,
                current_state=SignalState.NEW,
                first_eligible_timestamp=ts,
            )
            rec.state_history.append({"state": SignalState.NEW, "timestamp": ts, "reason": "DISCOVERY"})
            self.states[token_address] = rec
        return self.states[token_address]

    def transition(
        self,
        candidate: TokenCandidate,
        prediction: BreakoutPredictionOutput,
        current_market_cap_usd: float,
        is_dev_dump: bool = False,
        is_liquidity_drained: bool = False,
        current_ts: Optional[str] = None,
    ) -> str:
        """
        Evaluate candidate state and execute non-anticipative transition.
        """
        ts = current_ts or datetime.now(timezone.utc).isoformat()
        rec = self.get_or_create(candidate.address, ts)
        curr = rec.current_state
        next_state = curr
        reason = ""

        # 1. Check Invalidation Conditions
        if is_dev_dump or is_liquidity_drained or prediction.p_rug >= 0.60 or candidate.liquidity_usd < 500.0:
            next_state = SignalState.INVALIDATED
            reason = "RISK_INVALIDATION"

        # 2. Check Target Progression
        elif current_market_cap_usd >= 3_000_000.0:
            next_state = SignalState.EXIT
            reason = "TARGET_3M_REACHED"
        elif current_market_cap_usd >= 100_000.0 and curr in (SignalState.EARLY_BREAKOUT, SignalState.STRENGTHENING):
            next_state = SignalState.TARGET_PROGRESS
            reason = "TARGET_MILESTONE_PROGRESS"

        # 3. Lifecycle Transitions
        elif curr == SignalState.NEW:
            if prediction.alert_state in ("EARLY_BREAKOUT", "HIGH_CONVICTION"):
                next_state = SignalState.EARLY_BREAKOUT
                reason = "INITIAL_BREAKOUT_TRIGGER"
            else:
                next_state = SignalState.WATCH
                reason = "WATCH_MONITORING"

        elif curr == SignalState.WATCH:
            if prediction.alert_state in ("EARLY_BREAKOUT", "HIGH_CONVICTION"):
                next_state = SignalState.EARLY_BREAKOUT
                reason = "BREAKOUT_CRITERIA_MET"

        elif curr == SignalState.EARLY_BREAKOUT:
            if prediction.momentum_quality >= 0.70 and prediction.buyer_quality >= 0.70:
                next_state = SignalState.STRENGTHENING
                reason = "MOMENTUM_ACCELERATION"
            elif prediction.momentum_quality < 0.35:
                next_state = SignalState.WEAKENING
                reason = "MOMENTUM_DECELERATION"

        elif curr == SignalState.STRENGTHENING:
            if prediction.momentum_quality < 0.40:
                next_state = SignalState.WEAKENING
                reason = "MOMENTUM_EXHAUSTION"

        elif curr == SignalState.WEAKENING:
            if prediction.momentum_quality >= 0.70:
                next_state = SignalState.STRENGTHENING
                reason = "MOMENTUM_RECOVERY"

        # Apply state transition
        if next_state != curr:
            rec.previous_state = curr
            rec.current_state = next_state
            rec.state_history.append({"state": next_state, "timestamp": ts, "reason": reason})

            # Record First-Alert Opportunity Timestamps permanently
            if next_state == SignalState.EARLY_BREAKOUT and rec.first_signal_timestamp is None:
                rec.first_signal_timestamp = ts
                rec.first_alert_price_usd = candidate.price_usd
                rec.first_alert_mc_usd = candidate.market_cap_usd
                rec.first_alert_liquidity_usd = candidate.liquidity_usd

        return rec.current_state
