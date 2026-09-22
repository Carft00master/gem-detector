"""
True Shadow Universe Engine & Denominator Recorder (v1.0.0 Frozen)
Captures the complete state for every token entering the $8K-$35K discovery universe,
regardless of whether the model produces an alert, establishing the true empirical population denominator.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional
from src.feeds.base_feed import TokenCandidate
from src.models.predictor import BreakoutPredictionOutput
from src.version import FROZEN_VERSION_MANIFEST

logger = logging.getLogger(__name__)


@dataclass
class ShadowUniverseRecord:
    token_address: str
    symbol: str
    chain: str
    venue: str
    discovery_timestamp: str

    # Version Identifiers
    scanner_version: str = FROZEN_VERSION_MANIFEST.scanner_version
    model_version: str = FROZEN_VERSION_MANIFEST.model_version

    # Token & Pool Ages
    token_age_minutes: float = 0.0
    pool_age_minutes: float = 0.0
    time_since_first_trade_min: float = 0.0
    trade_count: int = 0
    holder_count: int = 0

    # Market State at Discovery
    market_cap_usd: float = 0.0
    fdv_usd: float = 0.0
    liquidity_usd: float = 0.0
    price_usd: float = 0.0
    volume_5m_usd: float = 0.0
    volume_1h_usd: float = 0.0
    unique_buyers: int = 0
    unique_sellers: int = 0

    # 12-Feature Model Vector
    effective_vol_mc_ratio: float = 0.0
    effective_buy_pressure: float = 0.0
    buyer_quality: float = 0.0
    liquidity_quality: float = 0.0
    holder_quality: float = 0.0
    breakout_quality: float = 0.0
    wallet_independence: float = 1.0
    wash_trade_risk: float = 0.0
    cabal_risk_score: float = 0.0
    dev_risk_score: float = 0.0
    contract_risk: float = 0.0
    liquidity_risk: float = 0.0

    # Full Calibrated Probability Vector
    p_reach_50k: float = 0.0
    p_reach_100k: float = 0.0
    p_reach_250k: float = 0.0
    p_reach_500k: float = 0.0
    p_reach_1m: float = 0.0
    p_reach_3m: float = 0.0
    p_reach_5m: float = 0.0

    # 4x4 Probability Grid
    p_100k_15m: float = 0.0
    p_100k_1h: float = 0.0
    p_100k_6h: float = 0.0
    p_100k_24h: float = 0.0

    p_3m_15m: float = 0.0
    p_3m_1h: float = 0.0
    p_3m_6h: float = 0.0
    p_3m_24h: float = 0.0

    # Calibrated Risk Probabilities & Telemetry
    p_rug: float = 0.0
    p_manipulation: float = 0.0
    data_confidence: float = 1.0
    market_regime: str = "NORMAL"

    # Selection State & Opportunity Flag
    signal_state: str = "NEW"           # "NEW" | "WATCH" | "EARLY_BREAKOUT" | "STRENGTHENING" | "WEAKENING" | "INVALIDATED"
    is_alert_candidate: bool = False     # True if model triggered an alert
    model_score: float = 50.0
    model_percentile_rank: float = 50.0  # Percentile rank within daily cohort


class ShadowUniverseLogger:
    def __init__(self, db_path: Optional[Path] = None, jsonl_path: Optional[Path] = None):
        from src.utils.paths import get_data_dir
        self.base_dir = get_data_dir()
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path or (self.base_dir / "shadow_universe.db")
        self.jsonl_path = jsonl_path or (self.base_dir / "shadow_universe.jsonl")
        self._init_db()

    def _init_db(self) -> None:
        """Initialize append-only SQLite shadow universe schema."""
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("PRAGMA journal_mode=WAL;")
            except Exception as e:
                logger.warning(f"Failed to set journal_mode=WAL for {self.db_path}: {e}")
            cursor.execute("PRAGMA synchronous=NORMAL;")
            cursor.execute("PRAGMA busy_timeout=30000;")
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS shadow_tokens (
                    token_address TEXT PRIMARY KEY,
                    symbol TEXT,
                    chain TEXT,
                    venue TEXT,
                    discovery_timestamp TEXT,
                    scanner_version TEXT,
                    model_version TEXT,
                    token_age_minutes REAL,
                    pool_age_minutes REAL,
                    time_since_first_trade_min REAL,
                    trade_count INTEGER,
                    holder_count INTEGER,
                    market_cap_usd REAL,
                    fdv_usd REAL,
                    liquidity_usd REAL,
                    price_usd REAL,
                    volume_5m_usd REAL,
                    volume_1h_usd REAL,
                    unique_buyers INTEGER,
                    unique_sellers INTEGER,
                    effective_vol_mc_ratio REAL,
                    effective_buy_pressure REAL,
                    buyer_quality REAL,
                    liquidity_quality REAL,
                    holder_quality REAL,
                    breakout_quality REAL,
                    wallet_independence REAL,
                    wash_trade_risk REAL,
                    cabal_risk_score REAL,
                    dev_risk_score REAL,
                    contract_risk REAL,
                    liquidity_risk REAL,
                    p_reach_50k REAL,
                    p_reach_100k REAL,
                    p_reach_250k REAL,
                    p_reach_500k REAL,
                    p_reach_1m REAL,
                    p_reach_3m REAL,
                    p_reach_5m REAL,
                    p_100k_15m REAL,
                    p_100k_1h REAL,
                    p_100k_6h REAL,
                    p_100k_24h REAL,
                    p_3m_15m REAL,
                    p_3m_1h REAL,
                    p_3m_6h REAL,
                    p_3m_24h REAL,
                    p_rug REAL,
                    p_manipulation REAL,
                    data_confidence REAL,
                    market_regime TEXT,
                    signal_state TEXT,
                    is_alert_candidate INTEGER,
                    model_score REAL,
                    model_percentile_rank REAL
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_shadow_disc ON shadow_tokens(discovery_timestamp)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_shadow_chain ON shadow_tokens(chain)")
            conn.commit()

    def build_record(
        self,
        cand: TokenCandidate,
        pred: BreakoutPredictionOutput,
        regime: str = "NORMAL",
        signal_state: str = "NEW",
    ) -> ShadowUniverseRecord:
        """Construct a frozen ShadowUniverseRecord from candidate and prediction outputs."""
        return ShadowUniverseRecord(
            token_address=cand.address,
            symbol=cand.symbol,
            chain=cand.chain,
            venue=cand.dex_id,
            discovery_timestamp=datetime.now(timezone.utc).isoformat(),
            token_age_minutes=cand.age_minutes,
            pool_age_minutes=cand.age_minutes,
            time_since_first_trade_min=cand.age_minutes,
            trade_count=cand.txns_5m_buys + cand.txns_5m_sells,
            holder_count=cand.unique_buyers_1h,
            market_cap_usd=cand.market_cap_usd,
            fdv_usd=cand.market_cap_usd,
            liquidity_usd=cand.liquidity_usd,
            price_usd=cand.price_usd,
            volume_5m_usd=cand.volume_5m_usd,
            volume_1h_usd=cand.volume_1h_usd,
            unique_buyers=cand.unique_buyers_1h,
            unique_sellers=cand.unique_sellers_1h,
            effective_vol_mc_ratio=cand.volume_mc_ratio_5m,
            effective_buy_pressure=cand.buy_sell_ratio_5m,
            buyer_quality=pred.buyer_quality,
            liquidity_quality=pred.liquidity_quality,
            holder_quality=pred.holder_quality,
            breakout_quality=pred.breakout_quality,
            wallet_independence=pred.wallet_independence,
            wash_trade_risk=pred.p_manipulation,
            cabal_risk_score=pred.p_cabal,
            dev_risk_score=pred.p_rug * 0.5,
            contract_risk=pred.p_rug,
            liquidity_risk=pred.p_liquidity_failure,
            p_reach_50k=pred.p_reach_50k,
            p_reach_100k=pred.p_reach_100k,
            p_reach_250k=pred.p_reach_250k,
            p_reach_500k=pred.p_reach_500k,
            p_reach_1m=pred.p_reach_1m,
            p_reach_3m=pred.p_reach_3m,
            p_reach_5m=pred.p_reach_5m,
            p_100k_15m=pred.p_100k_15m,
            p_100k_1h=pred.p_100k_1h,
            p_100k_6h=pred.p_100k_6h,
            p_100k_24h=pred.p_100k_24h,
            p_3m_15m=pred.p_3m_15m,
            p_3m_1h=pred.p_3m_1h,
            p_3m_6h=pred.p_3m_6h,
            p_3m_24h=pred.p_3m_24h,
            p_rug=pred.p_rug,
            p_manipulation=pred.p_manipulation,
            data_confidence=pred.data_confidence,
            market_regime=regime,
            signal_state=signal_state,
            is_alert_candidate=(pred.alert_state in ("EARLY_BREAKOUT", "HIGH_CONVICTION")),
            model_score=pred.model_score,
        )

    def _rec_to_tuple(self, rec: ShadowUniverseRecord) -> tuple:
        return (
            rec.token_address, rec.symbol, rec.chain, rec.venue, rec.discovery_timestamp,
            rec.scanner_version, rec.model_version, rec.token_age_minutes, rec.pool_age_minutes,
            rec.time_since_first_trade_min, rec.trade_count, rec.holder_count, rec.market_cap_usd,
            rec.fdv_usd, rec.liquidity_usd, rec.price_usd, rec.volume_5m_usd, rec.volume_1h_usd,
            rec.unique_buyers, rec.unique_sellers, rec.effective_vol_mc_ratio, rec.effective_buy_pressure,
            rec.buyer_quality, rec.liquidity_quality, rec.holder_quality, rec.breakout_quality,
            rec.wallet_independence, rec.wash_trade_risk, rec.cabal_risk_score, rec.dev_risk_score,
            rec.contract_risk, rec.liquidity_risk, rec.p_reach_50k, rec.p_reach_100k, rec.p_reach_250k,
            rec.p_reach_500k, rec.p_reach_1m, rec.p_reach_3m, rec.p_reach_5m, rec.p_100k_15m,
            rec.p_100k_1h, rec.p_100k_6h, rec.p_100k_24h, rec.p_3m_15m, rec.p_3m_1h,
            rec.p_3m_6h, rec.p_3m_24h, rec.p_rug, rec.p_manipulation, rec.data_confidence,
            rec.market_regime, rec.signal_state, int(rec.is_alert_candidate), rec.model_score,
            rec.model_percentile_rank
        )

    def record_candidate(
        self,
        cand: TokenCandidate,
        pred: BreakoutPredictionOutput,
        regime: str = "NORMAL",
        signal_state: str = "NEW",
    ) -> ShadowUniverseRecord:
        """
        Record a token entering the $8K-$35K discovery universe into the true denominator.
        """
        records = self.record_candidates_batch([(cand, pred, regime, signal_state)])
        return records[0]

    def record_candidates_batch(
        self,
        items: List[Tuple[TokenCandidate, BreakoutPredictionOutput, str, str]],
    ) -> List[ShadowUniverseRecord]:
        """
        Batch record candidates in a single SQLite transaction and single JSONL write.
        Eliminates per-candidate disk I/O lockups and virtual disk thrashing.
        """
        if not items:
            return []

        recs = [self.build_record(cand, pred, regime, sig_state) for cand, pred, regime, sig_state in items]
        sql = """
            INSERT OR REPLACE INTO shadow_tokens (
                token_address, symbol, chain, venue, discovery_timestamp, scanner_version,
                model_version, token_age_minutes, pool_age_minutes, time_since_first_trade_min,
                trade_count, holder_count, market_cap_usd, fdv_usd, liquidity_usd, price_usd,
                volume_5m_usd, volume_1h_usd, unique_buyers, unique_sellers,
                effective_vol_mc_ratio, effective_buy_pressure, buyer_quality, liquidity_quality,
                holder_quality, breakout_quality, wallet_independence, wash_trade_risk,
                cabal_risk_score, dev_risk_score, contract_risk, liquidity_risk,
                p_reach_50k, p_reach_100k, p_reach_250k, p_reach_500k, p_reach_1m, p_reach_3m,
                p_reach_5m, p_100k_15m, p_100k_1h, p_100k_6h, p_100k_24h, p_3m_15m,
                p_3m_1h, p_3m_6h, p_3m_24h, p_rug, p_manipulation, data_confidence,
                market_regime, signal_state, is_alert_candidate, model_score, model_percentile_rank
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        tuples = [self._rec_to_tuple(r) for r in recs]

        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            cursor = conn.cursor()
            cursor.executemany(sql, tuples)
            conn.commit()

        # Batch append to JSONL stream
        try:
            with open(self.jsonl_path, "a", encoding="utf-8") as f:
                f.write("".join(json.dumps(asdict(r)) + "\n" for r in recs))
        except Exception as e:
            logger.warning(f"Could not append batch to shadow JSONL: {e}")

        return recs

    def load_all_shadow_tokens(self) -> List[Dict[str, Any]]:
        """Load all recorded tokens from SQLite shadow universe."""
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM shadow_tokens ORDER BY discovery_timestamp ASC")
            return [dict(row) for row in cursor.fetchall()]

    def load_recent_shadow_tokens(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Fast query loading only the most recent tokens for instant UI startup."""
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM shadow_tokens ORDER BY discovery_timestamp DESC LIMIT ?", (limit,))
            return [dict(row) for row in cursor.fetchall()]
