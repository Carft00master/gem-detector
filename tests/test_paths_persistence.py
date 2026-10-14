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
        table_exists = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='paper_trades'").fetchone()
        assert table_exists is not None
        count = conn.execute("SELECT COUNT(*) FROM paper_trades").fetchone()[0]
        assert count >= 0
