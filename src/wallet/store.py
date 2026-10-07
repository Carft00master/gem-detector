"""
SQLite Storage Engine for Virtual Wallet (virtual_wallet.db).
Guarantees strict isolation from paper_trading.db, WAL-mode concurrency,
and persistent ledger history.
"""

import sqlite3
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone

from src.utils.paths import get_data_dir
from src.wallet.models import (
    WalletSessionRecord,
    WalletPositionRecord,
    WalletLedgerRecord,
    WalletEquitySnapshotRecord,
)

logger = logging.getLogger(__name__)


class WalletStore:
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or (get_data_dir() / "virtual_wallet.db")
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
        except Exception:
            pass
        conn.execute("PRAGMA busy_timeout=30000;")
        return conn

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._get_connection() as conn:
            cur = conn.cursor()

            # 1. Sessions Table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS wallet_sessions (
                    session_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    starting_capital_usd REAL NOT NULL,
                    risk_pct REAL NOT NULL,
                    sizing_mode TEXT NOT NULL,
                    current_cash_usd REAL NOT NULL,
                    current_equity_usd REAL NOT NULL,
                    peak_equity_usd REAL NOT NULL,
                    max_drawdown_pct REAL NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    notes TEXT
                )
            """)

            # 2. Positions Table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS wallet_positions (
                    position_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    paper_trade_id TEXT NOT NULL,
                    token_address TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    chain TEXT NOT NULL,
                    venue TEXT NOT NULL,
                    position_size_usd REAL NOT NULL,
                    entry_price_usd REAL NOT NULL,
                    simulated_fill_price_usd REAL NOT NULL,
                    entry_market_cap_usd REAL NOT NULL,
                    entry_liquidity_usd REAL NOT NULL,
                    entry_timestamp TEXT NOT NULL,
                    entry_price_impact_pct REAL DEFAULT 0.0,
                    entry_fees_usd REAL DEFAULT 0.0,
                    status TEXT NOT NULL,
                    skip_reason TEXT,
                    exit_price_usd REAL,
                    exit_market_cap_usd REAL,
                    exit_liquidity_usd REAL,
                    exit_timestamp TEXT,
                    exit_reason TEXT,
                    exit_price_impact_pct REAL DEFAULT 0.0,
                    exit_fees_usd REAL DEFAULT 0.0,
                    gross_exit_proceeds_usd REAL DEFAULT 0.0,
                    net_realized_pnl_usd REAL DEFAULT 0.0,
                    net_realized_return_pct REAL DEFAULT 0.0,
                    hold_duration_seconds REAL DEFAULT 0.0,
                    equity_before_usd REAL DEFAULT 1000.0,
                    equity_after_usd REAL DEFAULT 1000.0,
                    FOREIGN KEY (session_id) REFERENCES wallet_sessions(session_id)
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_wp_session ON wallet_positions(session_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_wp_paper_id ON wallet_positions(paper_trade_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_wp_status ON wallet_positions(status)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_wp_time ON wallet_positions(entry_timestamp)")

            # 3. Ledger Table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS wallet_ledger (
                    entry_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    entry_type TEXT NOT NULL,
                    amount_usd REAL NOT NULL,
                    cash_balance_after_usd REAL NOT NULL,
                    position_id TEXT,
                    notes TEXT,
                    FOREIGN KEY (session_id) REFERENCES wallet_sessions(session_id)
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_wl_session ON wallet_ledger(session_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_wl_time ON wallet_ledger(timestamp)")

            # 4. Snapshots Table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS wallet_equity_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    cash_balance_usd REAL NOT NULL,
                    deployed_capital_usd REAL NOT NULL,
                    mark_to_market_value_usd REAL NOT NULL,
                    total_equity_usd REAL NOT NULL,
                    open_positions_count INTEGER NOT NULL,
                    unrealized_pnl_usd REAL DEFAULT 0.0,
                    FOREIGN KEY (session_id) REFERENCES wallet_sessions(session_id)
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_ws_session_time ON wallet_equity_snapshots(session_id, timestamp)")
            conn.commit()

    # --- Session Management ---

    def get_or_create_default_session(
        self,
        starting_capital: float = 1000.0,
        risk_pct: float = 0.05,
        sizing_mode: str = "COMPOUNDING"
    ) -> WalletSessionRecord:
        """Fetch active session or bootstrap default $1,000 forward testing session."""
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM wallet_sessions WHERE is_active = 1 ORDER BY created_at DESC LIMIT 1")
            row = cur.fetchone()
            if row:
                return WalletSessionRecord(**dict(row))

            # Create default session
            import uuid
            sess_id = f"sess_{str(uuid.uuid4())[:8]}"
            now_iso = datetime.now(timezone.utc).isoformat()
            sess = WalletSessionRecord(
                session_id=sess_id,
                name="Live Forward Test ($1,000 @ 5%)",
                starting_capital_usd=starting_capital,
                risk_pct=risk_pct,
                sizing_mode=sizing_mode,
                current_cash_usd=starting_capital,
                current_equity_usd=starting_capital,
                peak_equity_usd=starting_capital,
                max_drawdown_pct=0.0,
                is_active=True,
                created_at=now_iso,
                updated_at=now_iso,
            )
            self.save_session(sess)

            # Record initial deposit in ledger
            dep_id = f"led_{str(uuid.uuid4())[:8]}"
            dep = WalletLedgerRecord(
                entry_id=dep_id,
                session_id=sess_id,
                timestamp=now_iso,
                entry_type="INITIAL_DEPOSIT",
                amount_usd=starting_capital,
                cash_balance_after_usd=starting_capital,
                notes=f"Initial virtual capital deposit: ${starting_capital:,.2f}"
            )
            self.record_ledger_entry(dep)
            return sess

    def get_session(self, session_id: str) -> Optional[WalletSessionRecord]:
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM wallet_sessions WHERE session_id = ?", (session_id,))
            row = cur.fetchone()
            return WalletSessionRecord(**dict(row)) if row else None

    def list_sessions(self) -> List[WalletSessionRecord]:
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM wallet_sessions ORDER BY created_at DESC")
            return [WalletSessionRecord(**dict(r)) for r in cur.fetchall()]

    def save_session(self, sess: WalletSessionRecord) -> None:
        sess.updated_at = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO wallet_sessions (
                    session_id, name, starting_capital_usd, risk_pct, sizing_mode,
                    current_cash_usd, current_equity_usd, peak_equity_usd,
                    max_drawdown_pct, is_active, created_at, updated_at, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    name = excluded.name,
                    starting_capital_usd = excluded.starting_capital_usd,
                    risk_pct = excluded.risk_pct,
                    sizing_mode = excluded.sizing_mode,
                    current_cash_usd = excluded.current_cash_usd,
                    current_equity_usd = excluded.current_equity_usd,
                    peak_equity_usd = excluded.peak_equity_usd,
                    max_drawdown_pct = excluded.max_drawdown_pct,
                    is_active = excluded.is_active,
                    updated_at = excluded.updated_at,
                    notes = excluded.notes
            """, (
                sess.session_id, sess.name, sess.starting_capital_usd, sess.risk_pct,
                sess.sizing_mode, sess.current_cash_usd, sess.current_equity_usd,
                sess.peak_equity_usd, sess.max_drawdown_pct, 1 if sess.is_active else 0,
                sess.created_at, sess.updated_at, sess.notes
            ))
            conn.commit()

    # --- Position Management ---

    def create_position(self, pos: WalletPositionRecord) -> None:
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO wallet_positions (
                    position_id, session_id, paper_trade_id, token_address, symbol,
                    chain, venue, position_size_usd, entry_price_usd, simulated_fill_price_usd,
                    entry_market_cap_usd, entry_liquidity_usd, entry_timestamp,
                    entry_price_impact_pct, entry_fees_usd, status, skip_reason,
                    exit_price_usd, exit_market_cap_usd, exit_liquidity_usd, exit_timestamp,
                    exit_reason, exit_price_impact_pct, exit_fees_usd, gross_exit_proceeds_usd,
                    net_realized_pnl_usd, net_realized_return_pct, hold_duration_seconds,
                    equity_before_usd, equity_after_usd
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                pos.position_id, pos.session_id, pos.paper_trade_id, pos.token_address, pos.symbol,
                pos.chain, pos.venue, pos.position_size_usd, pos.entry_price_usd, pos.simulated_fill_price_usd,
                pos.entry_market_cap_usd, pos.entry_liquidity_usd, pos.entry_timestamp,
                pos.entry_price_impact_pct, pos.entry_fees_usd, pos.status, pos.skip_reason,
                pos.exit_price_usd, pos.exit_market_cap_usd, pos.exit_liquidity_usd, pos.exit_timestamp,
                pos.exit_reason, pos.exit_price_impact_pct, pos.exit_fees_usd, pos.gross_exit_proceeds_usd,
                pos.net_realized_pnl_usd, pos.net_realized_return_pct, pos.hold_duration_seconds,
                pos.equity_before_usd, pos.equity_after_usd
            ))
            conn.commit()

    def update_position(self, pos: WalletPositionRecord) -> None:
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                UPDATE wallet_positions SET
                    status = ?,
                    skip_reason = ?,
                    exit_price_usd = ?,
                    exit_market_cap_usd = ?,
                    exit_liquidity_usd = ?,
                    exit_timestamp = ?,
                    exit_reason = ?,
                    exit_price_impact_pct = ?,
                    exit_fees_usd = ?,
                    gross_exit_proceeds_usd = ?,
                    net_realized_pnl_usd = ?,
                    net_realized_return_pct = ?,
                    hold_duration_seconds = ?,
                    equity_before_usd = ?,
                    equity_after_usd = ?
                WHERE position_id = ?
            """, (
                pos.status, pos.skip_reason, pos.exit_price_usd, pos.exit_market_cap_usd,
                pos.exit_liquidity_usd, pos.exit_timestamp, pos.exit_reason,
                pos.exit_price_impact_pct, pos.exit_fees_usd, pos.gross_exit_proceeds_usd,
                pos.net_realized_pnl_usd, pos.net_realized_return_pct, pos.hold_duration_seconds,
                pos.equity_before_usd, pos.equity_after_usd, pos.position_id
            ))
            conn.commit()

    def get_open_positions(self, session_id: str) -> List[WalletPositionRecord]:
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM wallet_positions WHERE session_id = ? AND status = 'OPEN'", (session_id,))
            return [WalletPositionRecord(**dict(r)) for r in cur.fetchall()]

    def get_all_positions(self, session_id: str, limit: int = 2000) -> List[WalletPositionRecord]:
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM wallet_positions WHERE session_id = ? ORDER BY entry_timestamp DESC LIMIT ?",
                (session_id, limit)
            )
            return [WalletPositionRecord(**dict(r)) for r in cur.fetchall()]

    def get_position_by_paper_id(self, session_id: str, paper_trade_id: str) -> Optional[WalletPositionRecord]:
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM wallet_positions WHERE session_id = ? AND paper_trade_id = ? LIMIT 1",
                (session_id, paper_trade_id)
            )
            row = cur.fetchone()
            return WalletPositionRecord(**dict(row)) if row else None

    # --- Ledger & Snapshots ---

    def record_ledger_entry(self, entry: WalletLedgerRecord) -> None:
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO wallet_ledger (
                    entry_id, session_id, timestamp, entry_type, amount_usd,
                    cash_balance_after_usd, position_id, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                entry.entry_id, entry.session_id, entry.timestamp, entry.entry_type,
                entry.amount_usd, entry.cash_balance_after_usd, entry.position_id, entry.notes
            ))
            conn.commit()

    def get_ledger_entries(self, session_id: str, limit: int = 500) -> List[WalletLedgerRecord]:
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM wallet_ledger WHERE session_id = ? ORDER BY timestamp DESC LIMIT ?",
                (session_id, limit)
            )
            return [WalletLedgerRecord(**dict(r)) for r in cur.fetchall()]

    def record_snapshot(self, snap: WalletEquitySnapshotRecord) -> None:
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO wallet_equity_snapshots (
                    snapshot_id, session_id, timestamp, cash_balance_usd,
                    deployed_capital_usd, mark_to_market_value_usd, total_equity_usd,
                    open_positions_count, unrealized_pnl_usd
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                snap.snapshot_id, snap.session_id, snap.timestamp, snap.cash_balance_usd,
                snap.deployed_capital_usd, snap.mark_to_market_value_usd, snap.total_equity_usd,
                snap.open_positions_count, snap.unrealized_pnl_usd
            ))
            conn.commit()

    def get_snapshots(self, session_id: str, limit: int = 1000) -> List[WalletEquitySnapshotRecord]:
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM wallet_equity_snapshots WHERE session_id = ? ORDER BY timestamp ASC LIMIT ?",
                (session_id, limit)
            )
            return [WalletEquitySnapshotRecord(**dict(r)) for r in cur.fetchall()]
