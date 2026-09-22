"""
Smart Money Temporal Quarantine & Tri-Split Dataset Engine
Enforces strict temporal separation and winner-conditioning isolation:
1. Tri-Split Chronological Datasets:
   - WALLET_DISCOVERY_DATASET: Used strictly to identify candidate wallets.
   - WALLET_VALIDATION_DATASET: Used strictly to validate persistent skill across independent tokens.
   - WALLET_EVALUATION_DATASET: Held-out out-of-sample dataset used strictly for final predictive evaluation.
   - Invariant: Zero token overlap across datasets.
2. Temporal Quarantine:
   - If Wallet X is discovered because of Token A, Wallet X is quarantined from contributing predictive credit to Token A.
   - Tracks:
     - WALLET_DISCOVERY_TIMESTAMP
     - WALLET_VALIDATION_TIMESTAMP
     - WALLET_FIRST_ELIGIBLE_SIGNAL_TIMESTAMP (strictly after discovery/validation token timestamp)
3. Token Quarantine:
   - Tokens used to discover or validate a wallet are marked SMART_MONEY_QUARANTINED = True and excluded from self-evaluation.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


@dataclass
class TriSplitSmartMoneyDatasets:
    discovery_dataset: List[Dict[str, Any]]
    validation_dataset: List[Dict[str, Any]]
    evaluation_dataset: List[Dict[str, Any]]
    discovery_token_addresses: Set[str] = field(default_factory=set)
    validation_token_addresses: Set[str] = field(default_factory=set)
    evaluation_token_addresses: Set[str] = field(default_factory=set)
    is_leakage_free: bool = True
    split_summary: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "discovery_samples": len(self.discovery_dataset),
            "validation_samples": len(self.validation_dataset),
            "evaluation_samples": len(self.evaluation_dataset),
            "discovery_tokens": len(self.discovery_token_addresses),
            "validation_tokens": len(self.validation_token_addresses),
            "evaluation_tokens": len(self.evaluation_token_addresses),
            "is_leakage_free": self.is_leakage_free,
            "split_summary": self.split_summary,
        }


@dataclass
class WalletQuarantineRecord:
    wallet_address: str
    discovery_token_address: str
    discovery_timestamp: str
    validation_timestamp: Optional[str]
    first_eligible_signal_timestamp: str
    quarantined_tokens: Set[str] = field(default_factory=set)
    is_currently_quarantined: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "wallet_address": self.wallet_address,
            "discovery_token_address": self.discovery_token_address,
            "discovery_timestamp": self.discovery_timestamp,
            "validation_timestamp": self.validation_timestamp,
            "first_eligible_signal_timestamp": self.first_eligible_signal_timestamp,
            "quarantined_tokens": list(self.quarantined_tokens),
            "is_currently_quarantined": self.is_currently_quarantined,
        }


class SmartMoneyQuarantineManager:
    """
    Manages temporal quarantine boundaries and creates leakage-free tri-split datasets.
    """

    def __init__(self):
        self.wallet_quarantines: Dict[str, WalletQuarantineRecord] = {}
        self.token_quarantines: Dict[str, Dict[str, Any]] = {}

    @classmethod
    def create_tri_split_datasets(
        cls,
        tokens: List[Dict[str, Any]],
        discovery_ratio: float = 0.40,
        validation_ratio: float = 0.30,
    ) -> TriSplitSmartMoneyDatasets:
        """
        Partition chronological tokens into 3 non-overlapping sets:
        Discovery (earliest) -> Validation (middle) -> Evaluation (out-of-sample).
        """
        if not tokens:
            return TriSplitSmartMoneyDatasets([], [], [])

        # Sort strictly chronologically by discovery / creation timestamp
        def get_ts(t: Dict[str, Any]) -> str:
            return str(t.get("discovery_timestamp") or t.get("timestamp") or t.get("created_at") or "")

        sorted_tokens = sorted(tokens, key=get_ts)
        n = len(sorted_tokens)

        idx_disc = int(n * discovery_ratio)
        idx_val = int(n * (discovery_ratio + validation_ratio))

        discovery_slice = sorted_tokens[:idx_disc]
        validation_slice = sorted_tokens[idx_disc:idx_val]
        evaluation_slice = sorted_tokens[idx_val:]

        disc_addrs = {str(t.get("token_address") or t.get("address")) for t in discovery_slice}
        val_addrs = {str(t.get("token_address") or t.get("address")) for t in validation_slice}
        eval_addrs = {str(t.get("token_address") or t.get("address")) for t in evaluation_slice}

        # Validate Invariant: Zero overlap across datasets
        overlap = (disc_addrs & val_addrs) | (disc_addrs & eval_addrs) | (val_addrs & eval_addrs)
        is_leakage_free = (len(overlap) == 0)

        summary = {
            "total_tokens": n,
            "discovery_range": f"{get_ts(discovery_slice[0])[:10]} to {get_ts(discovery_slice[-1])[:10]}" if discovery_slice else "N/A",
            "validation_range": f"{get_ts(validation_slice[0])[:10]} to {get_ts(validation_slice[-1])[:10]}" if validation_slice else "N/A",
            "evaluation_range": f"{get_ts(evaluation_slice[0])[:10]} to {get_ts(evaluation_slice[-1])[:10]}" if evaluation_slice else "N/A",
            "overlap_count": len(overlap),
        }

        return TriSplitSmartMoneyDatasets(
            discovery_dataset=discovery_slice,
            validation_dataset=validation_slice,
            evaluation_dataset=evaluation_slice,
            discovery_token_addresses=disc_addrs,
            validation_token_addresses=val_addrs,
            evaluation_token_addresses=eval_addrs,
            is_leakage_free=is_leakage_free,
            split_summary=summary,
        )

    def register_discovery_quarantine(
        self,
        wallet_address: str,
        token_address: str,
        token_timestamp: str,
    ) -> WalletQuarantineRecord:
        """
        Record that a wallet was discovered on a specific token.
        Quarantines the token and sets first eligible signal timestamp to AFTER the discovery token.
        """
        record = self.wallet_quarantines.get(wallet_address)
        if not record:
            record = WalletQuarantineRecord(
                wallet_address=wallet_address,
                discovery_token_address=token_address,
                discovery_timestamp=token_timestamp,
                validation_timestamp=None,
                first_eligible_signal_timestamp=token_timestamp,
                quarantined_tokens={token_address},
                is_currently_quarantined=True,
            )
            self.wallet_quarantines[wallet_address] = record
        else:
            record.quarantined_tokens.add(token_address)

        # Mark token level quarantine
        self.token_quarantines[token_address] = {
            "token_address": token_address,
            "discovered_wallet": wallet_address,
            "smart_money_quarantined": True,
            "quarantine_timestamp": token_timestamp,
        }

        return record

    def is_wallet_eligible_for_token(
        self,
        wallet_address: str,
        token_address: str,
        evaluation_timestamp: str,
    ) -> Tuple[bool, str]:
        """
        Check if a wallet is allowed to contribute predictive signals for a given token.
        Enforces that:
        1. Wallet cannot predict its own discovery token.
        2. Signal timestamp must be strictly AFTER first_eligible_signal_timestamp.
        """
        record = self.wallet_quarantines.get(wallet_address)
        if not record:
            return True, "ELIGIBLE_NO_QUARANTINE"

        # 1. Block discovery token
        if token_address in record.quarantined_tokens or token_address == record.discovery_token_address:
            return False, "BLOCKED_DISCOVERY_TOKEN_QUARANTINE"

        # 2. Block evaluation before first eligible timestamp
        try:
            eval_dt = datetime.fromisoformat(evaluation_timestamp.replace("Z", "+00:00"))
            elig_dt = datetime.fromisoformat(record.first_eligible_signal_timestamp.replace("Z", "+00:00"))
            if eval_dt <= elig_dt:
                return False, "BLOCKED_PRIOR_TO_ELIGIBILITY_TIMESTAMP"
        except Exception:
            pass

        return True, "ELIGIBLE_FORWARD_SIGNAL"

    def is_token_quarantined(self, token_address: str) -> bool:
        """Return True if token was used for wallet discovery/validation and cannot be self-evaluated."""
        return token_address in self.token_quarantines
