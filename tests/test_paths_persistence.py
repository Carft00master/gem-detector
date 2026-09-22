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
    data_dir = get_data_dir()
    paper_db = data_dir / "paper_trading.db"
    assert paper_db.exists()

    with sqlite3.connect(paper_db) as conn:
        count = conn.execute("SELECT COUNT(*) FROM paper_trades").fetchone()[0]
        # Invariant: Never lose trades
        assert count >= 1498, f"Expected at least 1498 trades, found {count}"

        # Verify 3M milestone winners are present
        t3m_count = conn.execute("SELECT COUNT(*) FROM paper_trades WHERE target_reached_3m = 1").fetchone()[0]
        assert t3m_count >= 50, f"Expected at least 50 3M winners, found {t3m_count}"
