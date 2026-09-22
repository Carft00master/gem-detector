"""
Macro Market-Regime Engine
Tracks broad market dynamics (SOL/ETH/BTC returns, volatility, memecoin launch velocity,
aggregate liquidity) and classifies regime into HOT | NORMAL | COLD | PANIC.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass
class MarketRegimeState:
    regime: str = "NORMAL"               # "HOT" | "NORMAL" | "COLD" | "PANIC"
    regime_multiplier: float = 1.0       # Scaler for opportunity scores (0.6x to 1.3x)
    sol_return_24h_pct: float = 0.0
    eth_return_24h_pct: float = 0.0
    btc_return_24h_pct: float = 0.0
    sol_volatility_sigma: float = 0.02
    token_launches_per_hour: int = 150
    median_token_1h_return_pct: float = 0.0
    aggregate_liquidity_depth_usd: float = 5000000.0
    signals: List[str] = field(default_factory=list)


class MarketRegimeEngine:
    @classmethod
    def evaluate_regime(
        cls,
        sol_return_24h_pct: float = 0.0,
        sol_return_1h_pct: float = 0.0,
        sol_volatility_sigma: float = 0.02,
        token_launches_per_hour: int = 150,
        median_token_1h_return_pct: float = 0.0,
    ) -> MarketRegimeState:
        """
        Classify macroeconomic and on-chain environment into operational regimes.
        """
        state = MarketRegimeState(
            sol_return_24h_pct=sol_return_24h_pct,
            sol_volatility_sigma=sol_volatility_sigma,
            token_launches_per_hour=token_launches_per_hour,
            median_token_1h_return_pct=median_token_1h_return_pct,
        )

        signals = []

        # 1. PANIC Regime (Severe macro drawdown or volatility spike)
        if sol_return_1h_pct <= -5.0 or sol_return_24h_pct <= -12.0 or sol_volatility_sigma >= 0.08:
            state.regime = "PANIC"
            state.regime_multiplier = 0.50
            signals.append("MACRO_PANIC_SELLOFF")

        # 2. HOT Regime (Strong bull momentum & broad retail participation)
        elif (
            sol_return_24h_pct >= 4.0
            and sol_return_1h_pct >= 0.5
            and token_launches_per_hour >= 120
            and median_token_1h_return_pct >= 0.0
        ):
            state.regime = "HOT"
            state.regime_multiplier = 1.25
            signals.append("BULLISH_MOMENTUM_EXPANSION")

        # 3. COLD Regime (Stagnant volume, negative drift, poor breakout follow-through)
        elif sol_return_24h_pct <= -3.0 or token_launches_per_hour < 40 or median_token_1h_return_pct < -5.0:
            state.regime = "COLD"
            state.regime_multiplier = 0.75
            signals.append("LOW_LIQUIDITY_COLD_REGIME")

        # 4. NORMAL Regime (Equilibrium)
        else:
            state.regime = "NORMAL"
            state.regime_multiplier = 1.00
            signals.append("BALANCED_MARKET_CONDITIONS")

        state.signals = signals
        return state
