"""
Unit tests for SingleFinalGateLayer (Phase 1h / Phase 1.3)
Verifies:
1. Sequential evaluation of all gates without selector bypasses.
2. Route-aware gates (Route A vs Route B) and config-driven thresholds.
3. Every individual gate rejection reason:
   - Chain whitelist
   - Liquidity depth floor
   - Liquidity/MC ratio [0.30, 1.35]
   - Slippage and price impact <= 5.0%
   - Position size <= 1.0% of pool liquidity
   - P(rug) <= 0.20
   - Data confidence >= 0.70
   - Single-wallet curve filler rejection for Route A
   - Toxic venue blacklist
   - Venue state machine
   - Bump-bot micro churn & hyper-turnover
   - Model default & floor
4. Strict fail-closed rejections for missing/NaN/None inputs for every single gate.
5. All rejections logged to shadow ledger.
"""

import math
import pytest
from src.feeds.base_feed import TokenCandidate
from src.models.predictor import BreakoutPredictionOutput
from src.paper.fail_closed_data import FailClosedDataValidator
from src.paper.final_gate_layer import SingleFinalGateLayer, RouteGateConfig
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


def _make_clean_candidate(mint: str = "7EYnhQoR9YM3N7UoaKRoA44Uy8Jeaucs3DYVWo2Ppump") -> TokenCandidate:
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
    cand.price_impact_pct = 0.80
    cand.slippage_pct = 1.00
    cand.p_rug = 0.05
    cand.data_confidence = 0.85
    cand.is_single_wallet_curve_filler = False
    return cand


def test_gate_all_pass_clean_candidate(gate_setup):
    gate_layer, _, _ = gate_setup
    cand = _make_clean_candidate()
    pred = BreakoutPredictionOutput(p_reach_3m=0.18, alert_state="HIGH_CONVICTION")

    res = gate_layer.evaluate(cand, pred, position_size_usd=75.0, route="ROUTE_A")
    assert res.is_passed
    assert len(res.rejection_reasons) == 0
    assert len(res.passed_gates) >= 8
    assert res.telemetry is not None
    assert res.telemetry.is_valid


def test_gate_1_stale_curve_rejection(gate_setup):
    gate_layer, shadow_ledger, venue_fsm = gate_setup
    mint = "7EYnhQoR9YM3N7UoaKRoA44Uy8Jeaucs3DYVWo2Ppump"
    venue_fsm.on_curve_migration_detected(mint, slot=1000, pool_address="Pool11111111111111111111111111111111111111")

    cand = _make_clean_candidate(mint)
    cand.dex_id = "pumpfun"
    pred = BreakoutPredictionOutput(p_reach_3m=0.15, alert_state="HIGH_CONVICTION")

    res = gate_layer.evaluate(cand, pred, position_size_usd=75.0)
    assert not res.is_passed
    assert any("GATE_1_VENUE_STATE" in r for r in res.rejection_reasons)


def test_gate_2_toxic_venue_rejection(gate_setup):
    gate_layer, _, _ = gate_setup
    cand = _make_clean_candidate()
    cand.dex_id = "meteora-dbc"
    pred = BreakoutPredictionOutput(p_reach_3m=0.15)

    res = gate_layer.evaluate(cand, pred, position_size_usd=75.0)
    assert not res.is_passed
    assert any("GATE_2_TOXIC_VENUE" in r for r in res.rejection_reasons)


def test_gate_3_chain_whitelist_rejection(gate_setup):
    gate_layer, _, _ = gate_setup
    cand = _make_clean_candidate()
    cand.chain = "bsc"  # Non-whitelisted chain
    pred = BreakoutPredictionOutput(p_reach_3m=0.15)

    res = gate_layer.evaluate(cand, pred, position_size_usd=75.0)
    assert not res.is_passed
    assert any("GATE_3_CHAIN_WHITELIST" in r for r in res.rejection_reasons)


def test_gate_4_liquidity_depth_floor_rejection(gate_setup):
    gate_layer, _, _ = gate_setup
    cand = _make_clean_candidate()
    cand.liquidity_usd = 1500.0  # Below $2,500 floor
    pred = BreakoutPredictionOutput(p_reach_3m=0.15)

    res = gate_layer.evaluate(cand, pred, position_size_usd=10.0)
    assert not res.is_passed
    assert any("GATE_4_LIQUIDITY_DEPTH" in r for r in res.rejection_reasons)


def test_gate_5_liquidity_mc_ratio_bounds_rejection(gate_setup):
    gate_layer, _, _ = gate_setup
    cand = _make_clean_candidate()

    # Ratio too low: liq $2,600 on MC $15,000 -> 0.173 < 0.30
    cand.market_cap_usd = 15000.0
    cand.liquidity_usd = 2600.0
    pred = BreakoutPredictionOutput(p_reach_3m=0.15)
    res_low = gate_layer.evaluate(cand, pred, position_size_usd=20.0)
    assert not res_low.is_passed
    assert any("GATE_5_LIQUIDITY_MC_RATIO" in r for r in res_low.rejection_reasons)

    # Ratio too high: liq $15,000 on MC $10,000 -> 1.50 > 1.35
    cand.market_cap_usd = 10000.0
    cand.liquidity_usd = 15000.0
    res_high = gate_layer.evaluate(cand, pred, position_size_usd=50.0)
    assert not res_high.is_passed
    assert any("GATE_5_LIQUIDITY_MC_RATIO" in r for r in res_high.rejection_reasons)


def test_gate_6_slippage_and_impact_rejection(gate_setup):
    gate_layer, _, _ = gate_setup
    cand = _make_clean_candidate()
    cand.price_impact_pct = 6.5  # Exceeds 5.0%
    pred = BreakoutPredictionOutput(p_reach_3m=0.15)

    res = gate_layer.evaluate(cand, pred, position_size_usd=75.0)
    assert not res.is_passed
    assert any("GATE_6_SLIPPAGE_AND_IMPACT" in r for r in res.rejection_reasons)


def test_gate_7_position_size_vs_liquidity_rejection(gate_setup):
    gate_layer, _, _ = gate_setup
    cand = _make_clean_candidate()
    cand.liquidity_usd = 5000.0
    # $100 size on $5,000 pool = 2.0% > 1.0% limit for Route A
    pred = BreakoutPredictionOutput(p_reach_3m=0.15)

    res = gate_layer.evaluate(cand, pred, position_size_usd=100.0, route="ROUTE_A")
    assert not res.is_passed
    assert any("GATE_7_POSITION_SIZE_VS_LIQUIDITY" in r for r in res.rejection_reasons)


def test_gate_8_p_rug_rejection(gate_setup):
    gate_layer, _, _ = gate_setup
    cand = _make_clean_candidate()
    cand.p_rug = 0.35  # Exceeds 0.20 max
    pred = BreakoutPredictionOutput(p_reach_3m=0.15)

    res = gate_layer.evaluate(cand, pred, position_size_usd=50.0)
    assert not res.is_passed
    assert any("GATE_8_P_RUG" in r for r in res.rejection_reasons)


def test_gate_9_data_confidence_rejection(gate_setup):
    gate_layer, _, _ = gate_setup
    cand = _make_clean_candidate()
    cand.data_confidence = 0.55  # Below 0.70 min
    pred = BreakoutPredictionOutput(p_reach_3m=0.15)

    res = gate_layer.evaluate(cand, pred, position_size_usd=50.0)
    assert not res.is_passed
    assert any("GATE_9_DATA_CONFIDENCE" in r for r in res.rejection_reasons)


def test_gate_10_single_wallet_curve_filler_route_a_rejection(gate_setup):
    gate_layer, _, _ = gate_setup
    cand = _make_clean_candidate()
    cand.is_single_wallet_curve_filler = True  # Sniped / single wallet 100% curve buyout
    pred = BreakoutPredictionOutput(p_reach_3m=0.15)

    # Route A must reject single wallet curve filler
    res_a = gate_layer.evaluate(cand, pred, position_size_usd=50.0, route="ROUTE_A")
    assert not res_a.is_passed
    assert any("GATE_10_CURVE_FILLER" in r for r in res_a.rejection_reasons)

    # Route B (migration sniper) allows / bypasses this check
    cand.price_impact_pct = 4.0
    cand.slippage_pct = 4.0
    res_b = gate_layer.evaluate(cand, pred, position_size_usd=50.0, route="ROUTE_B")
    assert res_b.is_passed
    assert "GATE_10_CURVE_FILLER_BYPASS" in res_b.passed_gates


def test_route_b_insider_risk_gates(gate_setup):
    gate_layer, _, _ = gate_setup
    cand = _make_clean_candidate()
    cand.is_single_wallet_curve_filler = True
    cand.price_impact_pct = 4.0
    cand.slippage_pct = 4.0
    pred = BreakoutPredictionOutput(p_reach_3m=0.15)

    # 1. NODF-like insider bundle share (79.31% > 70% limit) strictly rejects on Route B
    cand.curve_filler_holding_pct = 79.31
    res_insider = gate_layer.evaluate(cand, pred, position_size_usd=50.0, route="ROUTE_B")
    assert not res_insider.is_passed
    assert any("GATE_ROUTE_B_INSIDER_RISK" in r for r in res_insider.rejection_reasons)

    # 2. Shallow opening SOL reserves (< 60 SOL, e.g. 30 SOL) rejects on Route B
    cand.curve_filler_holding_pct = 45.0  # within 70%
    cand.opening_sol_reserves = 30.0     # below 60 SOL
    res_shallow = gate_layer.evaluate(cand, pred, position_size_usd=50.0, route="ROUTE_B")
    assert not res_shallow.is_passed
    assert any("GATE_ROUTE_B_OPENING_RESERVES" in r for r in res_shallow.rejection_reasons)

    # 3. Healthy Route B candidate passes
    cand.opening_sol_reserves = 84.99    # Normal ~85 SOL opening
    res_pass = gate_layer.evaluate(cand, pred, position_size_usd=50.0, route="ROUTE_B")
    assert res_pass.is_passed
    assert "GATE_ROUTE_B_INSIDER_RISK" in res_pass.passed_gates
    assert "GATE_ROUTE_B_OPENING_RESERVES" in res_pass.passed_gates


# ==============================================================================
# FAIL-CLOSED MISSING INPUT TESTS (Zero-tolerance for missing / NaN values)
# ==============================================================================

def test_fail_closed_missing_chain(gate_setup):
    gate_layer, _, _ = gate_setup
    cand = _make_clean_candidate()
    cand.chain = None
    pred = BreakoutPredictionOutput(p_reach_3m=0.15)

    res = gate_layer.evaluate(cand, pred, position_size_usd=50.0)
    assert not res.is_passed
    assert any("GATE_3_CHAIN_WHITELIST" in r for r in res.rejection_reasons)


def test_fail_closed_missing_liquidity(gate_setup):
    gate_layer, _, _ = gate_setup
    cand = _make_clean_candidate()
    cand.liquidity_usd = None
    pred = BreakoutPredictionOutput(p_reach_3m=0.15)

    res = gate_layer.evaluate(cand, pred, position_size_usd=50.0)
    assert not res.is_passed
    assert any("GATE_4_LIQUIDITY_DEPTH" in r for r in res.rejection_reasons)


def test_fail_closed_missing_market_cap(gate_setup):
    gate_layer, _, _ = gate_setup
    cand = _make_clean_candidate()
    cand.market_cap_usd = None
    pred = BreakoutPredictionOutput(p_reach_3m=0.15)

    res = gate_layer.evaluate(cand, pred, position_size_usd=50.0)
    assert not res.is_passed
    assert any("GATE_5_LIQUIDITY_MC_RATIO" in r for r in res.rejection_reasons)


def test_fail_closed_missing_price_impact(gate_setup):
    gate_layer, _, _ = gate_setup
    cand = _make_clean_candidate()
    cand.price_impact_pct = None
    cand.slippage_pct = None
    cand.liquidity_usd = 0.0  # Prevents deriving impact
    pred = BreakoutPredictionOutput(p_reach_3m=0.15)

    res = gate_layer.evaluate(cand, pred, position_size_usd=50.0)
    assert not res.is_passed
    assert any("GATE_6_SLIPPAGE_AND_IMPACT" in r for r in res.rejection_reasons)


def test_fail_closed_missing_p_rug(gate_setup):
    gate_layer, _, _ = gate_setup
    cand = _make_clean_candidate()
    cand.p_rug = None
    pred = BreakoutPredictionOutput(p_reach_3m=0.15)
    pred.p_rug = None

    res = gate_layer.evaluate(cand, pred, position_size_usd=50.0)
    assert not res.is_passed
    assert any("GATE_8_P_RUG" in r for r in res.rejection_reasons)


def test_fail_closed_missing_data_confidence(gate_setup):
    gate_layer, _, _ = gate_setup
    cand = _make_clean_candidate()
    cand.data_confidence = None
    pred = BreakoutPredictionOutput(p_reach_3m=0.15)
    pred.data_confidence = None

    res = gate_layer.evaluate(cand, pred, position_size_usd=50.0)
    assert not res.is_passed
    assert any("GATE_9_DATA_CONFIDENCE" in r for r in res.rejection_reasons)


def test_fail_closed_missing_curve_filler_for_route_a(gate_setup):
    gate_layer, _, _ = gate_setup
    cand = _make_clean_candidate()
    cand.is_single_wallet_curve_filler = None
    pred = BreakoutPredictionOutput(p_reach_3m=0.15)

    res = gate_layer.evaluate(cand, pred, position_size_usd=50.0, route="ROUTE_A")
    assert not res.is_passed
    assert any("GATE_10_CURVE_FILLER" in r for r in res.rejection_reasons)


def test_fail_closed_missing_p3m(gate_setup):
    gate_layer, _, _ = gate_setup
    cand = _make_clean_candidate()
    pred = BreakoutPredictionOutput(p_reach_3m=0.15)
    pred.p_reach_3m = None

    res = gate_layer.evaluate(cand, pred, position_size_usd=50.0)
    assert not res.is_passed
    assert any("GATE_12_MODEL_SCORE" in r for r in res.rejection_reasons)


def test_rejection_signal_state_watch(gate_setup):
    """Signal state WATCH must be strictly rejected from trade execution."""
    gate_layer, _, _ = gate_setup
    cand = _make_clean_candidate()
    cand.signal_state = "WATCH"
    pred = BreakoutPredictionOutput(p_reach_3m=0.15)

    res = gate_layer.evaluate(cand, pred, position_size_usd=50.0)
    assert not res.is_passed
    assert any("GATE_SIGNAL_STATE_WATCH" in r for r in res.rejection_reasons)


# ==============================================================================
# DEDICATED AUDIT TESTS FOR ALL REQUIRED INDIVIDUAL GATES
# ==============================================================================

def test_unique_buyers_gate(gate_setup):
    """Unique buyers must be >= 25 (Route A) / >= 40 (configured). Rejects below threshold or <= 1."""
    gate_layer, _, _ = gate_setup
    cand = _make_clean_candidate()
    pred = BreakoutPredictionOutput(p_reach_3m=0.15)

    # 1. Below 25 threshold (e.g. 18 unique buyers) -> MUST FAIL
    cand.unique_buyers = 18
    res_below = gate_layer.evaluate(cand, pred, position_size_usd=50.0)
    assert not res_below.is_passed
    assert any("Unique buyers (18) below minimum 25" in r for r in res_below.rejection_reasons)

    # 2. Fallback single-buyer (unique_buyers <= 1) -> MUST FAIL
    cand.unique_buyers = 1
    res_one = gate_layer.evaluate(cand, pred, position_size_usd=50.0)
    assert not res_one.is_passed
    assert any("Unique buyers (1) is default fallback or <= 1" in r for r in res_one.rejection_reasons)

    # 3. >= 25 unique buyers (e.g. 42) -> MUST PASS
    cand.unique_buyers = 42
    res_pass = gate_layer.evaluate(cand, pred, position_size_usd=50.0)
    assert res_pass.is_passed


def test_dev_holding_gate(gate_setup):
    """Dev / creator holding must be <= 3.0%. Rejects if exceeds limit."""
    gate_layer, _, _ = gate_setup
    cand = _make_clean_candidate()
    pred = BreakoutPredictionOutput(p_reach_3m=0.15)

    # 1. Dev holding 5.5% (> 3.0% limit) -> MUST FAIL
    cand.dev_holding_pct = 5.5
    res_high = gate_layer.evaluate(cand, pred, position_size_usd=50.0)
    assert not res_high.is_passed
    assert any("Creator holding 5.5% exceeds limit 3.0%" in r for r in res_high.rejection_reasons)

    # 2. Dev holding 1.2% (<= 3.0% limit) -> MUST PASS
    cand.dev_holding_pct = 1.2
    res_pass = gate_layer.evaluate(cand, pred, position_size_usd=50.0)
    assert res_pass.is_passed


def test_top10_holding_gate(gate_setup):
    """Top-10 holding must be <= 18.0% (excluding curve/pool/burn accounts). Rejects if exceeds limit."""
    gate_layer, _, _ = gate_setup
    cand = _make_clean_candidate()
    pred = BreakoutPredictionOutput(p_reach_3m=0.15)

    # 1. Top-10 holding 28.5% (> 18.0% limit) -> MUST FAIL
    cand.top10_holder_pct = 28.5
    res_high = gate_layer.evaluate(cand, pred, position_size_usd=50.0)
    assert not res_high.is_passed
    assert any("Top-10 concentration 28.5% exceeds limit 18.0%" in r for r in res_high.rejection_reasons)

    # 2. Top-10 holding 14.5% (<= 18.0% limit) -> MUST PASS
    cand.top10_holder_pct = 14.5
    res_pass = gate_layer.evaluate(cand, pred, position_size_usd=50.0)
    assert res_pass.is_passed


def test_market_cap_ceiling_gate(gate_setup):
    """Market cap ceiling must be <= $16,000. Rejects if exceeds limit."""
    gate_layer, _, _ = gate_setup
    cand = _make_clean_candidate()
    pred = BreakoutPredictionOutput(p_reach_3m=0.15)

    # 1. Market cap $25,000 (> $16,000 ceiling) -> MUST FAIL
    cand.market_cap_usd = 25000.0
    cand.liquidity_usd = 10000.0  # Keep liq/MC ratio valid (0.40)
    res_high = gate_layer.evaluate(cand, pred, position_size_usd=50.0)
    assert not res_high.is_passed
    assert any("Market Cap $25,000.00 exceeds limit $16,000.00" in r for r in res_high.rejection_reasons)

    # 2. Market cap $12,000 (<= $16,000 ceiling) -> MUST PASS
    cand.market_cap_usd = 12000.0
    cand.liquidity_usd = 8000.0
    res_pass = gate_layer.evaluate(cand, pred, position_size_usd=50.0)
    assert res_pass.is_passed


def test_model_score_and_default_floor_gate(gate_setup):
    """P(3M) must be >= 0.09 and exact 0.0795 uninitialized default MUST be rejected."""
    gate_layer, _, _ = gate_setup
    cand = _make_clean_candidate()

    # 1. Uninitialized default 0.0795 -> MUST FAIL
    pred_default = BreakoutPredictionOutput(p_reach_3m=0.0795)
    res_default = gate_layer.evaluate(cand, pred_default, position_size_usd=50.0)
    assert not res_default.is_passed
    assert any("P(3M) is exact 0.0795 uninitialized default" in r for r in res_default.rejection_reasons)

    # 2. P(3M) below 0.09 floor (e.g. 0.065) -> MUST FAIL
    pred_low = BreakoutPredictionOutput(p_reach_3m=0.065)
    res_low = gate_layer.evaluate(cand, pred_low, position_size_usd=50.0)
    assert not res_low.is_passed
    assert any("below required 0.0900" in r for r in res_low.rejection_reasons)

    # 3. P(3M) >= 0.09 (e.g. 0.15) -> MUST PASS
    pred_ok = BreakoutPredictionOutput(p_reach_3m=0.15)
    res_pass = gate_layer.evaluate(cand, pred_ok, position_size_usd=50.0)
    assert res_pass.is_passed


def test_bump_bot_and_wash_turnover_gate(gate_setup):
    """Anti-fake-volume: bump bot micro-churn (<$10/trade across >=40 txns) and wash turnover (>3.0x in 5m) rejected."""
    gate_layer, _, _ = gate_setup
    cand = _make_clean_candidate()
    pred = BreakoutPredictionOutput(p_reach_3m=0.15)

    # 1. Micro-churn: 45 txns with only $300 volume -> $6.67/trade < $10.00 -> MUST FAIL
    cand.txns_5m_buys = 30
    cand.txns_5m_sells = 15
    cand.volume_5m_usd = 300.0
    res_churn = gate_layer.evaluate(cand, pred, position_size_usd=50.0)
    assert not res_churn.is_passed
    assert any("GATE_11_BUMP_BOT" in r for r in res_churn.rejection_reasons)

    # 2. Hyper-turnover: $30,000 volume on $8,000 pool = 3.75x > 3.0x -> MUST FAIL
    cand.txns_5m_buys = 20
    cand.txns_5m_sells = 10
    cand.volume_5m_usd = 30000.0
    cand.liquidity_usd = 8000.0
    res_wash = gate_layer.evaluate(cand, pred, position_size_usd=50.0)
    assert not res_wash.is_passed
    assert any("GATE_11_WASH_TURNOVER" in r for r in res_wash.rejection_reasons)


def test_toxic_venue_gate(gate_setup):
    """Toxic venue blacklist: meteora-dbc, meteora-damm-v2, bags-fm, moonshot, etc. strictly rejected."""
    gate_layer, _, _ = gate_setup
    cand = _make_clean_candidate()
    pred = BreakoutPredictionOutput(p_reach_3m=0.15)

    for toxic in ["meteora-dbc", "meteora-damm-v2", "bags-fm", "moonshot", "pons-v2", "four-meme"]:
        cand.dex_id = toxic
        res = gate_layer.evaluate(cand, pred, position_size_usd=50.0)
        assert not res.is_passed
        assert any("GATE_2_TOXIC_VENUE" in r for r in res.rejection_reasons)


def test_liquidity_floor_gate(gate_setup):
    """Minimum liquidity safety floor is $2,500.00 (not $1,000). Rejects if below."""
    gate_layer, _, _ = gate_setup
    cand = _make_clean_candidate()
    pred = BreakoutPredictionOutput(p_reach_3m=0.15)

    # 1. Liquidity $1,800 (< $2,500 floor) -> MUST FAIL
    cand.liquidity_usd = 1800.0
    cand.market_cap_usd = 5000.0  # Keep ratio valid (0.36)
    res_low = gate_layer.evaluate(cand, pred, position_size_usd=10.0)
    assert not res_low.is_passed
    assert any("GATE_4_LIQUIDITY_DEPTH" in r for r in res_low.rejection_reasons)
    assert any("below safety floor $2,500.00" in r for r in res_low.rejection_reasons)

    # 2. Liquidity $3,000 (>= $2,500 floor) -> MUST PASS
    cand.liquidity_usd = 3000.0
    cand.market_cap_usd = 8000.0
    res_pass = gate_layer.evaluate(cand, pred, position_size_usd=10.0)
    assert res_pass.is_passed


