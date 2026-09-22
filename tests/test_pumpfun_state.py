"""
Unit tests for Pump.fun Point-in-Time Bonding Curve State Execution
"""

import pytest
from src.research.execution import AMMExecutionSimulator, PumpFunPointInTimeCurveState


def test_pumpfun_point_in_time_curve_state():
    sim = AMMExecutionSimulator()

    # Custom point-in-time state with 60 SOL virtual reserve offset (~$9,000 USD)
    custom_state = PumpFunPointInTimeCurveState(
        virtual_base_reserve=1_000_000_000.0,
        virtual_quote_reserve_sol=60.0,
        virtual_quote_reserve_usd=9000.0,
        real_base_reserve=500_000_000.0,
        real_quote_reserve_sol=25.0,
        curve_progress_pct=35.0,
    )

    res = sim.simulate_trade(
        position_size_usd=100.0,
        entry_mc=15000.0,
        exit_mc=150000.0,
        entry_liquidity=4000.0,
        exit_liquidity=40000.0,
        chain="solana",
        venue="pumpfun",
    )

    assert res.is_executable is True
    assert res.venue == "pumpfun"
    assert res.entry_price_impact_pct > 0.0
