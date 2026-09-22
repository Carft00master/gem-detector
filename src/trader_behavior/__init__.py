"""
Trader Behavior Intelligence Layer v1.0.0 (Research-Only Engine)
Exports the complete suite of activity density, participation breadth, two-sided market quality,
Pump.fun bonding curve traction, smart-wallet intelligence, and A/B validation harnesses.
"""

from src.trader_behavior.activity_density import (
    ActivityDensityEngine,
    ActivityDensityMetrics,
    get_age_bucket,
    get_liquidity_bucket,
    get_mc_bucket,
)
from src.trader_behavior.participation import (
    ParticipationBreadthEngine,
    ParticipationBreadthMetrics,
)
from src.trader_behavior.two_sided import (
    TwoSidedMarketQualityEngine,
    TwoSidedMarketQualityMetrics,
)
from src.trader_behavior.curve_traction import (
    CurveTractionEngine,
    CurveTractionMetrics,
)
from src.trader_behavior.composite import (
    EarlyTractionBundle,
    TraderStyleEarlyTractionEngine,
)
from src.trader_behavior.wallet_intelligence import (
    REFERENCE_WALLET_A,
    REFERENCE_WALLET_B,
    SmartWalletEngine,
    WalletBehaviorProfile,
    WalletTradeRecord,
)
from src.trader_behavior.ab_validation import (
    ABValidationHarness,
    ABValidationReport,
    ModelComparisonMetrics,
)
from src.trader_behavior.report import TraderBehaviorReportGenerator

__all__ = [
    "ActivityDensityEngine",
    "ActivityDensityMetrics",
    "get_age_bucket",
    "get_liquidity_bucket",
    "get_mc_bucket",
    "ParticipationBreadthEngine",
    "ParticipationBreadthMetrics",
    "TwoSidedMarketQualityEngine",
    "TwoSidedMarketQualityMetrics",
    "CurveTractionEngine",
    "CurveTractionMetrics",
    "EarlyTractionBundle",
    "TraderStyleEarlyTractionEngine",
    "REFERENCE_WALLET_A",
    "REFERENCE_WALLET_B",
    "SmartWalletEngine",
    "WalletBehaviorProfile",
    "WalletTradeRecord",
    "ABValidationHarness",
    "ABValidationReport",
    "ModelComparisonMetrics",
    "TraderBehaviorReportGenerator",
]
