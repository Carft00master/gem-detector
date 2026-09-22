"""
Venue-Specific AMM Execution & Dynamic Slippage Simulation Engine (v1.0.0 Frozen)
Implements exact reserve-based swap equations:
1. PumpFunBondingCurveExecution: Virtual SOL reserve offset (~30 SOL = ~$4,500) and 1.0% fee.
2. RaydiumConstantProductExecution: Standard constant-product AMM (x * y = k) with quote reserve x = L / 2, 0.25% fee.
3. UniswapV2BaseExecution: Standard constant-product AMM (x * y = k) with quote reserve x = L / 2, 0.30% fee.
4. UniswapV3ConcentratedExecution: Explicitly labeled CONCENTRATED_TICK_APPROXIMATION (Active Tick Virtual Depth Factor: 2.0x).
5. UnsupportedVenueExecution: Formally rejects unmodeled pool structures.

Calculates exact size-dependent executable returns across $25 to $1,000 position sizes
and solves exact analytical trade equations for 1%, 2%, 5%, and 10% price impact per venue.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import math
from typing import Any, Dict, List, Optional, Tuple
from src.version import EXECUTION_MODEL_VERSION


@dataclass
class MaxPositionSizeLimits:
    max_position_1pct_usd: float = 0.0
    max_position_2pct_usd: float = 0.0
    max_position_5pct_usd: float = 0.0
    max_position_10pct_usd: float = 0.0


@dataclass
class TradeExecutionResult:
    execution_model_version: str = EXECUTION_MODEL_VERSION
    position_size_usd: float = 100.0
    entry_market_cap: float = 15000.0
    exit_market_cap: float = 1500000.0
    entry_liquidity: float = 4000.0
    exit_liquidity: float = 300000.0
    chain: str = "solana"
    venue: str = "raydium"
    pool_type: str = "constant_product"

    # Slippage & Cost Breakdown
    entry_price_impact_pct: float = 0.0
    exit_price_impact_pct: float = 0.0
    dex_swap_fees_usd: float = 0.0
    network_priority_fees_usd: float = 0.0
    total_slippage_and_friction_usd: float = 0.0

    # Returns Comparison & Excursion
    theoretical_mfe_ratio: float = 1.0     # Exit MC / Entry MC
    executable_mfe_ratio: float = 1.0      # Net realized cash multiple (Exit Proceeds / Entry Capital)
    net_realized_pnl_usd: float = 0.0
    net_realized_return_pct: float = 0.0
    max_adverse_excursion_pct: float = 0.0
    is_executable: bool = True
    execution_rejection_reason: Optional[str] = None


class ExecutionModel(ABC):
    @abstractmethod
    def simulate(
        self,
        position_size_usd: float,
        entry_mc: float,
        exit_mc: float,
        entry_liquidity: float,
        exit_liquidity: float,
        chain: str,
        priority_fee_usd: float,
        trough_mc: Optional[float] = None,
    ) -> TradeExecutionResult:
        pass

    @abstractmethod
    def calculate_max_position(self, liquidity_usd: float, target_impact: float) -> float:
        """Solve trade equation for target price impact threshold I in [0, 1]."""
        pass


@dataclass
class PumpFunPointInTimeCurveState:
    virtual_base_reserve: float = 1_073_000_000.0  # 1.073B tokens
    virtual_quote_reserve_sol: float = 30.0         # 30 SOL
    virtual_quote_reserve_usd: float = 4500.0       # ~$4,500
    real_base_reserve: float = 793_100_000.0        # Tokens in curve
    real_quote_reserve_sol: float = 0.0             # SOL collected
    curve_progress_pct: float = 0.0                 # 0 - 100%
    curve_state: str = "BONDING_ACTIVE"             # "BONDING_ACTIVE" | "GRADUATION_PENDING" | "MIGRATED_RAYDIUM"
    curve_state_timestamp: Optional[str] = None


class PumpFunBondingCurveExecution(ExecutionModel):
    """
    Pump.fun virtual bonding curve with point-in-time reserve state tracking and 1.0% platform fee.
    """
    def simulate(
        self,
        position_size_usd: float,
        entry_mc: float,
        exit_mc: float,
        entry_liquidity: float,
        exit_liquidity: float,
        chain: str,
        priority_fee_usd: float,
        trough_mc: Optional[float] = None,
        curve_state: Optional[PumpFunPointInTimeCurveState] = None,
    ) -> TradeExecutionResult:
        res = TradeExecutionResult(
            position_size_usd=position_size_usd,
            entry_market_cap=entry_mc,
            exit_market_cap=exit_mc,
            entry_liquidity=entry_liquidity,
            exit_liquidity=exit_liquidity,
            chain=chain,
            venue="pumpfun",
            pool_type="virtual_bonding_curve",
        )
        if entry_mc <= 0 or exit_mc <= 0:
            res.is_executable = False
            res.execution_rejection_reason = "INVALID_MARKET_CAP"
            return res

        # In 50/50 virtual curve, effective quote reserve x = (L_real / 2) + virtual_quote_reserve
        v_offset = curve_state.virtual_quote_reserve_usd if curve_state else 4500.0
        eff_entry_x = max(500.0, (entry_liquidity / 2.0) + v_offset)
        eff_exit_x = max(500.0, (exit_liquidity / 2.0) + v_offset)

        fee_pct = 1.00 # 1.0% Pump.fun fee
        entry_impact = position_size_usd / (eff_entry_x + position_size_usd)
        res.entry_price_impact_pct = round(entry_impact * 100.0, 3)

        entry_fee = position_size_usd * (fee_pct / 100.0)
        net_entry_capital = (position_size_usd - entry_fee) * (1.0 - entry_impact)

        price_multiple = exit_mc / entry_mc
        gross_exit_val = net_entry_capital * price_multiple

        exit_impact = gross_exit_val / (eff_exit_x + gross_exit_val)
        res.exit_price_impact_pct = round(exit_impact * 100.0, 3)

        exit_fee = gross_exit_val * (fee_pct / 100.0)
        net_exit_capital = (gross_exit_val - exit_fee) * (1.0 - exit_impact)

        total_net_fees = priority_fee_usd * 2.0
        res.dex_swap_fees_usd = round(entry_fee + exit_fee, 2)
        res.network_priority_fees_usd = round(total_net_fees, 2)

        realized_pnl = net_exit_capital - position_size_usd - total_net_fees
        res.net_realized_pnl_usd = round(realized_pnl, 2)
        res.net_realized_return_pct = round((realized_pnl / position_size_usd) * 100.0, 2)
        res.theoretical_mfe_ratio = round(price_multiple, 2)
        res.executable_mfe_ratio = round(net_exit_capital / position_size_usd, 3)
        res.total_slippage_and_friction_usd = round((position_size_usd * price_multiple) - net_exit_capital + total_net_fees, 2)

        trough = trough_mc or entry_mc
        if trough < entry_mc:
            res.max_adverse_excursion_pct = round(((entry_mc - trough) / entry_mc) * 100.0, 2)
        return res

    def calculate_max_position(self, liquidity_usd: float, target_impact: float) -> float:
        eff_x = (liquidity_usd / 2.0) + 4500.0
        return round((target_impact * eff_x) / (1.0 - target_impact), 2)


class RaydiumConstantProductExecution(ExecutionModel):
    """Standard Constant Product AMM (x * y = k) with quote reserve x = L / 2 and 0.25% fee."""
    def simulate(
        self,
        position_size_usd: float,
        entry_mc: float,
        exit_mc: float,
        entry_liquidity: float,
        exit_liquidity: float,
        chain: str,
        priority_fee_usd: float,
        trough_mc: Optional[float] = None,
    ) -> TradeExecutionResult:
        res = TradeExecutionResult(
            position_size_usd=position_size_usd,
            entry_market_cap=entry_mc,
            exit_market_cap=exit_mc,
            entry_liquidity=entry_liquidity,
            exit_liquidity=exit_liquidity,
            chain=chain,
            venue="raydium",
            pool_type="constant_product",
        )
        if entry_liquidity < 1500.0:
            res.is_executable = False
            res.execution_rejection_reason = "INSUFFICIENT_LIQUIDITY_DEPTH"
            return res

        fee_pct = 0.25
        quote_reserve_entry = entry_liquidity / 2.0
        quote_reserve_exit = exit_liquidity / 2.0

        entry_impact = position_size_usd / (quote_reserve_entry + position_size_usd)
        res.entry_price_impact_pct = round(entry_impact * 100.0, 3)

        entry_fee = position_size_usd * (fee_pct / 100.0)
        net_entry_capital = (position_size_usd - entry_fee) * (1.0 - entry_impact)

        price_multiple = exit_mc / entry_mc
        gross_exit_val = net_entry_capital * price_multiple

        exit_impact = gross_exit_val / (quote_reserve_exit + gross_exit_val)
        res.exit_price_impact_pct = round(exit_impact * 100.0, 3)

        exit_fee = gross_exit_val * (fee_pct / 100.0)
        net_exit_capital = (gross_exit_val - exit_fee) * (1.0 - exit_impact)

        total_net_fees = priority_fee_usd * 2.0
        res.dex_swap_fees_usd = round(entry_fee + exit_fee, 2)
        res.network_priority_fees_usd = round(total_net_fees, 2)

        realized_pnl = net_exit_capital - position_size_usd - total_net_fees
        res.net_realized_pnl_usd = round(realized_pnl, 2)
        res.net_realized_return_pct = round((realized_pnl / position_size_usd) * 100.0, 2)
        res.theoretical_mfe_ratio = round(price_multiple, 2)
        res.executable_mfe_ratio = round(net_exit_capital / position_size_usd, 3)
        res.total_slippage_and_friction_usd = round((position_size_usd * price_multiple) - net_exit_capital + total_net_fees, 2)

        trough = trough_mc or entry_mc
        if trough < entry_mc:
            res.max_adverse_excursion_pct = round(((entry_mc - trough) / entry_mc) * 100.0, 2)
        return res

    def calculate_max_position(self, liquidity_usd: float, target_impact: float) -> float:
        if liquidity_usd < 1500.0:
            return 0.0
        quote_reserve = liquidity_usd / 2.0
        return round((target_impact * quote_reserve) / (1.0 - target_impact), 2)


class UniswapV2BaseExecution(ExecutionModel):
    """Standard Uniswap V2 AMM (x * y = k) with quote reserve x = L / 2 and 0.30% fee on Base."""
    def simulate(
        self,
        position_size_usd: float,
        entry_mc: float,
        exit_mc: float,
        entry_liquidity: float,
        exit_liquidity: float,
        chain: str,
        priority_fee_usd: float,
        trough_mc: Optional[float] = None,
    ) -> TradeExecutionResult:
        res = TradeExecutionResult(
            position_size_usd=position_size_usd,
            entry_market_cap=entry_mc,
            exit_market_cap=exit_mc,
            entry_liquidity=entry_liquidity,
            exit_liquidity=exit_liquidity,
            chain=chain,
            venue="uniswap",
            pool_type="uniswap_v2",
        )
        if entry_liquidity < 1500.0:
            res.is_executable = False
            res.execution_rejection_reason = "INSUFFICIENT_LIQUIDITY_DEPTH"
            return res

        fee_pct = 0.30
        quote_reserve_entry = entry_liquidity / 2.0
        quote_reserve_exit = exit_liquidity / 2.0

        entry_impact = position_size_usd / (quote_reserve_entry + position_size_usd)
        res.entry_price_impact_pct = round(entry_impact * 100.0, 3)

        entry_fee = position_size_usd * (fee_pct / 100.0)
        net_entry_capital = (position_size_usd - entry_fee) * (1.0 - entry_impact)

        price_multiple = exit_mc / entry_mc
        gross_exit_val = net_entry_capital * price_multiple

        exit_impact = gross_exit_val / (quote_reserve_exit + gross_exit_val)
        res.exit_price_impact_pct = round(exit_impact * 100.0, 3)

        exit_fee = gross_exit_val * (fee_pct / 100.0)
        net_exit_capital = (gross_exit_val - exit_fee) * (1.0 - exit_impact)

        total_net_fees = priority_fee_usd * 2.0
        res.dex_swap_fees_usd = round(entry_fee + exit_fee, 2)
        res.network_priority_fees_usd = round(total_net_fees, 2)

        realized_pnl = net_exit_capital - position_size_usd - total_net_fees
        res.net_realized_pnl_usd = round(realized_pnl, 2)
        res.net_realized_return_pct = round((realized_pnl / position_size_usd) * 100.0, 2)
        res.theoretical_mfe_ratio = round(price_multiple, 2)
        res.executable_mfe_ratio = round(net_exit_capital / position_size_usd, 3)
        res.total_slippage_and_friction_usd = round((position_size_usd * price_multiple) - net_exit_capital + total_net_fees, 2)

        trough = trough_mc or entry_mc
        if trough < entry_mc:
            res.max_adverse_excursion_pct = round(((entry_mc - trough) / entry_mc) * 100.0, 2)
        return res

    def calculate_max_position(self, liquidity_usd: float, target_impact: float) -> float:
        if liquidity_usd < 1500.0:
            return 0.0
        quote_reserve = liquidity_usd / 2.0
        return round((target_impact * quote_reserve) / (1.0 - target_impact), 2)


class UniswapV3ConcentratedExecution(ExecutionModel):
    """
    Concentrated Liquidity AMM (Uniswap V3 / Aerodrome Slipstream).
    Explicitly labeled as CONCENTRATED_TICK_APPROXIMATION with 2.0x virtual depth near active tick.
    """
    def simulate(
        self,
        position_size_usd: float,
        entry_mc: float,
        exit_mc: float,
        entry_liquidity: float,
        exit_liquidity: float,
        chain: str,
        priority_fee_usd: float,
        trough_mc: Optional[float] = None,
    ) -> TradeExecutionResult:
        res = TradeExecutionResult(
            position_size_usd=position_size_usd,
            entry_market_cap=entry_mc,
            exit_market_cap=exit_mc,
            entry_liquidity=entry_liquidity,
            exit_liquidity=exit_liquidity,
            chain=chain,
            venue="aerodrome",
            pool_type="concentrated_tick_approximation",
        )
        if entry_liquidity < 1500.0:
            res.is_executable = False
            res.execution_rejection_reason = "INSUFFICIENT_LIQUIDITY_DEPTH"
            return res

        fee_pct = 0.20
        # Active tick virtual depth factor: 2.0x quote reserve depth near current tick
        eff_quote_entry = entry_liquidity # (L / 2) * 2.0 = L
        eff_quote_exit = exit_liquidity

        entry_impact = position_size_usd / (eff_quote_entry + position_size_usd)
        res.entry_price_impact_pct = round(entry_impact * 100.0, 3)

        entry_fee = position_size_usd * (fee_pct / 100.0)
        net_entry_capital = (position_size_usd - entry_fee) * (1.0 - entry_impact)

        price_multiple = exit_mc / entry_mc
        gross_exit_val = net_entry_capital * price_multiple

        exit_impact = gross_exit_val / (eff_quote_exit + gross_exit_val)
        res.exit_price_impact_pct = round(exit_impact * 100.0, 3)

        exit_fee = gross_exit_val * (fee_pct / 100.0)
        net_exit_capital = (gross_exit_val - exit_fee) * (1.0 - exit_impact)

        total_net_fees = priority_fee_usd * 2.0
        res.dex_swap_fees_usd = round(entry_fee + exit_fee, 2)
        res.network_priority_fees_usd = round(total_net_fees, 2)

        realized_pnl = net_exit_capital - position_size_usd - total_net_fees
        res.net_realized_pnl_usd = round(realized_pnl, 2)
        res.net_realized_return_pct = round((realized_pnl / position_size_usd) * 100.0, 2)
        res.theoretical_mfe_ratio = round(price_multiple, 2)
        res.executable_mfe_ratio = round(net_exit_capital / position_size_usd, 3)
        res.total_slippage_and_friction_usd = round((position_size_usd * price_multiple) - net_exit_capital + total_net_fees, 2)

        trough = trough_mc or entry_mc
        if trough < entry_mc:
            res.max_adverse_excursion_pct = round(((entry_mc - trough) / entry_mc) * 100.0, 2)
        return res

    def calculate_max_position(self, liquidity_usd: float, target_impact: float) -> float:
        if liquidity_usd < 1500.0:
            return 0.0
        eff_quote = liquidity_usd
        return round((target_impact * eff_quote) / (1.0 - target_impact), 2)


class UnsupportedVenueExecution(ExecutionModel):
    """Rejects unmodeled or unsupported pool structures."""
    def simulate(
        self,
        position_size_usd: float,
        entry_mc: float,
        exit_mc: float,
        entry_liquidity: float,
        exit_liquidity: float,
        chain: str,
        priority_fee_usd: float,
        trough_mc: Optional[float] = None,
    ) -> TradeExecutionResult:
        res = TradeExecutionResult(
            position_size_usd=position_size_usd,
            entry_market_cap=entry_mc,
            exit_market_cap=exit_mc,
            entry_liquidity=entry_liquidity,
            exit_liquidity=exit_liquidity,
            chain=chain,
            venue="unsupported",
            pool_type="unsupported",
            is_executable=False,
            execution_rejection_reason="UNSUPPORTED_POOL_STRUCTURE",
        )
        return res

    def calculate_max_position(self, liquidity_usd: float, target_impact: float) -> float:
        return 0.0


class AMMExecutionSimulator:
    def __init__(
        self,
        dex_fee_pct: float = 0.30,
        min_pool_liquidity_usd: float = 5000.0,
        solana_priority_fee_usd: float = 0.02,
        base_priority_fee_usd: float = 0.05,
        bsc_priority_fee_usd: float = 0.03,
        robinhood_priority_fee_usd: float = 0.01,
        **kwargs,
    ):
        self.dex_fee_pct = dex_fee_pct
        self.min_pool_liquidity_usd = min_pool_liquidity_usd
        self.solana_priority_fee_usd = solana_priority_fee_usd
        self.base_priority_fee_usd = base_priority_fee_usd
        self.bsc_priority_fee_usd = bsc_priority_fee_usd
        self.robinhood_priority_fee_usd = robinhood_priority_fee_usd

        self.adapters: Dict[str, ExecutionModel] = {
            "pumpfun": PumpFunBondingCurveExecution(),
            "pump-fun": PumpFunBondingCurveExecution(),
            "pumpswap": PumpFunBondingCurveExecution(),
            "raydium": RaydiumConstantProductExecution(),
            "meteora": RaydiumConstantProductExecution(),
            "pancakeswap": UniswapV2BaseExecution(),
            "pancake": UniswapV2BaseExecution(),
            "uniswap": UniswapV2BaseExecution(),
            "uniswap-v2-base": UniswapV2BaseExecution(),
            "uniswap-v4-base": UniswapV3ConcentratedExecution(),
            "ramses": UniswapV2BaseExecution(),
            "aerodrome": UniswapV3ConcentratedExecution(),
            "unsupported": UnsupportedVenueExecution(),
        }
        self.default_adapter = RaydiumConstantProductExecution()

    def get_adapter(self, venue: str) -> ExecutionModel:
        v_lower = venue.lower()
        if "unsupported" in v_lower or "custom_exotic" in v_lower:
            return self.adapters["unsupported"]
        for k, adapter in self.adapters.items():
            if k in v_lower:
                return adapter
        return self.default_adapter

    def calculate_max_position_limits(self, liquidity_usd: float, venue: str = "raydium") -> MaxPositionSizeLimits:
        """
        Calculate per-token maximum executable position sizes for 1%, 2%, 5%, 10% price impact
        by solving the exact venue-specific trade equation.
        """
        adapter = self.get_adapter(venue)
        return MaxPositionSizeLimits(
            max_position_1pct_usd=adapter.calculate_max_position(liquidity_usd, 0.01),
            max_position_2pct_usd=adapter.calculate_max_position(liquidity_usd, 0.02),
            max_position_5pct_usd=adapter.calculate_max_position(liquidity_usd, 0.05),
            max_position_10pct_usd=adapter.calculate_max_position(liquidity_usd, 0.10),
        )

    def simulate_trade(
        self,
        position_size_usd: float,
        entry_mc: float,
        exit_mc: float,
        entry_liquidity: float,
        exit_liquidity: float,
        chain: str = "solana",
        venue: str = "raydium",
        trough_mc: Optional[float] = None,
    ) -> TradeExecutionResult:
        """
        Simulate trade execution using venue-specific adapter and actual position size.
        """
        adapter = self.get_adapter(venue)
        ch_lower = chain.lower()
        if ch_lower == "solana":
            priority_fee = self.solana_priority_fee_usd
        elif ch_lower in ("bsc", "bnb"):
            priority_fee = self.bsc_priority_fee_usd
        elif ch_lower == "robinhood":
            priority_fee = self.robinhood_priority_fee_usd
        else:
            priority_fee = self.base_priority_fee_usd
        return adapter.simulate(
            position_size_usd=position_size_usd,
            entry_mc=entry_mc,
            exit_mc=exit_mc,
            entry_liquidity=entry_liquidity,
            exit_liquidity=exit_liquidity,
            chain=chain,
            priority_fee_usd=priority_fee,
            trough_mc=trough_mc,
        )

    def evaluate_multi_tier_sizes(
        self,
        entry_mc: float,
        exit_mc: float,
        entry_liquidity: float,
        exit_liquidity: float,
        chain: str = "solana",
        venue: str = "raydium",
        trough_mc: Optional[float] = None,
        position_sizes: Tuple[float, ...] = (25.0, 50.0, 100.0, 250.0, 500.0, 1000.0),
    ) -> Dict[float, TradeExecutionResult]:
        """Simulate execution for $25, $50, $100, $250, $500, $1,000 position sizes."""
        results = {}
        for sz in position_sizes:
            results[sz] = self.simulate_trade(
                position_size_usd=sz,
                entry_mc=entry_mc,
                exit_mc=exit_mc,
                entry_liquidity=entry_liquidity,
                exit_liquidity=exit_liquidity,
                chain=chain,
                venue=venue,
                trough_mc=trough_mc,
            )
        return results
