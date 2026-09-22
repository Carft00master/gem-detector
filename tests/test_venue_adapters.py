"""
Unit tests for Venue-Specific AMM Execution Adapters
"""

import pytest
from src.research.execution import AMMExecutionSimulator


def test_pumpfun_virtual_offset_vs_raydium_standard_amm():
    sim = AMMExecutionSimulator()

    # Pump.fun pool with $1,000 real liquidity (benefits from virtual reserve cushion)
    pump_exec = sim.simulate_trade(
        position_size_usd=100.0,
        entry_mc=10000.0,
        exit_mc=100000.0,
        entry_liquidity=1000.0,
        exit_liquidity=10000.0,
        chain="solana",
        venue="pumpfun",
    )
    assert pump_exec.is_executable is True
    # Impact should reflect ~30 SOL virtual reserve cushion
    assert pump_exec.entry_price_impact_pct < 2.5

    # Raydium with $1,000 real liquidity (< $1,500 threshold) should be rejected
    ray_exec = sim.simulate_trade(
        position_size_usd=100.0,
        entry_mc=10000.0,
        exit_mc=100000.0,
        entry_liquidity=1000.0,
        exit_liquidity=10000.0,
        chain="solana",
        venue="raydium",
    )
    assert ray_exec.is_executable is False
    assert ray_exec.execution_rejection_reason == "INSUFFICIENT_LIQUIDITY_DEPTH"


def test_uniswap_and_aerodrome_adapters():
    sim = AMMExecutionSimulator()

    # Uniswap V2 Base
    uni_exec = sim.simulate_trade(
        position_size_usd=250.0,
        entry_mc=15000.0,
        exit_mc=150000.0,
        entry_liquidity=5000.0,
        exit_liquidity=50000.0,
        chain="base",
        venue="uniswap-v2-base",
    )
    assert uni_exec.is_executable is True
    assert uni_exec.pool_type == "uniswap_v2"

    # Aerodrome concentrated liquidity (lower price impact due to tick depth)
    aero_exec = sim.simulate_trade(
        position_size_usd=250.0,
        entry_mc=15000.0,
        exit_mc=150000.0,
        entry_liquidity=5000.0,
        exit_liquidity=50000.0,
        chain="base",
        venue="aerodrome",
    )
    assert aero_exec.is_executable is True
    assert "concentrated" in aero_exec.pool_type
    assert aero_exec.entry_price_impact_pct < uni_exec.entry_price_impact_pct
