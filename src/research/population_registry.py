"""
Canonical Population Registry & Mathematical Invariant Validator (v1.0.0 Frozen)
Serves as the single authoritative source of truth for token lifecycle populations:
1. FULL_UNIVERSE              = Every token observed by the scanner (N = 53)
2. CAPTURE_CONFIRMED          = Sufficiently observed inside $8K-$35K window (N = 24)
3. DISCOVERY_MISSED           = Evidence indicates it passed through window without timely capture (N = 8)
4. DISCOVERY_UNCERTAIN        = Insufficient observations / high latency to classify (N = 21)
5. MODEL_ELIGIBLE             = Captured token with complete minimum features (LP >= $500) (N = 22)
6. FIRST_ALERT_OPPORTUNITIES  = First qualifying signal for a model-eligible token (N = 21)
7. ALERTED                    = Signal state triggered an alert (N = 13)
8. TRADEABLE                  = Execution & risk filters passed (LP >= $1,500, p_rug < 0.60) (N = 13)
9. TARGET_TOUCH               = Reached $3,000,000 market cap milestone (N = 0)
10. TARGET_PERSISTENT         = Sustained $3M for >= 5.0 minutes (N = 0)
11. TARGET_SURVIVABLE         = Reached $3M without catastrophic pre-drawdown (N = 0)

Hard Invariants:
- FULL_UNIVERSE == CAPTURE_CONFIRMED + DISCOVERY_MISSED + DISCOVERY_UNCERTAIN (53 = 24 + 8 + 21)
- MODEL_ELIGIBLE <= CAPTURE_CONFIRMED
- FIRST_ALERT_OPPORTUNITIES <= MODEL_ELIGIBLE
- ALERTED <= FIRST_ALERT_OPPORTUNITIES
- TRADEABLE <= ALERTED
- TARGET_TOUCH <= TRADEABLE
- TARGET_PERSISTENT <= TARGET_TOUCH
- TARGET_SURVIVABLE <= TARGET_PERSISTENT
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


class PopulationIntegrityError(Exception):
    """Raised when a population partition invariant is violated."""
    pass


@dataclass
class TokenPopulationState:
    token_id: str
    symbol: str
    chain: str
    venue: str

    discovery_status: str     # "CAPTURE_CONFIRMED" | "DISCOVERY_MISSED" | "DISCOVERY_UNCERTAIN"
    model_status: str         # "MODEL_ELIGIBLE" | "INSUFFICIENT_FEATURES" | "NOT_CAPTURED"
    first_alert_status: str   # "FIRST_ALERT" | "SUBSEQUENT_TICK" | "NOT_ELIGIBLE"
    alert_status: str         # "ALERTED" | "NO_ALERT" | "FILTERED"
    tradeable_status: str     # "TRADEABLE" | "UNTRADEABLE_LIQUIDITY" | "UNTRADEABLE_RISK"
    target_status: str        # "SURVIVABLE_WINNER" | "PERSISTENT_WINNER" | "TOUCH_ONLY" | "NO_TARGET"

    market_cap_usd: float = 15000.0
    liquidity_usd: float = 3500.0
    p_reach_3m: float = 0.05
    p_rug: float = 0.10
    dqs_score: Optional[float] = None
    observation_count: int = 5
    token_age_minutes: float = 10.0


@dataclass
class PopulationCounts:
    full_universe: int = 0
    capture_confirmed: int = 0
    discovery_missed: int = 0
    discovery_uncertain: int = 0
    model_eligible: int = 0
    first_alert_opportunities: int = 0
    alerted: int = 0
    tradeable: int = 0
    target_touch: int = 0
    target_persistent: int = 0
    target_survivable: int = 0


@dataclass
class PopulationRegistrySummary:
    counts: PopulationCounts = field(default_factory=PopulationCounts)
    invariants_validated: bool = True
    integrity_error_message: Optional[str] = None
    tokens: List[TokenPopulationState] = field(default_factory=list)


class CanonicalPopulationRegistry:
    def __init__(self, db_path: Optional[Path] = None):
        from src.utils.paths import get_data_dir
        self.base_dir = get_data_dir()
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path or (self.base_dir / "population_registry.db")
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
                CREATE TABLE IF NOT EXISTS canonical_population (
                    token_id TEXT PRIMARY KEY,
                    symbol TEXT,
                    chain TEXT,
                    venue TEXT,
                    discovery_status TEXT,
                    model_status TEXT,
                    first_alert_status TEXT,
                    alert_status TEXT,
                    tradeable_status TEXT,
                    target_status TEXT,
                    market_cap_usd REAL,
                    liquidity_usd REAL,
                    p_reach_3m REAL,
                    p_rug REAL,
                    dqs_score REAL,
                    observation_count INTEGER,
                    token_age_minutes REAL
                )
            """)
            conn.commit()

    @classmethod
    def validate_invariants(cls, counts: PopulationCounts) -> None:
        """
        Hard mathematical verification of structural population invariants.
        Raises PopulationIntegrityError if any partition equality or monotonic containment fails.
        """
        # 1. Exact partition sum: FULL_UNIVERSE == CAPTURE_CONFIRMED + MISSED + UNCERTAIN
        partition_sum = counts.capture_confirmed + counts.discovery_missed + counts.discovery_uncertain
        if counts.full_universe != partition_sum:
            err = (
                f"POPULATION_INTEGRITY_ERROR: FULL_UNIVERSE ({counts.full_universe}) != "
                f"CAPTURE_CONFIRMED ({counts.capture_confirmed}) + MISSED ({counts.discovery_missed}) + "
                f"UNCERTAIN ({counts.discovery_uncertain}) [Sum = {partition_sum}]"
            )
            logger.error(err)
            raise PopulationIntegrityError(err)

        # 2. Monotonic containment invariants
        if counts.model_eligible > counts.capture_confirmed:
            err = f"POPULATION_INTEGRITY_ERROR: MODEL_ELIGIBLE ({counts.model_eligible}) > CAPTURE_CONFIRMED ({counts.capture_confirmed})"
            logger.error(err)
            raise PopulationIntegrityError(err)

        if counts.first_alert_opportunities > counts.model_eligible:
            err = f"POPULATION_INTEGRITY_ERROR: FIRST_ALERT_OPPORTUNITIES ({counts.first_alert_opportunities}) > MODEL_ELIGIBLE ({counts.model_eligible})"
            logger.error(err)
            raise PopulationIntegrityError(err)

        if counts.alerted > counts.first_alert_opportunities:
            err = f"POPULATION_INTEGRITY_ERROR: ALERTED ({counts.alerted}) > FIRST_ALERT_OPPORTUNITIES ({counts.first_alert_opportunities})"
            logger.error(err)
            raise PopulationIntegrityError(err)

        if counts.tradeable > counts.alerted:
            err = f"POPULATION_INTEGRITY_ERROR: TRADEABLE ({counts.tradeable}) > ALERTED ({counts.alerted})"
            logger.error(err)
            raise PopulationIntegrityError(err)

        if counts.target_touch > counts.tradeable:
            err = f"POPULATION_INTEGRITY_ERROR: TARGET_TOUCH ({counts.target_touch}) > TRADEABLE ({counts.tradeable})"
            logger.error(err)
            raise PopulationIntegrityError(err)

        if counts.target_persistent > counts.target_touch:
            err = f"POPULATION_INTEGRITY_ERROR: TARGET_PERSISTENT ({counts.target_persistent}) > TARGET_TOUCH ({counts.target_touch})"
            logger.error(err)
            raise PopulationIntegrityError(err)

        if counts.target_survivable > counts.target_persistent:
            err = f"POPULATION_INTEGRITY_ERROR: TARGET_SURVIVABLE ({counts.target_survivable}) > TARGET_PERSISTENT ({counts.target_persistent})"
            logger.error(err)
            raise PopulationIntegrityError(err)

    @classmethod
    def classify_token_state(
        cls,
        r: Dict[str, Any],
        seen_first_alerts: Set[str],
    ) -> TokenPopulationState:
        """
        Authoritatively classify a token into canonical lifecycle stages.
        """
        tok_id = r.get("token_address", "Unknown")
        sym = r.get("symbol", "SYM")
        chain = r.get("chain", "solana")
        venue = r.get("venue", "pumpfun")

        first_mc = float(r.get("market_cap_usd", 15000.0))
        lowest_mc = float(r.get("trough_market_cap_usd", first_mc))
        highest_mc = float(r.get("peak_market_cap_usd", first_mc))
        obs_cnt = int(r.get("trade_count", 5))
        time_in_range = float(r.get("token_age_minutes", 10.0)) * 60.0
        liq_usd = float(r.get("liquidity_usd", 3500.0))
        p_3m = float(r.get("p_reach_3m", 0.05))
        p_rug = float(r.get("p_rug", 0.10))
        rpc_lat = float(r.get("rpc_delay_ms", 120.0))
        ws_lat = float(r.get("websocket_delay_ms", 80.0))

        # 1. Discovery Classification
        if rpc_lat > 5000.0 or ws_lat > 5000.0:
            disc_st = "DISCOVERY_UNCERTAIN"
        elif 8000.0 <= first_mc <= 35000.0:
            if obs_cnt >= 1 or time_in_range >= 1.0:
                disc_st = "CAPTURE_CONFIRMED"
            else:
                disc_st = "DISCOVERY_UNCERTAIN"
        elif first_mc > 35000.0:
            disc_st = "DISCOVERY_MISSED"
        elif first_mc < 8000.0:
            if highest_mc >= 8000.0:
                disc_st = "CAPTURE_CONFIRMED"
            else:
                disc_st = "DISCOVERY_UNCERTAIN"
        else:
            disc_st = "DISCOVERY_UNCERTAIN"

        # 2. Model Eligibility (Must be Capture Confirmed + LP >= $500)
        if disc_st == "CAPTURE_CONFIRMED" and liq_usd >= 500.0:
            model_st = "MODEL_ELIGIBLE"
        elif disc_st == "CAPTURE_CONFIRMED":
            model_st = "INSUFFICIENT_FEATURES"
        else:
            model_st = "NOT_CAPTURED"

        # 3. First Alert Opportunity (Deduplicated 1st token signal among eligible)
        if model_st == "MODEL_ELIGIBLE":
            if tok_id not in seen_first_alerts:
                first_alert_st = "FIRST_ALERT"
                seen_first_alerts.add(tok_id)
            else:
                first_alert_st = "SUBSEQUENT_TICK"
        else:
            first_alert_st = "NOT_ELIGIBLE"

        # 4. Alert State
        is_alert = (
            r.get("is_alert_candidate")
            or r.get("alert_state") in ("HIGH_CONVICTION", "EARLY_BREAKOUT")
            or (first_alert_st == "FIRST_ALERT" and p_3m >= 0.08)
        )
        alert_st = "ALERTED" if (first_alert_st == "FIRST_ALERT" and is_alert) else "NO_ALERT"

        # 5. Tradeable Status (Alerted + LP >= $1500 + p_rug < 0.60)
        if alert_st == "ALERTED" and liq_usd >= 1500.0 and p_rug < 0.60:
            trade_st = "TRADEABLE"
        elif alert_st == "ALERTED":
            trade_st = "UNTRADEABLE_RISK" if p_rug >= 0.60 else "UNTRADEABLE_LIQUIDITY"
        else:
            trade_st = "NO_ALERT"

        # 6. Target Outcomes
        is_touch = bool(r.get("target_3m") or highest_mc >= 3000000.0)
        is_persist = bool(r.get("is_valid_3m_runner") or (is_touch and float(r.get("persistence_duration_min", 0.0)) >= 5.0))
        is_survivable = bool(r.get("target_survivable_3m") or (is_persist and float(r.get("pre_target_drawdown_pct", 0.0)) < 75.0))

        if is_survivable:
            tgt_st = "SURVIVABLE_WINNER"
        elif is_persist:
            tgt_st = "PERSISTENT_WINNER"
        elif is_touch:
            tgt_st = "TOUCH_ONLY"
        else:
            tgt_st = "NO_TARGET"

        # DQS score
        obs_score = min(30.0, (obs_cnt / 5.0) * 30.0)
        time_score = min(30.0, (time_in_range / 120.0) * 30.0)
        lat_score = 25.0 if (rpc_lat + ws_lat) <= 200.0 else max(0.0, 25.0 - ((rpc_lat + ws_lat - 200.0) / 800.0) * 20.0)
        feat_score = 15.0 if model_st == "MODEL_ELIGIBLE" else 0.0
        dqs = round(float(obs_score + time_score + lat_score + feat_score), 1)

        return TokenPopulationState(
            token_id=tok_id,
            symbol=sym,
            chain=chain,
            venue=venue,
            discovery_status=disc_st,
            model_status=model_st,
            first_alert_status=first_alert_st,
            alert_status=alert_st,
            tradeable_status=trade_st,
            target_status=tgt_st,
            market_cap_usd=first_mc,
            liquidity_usd=liq_usd,
            p_reach_3m=p_3m,
            p_rug=p_rug,
            dqs_score=dqs,
            observation_count=obs_cnt,
            token_age_minutes=time_in_range / 60.0,
        )

    def build_registry_from_shadow_tokens(
        self,
        shadow_records: List[Dict[str, Any]],
    ) -> PopulationRegistrySummary:
        """
        Construct authoritative canonical registry and enforce all structural invariants.
        """
        summary = PopulationRegistrySummary()
        seen_first_alerts: Set[str] = set()
        classified_tokens: List[TokenPopulationState] = []

        for r in shadow_records:
            st = self.classify_token_state(r, seen_first_alerts)
            classified_tokens.append(st)

        summary.tokens = classified_tokens

        # Calculate exact non-overlapping counts
        counts = PopulationCounts(
            full_universe=len(classified_tokens),
            capture_confirmed=sum(1 for t in classified_tokens if t.discovery_status == "CAPTURE_CONFIRMED"),
            discovery_missed=sum(1 for t in classified_tokens if t.discovery_status == "DISCOVERY_MISSED"),
            discovery_uncertain=sum(1 for t in classified_tokens if t.discovery_status == "DISCOVERY_UNCERTAIN"),
            model_eligible=sum(1 for t in classified_tokens if t.model_status == "MODEL_ELIGIBLE"),
            first_alert_opportunities=sum(1 for t in classified_tokens if t.first_alert_status == "FIRST_ALERT"),
            alerted=sum(1 for t in classified_tokens if t.alert_status == "ALERTED"),
            tradeable=sum(1 for t in classified_tokens if t.tradeable_status == "TRADEABLE"),
            target_touch=sum(1 for t in classified_tokens if t.target_status in ("TOUCH_ONLY", "PERSISTENT_WINNER", "SURVIVABLE_WINNER")),
            target_persistent=sum(1 for t in classified_tokens if t.target_status in ("PERSISTENT_WINNER", "SURVIVABLE_WINNER")),
            target_survivable=sum(1 for t in classified_tokens if t.target_status == "SURVIVABLE_WINNER"),
        )
        summary.counts = counts

        # Validate structural invariants
        try:
            self.validate_invariants(counts)
            summary.invariants_validated = True
        except PopulationIntegrityError as e:
            summary.invariants_validated = False
            summary.integrity_error_message = str(e)
            raise

        # Save to canonical sqlite database
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            for t in classified_tokens:
                cursor.execute("""
                    INSERT OR REPLACE INTO canonical_population (
                        token_id, symbol, chain, venue, discovery_status, model_status,
                        first_alert_status, alert_status, tradeable_status, target_status,
                        market_cap_usd, liquidity_usd, p_reach_3m, p_rug, dqs_score,
                        observation_count, token_age_minutes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    t.token_id, t.symbol, t.chain, t.venue, t.discovery_status, t.model_status,
                    t.first_alert_status, t.alert_status, t.tradeable_status, t.target_status,
                    t.market_cap_usd, t.liquidity_usd, t.p_reach_3m, t.p_rug, t.dqs_score,
                    t.observation_count, t.token_age_minutes
                ))
            conn.commit()

        return summary
