"""
Smart Money Maturity States & Lifecycle Definitions
Defines formal maturity states for on-chain wallets:
- CANDIDATE: Initial discovery (< 5 mature trades)
- OBSERVED: Active monitoring & data collection (5 <= N < 10)
- EMERGING: >= 10 mature trades with promising skill signal
- VALIDATED: >= 20 mature trades + statistically positive matched control lift (>= 10%) + confidence >= 70%
- ELITE: >= 30 mature trades + high matched lift (>= 20%) + confidence >= 85% + stable/improving skill trend
- DECLINING: Performance degradation over recent rolling window (> 10% 30D drop)
- DISQUALIFIED: Sybil / cabal / non-trader / rug exposure > 20%
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional


class WalletMaturityState(str, Enum):
    CANDIDATE = "CANDIDATE"
    OBSERVED = "OBSERVED"
    EMERGING = "EMERGING"
    VALIDATED = "VALIDATED"
    ELITE = "ELITE"
    DECLINING = "DECLINING"
    DISQUALIFIED = "DISQUALIFIED"


@dataclass(frozen=True)
class MaturityThresholds:
    min_trades_candidate: int = 1
    min_trades_observed: int = 5
    min_trades_emerging: int = 10
    min_trades_validated: int = 20
    min_trades_elite: int = 30
    min_validated_matched_lift: float = 10.0      # +10% lift over matched control group
    min_validated_confidence: float = 0.70        # 70% Bayesian confidence
    min_elite_matched_lift: float = 20.0          # +20% lift over matched control group
    min_elite_confidence: float = 0.85            # 85% Bayesian confidence
    declining_skill_drop_threshold: float = 10.0  # >10% 30D skill degradation
    disqualification_rug_rate_max: float = 20.0   # >20% rug exposure triggers disqualification


DEFAULT_MATURITY_THRESHOLDS = MaturityThresholds()


class WalletMaturityClassifier:
    """Classifies a wallet into its appropriate formal maturity state based on historical evidence."""

    @classmethod
    def classify(
        cls,
        wallet: Dict[str, Any],
        thresholds: MaturityThresholds = DEFAULT_MATURITY_THRESHOLDS,
    ) -> WalletMaturityState:
        mature_n = int(wallet.get("mature_trades", wallet.get("total_trades", 0)) or 0)
        matched_lift = float(wallet.get("matched_lift_pct", 0.0) or 0.0)
        conf = float(wallet.get("skill_confidence", 0.0) or 0.0)
        trend = str(wallet.get("skill_trend", "STABLE") or "STABLE")
        rug_rate = float(wallet.get("rug_rate_pct", 0.0) or 0.0)
        role = str(wallet.get("primary_role", "TRADER") or "TRADER")

        # Disqualification checks
        if rug_rate > thresholds.disqualification_rug_rate_max or role in ("MEV_BOT", "CABAL_COORDINATOR"):
            return WalletMaturityState.DISQUALIFIED

        # Declining checks
        if trend == "DECLINING" and mature_n >= thresholds.min_trades_emerging:
            return WalletMaturityState.DECLINING

        # Elite tier
        if (
            mature_n >= thresholds.min_trades_elite
            and matched_lift >= thresholds.min_elite_matched_lift
            and conf >= thresholds.min_elite_confidence
            and trend in ("IMPROVING", "STABLE")
        ):
            return WalletMaturityState.ELITE

        # Validated tier
        if (
            mature_n >= thresholds.min_trades_validated
            and matched_lift >= thresholds.min_validated_matched_lift
            and conf >= thresholds.min_validated_confidence
        ):
            return WalletMaturityState.VALIDATED

        # Emerging tier
        if mature_n >= thresholds.min_trades_emerging:
            return WalletMaturityState.EMERGING

        # Observed tier
        if mature_n >= thresholds.min_trades_observed:
            return WalletMaturityState.OBSERVED

        return WalletMaturityState.CANDIDATE
