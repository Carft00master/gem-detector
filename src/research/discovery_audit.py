"""
Discovery-Capture, Failure Cause Decomposition & Ingestion Latency Auditor (v1.0.0 Frozen)
Audits the complete Discovery -> Ingestion -> Evaluation pipeline.
Explicit Population Datasets:
1. FULL_UNIVERSE: Total tokens discovered entering $8K-$35K window.
2. CAPTURE_CONFIRMED: Promptly observed inside $8K-$35K with >= 2 data points.
3. DISCOVERY_MISSED: First observed above $35K without prompt capture.
4. DISCOVERY_UNCERTAIN: Single-tick transient moves or latency > 5000ms.
5. MODEL_ELIGIBLE: Capture-confirmed tokens with complete order-flow/price features.
6. FIRST_ALERT_OPPORTUNITIES: Deduplicated first alert generated per token.

11 Failure Cause Codes:
- RPC_LATENCY
- WEBSOCKET_GAP
- POLLING_GAP
- POOL_DISCOVERY_DELAY
- PRICE_CALCULATION_DELAY
- MC_CALCULATION_DELAY
- POOL_MIGRATION
- API_FAILURE
- DATA_MISSING
- INSUFFICIENT_OBSERVATIONS
- OTHER

Computes Discovery Quality Score (0-100) and Discovery Recall.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

logger = logging.getLogger(__name__)


class DiscoveryFailureCause:
    RPC_LATENCY = "RPC_LATENCY"
    WEBSOCKET_GAP = "WEBSOCKET_GAP"
    POLLING_GAP = "POLLING_GAP"
    POOL_DISCOVERY_DELAY = "POOL_DISCOVERY_DELAY"
    PRICE_CALCULATION_DELAY = "PRICE_CALCULATION_DELAY"
    MC_CALCULATION_DELAY = "MC_CALCULATION_DELAY"
    POOL_MIGRATION = "POOL_MIGRATION"
    API_FAILURE = "API_FAILURE"
    DATA_MISSING = "DATA_MISSING"
    INSUFFICIENT_OBSERVATIONS = "INSUFFICIENT_OBSERVATIONS"
    OTHER = "OTHER"


@dataclass
class DiscoveryRecord:
    token_address: str
    symbol: str
    chain: str
    venue: str

    pool_creation_timestamp: Optional[str] = None
    first_observed_timestamp: Optional[str] = None
    first_observed_mc_usd: float = 0.0
    lowest_observed_mc_usd: float = 0.0
    highest_observed_mc_usd: float = 0.0

    time_spent_in_discovery_range_sec: float = 0.0
    observation_count_in_range: int = 0
    poll_interval_sec: float = 3.0
    websocket_delay_ms: float = 80.0
    rpc_delay_ms: float = 120.0

    discovery_status: str = "DISCOVERY_CAPTURED"  # "DISCOVERY_CAPTURED" | "DISCOVERY_LATE" | "DISCOVERY_MISSED" | "DISCOVERY_UNCERTAIN"
    discovery_quality_score: float = 85.0         # 0 - 100
    failure_cause_code: Optional[str] = None      # DiscoveryFailureCause enum
    time_lost_before_capture_sec: float = 0.0
    audit_notes: List[str] = field(default_factory=list)


@dataclass
class FailureCauseBreakdownRow:
    cause_code: str
    count: int = 0
    percentage: float = 0.0
    median_latency_ms: float = 0.0
    median_time_lost_sec: float = 0.0


@dataclass
class PopulationSubsetsSummary:
    full_universe_count: int = 0
    capture_confirmed_count: int = 0
    discovery_missed_count: int = 0
    discovery_uncertain_count: int = 0
    model_eligible_count: int = 0
    first_alert_opportunities_count: int = 0


@dataclass
class DiscoveryAuditSummary:
    total_tokens_evaluated: int = 0
    discovery_captured_count: int = 0
    discovery_late_count: int = 0
    discovery_missed_count: int = 0
    discovery_uncertain_count: int = 0

    universe_capture_rate_pct: float = 0.0
    discovery_recall_pct: float = 0.0
    discovery_late_rate_pct: float = 0.0
    discovery_miss_rate_pct: float = 0.0
    discovery_uncertain_rate_pct: float = 0.0

    median_discovery_quality_score: float = 0.0
    median_dqs_capture_confirmed: float = 0.0
    median_dqs_full_universe: float = 0.0
    dqs_coverage_pct: float = 100.0
    median_time_in_range_sec: float = 0.0
    median_time_to_discovery_sec: float = 0.0
    median_rpc_latency_ms: float = 0.0
    median_websocket_latency_ms: float = 0.0

    population_subsets: PopulationSubsetsSummary = field(default_factory=PopulationSubsetsSummary)
    failure_causes: List[FailureCauseBreakdownRow] = field(default_factory=list)
    records: List[DiscoveryRecord] = field(default_factory=list)


class DiscoveryCaptureAuditor:
    def __init__(self, db_path: Optional[Path] = None):
        from src.utils.paths import get_data_dir
        self.base_dir = get_data_dir()
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path or (self.base_dir / "discovery_audit.db")
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("PRAGMA journal_mode=WAL;")
            except Exception as e:
                logger.warning(f"Failed to set journal_mode=WAL for {self.db_path}: {e}")
            cursor.execute("PRAGMA synchronous=NORMAL;")
            cursor.execute("PRAGMA busy_timeout=30000;")
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS discovery_events (
                    token_address TEXT PRIMARY KEY,
                    symbol TEXT,
                    chain TEXT,
                    venue TEXT,
                    pool_creation_timestamp TEXT,
                    first_observed_timestamp TEXT,
                    first_observed_mc_usd REAL,
                    lowest_observed_mc_usd REAL,
                    highest_observed_mc_usd REAL,
                    time_spent_in_discovery_range_sec REAL,
                    observation_count_in_range INTEGER,
                    poll_interval_sec REAL,
                    websocket_delay_ms REAL,
                    rpc_delay_ms REAL,
                    discovery_status TEXT,
                    discovery_quality_score REAL,
                    failure_cause_code TEXT,
                    time_lost_before_capture_sec REAL
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_disc_status ON discovery_events(discovery_status)")
            
            # Auto-migrate any missing columns
            cursor.execute("PRAGMA table_info(discovery_events)")
            existing_cols = {row[1] for row in cursor.fetchall()}
            required_cols = {
                "discovery_quality_score": "REAL",
                "failure_cause_code": "TEXT",
                "time_lost_before_capture_sec": "REAL",
            }
            for col_name, col_type in required_cols.items():
                if col_name not in existing_cols:
                    cursor.execute(f"ALTER TABLE discovery_events ADD COLUMN {col_name} {col_type}")
            conn.commit()

    @classmethod
    def calculate_telemetry_quality_score(
        cls,
        rpc_latency_ms: float,
        websocket_latency_ms: float,
        has_complete_features: bool = True,
        is_pool_state_complete: bool = True,
        is_wallet_data_complete: bool = True,
    ) -> float:
        """
        Compute TELEMETRY_QUALITY_SCORE (0 - 100):
        Measures stream transport delay, RPC freshness, and data packet integrity.
        """
        # 1. Latency score (0-50 pts)
        tot_lat = rpc_latency_ms + websocket_latency_ms
        if tot_lat <= 200.0:
            lat_score = 50.0
        elif tot_lat <= 1000.0:
            lat_score = max(10.0, 50.0 - ((tot_lat - 200.0) / 800.0) * 40.0)
        else:
            lat_score = 0.0

        # 2. Vector Completeness (0-50 pts)
        feat_score = 20.0 if has_complete_features else 0.0
        pool_score = 15.0 if is_pool_state_complete else 0.0
        wallet_score = 15.0 if is_wallet_data_complete else 0.0

        return round(float(np.clip(lat_score + feat_score + pool_score + wallet_score, 0.0, 100.0)), 1)

    @classmethod
    def calculate_discovery_capture_quality(
        cls,
        time_in_range_sec: float,
        observation_count: int,
        delay_from_true_entry_sec: float = 0.0,
        mc_crossed_range: bool = True,
    ) -> float:
        """
        Compute DISCOVERY_CAPTURE_QUALITY (0 - 100):
        Measures observation persistence and fidelity inside the $8K-$35K window.
        """
        # 1. Observation Frequency (0-40 pts)
        obs_score = min(40.0, (observation_count / 5.0) * 40.0)

        # 2. Time in Window (0-40 pts)
        time_score = min(40.0, (time_in_range_sec / 120.0) * 40.0)

        # 3. Entry Delay Penalty (0-20 pts)
        if delay_from_true_entry_sec <= 5.0 and mc_crossed_range:
            entry_score = 20.0
        else:
            entry_score = max(0.0, 20.0 - (delay_from_true_entry_sec / 30.0) * 20.0)

        return round(float(np.clip(obs_score + time_score + entry_score, 0.0, 100.0)), 1)

    @classmethod
    def calculate_discovery_quality_score(
        cls,
        observation_count: int,
        time_in_range_sec: float,
        rpc_latency_ms: float,
        websocket_latency_ms: float,
        has_complete_features: bool = True,
    ) -> float:
        """
        Compute Discovery Quality Score (0 - 100) strictly separate from Model Probability:
        - Observation continuity (0-30 pts)
        - Time spent in discovery range (0-30 pts)
        - Ingestion freshness / latency (0-25 pts)
        - Feature completeness (0-15 pts)
        """
        obs_score = min(30.0, (observation_count / 5.0) * 30.0)
        time_score = min(30.0, (time_in_range_sec / 120.0) * 30.0)

        tot_lat = rpc_latency_ms + websocket_latency_ms
        if tot_lat <= 200.0:
            lat_score = 25.0
        elif tot_lat <= 1000.0:
            lat_score = max(5.0, 25.0 - ((tot_lat - 200.0) / 800.0) * 20.0)
        else:
            lat_score = 0.0

        feat_score = 15.0 if has_complete_features else 0.0
        return round(float(np.clip(obs_score + time_score + lat_score + feat_score, 0.0, 100.0)), 1)

    @classmethod
    def classify_token_discovery(
        cls,
        first_mc: float,
        lowest_mc: float,
        highest_mc: float,
        observation_count: int,
        time_in_range_sec: float,
        rpc_latency_ms: float = 120.0,
        websocket_latency_ms: float = 80.0,
    ) -> Tuple[str, Optional[str], float, List[str]]:
        """
        Classify whether token was captured inside $8K-$35K and diagnose failure cause code.
        Returns (status, failure_cause_code, time_lost_sec, notes).
        """
        notes = []
        time_lost = 0.0
        cause = None

        if rpc_latency_ms > 5000.0:
            notes.append("EXCESSIVE_RPC_LATENCY (>5000ms)")
            return "DISCOVERY_UNCERTAIN", DiscoveryFailureCause.RPC_LATENCY, 15.0, notes
        if websocket_latency_ms > 5000.0:
            notes.append("EXCESSIVE_WEBSOCKET_LATENCY (>5000ms)")
            return "DISCOVERY_UNCERTAIN", DiscoveryFailureCause.WEBSOCKET_GAP, 15.0, notes

        # 1. Captured inside discovery window
        if 8000.0 <= first_mc <= 35000.0:
            if observation_count >= 2 or time_in_range_sec >= 10.0:
                notes.append("PROMPT_DISCOVERY_IN_WINDOW")
                return "DISCOVERY_CAPTURED", None, 0.0, notes
            else:
                notes.append("TRANSIENT_FAST_MOVE (Single Tick)")
                return "DISCOVERY_UNCERTAIN", DiscoveryFailureCause.INSUFFICIENT_OBSERVATIONS, 5.0, notes

        # 2. Late discovery (First seen above $35K)
        elif first_mc > 35000.0:
            if lowest_mc <= 35000.0:
                notes.append("DISCOVERED_LATE_AFTER_LAUNCH")
                time_lost = max(5.0, (first_mc - 35000.0) / 1000.0 * 2.0)
                return "DISCOVERY_LATE", DiscoveryFailureCause.POLLING_GAP, time_lost, notes
            else:
                notes.append("BYPASSED_DISCOVERY_RANGE")
                time_lost = max(10.0, (first_mc - 35000.0) / 1000.0 * 3.0)
                return "DISCOVERY_MISSED", DiscoveryFailureCause.POOL_DISCOVERY_DELAY, time_lost, notes

        # 3. Sub-8K launch (Ramping up)
        elif first_mc < 8000.0:
            if highest_mc >= 8000.0:
                notes.append("RAMPED_INTO_DISCOVERY_WINDOW")
                return "DISCOVERY_CAPTURED", None, 0.0, notes
            else:
                notes.append("SUB_WINDOW_MICROCAP")
                return "DISCOVERY_UNCERTAIN", DiscoveryFailureCause.INSUFFICIENT_OBSERVATIONS, 0.0, notes

        return "DISCOVERY_UNCERTAIN", DiscoveryFailureCause.OTHER, 0.0, notes

    def record_discovery(self, rec: DiscoveryRecord) -> None:
        self.record_discovery_batch([rec])

    def record_discovery_batch(self, records: List[DiscoveryRecord]) -> None:
        if not records:
            return
        params = [
            (
                rec.token_address, rec.symbol, rec.chain, rec.venue, rec.pool_creation_timestamp,
                rec.first_observed_timestamp, rec.first_observed_mc_usd, rec.lowest_observed_mc_usd,
                rec.highest_observed_mc_usd, rec.time_spent_in_discovery_range_sec,
                rec.observation_count_in_range, rec.poll_interval_sec, rec.websocket_delay_ms,
                rec.rpc_delay_ms, rec.discovery_status, rec.discovery_quality_score,
                rec.failure_cause_code, rec.time_lost_before_capture_sec
            )
            for rec in records
        ]
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.executemany("""
                    INSERT OR REPLACE INTO discovery_events (
                        token_address, symbol, chain, venue, pool_creation_timestamp,
                        first_observed_timestamp, first_observed_mc_usd, lowest_observed_mc_usd,
                        highest_observed_mc_usd, time_spent_in_discovery_range_sec,
                        observation_count_in_range, poll_interval_sec, websocket_delay_ms,
                        rpc_delay_ms, discovery_status, discovery_quality_score,
                        failure_cause_code, time_lost_before_capture_sec
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, params)
                conn.commit()
        except Exception as e:
            logger.debug(f"Error saving discovery events batch: {e}")

    def audit_ingestion_population(self, shadow_records: List[Dict[str, Any]]) -> DiscoveryAuditSummary:
        """
        Audit discovery capture rate and cause breakdowns across the full shadow population.
        """
        summary = DiscoveryAuditSummary(total_tokens_evaluated=len(shadow_records))
        if not shadow_records:
            return summary

        captured = 0
        late = 0
        missed = 0
        uncertain = 0
        eligible = 0
        times_in_range = []
        lead_times = []
        dqs_scores = []
        rpc_latencies = []
        ws_latencies = []
        records_list = []
        cause_map: Dict[str, List[Tuple[float, float]]] = {}  # cause -> [(latency, time_lost)]

        for r in shadow_records:
            first_mc = float(r.get("market_cap_usd", 15000.0))
            low_mc = float(r.get("trough_market_cap_usd", first_mc))
            high_mc = float(r.get("peak_market_cap_usd", first_mc))
            obs_cnt = int(r.get("trade_count", 5))
            time_in_range = float(r.get("token_age_minutes", 10.0)) * 60.0
            rpc_lat = float(r.get("rpc_delay_ms", 120.0))
            ws_lat = float(r.get("websocket_delay_ms", 80.0))

            status, cause, time_lost, notes = self.classify_token_discovery(
                first_mc=first_mc,
                lowest_mc=low_mc,
                highest_mc=high_mc,
                observation_count=obs_cnt,
                time_in_range_sec=time_in_range,
                rpc_latency_ms=rpc_lat,
                websocket_latency_ms=ws_lat,
            )

            dqs = self.calculate_discovery_quality_score(
                observation_count=obs_cnt,
                time_in_range_sec=time_in_range,
                rpc_latency_ms=rpc_lat,
                websocket_latency_ms=ws_lat,
                has_complete_features=True,
            )
            dqs_scores.append(dqs)

            if status == "DISCOVERY_CAPTURED":
                captured += 1
                if obs_cnt >= 2 and float(r.get("liquidity_usd", 1000.0)) >= 500.0:
                    eligible += 1
            elif status == "DISCOVERY_LATE":
                late += 1
            elif status == "DISCOVERY_MISSED":
                missed += 1
            else:
                uncertain += 1

            if cause:
                if cause not in cause_map:
                    cause_map[cause] = []
                cause_map[cause].append((rpc_lat + ws_lat, time_lost))

            times_in_range.append(time_in_range)
            rpc_latencies.append(rpc_lat)
            ws_latencies.append(ws_lat)

            rec = DiscoveryRecord(
                token_address=r.get("token_address", "Unknown"),
                symbol=r.get("symbol", "SYM"),
                chain=r.get("chain", "solana"),
                venue=r.get("venue", "pumpfun"),
                first_observed_timestamp=r.get("discovery_timestamp"),
                first_observed_mc_usd=first_mc,
                lowest_observed_mc_usd=low_mc,
                highest_observed_mc_usd=high_mc,
                time_spent_in_discovery_range_sec=time_in_range,
                observation_count_in_range=obs_cnt,
                websocket_delay_ms=ws_lat,
                rpc_delay_ms=rpc_lat,
                discovery_status=status,
                discovery_quality_score=dqs,
                failure_cause_code=cause,
                time_lost_before_capture_sec=time_lost,
                audit_notes=notes,
            )
            records_list.append(rec)

        # Batch record all discovery events in one single transaction
        self.record_discovery_batch(records_list)

        tot = len(shadow_records)
        summary.discovery_captured_count = captured
        summary.discovery_late_count = late
        summary.discovery_missed_count = missed
        summary.discovery_uncertain_count = uncertain
        summary.records = records_list

        summary.universe_capture_rate_pct = round((captured / tot) * 100.0, 2) if tot > 0 else 0.0
        summary.discovery_late_rate_pct = round((late / tot) * 100.0, 2) if tot > 0 else 0.0
        summary.discovery_miss_rate_pct = round((missed / tot) * 100.0, 2) if tot > 0 else 0.0
        summary.discovery_uncertain_rate_pct = round((uncertain / tot) * 100.0, 2) if tot > 0 else 0.0

        # Discovery Recall: captured / (captured + missed)
        denom_recall = captured + missed
        summary.discovery_recall_pct = round((captured / denom_recall) * 100.0, 2) if denom_recall > 0 else 100.0

        summary.median_discovery_quality_score = round(float(np.median(dqs_scores)), 1) if dqs_scores else 0.0
        captured_dqs = [r.discovery_quality_score for r in records_list if r.discovery_status == "DISCOVERY_CAPTURED"]
        summary.median_dqs_capture_confirmed = round(float(np.median(captured_dqs)), 1) if captured_dqs else 0.0
        summary.median_dqs_full_universe = round(float(np.median(dqs_scores)), 1) if dqs_scores else 0.0
        summary.dqs_coverage_pct = round((len(dqs_scores) / tot) * 100.0, 2) if tot > 0 else 0.0

        summary.median_time_in_range_sec = round(float(np.median(times_in_range)), 1) if times_in_range else 0.0
        summary.median_rpc_latency_ms = round(float(np.median(rpc_latencies)), 1) if rpc_latencies else 0.0
        summary.median_websocket_latency_ms = round(float(np.median(ws_latencies)), 1) if ws_latencies else 0.0

        # Population Subsets Summary
        unique_toks = len(set(r.get("token_address", "") for r in shadow_records))
        summary.population_subsets = PopulationSubsetsSummary(
            full_universe_count=tot,
            capture_confirmed_count=captured,
            discovery_missed_count=missed,
            discovery_uncertain_count=uncertain,
            model_eligible_count=eligible,
            first_alert_opportunities_count=min(unique_toks, eligible),
        )

        # Failure Causes Breakdown
        failure_rows = []
        tot_failures = late + missed + uncertain
        for c_code, c_data in sorted(cause_map.items(), key=lambda x: len(x[1]), reverse=True):
            cnt = len(c_data)
            pct = (cnt / tot_failures * 100.0) if tot_failures > 0 else 0.0
            lats = [d[0] for d in c_data]
            losts = [d[1] for d in c_data]
            failure_rows.append(FailureCauseBreakdownRow(
                cause_code=c_code,
                count=cnt,
                percentage=round(pct, 1),
                median_latency_ms=round(float(np.median(lats)), 1) if lats else 0.0,
                median_time_lost_sec=round(float(np.median(losts)), 1) if losts else 0.0,
            ))
        summary.failure_causes = failure_rows

        return summary
