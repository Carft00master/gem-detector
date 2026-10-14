"""
Shadow Ledger & Per-Event Price Path Recording Engine (Phase 1f)
1. Maintains a forensic Shadow Ledger: every candidate rejected by the bot gets its counterfactual forward outcome
   labeled from on-chain reserves to continuously evaluate selection false negatives.
2. Records granular per-event price paths for every open position for offline exit backtesting.
"""

from dataclasses import asdict
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional

from src.paper.ledger import ShadowTradeRecord, PaperTradingLedger
from src.utils.paths import get_data_dir

logger = logging.getLogger(__name__)


class ShadowLedgerManager:
    """
    Manages counterfactual tracking for all rejected token setups and
    fine-grained tick price paths for active trades.
    """
    def __init__(self, ledger: Optional[PaperTradingLedger] = None, db_path: Optional[Path] = None):
        self.ledger = ledger or PaperTradingLedger()
        self.data_dir = get_data_dir()
        ledger_db = getattr(self.ledger, "db_path", None)
        if isinstance(ledger_db, (str, Path)):
            self.db_path = db_path or Path(ledger_db)
        else:
            self.db_path = db_path or (self.data_dir / "paper_trading.db")
        self._init_path_table()

    def _init_path_table(self) -> None:
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS position_price_paths (
                    path_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trade_id TEXT NOT NULL,
                    token_address TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    slot INTEGER NOT NULL,
                    price_usd REAL NOT NULL,
                    market_cap_usd REAL NOT NULL,
                    sol_reserves REAL NOT NULL,
                    token_reserves REAL NOT NULL,
                    venue TEXT NOT NULL
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_path_trade ON position_price_paths(trade_id, slot)")
            conn.commit()

    def record_rejected_candidate(
        self,
        token_address: str,
        symbol: str,
        rejection_reason: str,
        failed_gates: List[str],
        market_cap_usd: float,
        liquidity_usd: float,
        p_reach_3m: float,
        chain: str = "solana",
    ) -> ShadowTradeRecord:
        """
        Record a rejected candidate in the shadow universe for forward counterfactual tracking.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        import uuid
        rec = ShadowTradeRecord(
            shadow_id=f"shd_{str(uuid.uuid4())[:12]}",
            token_address=token_address,
            symbol=symbol,
            chain=chain,
            rejection_reason=rejection_reason,
            failed_gates_json=json.dumps(failed_gates),
            rejection_timestamp=now_iso,
            market_cap_at_rejection=market_cap_usd,
            liquidity_at_rejection=liquidity_usd,
            p_reach_3m_at_rejection=p_reach_3m,
            max_future_mc_usd=market_cap_usd,
            target_reached_3m=False,
            outcome_label="REJECTED",
        )
        self.ledger.record_shadow_candidate(rec)
        logger.info(f"Shadow Ledger: Recorded rejected candidate {symbol} ({token_address}) - {rejection_reason}")
        return rec

    def get_rejected_candidates(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Retrieve recent rejected candidates from the shadow ledger."""
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("SELECT * FROM shadow_trade_ledger ORDER BY rejection_timestamp DESC LIMIT ?", (limit,))
            return [dict(r) for r in cur.fetchall()]

    def record_position_tick(
        self,
        trade_id: str,
        token_address: str,
        slot: int,
        price_usd: float,
        market_cap_usd: float,
        sol_reserves: float,
        token_reserves: float,
        venue: str,
        timestamp: Optional[str] = None,
    ) -> None:
        """Record a granular price point in the position's price path."""
        ts = timestamp or datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO position_price_paths (
                    trade_id, token_address, timestamp, slot, price_usd,
                    market_cap_usd, sol_reserves, token_reserves, venue
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                trade_id, token_address, ts, slot, price_usd,
                market_cap_usd, sol_reserves, token_reserves, venue
            ))
            conn.commit()

    def get_price_path(self, trade_id: str) -> List[Dict[str, Any]]:
        """Fetch the full recorded price path for an open or closed trade."""
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM position_price_paths WHERE trade_id = ? ORDER BY slot ASC, timestamp ASC",
                (trade_id,)
            )
            return [dict(r) for r in cur.fetchall()]

    def update_rejected_candidate_progress(self, token_address: str, current_market_cap_usd: float) -> None:
        """Update counterfactual outcome for a rejected token upon observing new market cap."""
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT shadow_id, max_future_mc_usd, target_reached_3m FROM shadow_trade_ledger WHERE token_address = ?",
                (token_address,)
            )
            rows = cur.fetchall()
            for shadow_id, max_mc, reached in rows:
                new_max = max(max_mc or 0.0, current_market_cap_usd)
                new_reached = reached or (1 if new_max >= 3_000_000.0 else 0)
                outcome = "FALSE_NEGATIVE_RUNNER" if new_reached else ("REJECTED_EXPANDED" if new_max > (max_mc or 0.0) * 2.0 else "REJECTED")
                cur.execute(
                    "UPDATE shadow_trade_ledger SET max_future_mc_usd = ?, target_reached_3m = ?, outcome_label = ? WHERE shadow_id = ?",
                    (new_max, new_reached, outcome, shadow_id)
                )
            conn.commit()
