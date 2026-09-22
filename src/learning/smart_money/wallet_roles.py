"""
Probabilistic Wallet Role Classification
Classifies wallet addresses into behavioral roles:
- TRADER: Repeated directional token selection and holding
- DEPLOYER: Token contract creator / launch coordinator
- CREATOR: Liquidity creator / metadata initializer
- SNIPER: Automated sub-second / block 0-1 repetitive entry
- MARKET_MAKER: High-frequency turnover / two-sided inventory balancing
- ARBITRAGE: Cross-pool / cross-venue atomic arbitrage
- WHALE: Outsized single-transaction positioning (> 5% pool depth)
- RETAIL: Low-frequency, standard sizing discretionary participant
- EXCHANGE: Centralized exchange hot/cold wallet
- ROUTER: DEX aggregator / router contract
- LIQUIDITY_PROVIDER: Pure LP deposit / withdrawal
- UNKNOWN: Insufficient history

Excludes non-traders from smart-money selection signals.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class WalletRoleClassification:
    wallet_address: str
    primary_role: str
    role_confidence: float
    role_probabilities: Dict[str, float]
    classification_timestamp: str
    is_smart_money_eligible: bool
    evidence: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class WalletRoleClassifier:
    """
    Evaluates historical on-chain interactions to probabilistically classify wallet roles.
    """

    NON_TRADER_ROLES = {
        "DEPLOYER",
        "CREATOR",
        "EXCHANGE",
        "ROUTER",
        "LIQUIDITY_PROVIDER",
        "MARKET_MAKER",
        "ARBITRAGE",
    }

    @classmethod
    def is_smart_money_eligible(cls, role: str) -> bool:
        """Returns True if the role represents organic directional trading."""
        return role in ("TRADER", "WHALE", "SNIPER", "RETAIL") and role not in cls.NON_TRADER_ROLES

    @classmethod
    def classify_wallet(
        cls,
        wallet_address: str,
        interactions: List[Dict[str, Any]],
        creation_count: int = 0,
        is_known_exchange: bool = False,
        is_known_router: bool = False,
        timestamp: Optional[str] = None,
    ) -> WalletRoleClassification:
        """
        Compute probabilistic role classification based strictly on historical evidence.
        """
        now_str = timestamp or datetime.now(timezone.utc).isoformat()

        if is_known_exchange:
            return WalletRoleClassification(
                wallet_address=wallet_address,
                primary_role="EXCHANGE",
                role_confidence=0.99,
                role_probabilities={"EXCHANGE": 0.99, "TRADER": 0.01},
                classification_timestamp=now_str,
                is_smart_money_eligible=False,
                evidence={"source": "KNOWN_EXCHANGE_REGISTRY"},
            )

        if is_known_router:
            return WalletRoleClassification(
                wallet_address=wallet_address,
                primary_role="ROUTER",
                role_confidence=0.99,
                role_probabilities={"ROUTER": 0.99, "TRADER": 0.01},
                classification_timestamp=now_str,
                is_smart_money_eligible=False,
                evidence={"source": "KNOWN_ROUTER_CONTRACT"},
            )

        if creation_count >= 3:
            return WalletRoleClassification(
                wallet_address=wallet_address,
                primary_role="DEPLOYER",
                role_confidence=min(0.95, 0.60 + (creation_count * 0.05)),
                role_probabilities={"DEPLOYER": 0.90, "TRADER": 0.10},
                classification_timestamp=now_str,
                is_smart_money_eligible=False,
                evidence={"tokens_created": creation_count},
            )

        if not interactions:
            return WalletRoleClassification(
                wallet_address=wallet_address,
                primary_role="UNKNOWN",
                role_confidence=0.50,
                role_probabilities={"UNKNOWN": 1.0},
                classification_timestamp=now_str,
                is_smart_money_eligible=False,
                evidence={"interactions": 0},
            )

        # Behavioral heuristics
        total_txs = len(interactions)
        fast_entries = sum(1 for t in interactions if float(t.get("entry_token_age", t.get("token_age_minutes", 10.0)) or 10.0) < 1.0)
        fast_ratio = fast_entries / total_txs if total_txs > 0 else 0.0

        durations = [float(t.get("holding_time", t.get("hold_duration_seconds", 300.0)) or 300.0) for t in interactions]
        avg_dur = sum(durations) / len(durations) if durations else 300.0

        sizes = [float(t.get("position_size", t.get("position_size_usd", 100.0)) or 100.0) for t in interactions]
        avg_size = sum(sizes) / len(sizes) if sizes else 100.0

        scores = {
            "SNIPER": 0.10,
            "TRADER": 0.30,
            "WHALE": 0.10,
            "MARKET_MAKER": 0.05,
            "ARBITRAGE": 0.05,
            "RETAIL": 0.40,
        }

        if fast_ratio >= 0.60 and total_txs >= 5:
            scores["SNIPER"] += 0.60
            scores["RETAIL"] -= 0.30

        if avg_dur < 60.0 and total_txs >= 10:
            scores["ARBITRAGE"] += 0.40
            scores["MARKET_MAKER"] += 0.30

        if avg_size >= 1000.0:
            scores["WHALE"] += 0.50
            scores["RETAIL"] -= 0.20

        if total_txs >= 15 and avg_dur >= 180.0:
            scores["TRADER"] += 0.50
            scores["RETAIL"] -= 0.20

        # Normalize probabilities
        positive_scores = {k: max(0.01, v) for k, v in scores.items()}
        total_score = sum(positive_scores.values())
        probs = {k: round(v / total_score, 4) for k, v in positive_scores.items()}

        primary_role = max(probs, key=probs.get)
        confidence = probs[primary_role]
        is_eligible = cls.is_smart_money_eligible(primary_role)

        return WalletRoleClassification(
            wallet_address=wallet_address,
            primary_role=primary_role,
            role_confidence=confidence,
            role_probabilities=probs,
            classification_timestamp=now_str,
            is_smart_money_eligible=is_eligible,
            evidence={
                "total_txs": total_txs,
                "fast_entry_ratio": round(fast_ratio, 2),
                "avg_hold_duration_sec": round(avg_dur, 1),
                "avg_position_size_usd": round(avg_size, 1),
            },
        )
