"""
Smart Wallet Cluster & Sybil Grouping Engine
Integrates with wallet transaction graphs to identify:
- Common funding origins
- Synchronized entry/exit execution windows
- Shared counterparty infrastructure
- Sybil clones operating as single synthetic actors

Calculates EFFECTIVE_INDEPENDENT_WALLET_COUNT to prevent 10 sybils from multiplying conviction.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime
import logging
from typing import Any, Dict, List, Set, Tuple

logger = logging.getLogger(__name__)


@dataclass
class WalletClusterRecord:
    cluster_id: str
    wallet_addresses: List[str]
    cluster_size: int
    common_funder: Optional[str]
    is_sybil_ring: bool
    effective_independent_count: float
    confidence: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class WalletClusterDetector:
    """
    Groups correlated wallets and computes effective independent signal counts.
    """

    @classmethod
    def analyze_wallet_set(
        cls,
        wallets: List[str],
        funding_map: Optional[Dict[str, str]] = None,
        synchronized_groups: Optional[List[List[str]]] = None,
    ) -> Tuple[List[WalletClusterRecord], float]:
        """
        Partition a group of participating wallets into clusters and return the total effective count.
        """
        if not wallets:
            return [], 0.0

        funding = funding_map or {}
        synced = synchronized_groups or []

        # Build adjacency graph
        parent: Dict[str, str] = {w: w for w in wallets}

        def find(u: str) -> str:
            if parent[u] != u:
                parent[u] = find(parent[u])
            return parent[u]

        def union(u: str, v: str):
            root_u = find(u)
            root_v = find(v)
            if root_u != root_v:
                parent[root_u] = root_v

        # Connect wallets with common private funding
        funder_groups: Dict[str, List[str]] = {}
        for w in wallets:
            f = funding.get(w)
            if f and not f.startswith("exchange_") and not f.startswith("bridge_"):
                funder_groups.setdefault(f, []).append(w)

        for f_addr, group in funder_groups.items():
            for i in range(1, len(group)):
                union(group[0], group[i])

        # Connect synchronized execution groups
        for group in synced:
            present = [w for w in group if w in parent]
            for i in range(1, len(present)):
                union(present[0], present[i])

        # Collect clusters
        clusters_map: Dict[str, List[str]] = {}
        for w in wallets:
            root = find(w)
            clusters_map.setdefault(root, []).append(w)

        cluster_records: List[WalletClusterRecord] = []
        total_effective_count = 0.0

        for root, members in clusters_map.items():
            k = len(members)
            # Sybil discounting: effective count = k^0.35 if grouped, or 1.0 if independent
            eff_count = 1.0 if k == 1 else round(k ** 0.35, 2)
            total_effective_count += eff_count

            cluster_records.append(WalletClusterRecord(
                cluster_id=f"cluster_{root[:8]}",
                wallet_addresses=members,
                cluster_size=k,
                common_funder=funding.get(root),
                is_sybil_ring=(k > 1),
                effective_independent_count=eff_count,
                confidence=0.90 if k > 1 else 0.50,
            ))

        return cluster_records, round(total_effective_count, 2)
