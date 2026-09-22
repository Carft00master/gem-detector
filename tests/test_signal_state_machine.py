"""
Unit tests for Non-Anticipative 8-State Signal State Machine
"""

import pytest
from src.engine.signal_state_machine import SignalState, SignalStateMachine
from src.feeds.base_feed import TokenCandidate
from src.models.predictor import BreakoutPredictionOutput


def test_signal_state_machine_lifecycle():
    sm = SignalStateMachine()
    cand = TokenCandidate(
        address="TestSMToken",
        pair_address="Pair",
        symbol="SM",
        name="StateMachineToken",
        chain="solana",
        dex_id="pumpfun",
        market_cap_usd=12000.0,
        price_usd=0.00012,
        liquidity_usd=4000.0,
    )

    # 1. First Discovery -> NEW / WATCH
    pred_watch = BreakoutPredictionOutput(alert_state="WATCH", momentum_quality=0.4)
    s1 = sm.transition(cand, pred_watch, current_market_cap_usd=12000.0, current_ts="2026-08-24T12:00:00Z")
    assert s1 == SignalState.WATCH

    # 2. Breakout Alert Trigger -> EARLY_BREAKOUT
    pred_break = BreakoutPredictionOutput(alert_state="EARLY_BREAKOUT", momentum_quality=0.6, buyer_quality=0.6)
    s2 = sm.transition(cand, pred_break, current_market_cap_usd=18000.0, current_ts="2026-08-24T12:05:00Z")
    assert s2 == SignalState.EARLY_BREAKOUT

    # Verify First-Alert Opportunity Timestamps recorded permanently
    rec = sm.get_or_create("TestSMToken")
    assert rec.first_signal_timestamp == "2026-08-24T12:05:00Z"
    assert rec.first_alert_mc_usd == 12000.0

    # 3. Follow-Through Acceleration -> STRENGTHENING
    pred_strong = BreakoutPredictionOutput(alert_state="HIGH_CONVICTION", momentum_quality=0.85, buyer_quality=0.85)
    s3 = sm.transition(cand, pred_strong, current_market_cap_usd=45000.0, current_ts="2026-08-24T12:15:00Z")
    assert s3 == SignalState.STRENGTHENING

    # 4. Dev Dumps -> INVALIDATED
    s4 = sm.transition(cand, pred_strong, current_market_cap_usd=20000.0, is_dev_dump=True, current_ts="2026-08-24T12:20:00Z")
    assert s4 == SignalState.INVALIDATED
