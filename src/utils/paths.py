"""
Unified filesystem path resolution and data persistence manager.
Ensures trade records, events, models, and telemetry are permanently preserved across:
- Application starts, exits, and restarts
- Incremental code edits and bug fixes
- PyInstaller standalone executable builds and updates
"""

import logging
import os
from pathlib import Path
import shutil
import sqlite3
import sys
from typing import Optional

logger = logging.getLogger(__name__)


def get_project_root() -> Path:
    """Return the root workspace directory."""
    if getattr(sys, "frozen", False):
        exe_path = Path(sys.executable).resolve()
        # If running in dist/MemecoinScanner/MemecoinScanner.exe inside repo workspace:
        candidate_repo_root = exe_path.parent.parent.parent
        if (candidate_repo_root / "src").is_dir() and (candidate_repo_root / "data").is_dir():
            return candidate_repo_root
        return exe_path.parent

    # When running as normal python module:
    return Path(__file__).resolve().parent.parent.parent


def get_data_dir() -> Path:
    """
    Get the permanent data directory.
    Priority order:
    1. Explicit environment variable: GEM_DETECTOR_DATA_DIR
    2. If running within repository workspace (dev mode or dist/ exe running in repo):
       <workspace>/data
    3. If running frozen standalone outside repository:
       <exe_dir>/data  (permanent folder adjacent to the executable, NEVER inside ephemeral _internal)
    4. Fallback: <workspace_or_cwd>/data
    """
    env_dir = os.environ.get("GEM_DETECTOR_DATA_DIR")
    if env_dir:
        p = Path(env_dir).resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p

    if getattr(sys, "frozen", False):
        exe_path = Path(sys.executable).resolve()
        # Check if running within repository workspace
        candidate_repo = exe_path.parent.parent.parent
        if (candidate_repo / "src").is_dir() and (candidate_repo / "data").is_dir():
            repo_data = candidate_repo / "data"
            repo_data.mkdir(parents=True, exist_ok=True)
            return repo_data

        # Running standalone outside repo: data directory sits right next to .exe
        exe_data = exe_path.parent / "data"
        exe_data.mkdir(parents=True, exist_ok=True)
        return exe_data

    # Development / source mode
    root = get_project_root()
    data_dir = root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def get_backups_dir() -> Path:
    """Return the permanent backups directory under data/backups."""
    b_dir = get_data_dir() / "backups"
    b_dir.mkdir(parents=True, exist_ok=True)
    return b_dir


def ensure_data_persistence() -> None:
    """
    Safety synchronization hook. Checks if higher-count trade data exists in any legacy
    or bundled directory (e.g. dist/MemecoinScanner/_internal/data) and preserves it to the
    active data directory.
    """
    target_data = get_data_dir()
    target_paper_db = target_data / "paper_trading.db"

    # Search known alternative paths
    root = get_project_root()
    candidate_paths = [
        root / "dist" / "MemecoinScanner" / "_internal" / "data",
        root / "dist" / "MemecoinScanner" / "data",
    ]

    for cand in candidate_paths:
        cand_paper_db = cand / "paper_trading.db"
        if cand_paper_db.exists() and cand_paper_db.resolve() != target_paper_db.resolve():
            try:
                target_cnt = 0
                if target_paper_db.exists():
                    conn_target = sqlite3.connect(target_paper_db)
                    try:
                        target_cnt = conn_target.execute("SELECT COUNT(*) FROM paper_trades").fetchone()[0]
                    finally:
                        conn_target.close()

                conn_cand = sqlite3.connect(cand_paper_db)
                try:
                    cand_cnt = conn_cand.execute("SELECT COUNT(*) FROM paper_trades").fetchone()[0]
                finally:
                    conn_cand.close()

                if cand_cnt > target_cnt:
                    logger.info(f"Syncing {cand_cnt} trades from {cand} to permanent {target_data}")
                    shutil.copy2(cand_paper_db, target_paper_db)
                    cand_jsonl = cand / "paper_trades.jsonl"
                    if cand_jsonl.exists():
                        shutil.copy2(cand_jsonl, target_data / "paper_trades.jsonl")
            except Exception as e:
                logger.warning(f"Data persistence sync warning for {cand}: {e}")
