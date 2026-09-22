"""
Learning Dataset Builder (v1.0.0 Frozen)
Consumes the full empirical Shadow Universe, joins with canonical outcome maturity labels,
and produces three distinct training datasets for selection, entry, and exit learning loops:

1. Selection Dataset:
   Evaluates discovery-time token features across the entire empirical denominator (winners and losers)
   against multi-target binary milestones (100K, 500K, 1M, 3M).

2. Entry Dataset:
   Simulates 6 non-anticipative entry execution policies (IMMEDIATE, CONFIRMATION, FIRST_PULLBACK,
   HIGHER_LOW_CONFIRMATION, LIQUIDITY_EXPANSION, MOMENTUM_REENTRY) for first-alert opportunities,
   evaluating entry quality labels against slippage, MFE, MAE, and lead time.

3. Exit Dataset:
   Evaluates path-dependent closed paper trades across 5 exit policies (TRAILING_STOP, RISK_INVALIDATION,
   TIME_BASED, FIXED_TARGETS, STAGED_EXITS) to classify exit quality and execution optimality.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.paper.ledger import PaperTradingLedger
from src.research.outcome_maturity import CanonicalOutcomeMaturityEngine
from src.research.shadow import ShadowUniverseLogger
from src.version import FROZEN_VERSION_MANIFEST

logger = logging.getLogger(__name__)

# Minimum observation thresholds required before training readiness is unlocked
MIN_SELECTION_OBSERVATIONS: int = 250
MIN_ENTRY_OBSERVATIONS: int = 250
MIN_EXIT_OBSERVATIONS: int = 250

# 12 Core Model Feature Names
SELECTION_FEATURE_NAMES: List[str] = [
    "effective_vol_mc_ratio",
    "effective_buy_pressure",
    "buyer_quality",
    "liquidity_quality",
    "holder_quality",
    "breakout_quality",
    "wallet_independence",
    "wash_trade_risk",
    "cabal_risk_score",
    "dev_risk_score",
    "contract_risk",
    "liquidity_risk",
]

ENTRY_FEATURE_NAMES: List[str] = [
    "alert_market_cap_usd",
    "alert_liquidity_usd",
    "alert_price_usd",
    "token_age_minutes",
    "entry_policy",
    "entry_price_usd",
    "entry_slippage_pct",
    "mfe_pct",
    "mae_pct",
    "time_to_target_min",
    "max_drawdown_pct",
    "net_executable_return_pct",
]

EXIT_FEATURE_NAMES: List[str] = [
    "entry_price_usd",
    "exit_price_usd",
    "exit_policy",
    "realized_return_pct",
    "mfe_pct",
    "mae_pct",
    "time_in_trade_min",
    "max_drawdown_pct",
    "slippage_pct",
    "fees_usd",
]


@dataclass
class SelectionDatasetRow:
    """Row schema for discovery-time candidate selection dataset."""

    token_address: str
    symbol: str
    chain: str
    venue: str
    discovery_timestamp: str
    market_cap_usd: float
    liquidity_usd: float
    token_age_minutes: float
    volume_5m_usd: float
    volume_1h_usd: float

    # 12 Core Features
    effective_vol_mc_ratio: float
    effective_buy_pressure: float
    buyer_quality: float
    liquidity_quality: float
    holder_quality: float
    breakout_quality: float
    wallet_independence: float
    wash_trade_risk: float
    cabal_risk_score: float
    dev_risk_score: float
    contract_risk: float
    liquidity_risk: float

    # Scanner Baseline Telemetry
    scanner_selected: bool
    scanner_probability_3m: float
    scanner_score: float
    market_regime: str

    # Ground Truth Multi-Target Milestones
    target_100k: Optional[int] = None
    target_500k: Optional[int] = None
    target_1m: Optional[int] = None
    target_3m: Optional[int] = None
    outcome_status: str = "PENDING"  # "SUCCESS" | "FAILURE" | "PENDING" | "RIGHT_CENSORED"
    is_mature: bool = False


@dataclass
class EntryDatasetRow:
    """Row schema for entry execution policy optimization dataset."""

    token_address: str
    symbol: str
    chain: str
    venue: str
    alert_timestamp: str
    alert_market_cap_usd: float
    alert_liquidity_usd: float
    alert_price_usd: float
    market_regime: str
    token_age_minutes: float
    entry_policy: str  # "IMMEDIATE" | "CONFIRMATION" | "FIRST_PULLBACK" | "HIGHER_LOW_CONFIRMATION" | "LIQUIDITY_EXPANSION" | "MOMENTUM_REENTRY"
    entry_price_usd: float
    entry_slippage_pct: float
    mfe_pct: float
    mae_pct: float
    time_to_target_min: float
    max_drawdown_pct: float
    net_executable_return_pct: float
    entry_quality_label: str = "UNKNOWN"  # "GOOD_ENTRY" | "EARLY_ENTRY" | "LATE_ENTRY" | "FALSE_BREAKOUT_ENTRY" | "HIGH_SLIPPAGE_ENTRY"


@dataclass
class ExitDatasetRow:
    """Row schema for exit policy execution and trade management dataset."""

    token_address: str
    symbol: str
    entry_timestamp: str
    exit_timestamp: str
    entry_price_usd: float
    exit_price_usd: float
    exit_policy: str  # "TRAILING_STOP" | "RISK_INVALIDATION" | "TIME_BASED" | "FIXED_TARGETS" | "STAGED_EXITS"
    realized_return_pct: float
    mfe_pct: float
    mae_pct: float
    time_in_trade_min: float
    max_drawdown_pct: float
    slippage_pct: float
    fees_usd: float
    entry_market_cap_usd: float = 0.0
    exit_market_cap_usd: float = 0.0
    exit_quality_label: str = "UNKNOWN"  # "EXIT_TOO_EARLY" | "EXIT_TOO_LATE" | "CORRECT_EXIT" | "RUG_PROTECTED" | "MISSED_EXTENSION"
    market_regime: str = "NORMAL"


@dataclass
class LearningDataset:
    """Container for compiled training datasets with cryptographic schema verification."""

    dataset_version: str
    build_timestamp: str
    dataset_type: str  # "SELECTION" | "ENTRY" | "EXIT"
    total_rows: int
    mature_rows: int
    pending_rows: int
    feature_count: int
    feature_schema_hash: str
    rows: List[Dict[str, Any]] = field(default_factory=list)
    readiness_status: str = "INSUFFICIENT_TRAINING_DATA"  # "READY" | "INSUFFICIENT_TRAINING_DATA"

    def to_dict(self) -> Dict[str, Any]:
        """Serialize dataset metadata and rows to dictionary."""
        return {
            "dataset_version": self.dataset_version,
            "build_timestamp": self.build_timestamp,
            "dataset_type": self.dataset_type,
            "total_rows": self.total_rows,
            "mature_rows": self.mature_rows,
            "pending_rows": self.pending_rows,
            "feature_count": self.feature_count,
            "feature_schema_hash": self.feature_schema_hash,
            "readiness_status": self.readiness_status,
            "rows": self.rows,
        }

    def save_json(self, destination_path: Path) -> None:
        """Save dataset to JSON file with directory creation."""
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        with open(destination_path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)
        logger.info(f"Saved {self.dataset_type} dataset to {destination_path} ({self.total_rows} rows)")


class LearningDatasetBuilder:
    """
    Constructs unified empirical machine learning datasets across candidate selection,
    entry timing optimization, and exit policy execution.
    """

    ENTRY_POLICY_CONFIGS = [
        ("IMMEDIATE", 0.0, 1.00, 2.5),
        ("CONFIRMATION", 2.0, 1.06, 1.8),
        ("FIRST_PULLBACK", 5.0, 0.92, 1.2),
        ("HIGHER_LOW_CONFIRMATION", 8.0, 0.98, 1.5),
        ("LIQUIDITY_EXPANSION", 10.0, 1.10, 0.8),
        ("MOMENTUM_REENTRY", 15.0, 1.18, 2.2),
    ]

    def __init__(
        self,
        shadow_logger: Optional[ShadowUniverseLogger] = None,
        maturity_engine: Optional[CanonicalOutcomeMaturityEngine] = None,
        paper_ledger: Optional[PaperTradingLedger] = None,
    ) -> None:
        self.shadow_logger = shadow_logger or ShadowUniverseLogger()
        self.maturity_engine = maturity_engine or CanonicalOutcomeMaturityEngine()
        self.paper_ledger = paper_ledger or PaperTradingLedger()

    @staticmethod
    def _compute_schema_hash(feature_names: List[str]) -> str:
        """Compute deterministic SHA256 checksum for dataset feature schema."""
        schema_str = f"{FROZEN_VERSION_MANIFEST.feature_schema_version}:{','.join(sorted(feature_names))}"
        return hashlib.sha256(schema_str.encode("utf-8")).hexdigest()[:16]

    def _classify_outcome(self, record: Dict[str, Any]) -> Tuple[str, Dict[str, Optional[int]]]:
        """
        Classify multi-target outcomes using CanonicalOutcomeMaturityEngine.

        Returns:
            Tuple of (overall_status, targets_dict) where targets_dict maps
            target keys to 1 (SUCCESS), 0 (FAILURE), or None (PENDING/RIGHT_CENSORED).
        """
        targets_dict: Dict[str, Optional[int]] = {
            "target_100k": None,
            "target_500k": None,
            "target_1m": None,
            "target_3m": None,
        }

        # Evaluate TARGET_3M at standard 24h horizon for overall outcome status
        state_3m = self.maturity_engine.evaluate_token_maturity(
            token_record=record,
            target_name="TARGET_3M",
            horizon_name="24h",
        )
        overall_status = state_3m.outcome_status

        target_mapping = [
            ("TARGET_100K", "target_100k"),
            ("TARGET_500K", "target_500k"),
            ("TARGET_1M", "target_1m"),
            ("TARGET_3M", "target_3m"),
        ]

        for canonical_target, field_key in target_mapping:
            state = self.maturity_engine.evaluate_token_maturity(
                token_record=record,
                target_name=canonical_target,
                horizon_name="24h",
            )
            if state.outcome_status == "SUCCESS":
                targets_dict[field_key] = 1
            elif state.outcome_status == "FAILURE":
                targets_dict[field_key] = 0
            else:
                targets_dict[field_key] = None

        return overall_status, targets_dict

    @classmethod
    def _label_entry_quality(
        cls,
        mfe_pct: float,
        mae_pct: float,
        slippage_pct: float,
        time_to_target_min: float,
    ) -> str:
        """
        Assign discrete entry quality label based on price excursion and execution friction:
        - HIGH_SLIPPAGE_ENTRY: slippage > 5%
        - FALSE_BREAKOUT_ENTRY: mae < -40% AND mfe < 15%
        - GOOD_ENTRY: mfe > 50% AND mae > -20% AND slippage < 3%
        - EARLY_ENTRY: mae < -30% but eventual recovery (mfe > 30%)
        - LATE_ENTRY: mfe < 20% (missed most of the move)
        """
        if slippage_pct > 5.0:
            return "HIGH_SLIPPAGE_ENTRY"
        if mae_pct < -40.0 and mfe_pct < 15.0:
            return "FALSE_BREAKOUT_ENTRY"
        if mfe_pct > 50.0 and mae_pct > -20.0 and slippage_pct < 3.0:
            return "GOOD_ENTRY"
        if mae_pct < -30.0 and mfe_pct > 30.0:
            return "EARLY_ENTRY"
        if mfe_pct < 20.0:
            return "LATE_ENTRY"
        return "UNKNOWN"

    @classmethod
    def _label_exit_quality(
        cls,
        realized_return_pct: float,
        mfe_pct: float,
        max_drawdown_pct: float,
    ) -> str:
        """
        Assign discrete exit quality label based on trade realization efficiency:
        - MISSED_EXTENSION: MFE > 500% but realized < 100%
        - EXIT_TOO_EARLY: realized_return < 50% of MFE AND MFE > 100%
        - EXIT_TOO_LATE: realized_return < 0 AND MFE > 50%
        - RUG_PROTECTED: max_drawdown > -60% avoided (or severe drawdown avoided)
        - CORRECT_EXIT: realized_return within 30% of MFE
        """
        if mfe_pct > 500.0 and realized_return_pct < 100.0:
            return "MISSED_EXTENSION"
        if mfe_pct > 100.0 and realized_return_pct < (0.50 * mfe_pct):
            return "EXIT_TOO_EARLY"
        if realized_return_pct < 0.0 and mfe_pct > 50.0:
            return "EXIT_TOO_LATE"
        if abs(max_drawdown_pct) >= 60.0 and realized_return_pct > -60.0:
            return "RUG_PROTECTED"
        if mfe_pct > 0.0 and realized_return_pct >= (0.70 * mfe_pct):
            return "CORRECT_EXIT"
        if mfe_pct <= 0.0 and realized_return_pct >= 0.0:
            return "CORRECT_EXIT"
        return "UNKNOWN"

    def build_selection_dataset(self) -> LearningDataset:
        """
        Load all shadow tokens, join with outcome maturity labels, and produce SelectionDatasetRows.
        Sets readiness_status to 'READY' only if mature_rows >= MIN_SELECTION_OBSERVATIONS.
        """
        raw_tokens = self.shadow_logger.load_all_shadow_tokens()
        rows: List[SelectionDatasetRow] = []

        for rec in raw_tokens:
            overall_status, targets = self._classify_outcome(rec)
            is_mature = overall_status in ("SUCCESS", "FAILURE")

            row = SelectionDatasetRow(
                token_address=str(rec.get("token_address", "")),
                symbol=str(rec.get("symbol", "")),
                chain=str(rec.get("chain", "solana")),
                venue=str(rec.get("venue", "pumpfun")),
                discovery_timestamp=str(rec.get("discovery_timestamp", "")),
                market_cap_usd=float(rec.get("market_cap_usd", 0.0)),
                liquidity_usd=float(rec.get("liquidity_usd", 0.0)),
                token_age_minutes=float(rec.get("token_age_minutes", 0.0)),
                volume_5m_usd=float(rec.get("volume_5m_usd", 0.0)),
                volume_1h_usd=float(rec.get("volume_1h_usd", 0.0)),
                effective_vol_mc_ratio=float(rec.get("effective_vol_mc_ratio", 0.0)),
                effective_buy_pressure=float(rec.get("effective_buy_pressure", 0.0)),
                buyer_quality=float(rec.get("buyer_quality", 0.0)),
                liquidity_quality=float(rec.get("liquidity_quality", 0.0)),
                holder_quality=float(rec.get("holder_quality", 0.0)),
                breakout_quality=float(rec.get("breakout_quality", 0.0)),
                wallet_independence=float(rec.get("wallet_independence", 1.0)),
                wash_trade_risk=float(rec.get("wash_trade_risk", 0.0)),
                cabal_risk_score=float(rec.get("cabal_risk_score", 0.0)),
                dev_risk_score=float(rec.get("dev_risk_score", 0.0)),
                contract_risk=float(rec.get("contract_risk", 0.0)),
                liquidity_risk=float(rec.get("liquidity_risk", 0.0)),
                scanner_selected=bool(rec.get("is_alert_candidate", False)),
                scanner_probability_3m=float(rec.get("p_reach_3m", 0.0)),
                scanner_score=float(rec.get("model_score", 0.0)),
                market_regime=str(rec.get("market_regime", "NORMAL")),
                target_100k=targets.get("target_100k"),
                target_500k=targets.get("target_500k"),
                target_1m=targets.get("target_1m"),
                target_3m=targets.get("target_3m"),
                outcome_status=overall_status,
                is_mature=is_mature,
            )
            rows.append(row)

        total_rows = len(rows)
        mature_rows = sum(1 for r in rows if r.is_mature)
        pending_rows = sum(1 for r in rows if not r.is_mature)
        readiness = "READY" if mature_rows >= MIN_SELECTION_OBSERVATIONS else "INSUFFICIENT_TRAINING_DATA"
        now_str = datetime.now(timezone.utc).isoformat()
        dataset_version = f"{FROZEN_VERSION_MANIFEST.scanner_version}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"

        schema_hash = self._compute_schema_hash(SELECTION_FEATURE_NAMES)

        logger.info(
            f"Selection dataset built: {total_rows} total, {mature_rows} mature, "
            f"{pending_rows} pending (readiness: {readiness})"
        )

        return LearningDataset(
            dataset_version=dataset_version,
            build_timestamp=now_str,
            dataset_type="SELECTION",
            total_rows=total_rows,
            mature_rows=mature_rows,
            pending_rows=pending_rows,
            feature_count=len(SELECTION_FEATURE_NAMES),
            feature_schema_hash=schema_hash,
            rows=[asdict(r) for r in rows],
            readiness_status=readiness,
        )

    def build_entry_dataset(self) -> LearningDataset:
        """
        Load first-alert opportunities and simulate 6 non-anticipative entry policies per token.
        Sets readiness based on MIN_ENTRY_OBSERVATIONS threshold.
        """
        raw_tokens = self.shadow_logger.load_all_shadow_tokens()
        rows: List[EntryDatasetRow] = []

        # Filter and deduplicate first-alert opportunities
        seen_tokens = set()
        alert_opportunities: List[Dict[str, Any]] = []

        for rec in raw_tokens:
            addr = rec.get("token_address")
            if not addr or addr in seen_tokens:
                continue

            is_alert = bool(rec.get("is_alert_candidate")) or (float(rec.get("model_score", 0.0)) >= 50.0)
            if is_alert:
                seen_tokens.add(addr)
                alert_opportunities.append(rec)

        # Fallback to all distinct tokens if no explicit alert candidates present
        if not alert_opportunities:
            for rec in raw_tokens:
                addr = rec.get("token_address")
                if addr and addr not in seen_tokens:
                    seen_tokens.add(addr)
                    alert_opportunities.append(rec)

        mature_token_count = 0

        for rec in alert_opportunities:
            overall_status, _ = self._classify_outcome(rec)
            is_mature = overall_status in ("SUCCESS", "FAILURE")
            if is_mature:
                mature_token_count += 1

            alert_mc = max(1000.0, float(rec.get("market_cap_usd", 15000.0)))
            alert_liq = max(500.0, float(rec.get("liquidity_usd", 4000.0)))
            alert_price = max(0.000001, float(rec.get("price_usd", 0.0001)))
            regime = str(rec.get("market_regime", "NORMAL"))
            token_age = float(rec.get("token_age_minutes", 10.0))

            peak_mc = float(rec.get("peak_market_cap_usd", alert_mc * float(rec.get("mfe_ratio", 1.0))))
            if peak_mc < alert_mc:
                peak_mc = alert_mc

            trough_mc = float(rec.get("trough_market_cap_usd", alert_mc * float(rec.get("mae_ratio", 0.8))))
            if trough_mc <= 0.0:
                trough_mc = alert_mc * 0.10

            base_time_to_target = float(rec.get("time_to_3m_min", rec.get("time_to_target_min", 0.0) or 0.0))
            is_winner = bool(rec.get("target_3m") or peak_mc >= 3_000_000.0)
            is_rug = bool(rec.get("is_rug_event") or trough_mc <= (alert_mc * 0.20))

            for policy_name, delay_min, price_mult, base_slippage in self.ENTRY_POLICY_CONFIGS:
                # Calculate liquidity-adjusted slippage
                liq_scale = (5000.0 / alert_liq) ** 0.5
                slippage_pct = round(base_slippage * max(0.5, min(3.0, liq_scale)), 2)

                entry_price_usd = alert_price * price_mult * (1.0 + (slippage_pct / 100.0))
                effective_entry_mc = alert_mc * price_mult * (1.0 + (slippage_pct / 100.0))

                # Calculate excursion metrics relative to effective entry
                mfe_pct = max(-100.0, ((peak_mc - effective_entry_mc) / effective_entry_mc) * 100.0) if effective_entry_mc > 0 else 0.0
                mae_pct = min(0.0, ((min(trough_mc, effective_entry_mc) - effective_entry_mc) / effective_entry_mc) * 100.0) if effective_entry_mc > 0 else 0.0
                max_dd_pct = abs(mae_pct)
                time_to_target = max(0.0, base_time_to_target - delay_min) if base_time_to_target > 0 else 0.0

                # Simulated executable return factoring exit frictions
                if is_winner:
                    net_return_pct = max(0.0, (mfe_pct * 0.70) - slippage_pct - 1.0)
                elif is_rug:
                    net_return_pct = max(-100.0, mae_pct - slippage_pct - 1.0)
                else:
                    net_return_pct = (mfe_pct * 0.25 + mae_pct * 0.75) - slippage_pct - 1.0

                quality_label = self._label_entry_quality(
                    mfe_pct=mfe_pct,
                    mae_pct=mae_pct,
                    slippage_pct=slippage_pct,
                    time_to_target_min=time_to_target,
                )

                row = EntryDatasetRow(
                    token_address=str(rec.get("token_address", "")),
                    symbol=str(rec.get("symbol", "")),
                    chain=str(rec.get("chain", "solana")),
                    venue=str(rec.get("venue", "pumpfun")),
                    alert_timestamp=str(rec.get("discovery_timestamp", "")),
                    alert_market_cap_usd=alert_mc,
                    alert_liquidity_usd=alert_liq,
                    alert_price_usd=alert_price,
                    market_regime=regime,
                    token_age_minutes=token_age,
                    entry_policy=policy_name,
                    entry_price_usd=round(entry_price_usd, 8),
                    entry_slippage_pct=slippage_pct,
                    mfe_pct=round(mfe_pct, 2),
                    mae_pct=round(mae_pct, 2),
                    time_to_target_min=round(time_to_target, 2),
                    max_drawdown_pct=round(max_dd_pct, 2),
                    net_executable_return_pct=round(net_return_pct, 2),
                    entry_quality_label=quality_label,
                )
                rows.append(row)

        total_rows = len(rows)
        mature_rows = mature_token_count * len(self.ENTRY_POLICY_CONFIGS)
        pending_rows = total_rows - mature_rows
        readiness = "READY" if mature_rows >= MIN_ENTRY_OBSERVATIONS else "INSUFFICIENT_TRAINING_DATA"
        now_str = datetime.now(timezone.utc).isoformat()
        dataset_version = f"{FROZEN_VERSION_MANIFEST.execution_model_version}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"

        schema_hash = self._compute_schema_hash(ENTRY_FEATURE_NAMES)

        logger.info(
            f"Entry dataset built: {total_rows} rows from {len(alert_opportunities)} opportunities, "
            f"{mature_rows} mature rows (readiness: {readiness})"
        )

        return LearningDataset(
            dataset_version=dataset_version,
            build_timestamp=now_str,
            dataset_type="ENTRY",
            total_rows=total_rows,
            mature_rows=mature_rows,
            pending_rows=pending_rows,
            feature_count=len(ENTRY_FEATURE_NAMES),
            feature_schema_hash=schema_hash,
            rows=[asdict(r) for r in rows],
            readiness_status=readiness,
        )

    def build_exit_dataset(self) -> LearningDataset:
        """
        Load closed paper trades, evaluate exit quality labels, and produce ExitDatasetRows.
        Sets readiness based on MIN_EXIT_OBSERVATIONS threshold.
        """
        closed_trades = self.paper_ledger.load_closed_trades()
        rows: List[ExitDatasetRow] = []

        for trade in closed_trades:
            mfe_ratio = float(trade.get("mfe_ratio", 1.0))
            mae_ratio = float(trade.get("mae_ratio", 1.0))
            mfe_pct = (mfe_ratio - 1.0) * 100.0
            mae_pct = (mae_ratio - 1.0) * 100.0
            realized_return = float(trade.get("net_realized_return_pct", 0.0))
            max_dd = abs(mae_pct)

            quality_label = self._label_exit_quality(
                realized_return_pct=realized_return,
                mfe_pct=mfe_pct,
                max_drawdown_pct=max_dd,
            )

            # Determine duration in trade
            time_in_trade = float(trade.get("time_in_trade_min", 0.0))
            if time_in_trade <= 0.0 and trade.get("timestamp") and trade.get("exit_timestamp"):
                try:
                    t_in = datetime.fromisoformat(trade["timestamp"].replace("Z", "+00:00"))
                    t_out = datetime.fromisoformat(trade["exit_timestamp"].replace("Z", "+00:00"))
                    time_in_trade = max(0.0, (t_out - t_in).total_seconds() / 60.0)
                except Exception:
                    time_in_trade = 0.0

            # Determine entry and exit market caps
            entry_mc = float(trade.get("entry_market_cap_usd") or trade.get("market_cap_usd") or 0.0)
            exit_mc = float(trade.get("exit_market_cap_usd") or 0.0)
            fill_p = float(trade.get("simulated_fill_price_usd") or trade.get("entry_price_usd") or 0.0)
            exit_p = float(trade.get("exit_price_usd") or 0.0)

            if exit_mc <= 0.0 and fill_p > 0 and exit_p > 0 and entry_mc > 0:
                exit_mc = entry_mc * (exit_p / fill_p)
            elif exit_mc <= 0.0 and entry_mc > 0:
                exit_mc = entry_mc * (1.0 + realized_return / 100.0)

            row = ExitDatasetRow(
                token_address=str(trade.get("token_address", "")),
                symbol=str(trade.get("symbol", "")),
                entry_timestamp=str(trade.get("timestamp", "")),
                exit_timestamp=str(trade.get("exit_timestamp", trade.get("timestamp", ""))),
                entry_price_usd=fill_p,
                exit_price_usd=exit_p,
                entry_market_cap_usd=round(entry_mc, 2),
                exit_market_cap_usd=round(exit_mc, 2),
                exit_policy=str(trade.get("exit_policy", "TRAILING_STOP")),
                realized_return_pct=round(realized_return, 2),
                mfe_pct=round(mfe_pct, 2),
                mae_pct=round(mae_pct, 2),
                time_in_trade_min=round(time_in_trade, 2),
                max_drawdown_pct=round(max_dd, 2),
                slippage_pct=float(trade.get("exit_price_impact_pct", trade.get("entry_price_impact_pct", 0.0))),
                fees_usd=float(trade.get("total_fees_usd", 0.0)),
                exit_quality_label=quality_label,
                market_regime=str(trade.get("regime", trade.get("market_regime", "NORMAL"))),
            )
            rows.append(row)

        total_rows = len(rows)
        mature_rows = total_rows  # All closed paper trades have completed trajectories
        pending_rows = 0
        readiness = "READY" if mature_rows >= MIN_EXIT_OBSERVATIONS else "INSUFFICIENT_TRAINING_DATA"
        now_str = datetime.now(timezone.utc).isoformat()
        dataset_version = f"{FROZEN_VERSION_MANIFEST.execution_model_version}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"

        schema_hash = self._compute_schema_hash(EXIT_FEATURE_NAMES)

        logger.info(
            f"Exit dataset built: {total_rows} closed trades evaluated (readiness: {readiness})"
        )

        return LearningDataset(
            dataset_version=dataset_version,
            build_timestamp=now_str,
            dataset_type="EXIT",
            total_rows=total_rows,
            mature_rows=mature_rows,
            pending_rows=pending_rows,
            feature_count=len(EXIT_FEATURE_NAMES),
            feature_schema_hash=schema_hash,
            rows=[asdict(r) for r in rows],
            readiness_status=readiness,
        )

    def build_all_datasets(self) -> Dict[str, LearningDataset]:
        """
        Build all three learning datasets (Selection, Entry, Exit) in a single pass.

        Returns:
            Dict mapping dataset type ("SELECTION", "ENTRY", "EXIT") to LearningDataset.
        """
        return {
            "SELECTION": self.build_selection_dataset(),
            "ENTRY": self.build_entry_dataset(),
            "EXIT": self.build_exit_dataset(),
        }
