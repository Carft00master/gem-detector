"""
Phase 1b Tests: Pyth SOL/USD Oracle Layer
Tests Pyth price parsing, SQLite timestamped store, forward-fill,
10s staleness rejection, secondary pool divergence, and NODF reconciliation.
"""

import struct
import pytest
from src.oracle.sol_usd import (
    PythSolUsdOracle,
    OraclePriceRecord,
    StaleOraclePriceError,
    OracleDivergenceAlert,
)


@pytest.fixture
def oracle(tmp_path):
    db_file = tmp_path / "test_oracle.db"
    return PythSolUsdOracle(db_path=db_file)


def test_oracle_seed_and_nodf_calibration_price(oracle):
    # NODF calibration block time 1791954967
    rec = oracle.get_price_at_timestamp(1791954967, max_staleness_seconds=10.0)
    assert rec is not None
    # Reconciled price: $9,124.64 / 85.0069 SOL = $107.34
    assert rec.price_usd == 107.34
    assert rec.source == "CALIBRATED_AUDIT_RECONCILED"


def test_oracle_record_and_forward_fill(oracle):
    t0 = 1000000
    oracle.record_price(timestamp=t0, price_usd=150.25, conf_usd=0.05, slot=300000)

    # Within 10s forward fill
    p1 = oracle.get_price_at_timestamp(t0 + 5, max_staleness_seconds=10.0)
    assert p1.price_usd == 150.25

    # Exact timestamp lookup
    p0 = oracle.get_price_at_timestamp(t0, max_staleness_seconds=10.0)
    assert p0.price_usd == 150.25


def test_oracle_fail_closed_on_stale_price(oracle):
    t0 = 1000000
    oracle.record_price(timestamp=t0, price_usd=150.25, conf_usd=0.05)

    # 11 seconds later: exceeds 10s maximum staleness threshold
    with pytest.raises(StaleOraclePriceError) as exc_info:
        oracle.get_price_at_timestamp(t0 + 11, max_staleness_seconds=10.0)
    assert "FAIL-CLOSED" in str(exc_info.value)
    assert "11.0s old" in str(exc_info.value)


def test_oracle_secondary_venue_cross_check_and_divergence_logging(oracle, caplog):
    # Primary: $150.00, Secondary: $152.00 (divergence = 1.33% > 1.0%)
    rec = oracle.record_price(
        timestamp=2000000,
        price_usd=150.00,
        conf_usd=0.05,
        secondary_price_usd=152.00,
    )
    assert rec.divergence_pct == pytest.approx(1.3333, abs=0.01)
    # Check warning was logged
    assert any("ORACLE_DIVERGENCE_ALERT" in record.message for record in caplog.records)


def test_parse_pyth_account_data(oracle):
    # Build a simulated 240-byte Pyth PriceAccount binary buffer
    # expo at offset 20: int32 = -8
    # price at offset 208: int64 = 15234000000 -> $152.34
    # conf at offset 216: uint64 = 8000000 -> $0.08
    # pub_slot at offset 232: uint64 = 312345678
    raw = bytearray(256)
    struct.pack_into('<i', raw, 20, -8)
    struct.pack_into('<q', raw, 208, 15234000000)
    struct.pack_into('<Q', raw, 216, 8000000)
    struct.pack_into('<Q', raw, 232, 312345678)

    rec = oracle.parse_pyth_account_data(bytes(raw), current_timestamp=3000000)
    assert rec.price_usd == 152.34
    assert rec.conf_usd == 0.08
    assert rec.slot == 312345678
    assert rec.source == "PYTH_ONCHAIN"
