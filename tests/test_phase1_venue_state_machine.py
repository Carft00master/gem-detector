"""
Phase 1c Tests: Per-Token Venue State Machine
Tests CURVE_OPEN -> MIGRATED -> POOL transitions, venue validation,
and price continuity checks across migration boundaries.
"""

import pytest
from src.paper.venue_state_machine import VenueStateMachine, VenueState


@pytest.fixture
def fsm():
    return VenueStateMachine()


def test_venue_state_transitions(fsm):
    mint = "TestMint1234567890"
    # Default initial state is CURVE_OPEN
    assert fsm.get_token_state(mint) == VenueState.CURVE_OPEN

    # Transition to MIGRATED
    fsm.on_curve_migration_detected(mint=mint, slot=100, pool_address="PoolAddr123")
    assert fsm.get_token_state(mint) == VenueState.MIGRATED

    # Transition to POOL
    fsm.on_pool_active_detected(mint=mint, slot=105, pool_address="PoolAddr123")
    assert fsm.get_token_state(mint) == VenueState.POOL


def test_stale_curve_entry_rejected_after_migration(fsm):
    mint = "qTFyfJiSQhMooT6LzybsWHjMXSGWsdkY3w8C9aXpump"  # NODF
    fsm.on_curve_migration_detected(mint=mint, slot=456718840, pool_address="BNchF8GCxGKxsWbpkUE5D8RhGfB31QGT7DbAvMPY7RiV")

    # Trying to enter on pumpfun curve after token migrated
    is_valid, err = fsm.validate_entry_venue(mint, requested_venue="pumpfun")
    assert not is_valid
    assert "REJECT_STALE_VENUE" in err


def test_premature_pool_entry_rejected_while_curve_open(fsm):
    mint = "OpenCurveMint123"
    # Token was tracked as CURVE_OPEN
    fsm.get_token_state(mint, default_venue="pumpfun")

    # Trying to enter on Raydium before migration has occurred
    is_valid, err = fsm.validate_entry_venue(mint, requested_venue="raydium")
    assert not is_valid
    assert "REJECT_PREMATURE_VENUE" in err


def test_price_continuity_verification(fsm):
    mint = "ContinuityTestMint"
    
    # Plausible transition (curve close $0.000030 -> pool open $0.000035 = 1.16x)
    is_ok, err = fsm.check_price_continuity(mint, curve_price=0.000030, pool_price=0.000035)
    assert is_ok
    assert err is None

    # Implausible phantom jump (curve close $0.000012 -> pool open $0.006834 = 569x jump!)
    is_ok2, err2 = fsm.check_price_continuity(mint, curve_price=0.000012, pool_price=0.006834)
    assert not is_ok2
    assert "IMPLAUSIBLE_VENUE_PRICE_JUMP" in err2
    assert "569.50x" in err2
