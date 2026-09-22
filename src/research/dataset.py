"""
Longitudinal Dataset Pipeline
Manages continuous token time-series tracking across 12 standard horizons,
preserving negative examples and population base-rates.
"""

from datetime import datetime, timezone
import math
from typing import Any, Dict, List, Optional
from src.feeds.base_feed import TokenCandidate
from src.research.outcomes import TargetOutcomes, TrajectoryEvaluator
from src.research.storage import ResearchStorage


class LongitudinalDatasetPipeline:
    STANDARD_HORIZONS = [0.0, 1.0, 3.0, 5.0, 10.0, 15.0, 30.0, 60.0, 120.0, 240.0, 720.0, 1440.0]
    MAX_TRACKED_TOKENS = 300
    MAX_HISTORY_PER_TOKEN = 30

    def __init__(self, storage: Optional[ResearchStorage] = None):
        self.storage = storage or ResearchStorage()
        self.tracked_tokens: Dict[str, Dict[str, Any]] = {}

    def prune_stale_tokens(self, protected_addresses: Optional[Any] = None) -> None:
        """Evict inactive tokens to prevent memory leaks and maintain bounded footprint."""
        now = datetime.now(timezone.utc)
        protected = set(protected_addresses) if protected_addresses else set()

        # 1. Evict tokens inactive for >60 minutes not in protected set
        to_evict = [
            addr for addr, state in self.tracked_tokens.items()
            if addr not in protected
            and (now - state.get("last_seen", state["discovered_at"])).total_seconds() > 3600.0
        ]
        for addr in to_evict:
            self.tracked_tokens.pop(addr, None)

        # 2. If dictionary still exceeds MAX_TRACKED_TOKENS, evict least recently seen
        if len(self.tracked_tokens) > self.MAX_TRACKED_TOKENS:
            candidates_to_prune = [
                (addr, state.get("last_seen", state["discovered_at"]))
                for addr, state in self.tracked_tokens.items()
                if addr not in protected
            ]
            candidates_to_prune.sort(key=lambda x: x[1])
            excess = len(self.tracked_tokens) - self.MAX_TRACKED_TOKENS
            for addr, _ in candidates_to_prune[:excess]:
                self.tracked_tokens.pop(addr, None)

    def register_token(self, candidate: TokenCandidate, data_quality_score: float = 1.0) -> None:
        """Register a newly discovered candidate token into the longitudinal tracker."""
        self.register_tokens_batch([candidate], data_quality_score=data_quality_score)

    def register_tokens_batch(self, candidates: List[TokenCandidate], data_quality_score: float = 1.0) -> None:
        """Batch register newly discovered tokens."""
        now = datetime.now(timezone.utc)
        new_discoveries = []

        for candidate in candidates:
            addr = candidate.address
            if addr in self.tracked_tokens:
                continue

            self.tracked_tokens[addr] = {
                "discovered_at": now,
                "last_seen": now,
                "snapshots_taken": set(),
                "history": [],
                "initial_mc": candidate.market_cap_usd,
                "initial_liq": candidate.liquidity_usd,
            }
            new_discoveries.append({
                "address": addr,
                "chain": candidate.chain,
                "venue": candidate.dex_id,
                "symbol": candidate.symbol,
                "name": candidate.name,
                "discovered_at": now,
                "initial_market_cap": candidate.market_cap_usd,
                "initial_liquidity": candidate.liquidity_usd,
                "created_at": candidate.created_at,
                "data_quality_score": data_quality_score,
            })

        if new_discoveries:
            self.storage.record_token_discoveries_batch(new_discoveries)

    def record_observation(
        self,
        candidate: TokenCandidate,
        features: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record point-in-time snapshot and map to nearest standard horizon."""
        self.record_observations_batch([(candidate, features)])

    def record_observations_batch(
        self,
        observations: List[Tuple[TokenCandidate, Optional[Dict[str, Any]]]],
    ) -> None:
        """Batch record observations in a single SQLite transaction and single JSONL write."""
        if not observations:
            return

        now = datetime.now(timezone.utc)
        unregistered = [c for c, _ in observations if c.address not in self.tracked_tokens]
        if unregistered:
            self.register_tokens_batch(unregistered)

        snapshot_dicts = []
        for candidate, features in observations:
            addr = candidate.address
            token_state = self.tracked_tokens[addr]
            token_state["last_seen"] = now
            elapsed_min = (now - token_state["discovered_at"]).total_seconds() / 60.0

            obs = {
                "timestamp": now.isoformat(),
                "elapsed_minutes": elapsed_min,
                "market_cap_usd": candidate.market_cap_usd,
                "liquidity_usd": candidate.liquidity_usd,
                "price_usd": candidate.price_usd,
            }
            token_state["history"].append(obs)
            if len(token_state["history"]) > self.MAX_HISTORY_PER_TOKEN:
                token_state["history"] = token_state["history"][-self.MAX_HISTORY_PER_TOKEN:]

            matched_horizon = None
            for h in self.STANDARD_HORIZONS:
                if h not in token_state["snapshots_taken"] and abs(elapsed_min - h) <= (1.0 if h <= 5.0 else 5.0):
                    matched_horizon = h
                    token_state["snapshots_taken"].add(h)
                    break

            horizon_label = f"T+{matched_horizon:.0f}m" if matched_horizon is not None else f"T+{elapsed_min:.1f}m"

            sec = candidate.security
            raw = getattr(candidate, "raw_data", None) or {}
            snapshot_dicts.append({
                "token_address": addr,
                "timestamp": now,
                "elapsed_minutes": elapsed_min,
                "horizon_label": horizon_label,
                "price_usd": candidate.price_usd,
                "market_cap_usd": candidate.market_cap_usd,
                "fdv_usd": raw.get("fdv") or candidate.market_cap_usd,
                "liquidity_usd": candidate.liquidity_usd,
                "virtual_liquidity_usd": raw.get("virtual_liquidity", candidate.liquidity_usd),
                "volume_5m_usd": candidate.volume_5m_usd,
                "volume_1h_usd": candidate.volume_1h_usd,
                "txns_5m_buys": candidate.txns_5m_buys,
                "txns_5m_sells": candidate.txns_5m_sells,
                "unique_buyers": candidate.unique_buyers_1h,
                "unique_sellers": candidate.unique_sellers_1h,
                "top10_raw_pct": sec.top10_holder_pct,
                "top10_effective_pct": features.get("effective_top10_pct", sec.top10_holder_pct) if features else sec.top10_holder_pct,
                "cabal_risk_score": features.get("cabal_risk_score", 0.0) if features else 0.0,
                "wash_trade_risk": features.get("wash_trade_risk", 0.0) if features else 0.0,
                "volume_quality_score": features.get("volume_quality_score", 1.0) if features else 1.0,
                "dev_holding_pct": sec.dev_holding_pct,
                "features": features,
            })

        if snapshot_dicts:
            self.storage.record_snapshots_batch(snapshot_dicts)

    def finalize_outcomes(self, token_address: str) -> Optional[TargetOutcomes]:
        """Compute and persist ground truth outcomes when token tracking window completes."""
        if token_address not in self.tracked_tokens:
            return None

        state = self.tracked_tokens[token_address]
        outcomes = TrajectoryEvaluator.evaluate(
            observations=state["history"],
            initial_market_cap=state["initial_mc"],
        )
        self.storage.record_outcomes(token_address, outcomes)
        return outcomes
