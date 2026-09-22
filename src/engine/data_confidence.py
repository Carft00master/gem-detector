"""
Data Confidence & Telemetry Quality Scorer
Computes DATA_CONFIDENCE (0.0 to 1.0) evaluating sample size, data freshness,
missing features, RPC latency, wallet history depth, and liquidity completeness.
Kept strictly separate from model probabilities (P(3M)) to avoid unprincipled skew.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from src.feeds.base_feed import TokenCandidate


@dataclass
class DataConfidenceReport:
    data_confidence_score: float = 1.0     # 0.0 to 1.0 overall telemetry reliability
    sample_size_score: float = 1.0         # Depth of observed history/ticks
    freshness_score: float = 1.0           # Seconds elapsed since last block update
    feature_completeness_score: float = 1.0 # Proportion of non-null features
    wallet_completeness_score: float = 1.0  # Top holders funding lineage resolved
    liquidity_depth_score: float = 1.0     # Active LP liquidity depth known
    rpc_latency_ms: float = 120.0
    signals: List[str] = field(default_factory=list)


class DataConfidenceEngine:
    @classmethod
    def evaluate(
        cls,
        candidate: TokenCandidate,
        resolved_wallets_count: int = 10,
        total_top_wallets: int = 10,
        rpc_latency_ms: float = 120.0,
        data_age_seconds: float = 5.0,
    ) -> DataConfidenceReport:
        report = DataConfidenceReport()
        signals = []

        # 1. Sample Size / Age Score
        # Tokens with < 2 minutes history have lower sample confidence
        if candidate.age_minutes >= 10.0:
            sample_score = 1.0
        elif candidate.age_minutes >= 3.0:
            sample_score = 0.85
        elif candidate.age_minutes >= 1.0:
            sample_score = 0.65
            signals.append("VERY_EARLY_LIFECYCLE_SAMPLE")
        else:
            sample_score = 0.40
            signals.append("SUB_MINUTE_SAMPLE_HIGH_VARIANCE")

        # 2. Freshness Score
        if data_age_seconds <= 15.0:
            freshness_score = 1.0
        elif data_age_seconds <= 60.0:
            freshness_score = 0.80
        elif data_age_seconds <= 300.0:
            freshness_score = 0.50
            signals.append("STALE_TELEMETRY_LATENCY")
        else:
            freshness_score = 0.20
            signals.append("HIGHLY_STALE_DATA_DEGRADED")

        # 3. Feature Completeness Score
        # Check presence of volume, transactions, price, market cap
        missing_count = 0
        if candidate.market_cap_usd <= 0:
            missing_count += 1
        if candidate.volume_5m_usd <= 0 and candidate.volume_1h_usd <= 0:
            missing_count += 1
        if candidate.txns_5m_buys + candidate.txns_5m_sells == 0:
            missing_count += 1
        if candidate.liquidity_usd <= 0:
            missing_count += 1

        feature_completeness = max(0.20, 1.0 - (missing_count * 0.20))
        if missing_count > 0:
            signals.append(f"MISSING_{missing_count}_CRITICAL_FIELDS")

        # 4. Wallet Completeness Score
        wallet_completeness = min(1.0, max(0.20, resolved_wallets_count / max(1, total_top_wallets)))
        if wallet_completeness < 0.60:
            signals.append("INCOMPLETE_HOLDER_LINEAGE")

        # 5. Liquidity Depth Score
        if candidate.liquidity_usd >= 5000.0:
            liq_score = 1.0
        elif candidate.liquidity_usd >= 2000.0:
            liq_score = 0.85
        elif candidate.liquidity_usd >= 800.0:
            liq_score = 0.60
            signals.append("THIN_LIQUIDITY_DEPTH")
        else:
            liq_score = 0.25
            signals.append("EXTREMELY_FRAGILE_LIQUIDITY")

        # 6. RPC Latency Penalty
        if rpc_latency_ms > 2500.0:
            rpc_penalty = 0.30
            signals.append("HIGH_RPC_LATENCY_LAG")
        elif rpc_latency_ms > 1000.0:
            rpc_penalty = 0.15
        else:
            rpc_penalty = 0.0

        overall = (
            sample_score * 0.25
            + freshness_score * 0.25
            + feature_completeness * 0.20
            + wallet_completeness * 0.15
            + liq_score * 0.15
            - rpc_penalty
        )

        report.data_confidence_score = round(min(1.0, max(0.10, overall)), 3)
        report.sample_size_score = round(sample_score, 3)
        report.freshness_score = round(freshness_score, 3)
        report.feature_completeness_score = round(feature_completeness, 3)
        report.wallet_completeness_score = round(wallet_completeness, 3)
        report.liquidity_depth_score = round(liq_score, 3)
        report.rpc_latency_ms = rpc_latency_ms
        report.signals = signals

        return report
