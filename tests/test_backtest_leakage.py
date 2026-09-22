"""
Unit tests for Temporal Integrity and Strict Absence of Future Data Leakage
"""

from datetime import datetime, timedelta, timezone
import pytest
from src.models.train import TemporalWalkForwardTrainer
from src.research.storage import ResearchStorage


def test_strict_chronological_splitting_no_leakage():
    """Verify that temporal splitting strictly orders data by time without shuffle leakage."""
    base_time = datetime(2026, 8, 24, 10, 0, 0, tzinfo=timezone.utc)
    records = []
    for i in range(100):
        t = base_time + timedelta(minutes=i * 5)
        records.append({
            "token_address": f"T_{i}",
            "timestamp": t.isoformat(),
            "market_cap_usd": 10000.0 + i * 100,
            "target_3m": int(i % 10 == 0),
        })

    trainer = TemporalWalkForwardTrainer()
    train_set, val_set, test_set = trainer.split_data_temporally(records, train_ratio=0.60, val_ratio=0.20)

    # 1. Check partition sizes
    assert len(train_set) == 60
    assert len(val_set) == 20
    assert len(test_set) == 20

    # 2. Verify all Train timestamps are strictly strictly before Validation timestamps
    max_train_time = max(r["timestamp"] for r in train_set)
    min_val_time = min(r["timestamp"] for r in val_set)
    assert max_train_time <= min_val_time

    # 3. Verify all Validation timestamps are strictly before Test timestamps
    max_val_time = max(r["timestamp"] for r in val_set)
    min_test_time = min(r["timestamp"] for r in test_set)
    assert max_val_time <= min_test_time
