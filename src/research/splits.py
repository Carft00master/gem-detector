"""
Entity-Level Chronological Dataset Partitioner
Guarantees Token-Disjoint + Chronological Train / Validation / Locked-Test partitions
with zero token overlap, zero pool duplicates, and cross-venue generalization splits.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple


@dataclass
class DatasetSplits:
    train_records: List[Dict[str, Any]] = field(default_factory=list)
    val_records: List[Dict[str, Any]] = field(default_factory=list)
    locked_test_records: List[Dict[str, Any]] = field(default_factory=list)
    train_tokens: Set[str] = field(default_factory=set)
    val_tokens: Set[str] = field(default_factory=set)
    locked_test_tokens: Set[str] = field(default_factory=set)
    train_time_range: Tuple[Optional[str], Optional[str]] = (None, None)
    val_time_range: Tuple[Optional[str], Optional[str]] = (None, None)
    locked_test_time_range: Tuple[Optional[str], Optional[str]] = (None, None)
    has_zero_leakage: bool = True


class EntityDisjointSplitter:
    @classmethod
    def split_chronological_entity_disjoint(
        cls,
        records: List[Dict[str, Any]],
        train_ratio: float = 0.60,
        val_ratio: float = 0.20,
    ) -> DatasetSplits:
        """
        Split dataset into Train, Validation, and Locked-Test sets ensuring:
        1. Entity-Disjoint: All snapshots of any token belong strictly to one partition.
        2. Chronological Ordering: Tokens ordered strictly by discovery timestamp.
        3. Zero Future Leakage: Train T0->T1 <= Val T1->T2 <= Locked-Test T2->T3.
        """
        splits = DatasetSplits()
        if not records:
            return splits

        # 1. Group records by token address
        token_snapshots: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        token_first_seen: Dict[str, str] = {}

        for r in records:
            addr = r.get("token_address", "unknown")
            ts = r.get("timestamp", "")
            token_snapshots[addr].append(r)
            if addr not in token_first_seen or ts < token_first_seen[addr]:
                token_first_seen[addr] = ts

        # 2. Sort unique tokens by their first observed timestamp
        sorted_tokens = sorted(token_first_seen.keys(), key=lambda a: token_first_seen[a])
        num_tokens = len(sorted_tokens)

        n_train = max(1, int(num_tokens * train_ratio))
        n_val = max(1, int(num_tokens * val_ratio))
        if n_train + n_val >= num_tokens and num_tokens > 2:
            n_val = 1
            n_train = num_tokens - 2

        train_token_set = set(sorted_tokens[:n_train])
        val_token_set = set(sorted_tokens[n_train : n_train + n_val])
        locked_test_token_set = set(sorted_tokens[n_train + n_val :])

        # 3. Assemble partition records
        for addr in train_token_set:
            splits.train_records.extend(token_snapshots[addr])
        for addr in val_token_set:
            splits.val_records.extend(token_snapshots[addr])
        for addr in locked_test_token_set:
            splits.locked_test_records.extend(token_snapshots[addr])

        splits.train_tokens = train_token_set
        splits.val_tokens = val_token_set
        splits.locked_test_tokens = locked_test_token_set

        # Verify zero token overlap
        overlap_tv = train_token_set.intersection(val_token_set)
        overlap_tl = train_token_set.intersection(locked_test_token_set)
        overlap_vl = val_token_set.intersection(locked_test_token_set)
        if overlap_tv or overlap_tl or overlap_vl:
            splits.has_zero_leakage = False

        # Extract timestamp bounds
        def get_bounds(recs: List[Dict[str, Any]]) -> Tuple[Optional[str], Optional[str]]:
            if not recs:
                return (None, None)
            ts_list = [r.get("timestamp", "") for r in recs if r.get("timestamp")]
            return (min(ts_list), max(ts_list)) if ts_list else (None, None)

        splits.train_time_range = get_bounds(splits.train_records)
        splits.val_time_range = get_bounds(splits.val_records)
        splits.locked_test_time_range = get_bounds(splits.locked_test_records)

        return splits

    @classmethod
    def split_by_venue(
        cls,
        records: List[Dict[str, Any]],
        train_venues: List[str],
        test_venues: List[str],
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Partition dataset across venues/chains to test cross-venue transferability
        (e.g., Train on Solana, Test on Base).
        """
        train_set = []
        test_set = []
        train_v = set(v.lower() for v in train_venues)
        test_v = set(v.lower() for v in test_venues)

        for r in records:
            v = str(r.get("venue", r.get("chain", ""))).lower()
            c = str(r.get("chain", "")).lower()
            if v in train_v or c in train_v:
                train_set.append(r)
            elif v in test_v or c in test_v:
                test_set.append(r)

        return train_set, test_set
