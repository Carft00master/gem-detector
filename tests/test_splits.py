"""
Unit tests for Entity-Disjoint and Cross-Venue Chronological Splitting
"""

import pytest
from src.research.splits import EntityDisjointSplitter


def test_entity_disjoint_token_partitioning():
    """Verify that every snapshot of a token resides in exactly one partition."""
    records = []
    for token_id in range(20):
        addr = f"Token_{token_id:02d}"
        for snap_idx in range(5):
            records.append({
                "token_address": addr,
                "timestamp": f"2026-08-24T{10 + token_id:02d}:{snap_idx * 10:02d}:00Z",
                "market_cap_usd": 15000.0,
                "target_3m": int(token_id % 5 == 0),
            })

    splits = EntityDisjointSplitter.split_chronological_entity_disjoint(
        records, train_ratio=0.60, val_ratio=0.20
    )

    assert splits.has_zero_leakage is True
    assert len(splits.train_tokens) == 12
    assert len(splits.val_tokens) == 4
    assert len(splits.locked_test_tokens) == 4

    # Strict disjointness
    assert len(splits.train_tokens.intersection(splits.val_tokens)) == 0
    assert len(splits.train_tokens.intersection(splits.locked_test_tokens)) == 0
    assert len(splits.val_tokens.intersection(splits.locked_test_tokens)) == 0

    # Strict chronological order
    max_train = max(r["timestamp"] for r in splits.train_records)
    min_val = min(r["timestamp"] for r in splits.val_records)
    assert max_train <= min_val


def test_cross_venue_splitting():
    """Verify cross-venue partition matrix (e.g. Train on Solana, Test on Base)."""
    records = [
        {"token_address": "Sol1", "chain": "solana", "venue": "pumpfun"},
        {"token_address": "Sol2", "chain": "solana", "venue": "raydium"},
        {"token_address": "Base1", "chain": "base", "venue": "aerodrome"},
        {"token_address": "Base2", "chain": "base", "venue": "uniswap"},
    ]

    train_set, test_set = EntityDisjointSplitter.split_by_venue(
        records, train_venues=["solana", "pumpfun", "raydium"], test_venues=["base", "aerodrome", "uniswap"]
    )

    assert len(train_set) == 2
    assert len(test_set) == 2
    assert all(r["chain"] == "solana" for r in train_set)
    assert all(r["chain"] == "base" for r in test_set)
