"""
End-to-End Integration Tests for Phase 1 Shared Foundation:
Onchain Event Layer, Oracle, Fill Simulator, Venue FSM, Fail-Closed Data, and Invariants.
"""

import sqlite3
import pytest

from src.feeds.base_feed import TokenCandidate
from src.models.predictor import BreakoutPredictionOutput
from src.onchain.events import OnChainEvent, OnChainEventStore
from src.oracle.sol_usd import PythSolUsdOracle
from src.paper.engine import PaperTradingEngine
from src.paper.fail_closed_data import FailClosedDataValidator
from src.paper.fill_simulator import ExecutableFillSimulator
from src.paper.invariants import LedgerInvariantValidator
from src.paper.ledger import PaperTradingLedger
from src.paper.shadow_ledger import ShadowLedgerManager
from src.paper.venue_state_machine import VenueStateMachine, VenueState


@pytest.fixture
def integrated_engine(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    db_file = data_dir / "paper_trading.db"
    jsonl_file = data_dir / "paper_trades.jsonl"
    oracle_db = data_dir / "oracle_prices.db"
    event_db = data_dir / "onchain_events.db"

    ledger = PaperTradingLedger(db_path=db_file, jsonl_path=jsonl_file)
    oracle = PythSolUsdOracle(db_path=oracle_db)
    # Seed current oracle price
    current_time = 1791955000.0
    oracle.record_price(timestamp=current_time, price_usd=107.34)
    # Keep prices fresh across simulation test window
    for t_offset in range(1, 300, 5):
        oracle.record_price(timestamp=current_time + t_offset, price_usd=107.34)

    fill_sim = ExecutableFillSimulator(oracle=oracle)
    venue_fsm = VenueStateMachine()
    data_validator = FailClosedDataValidator(max_market_cap_usd=16000.0)
    invariant_validator = LedgerInvariantValidator(ledger=ledger)
    shadow_ledger = ShadowLedgerManager(ledger=ledger, db_path=db_file)
    event_store = OnChainEventStore(db_path=event_db)

    engine = PaperTradingEngine(
        ledger=ledger,
        oracle=oracle,
        fill_sim=fill_sim,
        venue_fsm=venue_fsm,
        data_validator=data_validator,
        invariant_validator=invariant_validator,
        shadow_ledger=shadow_ledger,
        event_store=event_store,
        enforce_fail_closed=True,
    )
    return engine, oracle, current_time, db_file


def test_valid_onchain_candidate_opens_simulated_trade_and_tracks_path(integrated_engine):
    engine, oracle, start_time, db_file = integrated_engine
    mint = "7EYnhQoR9YM3N7UoaKRoA44Uy8Jeaucs3DYVWo2Ppump"
    cand = TokenCandidate(
        address=mint,
        pair_address="Pair11111111111111111111111111111111111111",
        symbol="VALID",
        name="Valid Token",
        chain="solana",
        dex_id="pumpfun",
        market_cap_usd=12000.0,
        price_usd=0.000012,
        liquidity_usd=8000.0,
    )
    # Provide complete, valid features (no NaNs, no fallbacks)
    cand.volume_5m_usd = 2500.0
    cand.token_age_minutes = 15.0
    cand.unique_buyers = 38
    cand.buy_sell_ratio = 2.4
    cand.txns_5m_buys = 45
    cand.txns_5m_sells = 18
    cand.dev_holding_pct = 1.5
    cand.top10_holder_pct = 12.0

    pred = BreakoutPredictionOutput(p_reach_3m=0.15, alert_state="HIGH_CONVICTION")

    # Enter paper trade (size $75 is within 1% of $8000 liquidity)
    trade = engine.on_breakout_alert(
        candidate=cand,
        prediction=pred,
        position_size=75.0,
        block_time=start_time,
    )

    assert trade is not None
    assert trade.token_address == mint
    assert trade.status == "OPEN"
    assert trade.simulated_fill_price_usd > 0.0
    assert trade.entry_price_impact_pct >= 0.0
    assert mint in engine.active_positions

    # Send price tick (rally)
    engine.on_price_tick(
        token_address=mint,
        current_price_usd=0.000024,
        current_market_cap_usd=24000.0,
        current_liquidity_usd=12000.0,
        elapsed_minutes=5.0,
        slot=1001,
        block_time=start_time + 10.0,
    )

    # Verify tick was captured in position_price_paths (entry tick + rally tick)
    paths = engine.shadow_ledger.get_price_path(trade.trade_id)
    assert len(paths) >= 2
    assert paths[0]["price_usd"] == pytest.approx(trade.simulated_fill_price_usd)
    assert paths[1]["price_usd"] == pytest.approx(0.000024)
    assert paths[1]["token_address"] == mint


def test_missing_data_candidate_rejected_and_tracked_in_shadow_ledger(integrated_engine):
    engine, oracle, start_time, db_file = integrated_engine
    mint = "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM"
    cand = TokenCandidate(
        address=mint,
        pair_address="Pair22222222222222222222222222222222222222",
        symbol="SHADOW",
        name="Shadow Token",
        chain="solana",
        dex_id="pumpfun",
        market_cap_usd=10000.0,
        price_usd=0.000010,
        liquidity_usd=7000.0,
    )
    # Missing unique_buyers and using exact default P(3M) = 0.0795
    cand.unique_buyers = 1
    cand.buy_sell_ratio = 1.0
    pred = BreakoutPredictionOutput(p_reach_3m=0.0795, alert_state="EARLY_BREAKOUT")

    trade = engine.on_breakout_alert(candidate=cand, prediction=pred, position_size=100.0)
    assert trade is None # Rejected fail-closed

    # Verify candidate recorded in shadow_trade_ledger
    with sqlite3.connect(db_file) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM shadow_trade_ledger WHERE token_address = ?", (mint,))
        row = cur.fetchone()
        assert row is not None
        assert row["rejection_reason"] == "GATE_FAILURE"
        assert row["outcome_label"] == "REJECTED"

    # Now a later price tick arrives showing this token exploded to $3.5M
    engine.on_price_tick(
        token_address=mint,
        current_price_usd=0.0035,
        current_market_cap_usd=3_500_000.0,
        current_liquidity_usd=150_000.0,
        elapsed_minutes=60.0,
    )

    # Verify counterfactual outcome was updated to FALSE_NEGATIVE_RUNNER
    with sqlite3.connect(db_file) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM shadow_trade_ledger WHERE token_address = ?", (mint,))
        updated = cur.fetchone()
        assert updated["target_reached_3m"] == 1
        assert updated["max_future_mc_usd"] == 3_500_000.0
        assert updated["outcome_label"] == "FALSE_NEGATIVE_RUNNER"


def test_stale_curve_entry_post_migration_rejected_by_venue_fsm(integrated_engine):
    engine, oracle, start_time, db_file = integrated_engine
    mint = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

    # Mark token as graduated / migrated to pool in venue FSM
    engine.venue_fsm.on_curve_migration_detected(
        mint=mint,
        slot=1000,
        pool_address="PoolAddr111111111111111111111111111111111",
    )
    assert engine.venue_fsm.get_token_state(mint) == VenueState.MIGRATED

    # Incoming stale alert tries to enter bonding curve
    cand = TokenCandidate(
        address=mint,
        pair_address="Pair33333333333333333333333333333333333333",
        symbol="STALE",
        name="Stale Curve Token",
        chain="solana",
        dex_id="pumpfun", # Stale venue!
        market_cap_usd=14000.0,
        price_usd=0.000014,
        liquidity_usd=9000.0,
    )
    cand.unique_buyers = 40
    cand.buy_sell_ratio = 2.0
    cand.txns_5m_buys = 30
    pred = BreakoutPredictionOutput(p_reach_3m=0.15, alert_state="HIGH_CONVICTION")

    trade = engine.on_breakout_alert(candidate=cand, prediction=pred, position_size=100.0)
    assert trade is None

    # Verify recorded as venue mismatch in shadow ledger
    with sqlite3.connect(db_file) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM shadow_trade_ledger WHERE token_address = ?", (mint,))
        row = cur.fetchone()
        assert row is not None
        assert row["rejection_reason"] == "STALE_VENUE_MISMATCH"


def test_single_tx_curve_completion_defense(integrated_engine):
    engine, oracle, start_time, db_file = integrated_engine
    mint = "qTFyfJiSQhMooT6LzybsWHjMXSGWsdkY3w8C9aXpump" # NODF mint

    # Record in event store that curve was completed in a single tx of 85 SOL
    engine.event_store.record_event(OnChainEvent(
        event_type="CURVE_BUY",
        slot=456718840,
        block_time=int(start_time),
        signature="SigBuy85SOL",
        mint=mint,
        wallet="SniperWallet111",
        side="BUY",
        sol_amount=85.0,
        token_amount=800_000_000.0,
        sol_reserves_after=85.0,
        token_reserves_after=206_900_000.0,
        pool_address=None,
    ))

    cand = TokenCandidate(
        address=mint,
        pair_address="Pair44444444444444444444444444444444444444",
        symbol="NODF",
        name="NODF Calibration",
        chain="solana",
        dex_id="pumpfun",
        market_cap_usd=12000.0,
        price_usd=0.000012,
        liquidity_usd=8000.0,
    )
    cand.unique_buyers = 30
    cand.buy_sell_ratio = 2.0
    cand.txns_5m_buys = 20
    pred = BreakoutPredictionOutput(p_reach_3m=0.20, alert_state="HIGH_CONVICTION")

    trade = engine.on_breakout_alert(candidate=cand, prediction=pred, position_size=100.0)
    assert trade is None # Single-tx curve filler rejected
