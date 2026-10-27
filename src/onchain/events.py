"""
On-Chain Event Models & Audit Persistence Store (Phase 1a)
Captures and persists every pump.fun bonding curve event, migration, and pool swap.
Enforces accurate block-time, slot ordering, detection latency measurement,
and distinct buyer wallet derivation.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional, Tuple
import uuid

from src.utils.paths import get_data_dir

logger = logging.getLogger(__name__)


@dataclass
class OnChainEvent:
    event_type: str                        # "CURVE_CREATE" | "CURVE_BUY" | "CURVE_SELL" | "MIGRATION" | "POOL_CREATE" | "POOL_SWAP"
    slot: int
    block_time: int                        # Unix timestamp in seconds
    signature: str
    mint: str
    wallet: str
    event_id: str = field(default_factory=lambda: f"ocev_{str(uuid.uuid4())[:12]}")
    tx_index_in_slot: Optional[int] = None
    side: Optional[str] = None             # "BUY" | "SELL" | "CREATE" | "MIGRATE"
    sol_amount: float = 0.0
    token_amount: float = 0.0
    sol_reserves_after: float = 0.0
    token_reserves_after: float = 0.0
    pool_address: Optional[str] = None
    detection_source: str = "WEBSOCKET"    # "GRPC" | "WEBSOCKET" | "RPC"
    commitment: str = "processed"          # "processed" | "confirmed" | "finalized"
    received_at: float = field(default_factory=lambda: datetime.now(timezone.utc).timestamp())
    latency_ms: float = 0.0
    slot_delta: Optional[int] = None       # Slot lag: max(0, current_slot - slot)
    details: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        # Discard second-resolution block_time subtraction:
        # Subtracting 1-second integer block_time from float received_at creates quantization artifacts.
        # Slot-level timing (slot_delta) is used instead:
        if self.slot_delta is None and "current_slot" in self.details:
            try:
                curr = int(self.details["current_slot"])
                if curr >= self.slot:
                    self.slot_delta = curr - self.slot
            except (ValueError, TypeError):
                pass

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class OnChainEventStore:
    """
    SQLite persistence layer for all on-chain events.
    Enables forensic trade audits, per-event reserve playback, and true holder accounting.
    """
    def __init__(self, db_path: Optional[Path] = None):
        self.data_dir = get_data_dir()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path or (self.data_dir / "onchain_events.db")
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS onchain_events (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    slot INTEGER NOT NULL,
                    block_time INTEGER NOT NULL,
                    signature TEXT NOT NULL,
                    tx_index_in_slot INTEGER,
                    mint TEXT NOT NULL,
                    wallet TEXT NOT NULL,
                    side TEXT,
                    sol_amount REAL NOT NULL,
                    token_amount REAL NOT NULL,
                    sol_reserves_after REAL NOT NULL,
                    token_reserves_after REAL NOT NULL,
                    pool_address TEXT,
                    detection_source TEXT NOT NULL,
                    commitment TEXT NOT NULL,
                    received_at REAL NOT NULL,
                    latency_ms REAL NOT NULL,
                    details_json TEXT
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_ocev_mint ON onchain_events(mint, slot)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_ocev_sig ON onchain_events(signature)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_ocev_pool ON onchain_events(pool_address)")
            conn.commit()

    def record_event(self, ev: OnChainEvent) -> None:
        """Persist on-chain event to SQLite."""
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT OR REPLACE INTO onchain_events (
                    event_id, event_type, slot, block_time, signature,
                    tx_index_in_slot, mint, wallet, side, sol_amount,
                    token_amount, sol_reserves_after, token_reserves_after,
                    pool_address, detection_source, commitment, received_at,
                    latency_ms, details_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                ev.event_id, ev.event_type, ev.slot, ev.block_time, ev.signature,
                ev.tx_index_in_slot, ev.mint, ev.wallet, ev.side, ev.sol_amount,
                ev.token_amount, ev.sol_reserves_after, ev.token_reserves_after,
                ev.pool_address, ev.detection_source, ev.commitment, ev.received_at,
                ev.latency_ms, json.dumps(ev.details or {})
            ))
            conn.commit()

    def get_events_for_mint(self, mint: str) -> List[OnChainEvent]:
        """Fetch chronological event path for a given token mint."""
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM onchain_events WHERE mint = ? ORDER BY slot ASC, tx_index_in_slot ASC, received_at ASC",
                (mint,)
            )
            rows = cur.fetchall()
            events = []
            for r in rows:
                d = dict(r)
                details = json.loads(d.pop("details_json", "{}") or "{}")
                events.append(OnChainEvent(**d, details=details))
            return events

    def get_latest_event(self, mint: str) -> Optional[OnChainEvent]:
        """Fetch the most recent on-chain event for a given token mint."""
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM onchain_events WHERE mint = ? ORDER BY slot DESC, received_at DESC LIMIT 1",
                (mint,)
            )
            row = cur.fetchone()
            if not row:
                return None
            d = dict(row)
            details = json.loads(d.pop("details_json", "{}") or "{}")
            return OnChainEvent(**d, details=details)

    def get_distinct_buyer_wallets(self, mint: str) -> List[str]:
        """
        Compute actual unique buyer WALLETS strictly from on-chain buy events,
        completely replacing reliance on transaction counts or DexScreener aggregates.
        """
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT DISTINCT wallet FROM onchain_events
                WHERE mint = ? AND (side = 'BUY' OR event_type = 'CURVE_BUY' OR (event_type = 'POOL_SWAP' AND side = 'BUY'))
            """, (mint,))
            return [row[0] for row in cur.fetchall()]

    def audit_curve_completion(self, mint: str) -> Dict[str, Any]:
        """
        Audit curve lifecycle:
        Checks whether curve was completed by a single wallet or transaction,
        total distinct buyers, and migration parameters.
        """
        events = self.get_events_for_mint(mint)
        curve_buys = [e for e in events if e.event_type == "CURVE_BUY" or (e.side == "BUY" and not e.pool_address)]
        distinct_wallets = {e.wallet for e in curve_buys}
        
        single_tx_completion = False
        curve_filler_wallet = None
        curve_filler_sol = 0.0

        for buy in curve_buys:
            # Check if this single buy exceeded 80 SOL or pushed curve to 100%
            if buy.sol_amount >= 80.0 or buy.sol_reserves_after >= 84.0:
                single_tx_completion = True
                curve_filler_wallet = buy.wallet
                curve_filler_sol = buy.sol_amount
                break

        migration_ev = next((e for e in events if e.event_type == "MIGRATION"), None)

        return {
            "curve_total_buys": len(curve_buys),
            "curve_distinct_buyers": len(distinct_wallets),
            "curve_completed_by_single_tx": single_tx_completion,
            "curve_filler_wallet": curve_filler_wallet,
            "curve_filler_sol": curve_filler_sol,
            "has_migrated": migration_ev is not None,
            "migration_slot": migration_ev.slot if migration_ev else None,
            "migration_block_time": migration_ev.block_time if migration_ev else None,
            "pool_address": migration_ev.pool_address if migration_ev else None,
        }
