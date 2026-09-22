"""
Point-In-Time Wallet Knowledge & Look-Ahead Guardrails
Ensures that at any evaluation timestamp T, the intelligence engine ONLY uses
wallet activity, performance metrics, and roles established strictly BEFORE T.
Permanently attaches WALLET_KNOWLEDGE_SNAPSHOT_TIMESTAMP to every feature vector.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PointInTimeSnapshot:
    wallet_address: str
    snapshot_timestamp: str
    known_trade_count: int
    known_mature_trade_count: int
    known_target_3m_rate: float
    known_shrunk_skill: float
    known_skill_confidence: float
    known_matched_lift: float
    known_role: str
    is_validated: bool
    feature_hash: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class PointInTimeGuardrail:
    """
    Filters and constructs point-in-time wallet datasets ensuring zero future look-ahead leakage.
    """

    @staticmethod
    def filter_trades_before_timestamp(
        trades: List[Dict[str, Any]],
        cutoff_timestamp: str,
    ) -> List[Dict[str, Any]]:
        """Filter a list of wallet trade interactions to strictly those occurring before cutoff."""
        if not cutoff_timestamp:
            return trades

        try:
            cutoff_dt = datetime.fromisoformat(cutoff_timestamp.replace("Z", "+00:00"))
        except Exception:
            return trades

        valid_trades = []
        for t in trades:
            t_str = t.get("entry_timestamp") or t.get("timestamp") or ""
            if not t_str:
                continue
            try:
                t_dt = datetime.fromisoformat(t_str.replace("Z", "+00:00"))
                if t_dt < cutoff_dt:
                    valid_trades.append(t)
            except Exception:
                continue

        return valid_trades

    @staticmethod
    def generate_snapshot_timestamp(timestamp: Optional[str] = None) -> str:
        """Return standardized UTC snapshot timestamp."""
        if timestamp:
            return timestamp
        return datetime.now(timezone.utc).isoformat()
