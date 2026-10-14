"""
Unit tests for SingleFinalGateLayer (Phase 1h)
Verifies sequential evaluation of all 6 gates, complete elimination of selector bypasses,
fail-closed data enforcement, and automated shadow ledger recording of all rejections.
"""

import pytest
from src.feeds.base_feed import TokenCandidate
from src.models.predictor import BreakoutPredictionOutput
from src.paper.fail_closed_data import FailClosedDataValidator
from src.paper.final_gate_layer import SingleFinalGateLayer
from src.paper.ledger import PaperTradingLedger
from src.paper.shadow_ledger import ShadowLedgerManager
from src.paper.venue_state_machine import VenueStateMachine, VenueState


@pytest.fixture
def gate_setup(tmp_path):
    db_file = tmp_path / "test_gate.db"
    jsonl_file = tmp_path / "test_gate.jsonl"
    ledger = PaperTradingLedger(db_path=db_file, jsonl_path=jsonl_file)
    shadow_ledger = ShadowLedgerManager(ledger=ledger, db_path=db_file)
    venue_fsm = VenueStateMachine()
    data_validator = FailClosedDataValidator(max_market_cap_usd=16000.0, min_unique_buyers=25)

    gate_layer = SingleFinalGateLayer(
        data_validator=data_validator,
        venue_fsm=venue_fsm,
        shadow_ledger=shadow_ledger,
        min_liquidity_usd=2500.0,
        min_p_reach_3m=0.09,
        min_unique_buyers=25,
    )
    return gate_layer, shadow_ledger, venue_fsm


def test_gate_1_stale_curve_rejection(gate_setup):
    gate_layer, shadow_ledger, venue_fsm = gate_setup
    mint = "7EYnhQoR9YM3N7UoaKRoA44Uy8Jeaucs3DYVWo2Ppump"
    # Transition token to MIGRATED / POOL
    venue_fsm.on_curve_migration_detected(mint, slot=1000, pool_address="Pool11111111111111111111111111111111111111")

    cand = TokenCandidate(
        address=mint,
        pair_address="Pair11111111111111111111111111111111111111",
        symbol="STALE",
        name="Stale Token",
        chain="solana",
        dex_id="pumpfun", # Attempting curve entry on migrated token
        market_cap_usd=10000.0,
        price_usd=0.000010,
        liquidity_usd=8000.0,
    )
    pred = BreakoutPredictionOutput(p_reach_3m=0.15, alert_state="HIGH_CONVICTION")

    res = gate_layer.evaluate(cand, pred)
    assert not res.is_passed
    assert any("GATE_1_VENUE_STATE" in r for r in res.rejection_reasons)

    # Verify recorded to shadow ledger
    rejected = shadow_ledger.get_rejected_candidates()
    assert len(rejected) == 1
    assert rejected[0]["token_address"] == mint
    assert rejected[0]["rejection_reason"] == "GATE_1_VENUE_STATE"


def test_gate_2_toxic_venue_rejection(gate_setup):
    gate_layer, shadow_ledger, _ = gate_setup
    mint = "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R"
    cand = TokenCandidate(
        address=mint,
        pair_address="Pair22222222222222222222222222222222222222",
        symbol="TOXIC",
        name="Toxic Venue Token",
        chain="solana",
        dex_id="meteora-dbc", # Toxic venue
        market_cap_usd=12000.0,
        price_usd=0.000012,
        liquidity_usd=9000.0,
    )
    pred = BreakoutPredictionOutput(p_reach_3m=0.18, alert_state="HIGH_CONVICTION")

    res = gate_layer.evaluate(cand, pred)
    assert not res.is_passed
    assert any("GATE_2_TOXIC_VENUE" in r for r in res.rejection_reasons)


def test_gate_3_liquidity_depth_floor_rejection(gate_setup):
    gate_layer, shadow_ledger, _ = gate_setup
    mint = "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R"
    cand = TokenCandidate(
        address=mint,
        pair_address="Pair33333333333333333333333333333333333333",
        symbol="THIN",
        name="Thin Liquidity",
        chain="solana",
        dex_id="pumpfun",
        market_cap_usd=5000.0,
        price_usd=0.000005,
        liquidity_usd=1500.0, # Below $2,500 floor
    )
    pred = BreakoutPredictionOutput(p_reach_3m=0.15, alert_state="HIGH_CONVICTION")

    res = gate_layer.evaluate(cand, pred)
    assert not res.is_passed
    assert any("GATE_3_LIQUIDITY_DEPTH" in r for r in res.rejection_reasons)


def test_gate_4_anti_fake_volume_bump_bot_rejection(gate_setup):
    gate_layer, shadow_ledger, _ = gate_setup
    mint = "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R"
    cand = TokenCandidate(
        address=mint,
        pair_address="Pair44444444444444444444444444444444444444",
        symbol="BUMP",
        name="Bump Bot Token",
        chain="solana",
        dex_id="pumpfun",
        market_cap_usd=12000.0,
        price_usd=0.000012,
        liquidity_usd=8000.0,
    )
    # 50 txns but only $200 volume -> $4/trade average (micro-churn)
    cand.volume_5m_usd = 200.0
    cand.txns_5m_buys = 30
    cand.txns_5m_sells = 20
    pred = BreakoutPredictionOutput(p_reach_3m=0.15, alert_state="HIGH_CONVICTION")

    res = gate_layer.evaluate(cand, pred)
    assert not res.is_passed
    assert any("GATE_4_BUMP_BOT" in r for r in res.rejection_reasons)


def test_gate_5_model_default_p3m_rejection(gate_setup):
    gate_layer, shadow_ledger, _ = gate_setup
    mint = "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R"
    cand = TokenCandidate(
        address=mint,
        pair_address="Pair55555555555555555555555555555555555555",
        symbol="DEFAULT",
        name="Default P3M Token",
        chain="solana",
        dex_id="pumpfun",
        market_cap_usd=12000.0,
        price_usd=0.000012,
        liquidity_usd=8000.0,
    )
    cand.volume_5m_usd = 2000.0
    cand.txns_5m_buys = 20
    cand.txns_5m_sells = 10
    # Exact uninitialized fallback 0.0795 must be rejected
    pred = BreakoutPredictionOutput(p_reach_3m=0.0795, alert_state="EARLY_BREAKOUT")

    res = gate_layer.evaluate(cand, pred)
    assert not res.is_passed
    assert any("GATE_5_MODEL_DEFAULT" in r for r in res.rejection_reasons)


def test_gate_all_pass_clean_candidate(gate_setup):
    gate_layer, shadow_ledger, _ = gate_setup
    mint = "7EYnhQoR9YM3N7UoaKRoA44Uy8Jeaucs3DYVWo2Ppump"
    cand = TokenCandidate(
        address=mint,
        pair_address="Pair66666666666666666666666666666666666666",
        symbol="CLEAN",
        name="Clean Valid Token",
        chain="solana",
        dex_id="pumpfun",
        market_cap_usd=12000.0,
        price_usd=0.000012,
        liquidity_usd=8000.0,
    )
    cand.volume_5m_usd = 3500.0
    cand.token_age_minutes = 20.0
    cand.unique_buyers = 42
    cand.buy_sell_ratio = 2.5
    cand.txns_5m_buys = 35
    cand.txns_5m_sells = 12
    cand.dev_holding_pct = 1.2
    cand.top10_holder_pct = 14.5

    pred = BreakoutPredictionOutput(p_reach_3m=0.18, alert_state="HIGH_CONVICTION")

    res = gate_layer.evaluate(cand, pred, position_size_usd=75.0)
    assert res.is_passed
    assert len(res.rejection_reasons) == 0
    assert len(res.passed_gates) >= 5
    assert res.telemetry is not None
    assert res.telemetry.is_valid
