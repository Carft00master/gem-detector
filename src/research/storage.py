"""
Longitudinal Token Storage Engine (SQLite & JSONL)
Stores full token population snapshots, time-series horizons, feature sets, and outcome labels.
"""

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional
from src.research.outcomes import TargetOutcomes

logger = logging.getLogger(__name__)


class ResearchStorage:
    def __init__(self, db_path: Optional[str] = None, jsonl_path: Optional[str] = None):
        from src.utils.paths import get_data_dir
        base_dir = get_data_dir()
        self.db_path = Path(db_path) if db_path else (base_dir / "research_dataset.db")
        self.jsonl_path = Path(jsonl_path) if jsonl_path else (base_dir / "snapshots.jsonl")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_sqlite()

    def _init_sqlite(self) -> None:
        """Initialize database tables with indexes, WAL mode, and concurrency tuning."""
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("PRAGMA journal_mode=WAL;")
            except Exception as e:
                logger.warning(f"Failed to set journal_mode=WAL for {self.db_path}: {e}")
            cursor.execute("PRAGMA synchronous=NORMAL;")
            cursor.execute("PRAGMA busy_timeout=30000;")
            # 1. Tokens Discovery Registry (Full population base rate)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tokens (
                    address TEXT PRIMARY KEY,
                    chain TEXT NOT NULL,
                    venue TEXT NOT NULL,
                    symbol TEXT,
                    name TEXT,
                    created_at TEXT,
                    discovered_at TEXT NOT NULL,
                    initial_market_cap REAL,
                    initial_liquidity REAL,
                    data_quality_score REAL DEFAULT 1.0
                )
            """)

            # 2. Time-Series Feature Snapshots
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    token_address TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    elapsed_minutes REAL NOT NULL,
                    horizon_label TEXT NOT NULL,
                    price_usd REAL,
                    market_cap_usd REAL,
                    fdv_usd REAL,
                    liquidity_usd REAL,
                    virtual_liquidity_usd REAL,
                    volume_5m_usd REAL,
                    volume_1h_usd REAL,
                    txns_5m_buys INTEGER,
                    txns_5m_sells INTEGER,
                    unique_buyers INTEGER,
                    unique_sellers INTEGER,
                    top10_raw_pct REAL,
                    top10_effective_pct REAL,
                    cabal_risk_score REAL,
                    wash_trade_risk REAL,
                    volume_quality_score REAL,
                    dev_holding_pct REAL,
                    features_json TEXT,
                    FOREIGN KEY (token_address) REFERENCES tokens(address)
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_token ON snapshots(token_address, elapsed_minutes)")

            # 3. Ground Truth Out-of-Sample Outcomes
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS outcomes (
                    token_address TEXT PRIMARY KEY,
                    evaluated_at TEXT NOT NULL,
                    target_50k INTEGER,
                    target_100k INTEGER,
                    target_250k INTEGER,
                    target_500k INTEGER,
                    target_1m INTEGER,
                    target_3m INTEGER,
                    target_5m INTEGER,
                    time_to_50k_min REAL,
                    time_to_100k_min REAL,
                    time_to_1m_min REAL,
                    time_to_3m_min REAL,
                    mfe_ratio REAL,
                    mae_ratio REAL,
                    peak_drawdown_pct REAL,
                    persistence_3m_minutes REAL,
                    is_valid_3m_runner INTEGER,
                    is_rug_event INTEGER,
                    survival_time_hours REAL,
                    FOREIGN KEY (token_address) REFERENCES tokens(address)
                )
            """)
            conn.commit()

    def record_token_discovery(
        self,
        address: str,
        chain: str,
        venue: str,
        symbol: str,
        name: str,
        discovered_at: datetime,
        initial_market_cap: float,
        initial_liquidity: float,
        created_at: Optional[datetime] = None,
        data_quality_score: float = 1.0,
    ) -> None:
        """Register a newly discovered token in the population database."""
        self.record_token_discoveries_batch([{
            "address": address,
            "chain": chain,
            "venue": venue,
            "symbol": symbol,
            "name": name,
            "discovered_at": discovered_at,
            "initial_market_cap": initial_market_cap,
            "initial_liquidity": initial_liquidity,
            "created_at": created_at,
            "data_quality_score": data_quality_score,
        }])

    def record_token_discoveries_batch(self, discoveries: List[Dict[str, Any]]) -> None:
        """Batch insert discovered tokens in a single transaction."""
        if not discoveries:
            return
        sql = """
            INSERT OR IGNORE INTO tokens (
                address, chain, venue, symbol, name, created_at,
                discovered_at, initial_market_cap, initial_liquidity, data_quality_score
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        rows = [
            (
                d["address"],
                d["chain"],
                d["venue"],
                d.get("symbol", ""),
                d.get("name", ""),
                d["created_at"].isoformat() if d.get("created_at") else None,
                d["discovered_at"].isoformat() if hasattr(d["discovered_at"], "isoformat") else str(d["discovered_at"]),
                d.get("initial_market_cap", 0.0),
                d.get("initial_liquidity", 0.0),
                d.get("data_quality_score", 1.0),
            )
            for d in discoveries
        ]
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            cursor = conn.cursor()
            cursor.executemany(sql, rows)
            conn.commit()

    def record_snapshot(
        self,
        token_address: str,
        timestamp: datetime,
        elapsed_minutes: float,
        horizon_label: str,
        price_usd: float,
        market_cap_usd: float,
        fdv_usd: float,
        liquidity_usd: float,
        virtual_liquidity_usd: float,
        volume_5m_usd: float,
        volume_1h_usd: float,
        txns_5m_buys: int,
        txns_5m_sells: int,
        unique_buyers: int,
        unique_sellers: int,
        top10_raw_pct: float,
        top10_effective_pct: float,
        cabal_risk_score: float,
        wash_trade_risk: float,
        volume_quality_score: float,
        dev_holding_pct: float,
        features: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Store a point-in-time observation snapshot."""
        self.record_snapshots_batch([{
            "token_address": token_address,
            "timestamp": timestamp,
            "elapsed_minutes": elapsed_minutes,
            "horizon_label": horizon_label,
            "price_usd": price_usd,
            "market_cap_usd": market_cap_usd,
            "fdv_usd": fdv_usd,
            "liquidity_usd": liquidity_usd,
            "virtual_liquidity_usd": virtual_liquidity_usd,
            "volume_5m_usd": volume_5m_usd,
            "volume_1h_usd": volume_1h_usd,
            "txns_5m_buys": txns_5m_buys,
            "txns_5m_sells": txns_5m_sells,
            "unique_buyers": unique_buyers,
            "unique_sellers": unique_sellers,
            "top10_raw_pct": top10_raw_pct,
            "top10_effective_pct": top10_effective_pct,
            "cabal_risk_score": cabal_risk_score,
            "wash_trade_risk": wash_trade_risk,
            "volume_quality_score": volume_quality_score,
            "dev_holding_pct": dev_holding_pct,
            "features": features,
        }])

    def record_snapshots_batch(self, snapshots: List[Dict[str, Any]]) -> None:
        """Batch insert snapshots in a single SQLite transaction and single JSONL append."""
        if not snapshots:
            return

        sql = """
            INSERT INTO snapshots (
                token_address, timestamp, elapsed_minutes, horizon_label,
                price_usd, market_cap_usd, fdv_usd, liquidity_usd, virtual_liquidity_usd,
                volume_5m_usd, volume_1h_usd, txns_5m_buys, txns_5m_sells,
                unique_buyers, unique_sellers, top10_raw_pct, top10_effective_pct,
                cabal_risk_score, wash_trade_risk, volume_quality_score, dev_holding_pct, features_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        rows = []
        jsonl_lines = []

        for s in snapshots:
            ts_str = s["timestamp"].isoformat() if hasattr(s["timestamp"], "isoformat") else str(s["timestamp"])
            feats = s.get("features") or {}
            features_json = json.dumps(feats)
            rows.append((
                s["token_address"],
                ts_str,
                s["elapsed_minutes"],
                s["horizon_label"],
                s.get("price_usd", 0.0),
                s.get("market_cap_usd", 0.0),
                s.get("fdv_usd", 0.0),
                s.get("liquidity_usd", 0.0),
                s.get("virtual_liquidity_usd", 0.0),
                s.get("volume_5m_usd", 0.0),
                s.get("volume_1h_usd", 0.0),
                s.get("txns_5m_buys", 0),
                s.get("txns_5m_sells", 0),
                s.get("unique_buyers", 0),
                s.get("unique_sellers", 0),
                s.get("top10_raw_pct", 0.0),
                s.get("top10_effective_pct", 0.0),
                s.get("cabal_risk_score", 0.0),
                s.get("wash_trade_risk", 0.0),
                s.get("volume_quality_score", 1.0),
                s.get("dev_holding_pct", 0.0),
                features_json,
            ))
            jsonl_lines.append(json.dumps({
                "token_address": s["token_address"],
                "timestamp": ts_str,
                "elapsed_minutes": s["elapsed_minutes"],
                "horizon_label": s["horizon_label"],
                "market_cap_usd": s.get("market_cap_usd", 0.0),
                "liquidity_usd": s.get("liquidity_usd", 0.0),
                "volume_5m_usd": s.get("volume_5m_usd", 0.0),
                "cabal_risk_score": s.get("cabal_risk_score", 0.0),
                "wash_trade_risk": s.get("wash_trade_risk", 0.0),
                "features": feats,
            }) + "\n")

        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            cursor = conn.cursor()
            cursor.executemany(sql, rows)
            conn.commit()

        try:
            with open(self.jsonl_path, "a", encoding="utf-8") as f:
                f.write("".join(jsonl_lines))
        except Exception as e:
            logger.warning(f"Could not append batch to snapshots JSONL: {e}")

    def record_outcomes(self, token_address: str, outcomes: TargetOutcomes) -> None:
        """Store ground-truth outcomes for a token."""
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO outcomes (
                    token_address, evaluated_at, target_50k, target_100k, target_250k,
                    target_500k, target_1m, target_3m, target_5m,
                    time_to_50k_min, time_to_100k_min, time_to_1m_min, time_to_3m_min,
                    mfe_ratio, mae_ratio, peak_drawdown_pct, persistence_3m_minutes,
                    is_valid_3m_runner, is_rug_event, survival_time_hours
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                token_address,
                datetime.now(timezone.utc).isoformat(),
                int(outcomes.target_50k),
                int(outcomes.target_100k),
                int(outcomes.target_250k),
                int(outcomes.target_500k),
                int(outcomes.target_1m),
                int(outcomes.target_3m),
                int(outcomes.target_5m),
                outcomes.time_to_50k_min,
                outcomes.time_to_100k_min,
                outcomes.time_to_1m_min,
                outcomes.time_to_3m_min,
                outcomes.mfe_ratio,
                outcomes.mae_ratio,
                outcomes.peak_drawdown_pct,
                outcomes.persistence_3m_minutes,
                int(outcomes.is_valid_3m_runner),
                int(outcomes.is_rug_event),
                outcomes.survival_time_hours,
            ))
            conn.commit()

    def load_training_dataset(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Load merged point-in-time snapshots with their out-of-sample outcome labels.
        Accepts optional limit to avoid unbounded memory loading.
        """
        records = []
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            if limit is not None:
                cursor.execute("""
                    SELECT 
                        s.*,
                        t.chain,
                        t.venue,
                        t.discovered_at,
                        o.target_100k,
                        o.target_500k,
                        o.target_1m,
                        o.target_3m,
                        o.is_valid_3m_runner,
                        o.is_rug_event,
                        o.mfe_ratio,
                        o.peak_drawdown_pct
                    FROM snapshots s
                    JOIN tokens t ON s.token_address = t.address
                    LEFT JOIN outcomes o ON s.token_address = o.token_address
                    ORDER BY s.timestamp DESC
                    LIMIT ?
                """, (limit,))
            else:
                cursor.execute("""
                    SELECT 
                        s.*,
                        t.chain,
                        t.venue,
                        t.discovered_at,
                        o.target_100k,
                        o.target_500k,
                        o.target_1m,
                        o.target_3m,
                        o.is_valid_3m_runner,
                        o.is_rug_event,
                        o.mfe_ratio,
                        o.peak_drawdown_pct
                    FROM snapshots s
                    JOIN tokens t ON s.token_address = t.address
                    LEFT JOIN outcomes o ON s.token_address = o.token_address
                    ORDER BY s.timestamp ASC
                """)
            for row in cursor.fetchall():
                d = dict(row)
                if d.get("features_json"):
                    try:
                        d["features"] = json.loads(d["features_json"])
                    except Exception:
                        d["features"] = {}
                records.append(d)
        if limit is not None:
            records.reverse()
        return records
