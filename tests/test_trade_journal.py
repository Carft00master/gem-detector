"""
Tests for Immutable Trade Journal, Version Provenance & Trade Event Timeline.
"""

from datetime import datetime, timezone
import os
from pathlib import Path
import tempfile
import pytest

from src.paper.ledger import PaperTradingLedger, PaperTradeRecord, TradeEventRecord
from src.paper.backup import LedgerBackupManager
from src.version import (
    FROZEN_VERSION_MANIFEST,
    LEARNING_DATA_VERSION,
    SCANNER_VERSION,
    TRADE_LEDGER_SCHEMA_VERSION,
)


def test_immutable_trade_record_creation_and_version_provenance():
    """Verify PaperTradeRecord stores all required version and point-in-time snapshot fields."""
    trade = PaperTradeRecord(
        signal_id="sig_test_001",
        token_address="TokenAddr1111111111111111111111111111111",
        symbol="TEST",
        chain="solana",
        venue="pumpfun",
        timestamp=datetime.now(timezone.utc).isoformat(),
        market_cap_usd=12500.0,
        entry_market_cap_usd=12500.0,
        liquidity_usd=4500.0,
        p_reach_100k=0.75,
        p_reach_500k=0.45,
        p_reach_1m=0.25,
        p_reach_3m=0.12,
        p_rug=0.04,
        position_size_usd=250.0,
        entry_price_usd=0.0000125,
        simulated_fill_price_usd=0.0000126,
    )

    assert trade.scanner_version == SCANNER_VERSION
    assert trade.trade_ledger_schema_version == TRADE_LEDGER_SCHEMA_VERSION
    assert trade.p_reach_3m_at_entry == 0.12
    assert trade.rug_risk_at_entry == 0.04
    assert trade.entry_market_cap_usd == 12500.0
    assert trade.discovery_timestamp is not None


def test_trade_event_timeline_logging(tmp_path):
    """Verify chronological trade event persistence and query retrieval."""
    db_file = tmp_path / "paper_trading.db"
    jsonl_file = tmp_path / "paper_trades.jsonl"
    ledger = PaperTradingLedger(db_path=db_file, jsonl_path=jsonl_file)

    t_id = "trade_alpha_99"
    ev1 = TradeEventRecord(
        event_id="ev_01",
        trade_id=t_id,
        token_address="Token99",
        timestamp="2026-08-26T10:00:00Z",
        event_type="DISCOVERED",
        market_cap_usd=8000.0,
        liquidity_usd=3000.0,
        signal_state="WATCH",
    )
    ev2 = TradeEventRecord(
        event_id="ev_02",
        trade_id=t_id,
        token_address="Token99",
        timestamp="2026-08-26T10:05:00Z",
        event_type="PAPER_ENTRY",
        market_cap_usd=10500.0,
        liquidity_usd=4200.0,
        price_usd=0.000105,
        signal_state="PAPER_ENTRY",
        p_reach_3m=0.18,
    )
    ev3 = TradeEventRecord(
        event_id="ev_03",
        trade_id=t_id,
        token_address="Token99",
        timestamp="2026-08-26T10:45:00Z",
        event_type="EXIT",
        market_cap_usd=32000.0,
        liquidity_usd=9000.0,
        price_usd=0.000320,
        signal_state="EXIT",
        details={"net_realized_pnl_usd": 480.0},
    )

    ledger.record_trade_event(ev1)
    ledger.record_trade_event(ev2)
    ledger.record_trade_event(ev3)

    retrieved = ledger.load_trade_events(t_id)
    assert len(retrieved) == 3
    assert retrieved[0]["event_type"] == "DISCOVERED"
    assert retrieved[1]["event_type"] == "PAPER_ENTRY"
    assert retrieved[2]["event_type"] == "EXIT"
    assert retrieved[2]["details"]["net_realized_pnl_usd"] == 480.0


def test_backup_manager_invariant_preservation(tmp_path):
    """Verify LedgerBackupManager creates backup archive and detects zero data loss."""
    mgr = LedgerBackupManager(base_data_dir=tmp_path)
    # Create test SQLite db
    db_file = tmp_path / "paper_trading.db"
    ledger = PaperTradingLedger(db_path=db_file, jsonl_path=tmp_path / "paper_trades.jsonl")

    trade = PaperTradeRecord(
        signal_id="sig_bak_1",
        token_address="AddrBak",
        symbol="BAK",
        chain="solana",
        venue="pumpfun",
        timestamp=datetime.now(timezone.utc).isoformat(),
        market_cap_usd=10000.0,
        entry_market_cap_usd=10000.0,
        liquidity_usd=5000.0,
        position_size_usd=250.0,
    )
    ledger.record_entry(trade)

    bak_path, baseline = mgr.create_pre_migration_backup("test_backup")
    assert bak_path.exists()
    assert baseline.total_paper_trades == 1

    is_valid, violations = mgr.validate_invariants(baseline)
    assert is_valid is True
    assert len(violations) == 0
