"""
Unit tests for Ledger-Write Integrity Invariants & Trade Quarantine Engine (Phase 1e)
"""

import sqlite3
import pytest
from src.paper.invariants import LedgerInvariantValidator
from src.paper.ledger import PaperTradeRecord, PaperTradingLedger


@pytest.fixture
def ledger(tmp_path):
    db_file = tmp_path / "test_ledger.db"
    jsonl_file = tmp_path / "test_ledger.jsonl"
    return PaperTradingLedger(db_path=db_file, jsonl_path=jsonl_file)


@pytest.fixture
def validator(ledger):
    return LedgerInvariantValidator(ledger=ledger, max_hold_seconds=3600.0)


@pytest.fixture
def base_trade():
    return PaperTradeRecord(
        signal_id="sig_test_101",
        trade_id="tr_test_101",
        token_address="6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P",
        symbol="TEST",
        chain="solana",
        venue="pump_fun",
        timestamp="2026-10-14T10:00:00Z",
        entry_price_usd=0.001,
        simulated_fill_price_usd=0.001,
        position_size_usd=100.0,
        entry_market_cap_usd=10_000.0,
        entry_liquidity_usd=8_000.0,
        route="ROUTE_A",
        status="OPEN",
        hold_duration_seconds=600.0,
        exit_market_cap_usd=15_000.0,
        mfe_ratio=1.60,
        net_realized_pnl_usd=50.0,
        net_realized_return_pct=50.0,
        exit_net_proceeds_usd=150.0,
    )


def test_entry_duplicate_route_mint_rejected(validator, base_trade, ledger):
    active_positions = {"ROUTE_A:6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P": base_trade}
    valid, reason = validator.validate_entry(base_trade, active_positions=active_positions)
    assert not valid
    assert "Duplicate open position" in reason

    # Verify quarantine recorded
    with sqlite3.connect(ledger.db_path) as conn:
        cur = conn.cursor()
        cur.execute("SELECT quarantine_reason, token_address FROM trade_quarantine")
        rows = cur.fetchall()
        assert len(rows) == 1
        assert "Duplicate open position" in rows[0][0]


def test_entry_outside_executable_range_rejected(validator, base_trade, ledger):
    # Executable range in slot: [0.0012, 0.0015], but trade fill was 0.0010
    valid, reason = validator.validate_entry(
        base_trade,
        active_positions={},
        min_executable_price=0.0012,
        max_executable_price=0.0015,
    )
    assert not valid
    assert "outside executable slot range" in reason


def test_entry_non_positive_position_size_rejected(validator, base_trade):
    base_trade.position_size_usd = 0.0
    valid, reason = validator.validate_entry(base_trade, active_positions={})
    assert not valid
    assert "Non-positive position size" in reason


def test_entry_valid_passes(validator, base_trade, ledger):
    valid, reason = validator.validate_entry(
        base_trade,
        active_positions={},
        min_executable_price=0.00095,
        max_executable_price=0.00105,
    )
    assert valid
    assert reason is None

    # No quarantine entry
    with sqlite3.connect(ledger.db_path) as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM trade_quarantine")
        assert cur.fetchone()[0] == 0


def test_exit_exceeding_mfe_rejected(validator, base_trade, ledger):
    # Entry MC: 10,000, Exit MC: 25,000 => multiple = 2.5x, but MFE is only 1.6x
    base_trade.exit_market_cap_usd = 25_000.0
    base_trade.mfe_ratio = 1.60

    valid, reason = validator.validate_exit(base_trade)
    assert not valid
    assert "exceeds peak multiple / MFE ratio" in reason

    with sqlite3.connect(ledger.db_path) as conn:
        cur = conn.cursor()
        cur.execute("SELECT quarantine_reason FROM trade_quarantine")
        assert "exceeds peak multiple / MFE ratio" in cur.fetchone()[0]


def test_exit_exceeding_pool_sol_reserve_rejected(validator, base_trade, ledger):
    # Net proceeds: $150. Pool SOL reserve: 0.5 SOL @ $100/SOL = $50 pool value
    valid, reason = validator.validate_exit(
        base_trade,
        pool_sol_reserve=0.5,
        oracle_sol_usd=100.0,
    )
    assert not valid
    assert "exceed pool total SOL reserves" in reason


def test_exit_exceeding_max_hold_seconds_rejected(validator, base_trade):
    # Max hold is 3600s, trade held for 7200s
    base_trade.hold_duration_seconds = 7200.0
    valid, reason = validator.validate_exit(base_trade)
    assert not valid
    assert "exceeds maximum allowable hold" in reason


def test_exit_mismatched_return_pct_rejected(validator, base_trade):
    # Position size = 100, Net PnL = 50 => expected return % is 50.0%
    base_trade.net_realized_pnl_usd = 50.0
    base_trade.net_realized_return_pct = 95.0 # Fabricated / inconsistent

    valid, reason = validator.validate_exit(base_trade)
    assert not valid
    assert "Net return % (95.00%) does not match fill-derived PnL / Size (50.00%)" in reason


def test_exit_valid_passes(validator, base_trade, ledger):
    base_trade.exit_market_cap_usd = 15_000.0
    base_trade.mfe_ratio = 1.60
    base_trade.position_size_usd = 100.0
    base_trade.net_realized_pnl_usd = 50.0
    base_trade.net_realized_return_pct = 50.0
    base_trade.hold_duration_seconds = 600.0

    valid, reason = validator.validate_exit(
        base_trade,
        pool_sol_reserve=10.0, # 10 SOL @ $100 = $1000 pool value
        oracle_sol_usd=100.0,
    )
    assert valid
    assert reason is None
