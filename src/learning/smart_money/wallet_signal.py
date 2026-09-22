"""
Real-Time Smart Wallet Activity & Consensus Signal Engine
Tracks active participating wallets on candidate tokens:
- SMART_WALLET_ACTIVITY States:
  - NONE: No tracked smart wallets detected
  - OBSERVED: Single validated wallet entry
  - MULTIPLE_OBSERVED: Multiple validated wallets present
  - HIGH_CONFIDENCE_CONSENSUS: 3+ statistically independent validated wallets entered in early window
- SMART_MONEY_CONSENSUS:
  - Cluster-discounted consensus score factoring independent entity count and Bayesian skill weights
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional
from src.learning.smart_money.wallet_clusters import WalletClusterDetector

logger = logging.getLogger(__name__)


@dataclass
class WalletActivityEvent:
    wallet_address: str
    token_address: str
    timestamp: str
    entry_market_cap_usd: float
    entry_liquidity_usd: float
    position_size_usd: float
    role: str
    shrunk_skill: float
    skill_confidence: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SmartMoneyConsensusReport:
    token_address: str
    activity_state: str                  # NONE, OBSERVED, MULTIPLE_OBSERVED, HIGH_CONFIDENCE_CONSENSUS
    consensus_score: float               # 0.0 to 1.0
    effective_independent_wallets: float
    raw_participating_wallets: int
    participating_wallets: List[str]
    participating_events: List[WalletActivityEvent]
    is_high_conviction_consensus: bool
    evaluation_timestamp: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "token_address": self.token_address,
            "activity_state": self.activity_state,
            "consensus_score": self.consensus_score,
            "effective_independent_wallets": self.effective_independent_wallets,
            "raw_participating_wallets": self.raw_participating_wallets,
            "participating_wallets": self.participating_wallets,
            "participating_events": [e.to_dict() for e in self.participating_events],
            "is_high_conviction_consensus": self.is_high_conviction_consensus,
            "evaluation_timestamp": self.evaluation_timestamp,
        }


class SmartMoneySignalEngine:
    """
    Evaluates real-time token events for cluster-adjusted smart-money consensus.
    """

    @classmethod
    def evaluate_token_activity(
        cls,
        token_address: str,
        active_wallet_events: List[WalletActivityEvent],
        funding_map: Optional[Dict[str, str]] = None,
    ) -> SmartMoneyConsensusReport:
        """
        Evaluate consensus from active smart-wallet entries on a token.
        """
        now_str = datetime.now(timezone.utc).isoformat()
        if not active_wallet_events:
            return SmartMoneyConsensusReport(
                token_address=token_address,
                activity_state="NONE",
                consensus_score=0.0,
                effective_independent_wallets=0.0,
                raw_participating_wallets=0,
                participating_wallets=[],
                participating_events=[],
                is_high_conviction_consensus=False,
                evaluation_timestamp=now_str,
            )

        wallets = [e.wallet_address for e in active_wallet_events]
        clusters, eff_count = WalletClusterDetector.analyze_wallet_set(
            wallets=wallets,
            funding_map=funding_map,
        )

        raw_count = len(wallets)
        avg_skill = sum(e.shrunk_skill for e in active_wallet_events) / raw_count
        avg_conf = sum(e.skill_confidence for e in active_wallet_events) / raw_count

        # Consensus score formula combining effective independent count and skill
        consensus_score = min(1.0, (eff_count / 3.0) * (avg_skill / 0.20) * avg_conf)

        if eff_count >= 3.0 and consensus_score >= 0.70:
            state = "HIGH_CONFIDENCE_CONSENSUS"
            is_high = True
        elif eff_count >= 2.0:
            state = "MULTIPLE_OBSERVED"
            is_high = False
        elif eff_count >= 1.0:
            state = "OBSERVED"
            is_high = False
        else:
            state = "NONE"
            is_high = False

        return SmartMoneyConsensusReport(
            token_address=token_address,
            activity_state=state,
            consensus_score=round(consensus_score, 4),
            effective_independent_wallets=eff_count,
            raw_participating_wallets=raw_count,
            participating_wallets=wallets,
            participating_events=active_wallet_events,
            is_high_conviction_consensus=is_high,
            evaluation_timestamp=now_str,
        )
