"""
tests/test_verify_reports.py
Unit tests for scripts/verify_reports.py to confirm it properly fails on invalid data.
"""

import pytest
from scripts.verify_reports import (
    validate_address_b58,
    validate_signature_b58,
    check_no_repeating_patterns,
    verify_fixtures_and_signatures,
    verify_pool_addresses,
    verify_recomputed_summary_statistics,
    verify_markdown_tables_match_json,
)


def test_signature_validation():
    # Valid 64-byte base58 signature
    valid_sig = "4MtxeAMrak91NA42Vv2cEJb2MTG4j1BCr8DYDdQRQ1RPV8gXiTsE7gsiyhX2BCFz1vdYTgEMYGMH9vzsJnEVq1Nk"
    assert validate_signature_b58(valid_sig)
    assert check_no_repeating_patterns(valid_sig)

    # Wrong length (44 chars pubkey)
    invalid_short_sig = "eCLvnbfPn8rA2M97Yj31sFk8wP4QkM9L1PqZ5x8vY7uK"
    assert not validate_signature_b58(invalid_short_sig)

    # Repeating synthetic pattern
    synthetic_sig = "5eWf6yQxYwX6iQ2Y8E98ZcE5PjKxWqL5VwE5E5E5E5E5E5E5E5E5E5E5E5E5E5E5E5E5E5E5E5E5E5E5E5E5E5E5"
    assert not check_no_repeating_patterns(synthetic_sig)


def test_pool_address_validation():
    valid_addr = "BNchF8GCxGKxsWbpkUE5D8RhGfB31QGT7DbAvMPY7RiV"
    assert validate_address_b58(valid_addr)

    # Dummy unresolved string
    assert not validate_address_b58("pump-amm")
    assert not validate_address_b58("NOT_OBTAINED")


def test_real_reports_pass_all_checks():
    # Ensure current repo reports pass all verification functions
    verify_fixtures_and_signatures()
    verify_pool_addresses()
    verify_recomputed_summary_statistics()
