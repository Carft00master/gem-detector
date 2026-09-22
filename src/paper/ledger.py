"""
Live Paper-Trading Ledger & Immutable Trade Journal (v1.0.0 Frozen Release with Schema v1.1.0)
Persists simulated live and backtested paper trades into an append-only SQLite schema and JSONL stream.
Permanently records immutable frozen system versions and granular point-in-time trade events.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional
import uuid

from src.version import (
    CALIBRATION_VERSION,
    EXECUTION_MODEL_VERSION,
    FEATURE_SCHEMA_VERSION,
    LEARNING_DATA_VERSION,
    MODEL_VERSION,
    REGIME_VERSION,
    RISK_RULES_VERSION,
    SCANNER_VERSION,
    TRADE_LEDGER_SCHEMA_VERSION,
)

logger = logging.getLogger(__name__)


@dataclass
class TradeEventRecord:
    """
    Immutable chronological state transition or telemetry event for a paper trade.
    """
    event_id: str
    trade_id: str
    token_address: str
    timestamp: str
    event_type: str  # DISCOVERED, WATCH, EARLY_BREAKOUT, STRENGTHENING, WEAKENING, PAPER_ENTRY, TARGET_PROGRESS, RISK_WARNING, INVALIDATED, EXIT, TARGET_REACHED
    market_cap_usd: float = 0.0
    liquidity_usd: float = 0.0
    price_usd: float = 0.0
    signal_state: str = "WATCH"
    p_reach_100k: float = 0.0
    p_reach_500k: float = 0.0
    p_reach_1m: float = 0.0
    p_reach_3m: float = 0.0
    risk_scores: Dict[str, float] = field(default_factory=dict)
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PaperTradeRecord:
    """
    Comprehensive immutable trade journal record with full provenance, point-in-time
    entry state snapshots, and realized exit telemetry.
    """
    signal_id: str
    token_address: str
    symbol: str
    chain: str
    venue: str
    timestamp: str

    # Identification & Versions
    trade_id: Optional[str] = None
    scanner_version: str = SCANNER_VERSION
    model_version: str = MODEL_VERSION
    feature_schema_version: str = FEATURE_SCHEMA_VERSION
    calibration_version: str = CALIBRATION_VERSION
    regime_version: str = REGIME_VERSION
    risk_rules_version: str = RISK_RULES_VERSION
    execution_model_version: str = EXECUTION_MODEL_VERSION
    trade_ledger_schema_version: str = TRADE_LEDGER_SCHEMA_VERSION
    pool_type: str = "CONSTANT_PRODUCT"

    # Granular Timestamps
    discovery_timestamp: Optional[str] = None
    first_alert_timestamp: Optional[str] = None
    entry_signal_timestamp: Optional[str] = None
    simulated_entry_timestamp: Optional[str] = None
    entry_execution_timestamp: Optional[str] = None
    exit_signal_timestamp: Optional[str] = None
    simulated_exit_timestamp: Optional[str] = None
    exit_execution_timestamp: Optional[str] = None
    hold_duration_seconds: float = 0.0

    # Market State & Execution at Entry
    market_cap_usd: float = 0.0
    entry_market_cap_usd: float = 0.0
    liquidity_usd: float = 0.0
    entry_liquidity_usd: float = 0.0
    entry_price_usd: float = 0.0
    simulated_fill_price_usd: float = 0.0
    position_size_usd: float = 250.0
    entry_price_impact_pct: float = 0.0
    entry_slippage_pct: float = 0.0

    # Predictions & Risk Profile at Entry (Frozen - Never Rewritten)
    p_reach_100k: float = 0.0
    p_reach_500k: float = 0.0
    p_reach_1m: float = 0.0
    p_reach_3m: float = 0.0
    p_rug: float = 0.0
    p_reach_100k_at_entry: float = 0.0
    p_reach_500k_at_entry: float = 0.0
    p_reach_1m_at_entry: float = 0.0
    p_reach_3m_at_entry: float = 0.0
    rug_risk_at_entry: float = 0.0
    manipulation_risk_at_entry: float = 0.0
    cabal_risk_at_entry: float = 0.0
    data_confidence: float = 1.0
    data_confidence_at_entry: float = 1.0
    discovery_quality_at_entry: float = 1.0
    signal_state_at_entry: str = "EARLY_BREAKOUT"
    regime: str = "NORMAL"

    # Execution Lifecycle & Outcome
    status: str = "OPEN"                   # "OPEN" | "CLOSED"
    entry_reason: str = "BREAKOUT_CONVICTION"
    exit_policy: str = "TRAILING_STOP"
    exit_price_usd: Optional[float] = None
    exit_market_cap_usd: Optional[float] = None
    exit_liquidity_usd: Optional[float] = None
    exit_timestamp: Optional[str] = None
    exit_reason: Optional[str] = None      # "FIXED_TARGET" | "TRAILING_STOP" | "RISK_INVALIDATION" | "TIME_BASED"
    exit_price_impact_pct: float = 0.0
    exit_slippage_pct: float = 0.0
    total_fees_usd: float = 0.0
    network_cost_usd: float = 0.0
    net_realized_pnl_usd: float = 0.0
    net_realized_return_pct: float = 0.0
    mfe_ratio: float = 1.0
    mae_ratio: float = 1.0
    target_reached_3m: bool = False
    outcome_label: str = "PENDING"         # "SUCCESS" | "FAILURE" | "RIGHT_CENSORED" | "PENDING"

    def __post_init__(self):
        if not self.trade_id:
            self.trade_id = self.signal_id

        # Keep legacy aliases in sync
        if self.entry_market_cap_usd == 0.0 and self.market_cap_usd > 0.0:
            self.entry_market_cap_usd = self.market_cap_usd
        elif self.market_cap_usd == 0.0 and self.entry_market_cap_usd > 0.0:
            self.market_cap_usd = self.entry_market_cap_usd

        if self.entry_liquidity_usd == 0.0 and self.liquidity_usd > 0.0:
            self.entry_liquidity_usd = self.liquidity_usd
        elif self.liquidity_usd == 0.0 and self.entry_liquidity_usd > 0.0:
            self.liquidity_usd = self.entry_liquidity_usd

        if self.entry_slippage_pct == 0.0 and self.entry_price_impact_pct > 0.0:
            self.entry_slippage_pct = self.entry_price_impact_pct

        if self.p_reach_3m_at_entry == 0.0 and self.p_reach_3m > 0.0:
            self.p_reach_100k_at_entry = self.p_reach_100k
            self.p_reach_500k_at_entry = self.p_reach_500k
            self.p_reach_1m_at_entry = self.p_reach_1m
            self.p_reach_3m_at_entry = self.p_reach_3m
            self.rug_risk_at_entry = self.p_rug
            self.data_confidence_at_entry = self.data_confidence

        if not self.discovery_timestamp:
            self.discovery_timestamp = self.timestamp
        if not self.first_alert_timestamp:
            self.first_alert_timestamp = self.timestamp
        if not self.entry_signal_timestamp:
            self.entry_signal_timestamp = self.timestamp
        if not self.simulated_entry_timestamp:
            self.simulated_entry_timestamp = self.timestamp
        if not self.entry_execution_timestamp:
            self.entry_execution_timestamp = self.timestamp


_INITIALIZED_LEDGER_DBS = set()


class PaperTradingLedger:
    def __init__(self, db_path: Optional[Path] = None, jsonl_path: Optional[Path] = None):
        from src.utils.paths import get_data_dir
        self.base_dir = get_data_dir()
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path or (self.base_dir / "paper_trading.db")
        self.jsonl_path = jsonl_path or (self.base_dir / "paper_trades.jsonl")
        self.event_jsonl_path = self.base_dir / "trade_events.jsonl"
        self._init_db()

    def _init_db(self) -> None:
        """Initialize append-only SQLite paper trading schema with frozen version fields and timeline events."""
        db_key = str(self.db_path)
        if db_key in _INITIALIZED_LEDGER_DBS:
            return

        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("PRAGMA journal_mode=WAL;")
            except Exception as e:
                logger.warning(f"Failed to set journal_mode=WAL for {self.db_path}: {e}")
            cursor.execute("PRAGMA busy_timeout=30000;")

            # 1. Main Paper Trades Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS paper_trades (
                    signal_id TEXT PRIMARY KEY,
                    trade_id TEXT,
                    scanner_version TEXT,
                    model_version TEXT,
                    feature_schema_version TEXT,
                    calibration_version TEXT,
                    regime_version TEXT,
                    risk_rules_version TEXT,
                    execution_model_version TEXT,
                    trade_ledger_schema_version TEXT,
                    token_address TEXT NOT NULL,
                    symbol TEXT,
                    chain TEXT,
                    venue TEXT,
                    pool_type TEXT,
                    timestamp TEXT,
                    discovery_timestamp TEXT,
                    first_alert_timestamp TEXT,
                    entry_signal_timestamp TEXT,
                    simulated_entry_timestamp TEXT,
                    entry_execution_timestamp TEXT,
                    exit_signal_timestamp TEXT,
                    simulated_exit_timestamp TEXT,
                    exit_execution_timestamp TEXT,
                    hold_duration_seconds REAL,
                    market_cap_usd REAL,
                    entry_market_cap_usd REAL,
                    liquidity_usd REAL,
                    entry_liquidity_usd REAL,
                    entry_price_usd REAL,
                    simulated_fill_price_usd REAL,
                    position_size_usd REAL,
                    entry_price_impact_pct REAL,
                    entry_slippage_pct REAL,
                    p_reach_100k REAL,
                    p_reach_500k REAL,
                    p_reach_1m REAL,
                    p_reach_3m REAL,
                    p_rug REAL,
                    p_reach_100k_at_entry REAL,
                    p_reach_500k_at_entry REAL,
                    p_reach_1m_at_entry REAL,
                    p_reach_3m_at_entry REAL,
                    rug_risk_at_entry REAL,
                    manipulation_risk_at_entry REAL,
                    cabal_risk_at_entry REAL,
                    data_confidence REAL,
                    data_confidence_at_entry REAL,
                    discovery_quality_at_entry REAL,
                    signal_state_at_entry TEXT,
                    regime TEXT,
                    status TEXT,
                    entry_reason TEXT,
                    exit_policy TEXT,
                    exit_price_usd REAL,
                    exit_market_cap_usd REAL,
                    exit_liquidity_usd REAL,
                    exit_timestamp TEXT,
                    exit_reason TEXT,
                    exit_price_impact_pct REAL,
                    exit_slippage_pct REAL,
                    total_fees_usd REAL,
                    network_cost_usd REAL,
                    net_realized_pnl_usd REAL,
                    net_realized_return_pct REAL,
                    mfe_ratio REAL,
                    mae_ratio REAL,
                    target_reached_3m INTEGER,
                    outcome_label TEXT
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_paper_token ON paper_trades(token_address)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_paper_status ON paper_trades(status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_paper_time ON paper_trades(timestamp)")

            # 2. Trade Event Timeline Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trade_event_log (
                    event_id TEXT PRIMARY KEY,
                    trade_id TEXT NOT NULL,
                    token_address TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    market_cap_usd REAL,
                    liquidity_usd REAL,
                    price_usd REAL,
                    signal_state TEXT,
                    p_reach_100k REAL,
                    p_reach_500k REAL,
                    p_reach_1m REAL,
                    p_reach_3m REAL,
                    risk_scores_json TEXT,
                    details_json TEXT
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_event_trade ON trade_event_log(trade_id, timestamp)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_event_token ON trade_event_log(token_address)")

            # Auto-migrate any missing columns in paper_trades
            cursor.execute("PRAGMA table_info(paper_trades)")
            existing_cols = {row[1] for row in cursor.fetchall()}
            required_cols = {
                "trade_id": "TEXT",
                "scanner_version": "TEXT",
                "model_version": "TEXT",
                "feature_schema_version": "TEXT",
                "calibration_version": "TEXT",
                "regime_version": "TEXT",
                "risk_rules_version": "TEXT",
                "execution_model_version": "TEXT",
                "trade_ledger_schema_version": "TEXT",
                "pool_type": "TEXT",
                "discovery_timestamp": "TEXT",
                "first_alert_timestamp": "TEXT",
                "entry_signal_timestamp": "TEXT",
                "simulated_entry_timestamp": "TEXT",
                "entry_execution_timestamp": "TEXT",
                "exit_signal_timestamp": "TEXT",
                "simulated_exit_timestamp": "TEXT",
                "exit_execution_timestamp": "TEXT",
                "hold_duration_seconds": "REAL",
                "entry_market_cap_usd": "REAL",
                "entry_liquidity_usd": "REAL",
                "entry_slippage_pct": "REAL",
                "p_reach_100k_at_entry": "REAL",
                "p_reach_500k_at_entry": "REAL",
                "p_reach_1m_at_entry": "REAL",
                "p_reach_3m_at_entry": "REAL",
                "rug_risk_at_entry": "REAL",
                "manipulation_risk_at_entry": "REAL",
                "cabal_risk_at_entry": "REAL",
                "data_confidence_at_entry": "REAL",
                "discovery_quality_at_entry": "REAL",
                "signal_state_at_entry": "TEXT",
                "entry_reason": "TEXT",
                "exit_market_cap_usd": "REAL",
                "exit_liquidity_usd": "REAL",
                "exit_slippage_pct": "REAL",
                "network_cost_usd": "REAL",
            }
            for col_name, col_type in required_cols.items():
                if col_name not in existing_cols:
                    cursor.execute(f"ALTER TABLE paper_trades ADD COLUMN {col_name} {col_type}")

            # Non-destructive backfills for legacy records
            cursor.execute("""
                UPDATE paper_trades
                SET trade_id = signal_id
                WHERE trade_id IS NULL OR trade_id = ''
            """)
            cursor.execute("""
                UPDATE paper_trades
                SET entry_market_cap_usd = market_cap_usd
                WHERE (entry_market_cap_usd IS NULL OR entry_market_cap_usd = 0.0)
                  AND market_cap_usd IS NOT NULL AND market_cap_usd > 0.0
            """)
            cursor.execute("""
                UPDATE paper_trades
                SET entry_liquidity_usd = liquidity_usd
                WHERE (entry_liquidity_usd IS NULL OR entry_liquidity_usd = 0.0)
                  AND liquidity_usd IS NOT NULL AND liquidity_usd > 0.0
            """)
            cursor.execute("""
                UPDATE paper_trades
                SET p_reach_3m_at_entry = p_reach_3m,
                    p_reach_1m_at_entry = p_reach_1m,
                    p_reach_500k_at_entry = p_reach_500k,
                    p_reach_100k_at_entry = p_reach_100k,
                    rug_risk_at_entry = p_rug,
                    data_confidence_at_entry = data_confidence
                WHERE p_reach_3m_at_entry IS NULL OR p_reach_3m_at_entry = 0.0
            """)
            cursor.execute("""
                UPDATE paper_trades
                SET trade_ledger_schema_version = 'v1.1.0'
                WHERE trade_ledger_schema_version IS NULL OR trade_ledger_schema_version = ''
            """)
            cursor.execute("""
                UPDATE paper_trades
                SET discovery_timestamp = timestamp,
                    first_alert_timestamp = timestamp,
                    entry_signal_timestamp = timestamp,
                    simulated_entry_timestamp = timestamp,
                    entry_execution_timestamp = timestamp
                WHERE discovery_timestamp IS NULL OR discovery_timestamp = ''
            """)

            conn.commit()
        _INITIALIZED_LEDGER_DBS.add(db_key)

    def record_entry(self, trade: PaperTradeRecord) -> None:
        """Append initial trade entry to SQLite and JSONL."""
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO paper_trades (
                    signal_id, trade_id, scanner_version, model_version, feature_schema_version,
                    calibration_version, regime_version, risk_rules_version, execution_model_version,
                    trade_ledger_schema_version, token_address, symbol, chain, venue, pool_type,
                    timestamp, discovery_timestamp, first_alert_timestamp, entry_signal_timestamp,
                    simulated_entry_timestamp, entry_execution_timestamp, exit_signal_timestamp,
                    simulated_exit_timestamp, exit_execution_timestamp, hold_duration_seconds,
                    market_cap_usd, entry_market_cap_usd, liquidity_usd, entry_liquidity_usd,
                    entry_price_usd, simulated_fill_price_usd, position_size_usd,
                    entry_price_impact_pct, entry_slippage_pct, p_reach_100k, p_reach_500k,
                    p_reach_1m, p_reach_3m, p_rug, p_reach_100k_at_entry, p_reach_500k_at_entry,
                    p_reach_1m_at_entry, p_reach_3m_at_entry, rug_risk_at_entry, manipulation_risk_at_entry,
                    cabal_risk_at_entry, data_confidence, data_confidence_at_entry,
                    discovery_quality_at_entry, signal_state_at_entry, regime, status,
                    entry_reason, exit_policy, exit_price_usd, exit_market_cap_usd, exit_liquidity_usd,
                    exit_timestamp, exit_reason, exit_price_impact_pct, exit_slippage_pct,
                    total_fees_usd, network_cost_usd, net_realized_pnl_usd, net_realized_return_pct,
                    mfe_ratio, mae_ratio, target_reached_3m, outcome_label
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?
                )
            """, (
                trade.signal_id, trade.trade_id or trade.signal_id, trade.scanner_version, trade.model_version, trade.feature_schema_version,
                trade.calibration_version, trade.regime_version, trade.risk_rules_version, trade.execution_model_version,
                trade.trade_ledger_schema_version, trade.token_address, trade.symbol, trade.chain, trade.venue, trade.pool_type,
                trade.timestamp, trade.discovery_timestamp, trade.first_alert_timestamp, trade.entry_signal_timestamp,
                trade.simulated_entry_timestamp, trade.entry_execution_timestamp, trade.exit_signal_timestamp,
                trade.simulated_exit_timestamp, trade.exit_execution_timestamp, trade.hold_duration_seconds,
                trade.market_cap_usd, trade.entry_market_cap_usd, trade.liquidity_usd, trade.entry_liquidity_usd,
                trade.entry_price_usd, trade.simulated_fill_price_usd, trade.position_size_usd,
                trade.entry_price_impact_pct, trade.entry_slippage_pct, trade.p_reach_100k, trade.p_reach_500k,
                trade.p_reach_1m, trade.p_reach_3m, trade.p_rug, trade.p_reach_100k_at_entry, trade.p_reach_500k_at_entry,
                trade.p_reach_1m_at_entry, trade.p_reach_3m_at_entry, trade.rug_risk_at_entry, trade.manipulation_risk_at_entry,
                trade.cabal_risk_at_entry, trade.data_confidence, trade.data_confidence_at_entry,
                trade.discovery_quality_at_entry, trade.signal_state_at_entry, trade.regime, trade.status,
                trade.entry_reason, trade.exit_policy, trade.exit_price_usd, trade.exit_market_cap_usd, trade.exit_liquidity_usd,
                trade.exit_timestamp, trade.exit_reason, trade.exit_price_impact_pct, trade.exit_slippage_pct,
                trade.total_fees_usd, trade.network_cost_usd, trade.net_realized_pnl_usd, trade.net_realized_return_pct,
                trade.mfe_ratio, trade.mae_ratio, int(trade.target_reached_3m), trade.outcome_label
            ))
            conn.commit()

        # Append to JSONL stream
        with open(self.jsonl_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(trade)) + "\n")

    def record_exit(self, trade: PaperTradeRecord) -> None:
        """Record trade closing with realized exit metrics."""
        trade.status = "CLOSED"
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE paper_trades SET
                    status = 'CLOSED',
                    exit_price_usd = ?,
                    exit_market_cap_usd = ?,
                    exit_liquidity_usd = ?,
                    exit_signal_timestamp = ?,
                    simulated_exit_timestamp = ?,
                    exit_execution_timestamp = ?,
                    exit_timestamp = ?,
                    hold_duration_seconds = ?,
                    exit_reason = ?,
                    exit_price_impact_pct = ?,
                    exit_slippage_pct = ?,
                    total_fees_usd = ?,
                    network_cost_usd = ?,
                    net_realized_pnl_usd = ?,
                    net_realized_return_pct = ?,
                    mfe_ratio = ?,
                    mae_ratio = ?,
                    target_reached_3m = ?,
                    outcome_label = ?
                WHERE signal_id = ?
            """, (
                trade.exit_price_usd, trade.exit_market_cap_usd, trade.exit_liquidity_usd,
                trade.exit_signal_timestamp or trade.exit_timestamp,
                trade.simulated_exit_timestamp or trade.exit_timestamp,
                trade.exit_execution_timestamp or trade.exit_timestamp,
                trade.exit_timestamp, trade.hold_duration_seconds, trade.exit_reason,
                trade.exit_price_impact_pct, trade.exit_slippage_pct or trade.exit_price_impact_pct,
                trade.total_fees_usd, trade.network_cost_usd, trade.net_realized_pnl_usd,
                trade.net_realized_return_pct, trade.mfe_ratio, trade.mae_ratio,
                int(trade.target_reached_3m), trade.outcome_label, trade.signal_id
            ))
            conn.commit()

        # Append exit log event
        with open(self.jsonl_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"event": "TRADE_EXIT", "record": asdict(trade)}) + "\n")

    def record_trade_event(self, event: TradeEventRecord) -> None:
        """Record an immutable chronological trade event into the timeline."""
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO trade_event_log (
                    event_id, trade_id, token_address, timestamp, event_type,
                    market_cap_usd, liquidity_usd, price_usd, signal_state,
                    p_reach_100k, p_reach_500k, p_reach_1m, p_reach_3m,
                    risk_scores_json, details_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                event.event_id, event.trade_id, event.token_address, event.timestamp, event.event_type,
                event.market_cap_usd, event.liquidity_usd, event.price_usd, event.signal_state,
                event.p_reach_100k, event.p_reach_500k, event.p_reach_1m, event.p_reach_3m,
                json.dumps(event.risk_scores or {}), json.dumps(event.details or {})
            ))
            conn.commit()

        with open(self.event_jsonl_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(event)) + "\n")

    def load_trade_events(self, trade_id: str) -> List[Dict[str, Any]]:
        """Load all chronological timeline events for a given trade."""
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM trade_event_log WHERE trade_id = ? ORDER BY timestamp ASC",
                (trade_id,)
            )
            rows = cursor.fetchall()
            events = []
            for r in rows:
                d = dict(r)
                if d.get("risk_scores_json"):
                    try:
                        d["risk_scores"] = json.loads(d["risk_scores_json"])
                    except Exception:
                        d["risk_scores"] = {}
                if d.get("details_json"):
                    try:
                        d["details"] = json.loads(d["details_json"])
                    except Exception:
                        d["details"] = {}
                events.append(d)
            return events

    def load_all_trades(self) -> List[Dict[str, Any]]:
        """Load all trade records from SQLite sorted chronologically."""
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM paper_trades ORDER BY timestamp ASC")
            return [dict(row) for row in cursor.fetchall()]

    def load_closed_trades(self) -> List[Dict[str, Any]]:
        """Load only completed closed paper trades."""
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM paper_trades WHERE status = 'CLOSED' ORDER BY timestamp ASC")
            return [dict(row) for row in cursor.fetchall()]

    def load_recent_trades(self, limit: int = 200) -> List[Dict[str, Any]]:
        """Fast query loading only the most recent trades for instant memory pre-population."""
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM paper_trades ORDER BY timestamp DESC LIMIT ?", (limit,))
            return [dict(row) for row in cursor.fetchall()]
