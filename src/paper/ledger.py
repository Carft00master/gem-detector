"""
Live Paper-Trading Ledger & Immutable Trade Journal (v2.0.0 Release with Ledger Epochs & Fill Simulation)
Persists simulated live and backtested paper trades into an append-only SQLite schema and JSONL stream.
Permanently records immutable frozen system versions, execution routes, point-in-time trade events,
and granular on-chain fill/lifecycle telemetry.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import sqlite3
import subprocess
from typing import Any, Dict, List, Optional
import uuid

from src.version import (
    CALIBRATION_VERSION,
    EXECUTION_MODEL_VERSION,
    FEATURE_SCHEMA_VERSION,
    LEARNING_DATA_VERSION,
    LEDGER_EPOCH,
    MODEL_VERSION,
    REGIME_VERSION,
    RISK_RULES_VERSION,
    SCANNER_VERSION,
    TRADE_LEDGER_SCHEMA_VERSION,
)

logger = logging.getLogger(__name__)


def get_current_git_commit() -> str:
    """Safely obtain the current git commit SHA without raising."""
    try:
        res = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=2.0)
        if res.returncode == 0:
            return res.stdout.strip()
    except Exception:
        pass
    return ""


def get_current_config_hash() -> str:
    """Compute a deterministic hash of current execution and selector configuration."""
    try:
        from src.config import load_config
        cfg = load_config()
        data = {
            "selector": getattr(cfg, "selector", None).__dict__ if hasattr(getattr(cfg, "selector", None), "__dict__") else {},
            "paper": getattr(cfg, "paper_trading", None).__dict__ if hasattr(getattr(cfg, "paper_trading", None), "__dict__") else {},
        }
        raw = json.dumps(data, default=str, sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    except Exception:
        return ""


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
class QuarantinedTradeRecord:
    """
    Trade quarantined due to failed integrity invariants (e.g., price jump across venues,
    exceeding pool liquidity limit, impossible fills, backwards timeline).
    """
    quarantine_id: str
    token_address: str
    quarantine_reason: str
    timestamp: str
    signal_id: Optional[str] = None
    trade_id: Optional[str] = None
    route: str = "ROUTE_A"
    trade_record_json: str = "{}"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ShadowTradeRecord:
    """
    Candidate rejected by the bot whose counterfactual forward outcome is tracked from on-chain reserves.
    """
    shadow_id: str
    token_address: str
    rejection_reason: str
    rejection_timestamp: str
    symbol: str = ""
    chain: str = "solana"
    failed_gates_json: str = "{}"
    market_cap_at_rejection: float = 0.0
    liquidity_at_rejection: float = 0.0
    p_reach_3m_at_rejection: float = 0.0
    max_future_mc_usd: float = 0.0
    target_reached_3m: bool = False
    outcome_label: str = "REJECTED"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PaperTradeRecord:
    """
    Comprehensive immutable trade journal record with full provenance, point-in-time
    entry state snapshots, realized exit telemetry, on-chain fill simulation,
    and lifecycle event tracking.
    """
    signal_id: str
    token_address: str
    symbol: str
    chain: str
    venue: str
    timestamp: str

    # Identification, Epoch & Versions
    trade_id: Optional[str] = None
    schema_version: str = TRADE_LEDGER_SCHEMA_VERSION
    ledger_epoch: str = LEDGER_EPOCH
    route: str = "ROUTE_A"                 # "ROUTE_A" (Organic) | "ROUTE_B" (First-Block)
    provider_tier: str = "FREE"            # "FREE" | "PAID"
    detection_mode: str = "polled, not streamed" # "polled, not streamed" | "streamed_processed"
    mint_lifecycle_id: Optional[str] = None
    config_hash: str = ""
    git_commit: str = ""
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

    # Holder Distribution & Order Flow Telemetry at Entry
    dev_holding_pct: float = 0.0
    top10_holder_pct: float = 0.0
    unique_buyers: int = 0
    buy_sell_ratio: float = 1.0

    # Fill Simulation & On-Chain Mechanics (Phase 1b)
    entry_venue: str = ""                  # "CURVE" | "POOL"
    entry_slot: Optional[int] = None
    entry_block_time: Optional[str] = None
    entry_tokens_received: float = 0.0
    entry_effective_sol_usd: float = 0.0
    entry_priority_fee_sol: float = 0.0
    entry_pool_sol_reserves_before: float = 0.0
    entry_pool_sol_reserves_after: float = 0.0
    entry_pool_token_reserves_before: float = 0.0
    entry_pool_token_reserves_after: float = 0.0
    landing_slot: Optional[int] = None
    landing_ordering: Optional[int] = None
    exit_venue: str = ""                   # "CURVE" | "POOL"
    exit_slot: Optional[int] = None
    exit_block_time: Optional[str] = None
    exit_tokens_sold: float = 0.0
    exit_gross_proceeds_usd: float = 0.0
    exit_net_proceeds_usd: float = 0.0
    exit_effective_sol_usd: float = 0.0
    exit_priority_fee_sol: float = 0.0
    exit_proceeds_pct_of_pool: float = 0.0
    exit_pool_sol_reserves_before: float = 0.0
    exit_pool_sol_reserves_after: float = 0.0
    exit_pool_token_reserves_before: float = 0.0
    exit_pool_token_reserves_after: float = 0.0

    # Per-Trade Lifecycle & On-Chain Gate Audit (Phase 1a/1c/1d)
    curve_creation_timestamp: Optional[str] = None
    curve_creation_slot: Optional[int] = None
    curve_completed_by_single_tx: bool = False
    curve_distinct_buyers: int = 0
    curve_migration_timestamp: Optional[str] = None
    curve_migration_slot: Optional[int] = None
    pool_address: Optional[str] = None
    pool_creation_timestamp: Optional[str] = None
    pool_creation_slot: Optional[int] = None
    pool_opening_price_usd: float = 0.0
    pool_opening_sol_reserve: float = 0.0
    pool_opening_token_reserve: float = 0.0
    venue_state_at_entry: str = "CURVE_OPEN"  # "CURVE_OPEN" | "MIGRATED" | "POOL"
    venue_state_at_exit: str = "CURVE_OPEN"   # "CURVE_OPEN" | "MIGRATED" | "POOL"
    actual_creator_holding_pct: float = 0.0
    actual_top10_holding_pct: float = 0.0
    actual_curve_filler_holding_pct: float = 0.0

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
        if not self.git_commit:
            self.git_commit = get_current_git_commit()
        if not self.config_hash:
            self.config_hash = get_current_config_hash()
        if not self.schema_version:
            self.schema_version = self.trade_ledger_schema_version or TRADE_LEDGER_SCHEMA_VERSION
        if not self.trade_ledger_schema_version:
            self.trade_ledger_schema_version = self.schema_version
        if not self.ledger_epoch:
            self.ledger_epoch = LEDGER_EPOCH

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
        """Initialize append-only SQLite paper trading schema with frozen version fields, routes, and timeline events."""
        db_key = str(self.db_path)
        if db_key in _INITIALIZED_LEDGER_DBS:
            return

        # Defensive self-healing: purge any 0-byte WAL or orphaned SHM file left behind on Windows
        try:
            wal_path = Path(str(self.db_path) + "-wal")
            shm_path = Path(str(self.db_path) + "-shm")
            if wal_path.exists() and wal_path.stat().st_size == 0:
                wal_path.unlink()
                if shm_path.exists():
                    shm_path.unlink()
                logger.info(f"Purged 0-byte WAL file for {self.db_path}")
        except Exception as e:
            logger.debug(f"Notice during WAL check for {self.db_path}: {e}")

        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("PRAGMA journal_mode=WAL;")
            except Exception as e:
                logger.warning(f"Failed to set journal_mode=WAL for {self.db_path}: {e}")
            cursor.execute("PRAGMA busy_timeout=30000;")

            # 1. Main Paper Trades Table (v2.0.0 Schema)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS paper_trades (
                    signal_id TEXT PRIMARY KEY,
                    trade_id TEXT,
                    schema_version TEXT DEFAULT 'v2.0.0',
                    ledger_epoch TEXT DEFAULT 'epoch_20261014',
                    route TEXT DEFAULT 'ROUTE_A',
                    config_hash TEXT,
                    git_commit TEXT,
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
                    outcome_label TEXT,
                    dev_holding_pct REAL,
                    top10_holder_pct REAL,
                    unique_buyers INTEGER,
                    buy_sell_ratio REAL,
                    entry_venue TEXT,
                    entry_slot INTEGER,
                    entry_block_time TEXT,
                    entry_tokens_received REAL,
                    entry_effective_sol_usd REAL,
                    entry_priority_fee_sol REAL,
                    entry_pool_sol_reserves_before REAL,
                    entry_pool_sol_reserves_after REAL,
                    entry_pool_token_reserves_before REAL,
                    entry_pool_token_reserves_after REAL,
                    landing_slot INTEGER,
                    landing_ordering INTEGER,
                    exit_venue TEXT,
                    exit_slot INTEGER,
                    exit_block_time TEXT,
                    exit_tokens_sold REAL,
                    exit_gross_proceeds_usd REAL,
                    exit_net_proceeds_usd REAL,
                    exit_effective_sol_usd REAL,
                    exit_priority_fee_sol REAL,
                    exit_proceeds_pct_of_pool REAL,
                    exit_pool_sol_reserves_before REAL,
                    exit_pool_sol_reserves_after REAL,
                    exit_pool_token_reserves_before REAL,
                    exit_pool_token_reserves_after REAL,
                    curve_creation_timestamp TEXT,
                    curve_creation_slot INTEGER,
                    curve_completed_by_single_tx INTEGER,
                    curve_distinct_buyers INTEGER,
                    curve_migration_timestamp TEXT,
                    curve_migration_slot INTEGER,
                    pool_address TEXT,
                    pool_creation_timestamp TEXT,
                    pool_creation_slot INTEGER,
                    pool_opening_price_usd REAL,
                    pool_opening_sol_reserve REAL,
                    pool_opening_token_reserve REAL,
                    venue_state_at_entry TEXT,
                    venue_state_at_exit TEXT,
                    actual_creator_holding_pct REAL,
                    actual_top10_holding_pct REAL,
                    actual_curve_filler_holding_pct REAL,
                    provider_tier TEXT DEFAULT 'FREE',
                    detection_mode TEXT DEFAULT 'polled, not streamed',
                    mint_lifecycle_id TEXT
                )
            """)
            # Migration check for existing databases
            cursor.execute("PRAGMA table_info(paper_trades)")
            existing_cols = {row[1] for row in cursor.fetchall()}
            if "provider_tier" not in existing_cols:
                cursor.execute("ALTER TABLE paper_trades ADD COLUMN provider_tier TEXT DEFAULT 'FREE'")
            if "detection_mode" not in existing_cols:
                cursor.execute("ALTER TABLE paper_trades ADD COLUMN detection_mode TEXT DEFAULT 'polled, not streamed'")
            if "mint_lifecycle_id" not in existing_cols:
                cursor.execute("ALTER TABLE paper_trades ADD COLUMN mint_lifecycle_id TEXT")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_paper_token ON paper_trades(token_address)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_paper_status ON paper_trades(status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_paper_time ON paper_trades(timestamp)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_paper_route ON paper_trades(route)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_paper_epoch ON paper_trades(ledger_epoch)")

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

            # 3. Trade Quarantine Table (Phase 1e Invariant Failures)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trade_quarantine (
                    quarantine_id TEXT PRIMARY KEY,
                    signal_id TEXT,
                    trade_id TEXT,
                    token_address TEXT NOT NULL,
                    route TEXT DEFAULT 'ROUTE_A',
                    quarantine_reason TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    trade_record_json TEXT
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_quarantine_time ON trade_quarantine(timestamp)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_quarantine_token ON trade_quarantine(token_address)")

            # 4. Shadow Trade Ledger (Phase 1f Counterfactual Outcomes)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS shadow_trade_ledger (
                    shadow_id TEXT PRIMARY KEY,
                    token_address TEXT NOT NULL,
                    symbol TEXT,
                    chain TEXT DEFAULT 'solana',
                    rejection_reason TEXT NOT NULL,
                    failed_gates_json TEXT,
                    rejection_timestamp TEXT NOT NULL,
                    market_cap_at_rejection REAL,
                    liquidity_at_rejection REAL,
                    p_reach_3m_at_rejection REAL,
                    max_future_mc_usd REAL DEFAULT 0.0,
                    target_reached_3m INTEGER DEFAULT 0,
                    outcome_label TEXT DEFAULT 'REJECTED'
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_shadow_token ON shadow_trade_ledger(token_address)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_shadow_time ON shadow_trade_ledger(rejection_timestamp)")

            # Auto-migrate any missing columns in paper_trades
            cursor.execute("PRAGMA table_info(paper_trades)")
            existing_cols = {row[1] for row in cursor.fetchall()}
            required_cols = {
                "schema_version": "TEXT DEFAULT 'v2.0.0'",
                "ledger_epoch": "TEXT DEFAULT 'epoch_20261014'",
                "route": "TEXT DEFAULT 'ROUTE_A'",
                "config_hash": "TEXT",
                "git_commit": "TEXT",
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
                "dev_holding_pct": "REAL",
                "top10_holder_pct": "REAL",
                "unique_buyers": "INTEGER",
                "buy_sell_ratio": "REAL",
                "entry_venue": "TEXT",
                "entry_slot": "INTEGER",
                "entry_block_time": "TEXT",
                "entry_tokens_received": "REAL",
                "entry_effective_sol_usd": "REAL",
                "entry_priority_fee_sol": "REAL",
                "entry_pool_sol_reserves_before": "REAL",
                "entry_pool_sol_reserves_after": "REAL",
                "entry_pool_token_reserves_before": "REAL",
                "entry_pool_token_reserves_after": "REAL",
                "landing_slot": "INTEGER",
                "landing_ordering": "INTEGER",
                "exit_venue": "TEXT",
                "exit_slot": "INTEGER",
                "exit_block_time": "TEXT",
                "exit_tokens_sold": "REAL",
                "exit_gross_proceeds_usd": "REAL",
                "exit_net_proceeds_usd": "REAL",
                "exit_effective_sol_usd": "REAL",
                "exit_priority_fee_sol": "REAL",
                "exit_proceeds_pct_of_pool": "REAL",
                "exit_pool_sol_reserves_before": "REAL",
                "exit_pool_sol_reserves_after": "REAL",
                "exit_pool_token_reserves_before": "REAL",
                "exit_pool_token_reserves_after": "REAL",
                "curve_creation_timestamp": "TEXT",
                "curve_creation_slot": "INTEGER",
                "curve_completed_by_single_tx": "INTEGER",
                "curve_distinct_buyers": "INTEGER",
                "curve_migration_timestamp": "TEXT",
                "curve_migration_slot": "INTEGER",
                "pool_address": "TEXT",
                "pool_creation_timestamp": "TEXT",
                "pool_creation_slot": "INTEGER",
                "pool_opening_price_usd": "REAL",
                "pool_opening_sol_reserve": "REAL",
                "pool_opening_token_reserve": "REAL",
                "venue_state_at_entry": "TEXT",
                "venue_state_at_exit": "TEXT",
                "actual_creator_holding_pct": "REAL",
                "actual_top10_holding_pct": "REAL",
                "actual_curve_filler_holding_pct": "REAL",
            }
            for col_name, col_type in required_cols.items():
                if col_name not in existing_cols:
                    cursor.execute(f"ALTER TABLE paper_trades ADD COLUMN {col_name} {col_type}")

            conn.commit()
        _INITIALIZED_LEDGER_DBS.add(db_key)

    def record_entry(self, trade: PaperTradeRecord) -> None:
        """Append initial trade entry to SQLite and JSONL."""
        fields = {
            "signal_id": trade.signal_id,
            "trade_id": trade.trade_id or trade.signal_id,
            "schema_version": trade.schema_version,
            "ledger_epoch": trade.ledger_epoch,
            "route": trade.route,
            "config_hash": trade.config_hash,
            "git_commit": trade.git_commit,
            "scanner_version": trade.scanner_version,
            "model_version": trade.model_version,
            "feature_schema_version": trade.feature_schema_version,
            "calibration_version": trade.calibration_version,
            "regime_version": trade.regime_version,
            "risk_rules_version": trade.risk_rules_version,
            "execution_model_version": trade.execution_model_version,
            "trade_ledger_schema_version": trade.trade_ledger_schema_version,
            "token_address": trade.token_address,
            "symbol": trade.symbol,
            "chain": trade.chain,
            "venue": trade.venue,
            "pool_type": trade.pool_type,
            "timestamp": trade.timestamp,
            "discovery_timestamp": trade.discovery_timestamp,
            "first_alert_timestamp": trade.first_alert_timestamp,
            "entry_signal_timestamp": trade.entry_signal_timestamp,
            "simulated_entry_timestamp": trade.simulated_entry_timestamp,
            "entry_execution_timestamp": trade.entry_execution_timestamp,
            "exit_signal_timestamp": trade.exit_signal_timestamp,
            "simulated_exit_timestamp": trade.simulated_exit_timestamp,
            "exit_execution_timestamp": trade.exit_execution_timestamp,
            "hold_duration_seconds": trade.hold_duration_seconds,
            "market_cap_usd": trade.market_cap_usd,
            "entry_market_cap_usd": trade.entry_market_cap_usd,
            "liquidity_usd": trade.liquidity_usd,
            "entry_liquidity_usd": trade.entry_liquidity_usd,
            "entry_price_usd": trade.entry_price_usd,
            "simulated_fill_price_usd": trade.simulated_fill_price_usd,
            "position_size_usd": trade.position_size_usd,
            "entry_price_impact_pct": trade.entry_price_impact_pct,
            "entry_slippage_pct": trade.entry_slippage_pct,
            "p_reach_100k": trade.p_reach_100k,
            "p_reach_500k": trade.p_reach_500k,
            "p_reach_1m": trade.p_reach_1m,
            "p_reach_3m": trade.p_reach_3m,
            "p_rug": trade.p_rug,
            "p_reach_100k_at_entry": trade.p_reach_100k_at_entry,
            "p_reach_500k_at_entry": trade.p_reach_500k_at_entry,
            "p_reach_1m_at_entry": trade.p_reach_1m_at_entry,
            "p_reach_3m_at_entry": trade.p_reach_3m_at_entry,
            "rug_risk_at_entry": trade.rug_risk_at_entry,
            "manipulation_risk_at_entry": trade.manipulation_risk_at_entry,
            "cabal_risk_at_entry": trade.cabal_risk_at_entry,
            "data_confidence": trade.data_confidence,
            "data_confidence_at_entry": trade.data_confidence_at_entry,
            "discovery_quality_at_entry": trade.discovery_quality_at_entry,
            "signal_state_at_entry": trade.signal_state_at_entry,
            "regime": trade.regime,
            "status": trade.status,
            "entry_reason": trade.entry_reason,
            "exit_policy": trade.exit_policy,
            "exit_price_usd": trade.exit_price_usd,
            "exit_market_cap_usd": trade.exit_market_cap_usd,
            "exit_liquidity_usd": trade.exit_liquidity_usd,
            "exit_timestamp": trade.exit_timestamp,
            "exit_reason": trade.exit_reason,
            "exit_price_impact_pct": trade.exit_price_impact_pct,
            "exit_slippage_pct": trade.exit_slippage_pct,
            "total_fees_usd": trade.total_fees_usd,
            "network_cost_usd": trade.network_cost_usd,
            "net_realized_pnl_usd": trade.net_realized_pnl_usd,
            "net_realized_return_pct": trade.net_realized_return_pct,
            "mfe_ratio": trade.mfe_ratio,
            "mae_ratio": trade.mae_ratio,
            "target_reached_3m": int(trade.target_reached_3m),
            "outcome_label": trade.outcome_label,
            "dev_holding_pct": getattr(trade, "dev_holding_pct", 0.0),
            "top10_holder_pct": getattr(trade, "top10_holder_pct", 0.0),
            "unique_buyers": getattr(trade, "unique_buyers", 0),
            "buy_sell_ratio": getattr(trade, "buy_sell_ratio", 1.0),
            "entry_venue": getattr(trade, "entry_venue", ""),
            "entry_slot": getattr(trade, "entry_slot", None),
            "entry_block_time": getattr(trade, "entry_block_time", None),
            "entry_tokens_received": getattr(trade, "entry_tokens_received", 0.0),
            "entry_effective_sol_usd": getattr(trade, "entry_effective_sol_usd", 0.0),
            "entry_priority_fee_sol": getattr(trade, "entry_priority_fee_sol", 0.0),
            "entry_pool_sol_reserves_before": getattr(trade, "entry_pool_sol_reserves_before", 0.0),
            "entry_pool_sol_reserves_after": getattr(trade, "entry_pool_sol_reserves_after", 0.0),
            "entry_pool_token_reserves_before": getattr(trade, "entry_pool_token_reserves_before", 0.0),
            "entry_pool_token_reserves_after": getattr(trade, "entry_pool_token_reserves_after", 0.0),
            "landing_slot": getattr(trade, "landing_slot", None),
            "landing_ordering": getattr(trade, "landing_ordering", None),
            "exit_venue": getattr(trade, "exit_venue", ""),
            "exit_slot": getattr(trade, "exit_slot", None),
            "exit_block_time": getattr(trade, "exit_block_time", None),
            "exit_tokens_sold": getattr(trade, "exit_tokens_sold", 0.0),
            "exit_gross_proceeds_usd": getattr(trade, "exit_gross_proceeds_usd", 0.0),
            "exit_net_proceeds_usd": getattr(trade, "exit_net_proceeds_usd", 0.0),
            "exit_effective_sol_usd": getattr(trade, "exit_effective_sol_usd", 0.0),
            "exit_priority_fee_sol": getattr(trade, "exit_priority_fee_sol", 0.0),
            "exit_proceeds_pct_of_pool": getattr(trade, "exit_proceeds_pct_of_pool", 0.0),
            "exit_pool_sol_reserves_before": getattr(trade, "exit_pool_sol_reserves_before", 0.0),
            "exit_pool_sol_reserves_after": getattr(trade, "exit_pool_sol_reserves_after", 0.0),
            "exit_pool_token_reserves_before": getattr(trade, "exit_pool_token_reserves_before", 0.0),
            "exit_pool_token_reserves_after": getattr(trade, "exit_pool_token_reserves_after", 0.0),
            "curve_creation_timestamp": getattr(trade, "curve_creation_timestamp", None),
            "curve_creation_slot": getattr(trade, "curve_creation_slot", None),
            "curve_completed_by_single_tx": int(getattr(trade, "curve_completed_by_single_tx", False)),
            "curve_distinct_buyers": getattr(trade, "curve_distinct_buyers", 0),
            "curve_migration_timestamp": getattr(trade, "curve_migration_timestamp", None),
            "curve_migration_slot": getattr(trade, "curve_migration_slot", None),
            "pool_address": getattr(trade, "pool_address", None),
            "pool_creation_timestamp": getattr(trade, "pool_creation_timestamp", None),
            "pool_creation_slot": getattr(trade, "pool_creation_slot", None),
            "pool_opening_price_usd": getattr(trade, "pool_opening_price_usd", 0.0),
            "pool_opening_sol_reserve": getattr(trade, "pool_opening_sol_reserve", 0.0),
            "pool_opening_token_reserve": getattr(trade, "pool_opening_token_reserve", 0.0),
            "venue_state_at_entry": getattr(trade, "venue_state_at_entry", "CURVE_OPEN"),
            "venue_state_at_exit": getattr(trade, "venue_state_at_exit", "CURVE_OPEN"),
            "actual_creator_holding_pct": getattr(trade, "actual_creator_holding_pct", 0.0),
            "actual_top10_holding_pct": getattr(trade, "actual_top10_holding_pct", 0.0),
            "actual_curve_filler_holding_pct": getattr(trade, "actual_curve_filler_holding_pct", 0.0),
        }
        cols = ", ".join(fields.keys())
        placeholders = ", ".join(["?"] * len(fields))

        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            cursor = conn.cursor()
            cursor.execute(f"INSERT OR REPLACE INTO paper_trades ({cols}) VALUES ({placeholders})", tuple(fields.values()))
            conn.commit()

        # Append to JSONL stream
        with open(self.jsonl_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(trade)) + "\n")

    def record_exit(self, trade: PaperTradeRecord) -> None:
        """Record trade closing with realized exit metrics and fill telemetry."""
        trade.status = "CLOSED"
        exit_fields = {
            "status": "CLOSED",
            "exit_price_usd": trade.exit_price_usd,
            "exit_market_cap_usd": trade.exit_market_cap_usd,
            "exit_liquidity_usd": trade.exit_liquidity_usd,
            "exit_signal_timestamp": trade.exit_signal_timestamp or trade.exit_timestamp,
            "simulated_exit_timestamp": trade.simulated_exit_timestamp or trade.exit_timestamp,
            "exit_execution_timestamp": trade.exit_execution_timestamp or trade.exit_timestamp,
            "exit_timestamp": trade.exit_timestamp,
            "hold_duration_seconds": trade.hold_duration_seconds,
            "exit_reason": trade.exit_reason,
            "exit_price_impact_pct": trade.exit_price_impact_pct,
            "exit_slippage_pct": trade.exit_slippage_pct or trade.exit_price_impact_pct,
            "total_fees_usd": trade.total_fees_usd,
            "network_cost_usd": trade.network_cost_usd,
            "net_realized_pnl_usd": trade.net_realized_pnl_usd,
            "net_realized_return_pct": trade.net_realized_return_pct,
            "mfe_ratio": trade.mfe_ratio,
            "mae_ratio": trade.mae_ratio,
            "target_reached_3m": int(trade.target_reached_3m),
            "outcome_label": trade.outcome_label,
            "exit_venue": getattr(trade, "exit_venue", ""),
            "exit_slot": getattr(trade, "exit_slot", None),
            "exit_block_time": getattr(trade, "exit_block_time", None),
            "exit_tokens_sold": getattr(trade, "exit_tokens_sold", 0.0),
            "exit_gross_proceeds_usd": getattr(trade, "exit_gross_proceeds_usd", 0.0),
            "exit_net_proceeds_usd": getattr(trade, "exit_net_proceeds_usd", 0.0),
            "exit_effective_sol_usd": getattr(trade, "exit_effective_sol_usd", 0.0),
            "exit_priority_fee_sol": getattr(trade, "exit_priority_fee_sol", 0.0),
            "exit_proceeds_pct_of_pool": getattr(trade, "exit_proceeds_pct_of_pool", 0.0),
            "exit_pool_sol_reserves_before": getattr(trade, "exit_pool_sol_reserves_before", 0.0),
            "exit_pool_sol_reserves_after": getattr(trade, "exit_pool_sol_reserves_after", 0.0),
            "exit_pool_token_reserves_before": getattr(trade, "exit_pool_token_reserves_before", 0.0),
            "exit_pool_token_reserves_after": getattr(trade, "exit_pool_token_reserves_after", 0.0),
            "venue_state_at_exit": getattr(trade, "venue_state_at_exit", "CURVE_OPEN"),
        }
        set_clause = ", ".join([f"{k} = ?" for k in exit_fields.keys()])
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            cursor = conn.cursor()
            cursor.execute(f"UPDATE paper_trades SET {set_clause} WHERE signal_id = ?", tuple(exit_fields.values()) + (trade.signal_id,))
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

    def record_quarantine(
        self,
        token_address: str,
        reason: str,
        route: str = "ROUTE_A",
        signal_id: Optional[str] = None,
        trade_id: Optional[str] = None,
        trade_dict: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Persist a failed invariant violation to the quarantine table for post-mortem analysis."""
        quarantine_id = f"quar_{str(uuid.uuid4())[:12]}"
        now_iso = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO trade_quarantine (
                    quarantine_id, signal_id, trade_id, token_address, route,
                    quarantine_reason, timestamp, trade_record_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                quarantine_id, signal_id, trade_id, token_address, route,
                reason, now_iso, json.dumps(trade_dict or {})
            ))
            conn.commit()
        logger.warning(f"Quarantined trade for {token_address} (route {route}): {reason}")
        return quarantine_id

    def record_shadow_candidate(self, shadow: ShadowTradeRecord) -> None:
        """Record a rejected candidate in the shadow ledger for un-biased counterfactual verification."""
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO shadow_trade_ledger (
                    shadow_id, token_address, symbol, chain, rejection_reason,
                    failed_gates_json, rejection_timestamp, market_cap_at_rejection,
                    liquidity_at_rejection, p_reach_3m_at_rejection, max_future_mc_usd,
                    target_reached_3m, outcome_label
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                shadow.shadow_id, shadow.token_address, shadow.symbol, shadow.chain,
                shadow.rejection_reason, shadow.failed_gates_json, shadow.rejection_timestamp,
                shadow.market_cap_at_rejection, shadow.liquidity_at_rejection,
                shadow.p_reach_3m_at_rejection, shadow.max_future_mc_usd,
                int(shadow.target_reached_3m), shadow.outcome_label
            ))
            conn.commit()

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

    def load_trades_by_route(self, route: str) -> List[Dict[str, Any]]:
        """Load trades belonging exclusively to a specific execution route (ROUTE_A or ROUTE_B)."""
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM paper_trades WHERE route = ? ORDER BY timestamp ASC", (route,))
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

    def load_quarantined_trades(self) -> List[Dict[str, Any]]:
        """Load all quarantined trades with violation reasons."""
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM trade_quarantine ORDER BY timestamp DESC")
            return [dict(row) for row in cursor.fetchall()]

    def load_shadow_trades(self, limit: int = 500) -> List[Dict[str, Any]]:
        """Load counterfactual shadow trades for rejection audit."""
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM shadow_trade_ledger ORDER BY rejection_timestamp DESC LIMIT ?", (limit,))
            return [dict(row) for row in cursor.fetchall()]
