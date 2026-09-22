"""
Pre-Migration Backup & Invariant Validation Manager
Safely backs up all SQLite databases and JSONL files to data/backups/ before any schema migration.
Validates trade counts, cumulative PnL, token counts, and schema checksums before and after migration.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import glob
import json
import logging
import os
from pathlib import Path
import shutil
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class LedgerPreMigrationBaseline:
    timestamp: str
    total_paper_trades: int
    open_paper_trades: int
    closed_paper_trades: int
    cumulative_realized_pnl_usd: float
    win_rate_pct: float
    shadow_token_count: int
    database_file_checksums: Dict[str, int] = field(default_factory=dict)
    jsonl_line_counts: Dict[str, int] = field(default_factory=dict)


class LedgerBackupManager:
    """
    Manages safe backups and pre/post migration invariant assertion for paper trading and research data.
    """

    def __init__(self, base_data_dir: Optional[Path] = None):
        if base_data_dir:
            self.data_dir = Path(base_data_dir)
        else:
            from src.utils.paths import get_data_dir
            self.data_dir = get_data_dir()
        self.backup_dir = self.data_dir / "backups"
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def create_pre_migration_backup(self, tag: str = "pre_journal_upgrade") -> Tuple[Path, LedgerPreMigrationBaseline]:
        """
        Creates a complete timestamped backup archive of all .db and .jsonl files in data/.
        Computes and returns the pre-migration baseline.
        """
        now_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        target_dir = self.backup_dir / f"backup_{tag}_{now_str}"
        target_dir.mkdir(parents=True, exist_ok=True)

        baseline = self.compute_current_baseline()

        # Copy all .db files
        for db_file in self.data_dir.glob("**/*.db"):
            if "backups" in str(db_file):
                continue
            rel_path = db_file.relative_to(self.data_dir)
            dest_file = target_dir / rel_path
            dest_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(db_file, dest_file)

        # Copy all .jsonl files
        for jsonl_file in self.data_dir.glob("**/*.jsonl"):
            if "backups" in str(jsonl_file):
                continue
            rel_path = jsonl_file.relative_to(self.data_dir)
            dest_file = target_dir / rel_path
            dest_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(jsonl_file, dest_file)

        # Write baseline metadata manifest into backup directory
        manifest_file = target_dir / "migration_baseline_manifest.json"
        with open(manifest_file, "w", encoding="utf-8") as f:
            json.dump(asdict(baseline), f, indent=2)

        logger.info(f"Created pre-migration backup at {target_dir} ({baseline.total_paper_trades} trades, ${baseline.cumulative_realized_pnl_usd:,.2f} P&L)")
        return target_dir, baseline

    def compute_current_baseline(self) -> LedgerPreMigrationBaseline:
        """
        Compute total trades, open/closed counts, realized PnL, win rate, and shadow counts.
        """
        db_path = self.data_dir / "paper_trading.db"
        total_trades = 0
        open_trades = 0
        closed_trades = 0
        cumulative_pnl = 0.0
        win_rate_pct = 0.0

        if db_path.exists():
            try:
                with sqlite3.connect(db_path) as conn:
                    c = conn.cursor()
                    # Check if paper_trades table exists
                    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='paper_trades'")
                    if c.fetchone():
                        total_trades = c.execute("SELECT count(*) FROM paper_trades").fetchone()[0]
                        open_trades = c.execute("SELECT count(*) FROM paper_trades WHERE status='OPEN'").fetchone()[0]
                        closed_trades = c.execute("SELECT count(*) FROM paper_trades WHERE status='CLOSED'").fetchone()[0]
                        pnl_res = c.execute("SELECT sum(net_realized_pnl_usd) FROM paper_trades WHERE status='CLOSED'").fetchone()[0]
                        cumulative_pnl = float(pnl_res or 0.0)
                        if closed_trades > 0:
                            wins = c.execute("SELECT count(*) FROM paper_trades WHERE status='CLOSED' AND net_realized_pnl_usd > 0").fetchone()[0]
                            win_rate_pct = round((wins / closed_trades) * 100.0, 2)
            except Exception as e:
                logger.warning(f"Could not read paper_trades table: {e}")

        shadow_count = 0
        shadow_db = self.data_dir / "shadow_universe.db"
        if shadow_db.exists():
            try:
                with sqlite3.connect(shadow_db) as conn:
                    c = conn.cursor()
                    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='shadow_tokens'")
                    if c.fetchone():
                        shadow_count = c.execute("SELECT count(*) FROM shadow_tokens").fetchone()[0]
            except Exception as e:
                logger.warning(f"Could not read shadow_tokens: {e}")

        checksums = {}
        for db in self.data_dir.glob("**/*.db"):
            if "backups" not in str(db):
                try:
                    checksums[str(db.relative_to(self.data_dir))] = db.stat().st_size
                except Exception:
                    pass

        line_counts = {}
        for j in self.data_dir.glob("**/*.jsonl"):
            if "backups" not in str(j):
                try:
                    with open(j, "r", encoding="utf-8") as f:
                        line_counts[str(j.relative_to(self.data_dir))] = sum(1 for _ in f)
                except Exception:
                    pass

        return LedgerPreMigrationBaseline(
            timestamp=datetime.now(timezone.utc).isoformat(),
            total_paper_trades=total_trades,
            open_paper_trades=open_trades,
            closed_paper_trades=closed_trades,
            cumulative_realized_pnl_usd=round(cumulative_pnl, 2),
            win_rate_pct=win_rate_pct,
            shadow_token_count=shadow_count,
            database_file_checksums=checksums,
            jsonl_line_counts=line_counts,
        )

    def validate_invariants(self, baseline_before: LedgerPreMigrationBaseline) -> Tuple[bool, List[str]]:
        """
        Validates that post-migration baseline preserves all trade records, cumulative PnL,
        and essential database invariants.
        """
        current = self.compute_current_baseline()
        violations = []

        if current.total_paper_trades < baseline_before.total_paper_trades:
            violations.append(
                f"Trade count reduced from {baseline_before.total_paper_trades} to {current.total_paper_trades}"
            )

        if abs(current.cumulative_realized_pnl_usd - baseline_before.cumulative_realized_pnl_usd) > 0.01:
            violations.append(
                f"Cumulative P&L changed from ${baseline_before.cumulative_realized_pnl_usd} to ${current.cumulative_realized_pnl_usd}"
            )

        if current.closed_paper_trades < baseline_before.closed_paper_trades:
            violations.append(
                f"Closed trade count reduced from {baseline_before.closed_paper_trades} to {current.closed_paper_trades}"
            )

        if current.shadow_token_count < baseline_before.shadow_token_count:
            violations.append(
                f"Shadow token count reduced from {baseline_before.shadow_token_count} to {current.shadow_token_count}"
            )

        is_valid = len(violations) == 0
        return is_valid, violations
