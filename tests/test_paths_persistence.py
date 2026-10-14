import os
from pathlib import Path
import sqlite3
import pytest

from src.utils.paths import get_data_dir, get_project_root, get_backups_dir, ensure_data_persistence


def test_paths_resolution():
    root = get_project_root()
    assert (root / "src").is_dir()
    
    data_dir = get_data_dir()
    assert data_dir.is_dir()
    assert (data_dir / "paper_trading.db").exists()
    
    backups_dir = get_backups_dir()
    assert backups_dir.is_dir()


def test_data_persistence_invariants():
    """
    Enforces real schema and migration invariants for the fresh epoch v2.0.0 ledger:
    1. Database file exists and connects cleanly.
    2. All mandatory tables exist (paper_trades, trade_event_log, trade_quarantine, shadow_trade_ledger).
    3. Mandatory Phase 0/1 columns and default values exist in paper_trades.
    4. Required performance indices exist.
    5. Clean epoch reset invariant: newly initialized ledger is strictly segregated from archive.
    """
    data_dir = get_data_dir()
    paper_db = data_dir / "paper_trading.db"
    assert paper_db.exists()

    with sqlite3.connect(paper_db) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # 1. Mandatory Tables
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row["name"] for row in cur.fetchall()}
        required_tables = {"paper_trades", "trade_event_log", "trade_quarantine", "shadow_trade_ledger"}
        missing_tables = required_tables - tables
        assert not missing_tables, f"Missing required database tables: {missing_tables}"

        # 2. Mandatory Columns in paper_trades
        cur.execute("PRAGMA table_info(paper_trades)")
        columns = {row["name"]: row for row in cur.fetchall()}
        required_columns = [
            "trade_id", "schema_version", "ledger_epoch", "route", "config_hash", "git_commit",
            "token_address", "symbol", "chain", "venue", "status", "entry_venue", "entry_slot",
            "entry_block_time", "entry_tokens_received", "entry_effective_sol_usd",
            "entry_priority_fee_sol", "entry_pool_sol_reserves_before", "entry_pool_sol_reserves_after",
            "entry_pool_token_reserves_before", "entry_pool_token_reserves_after", "simulated_fill_price_usd",
            "entry_price_impact_pct", "exit_venue", "exit_slot", "exit_block_time", "exit_tokens_sold",
            "exit_gross_proceeds_usd", "exit_net_proceeds_usd", "exit_effective_sol_usd",
            "exit_priority_fee_sol", "net_realized_pnl_usd", "net_realized_return_pct",
            "mfe_ratio", "mae_ratio", "target_reached_3m", "outcome_label"
        ]
        missing_columns = [c for c in required_columns if c not in columns]
        assert not missing_columns, f"Missing required schema columns in paper_trades: {missing_columns}"

        # 3. Default Values & Column Types
        assert "v2.0.0" in str(columns["schema_version"]["dflt_value"])
        assert "epoch_20261014" in str(columns["ledger_epoch"]["dflt_value"])
        assert "ROUTE_A" in str(columns["route"]["dflt_value"])

        # 4. Mandatory Indices
        cur.execute("SELECT name FROM sqlite_master WHERE type='index'")
        indices = {row["name"] for row in cur.fetchall()}
        required_indices = {"idx_paper_status", "idx_paper_token", "idx_shadow_token", "idx_paper_route", "idx_paper_epoch"}
        missing_indices = required_indices - indices
        assert not missing_indices, f"Missing required database indices: {missing_indices}"

        # 5. Clean epoch reset invariant: fresh ledger starts empty
        trade_count = cur.execute("SELECT COUNT(*) FROM paper_trades").fetchone()[0]
        assert trade_count == 0, f"Expected 0 trades in fresh epoch ledger, found {trade_count}"
