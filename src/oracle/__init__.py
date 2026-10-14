"""
Oracle package for timestamped price feeds.
"""
from src.oracle.sol_usd import (
    PythSolUsdOracle,
    OraclePriceRecord,
    StaleOraclePriceError,
    OracleDivergenceAlert,
    PYTH_SOL_USD_ACCOUNT,
    PYTH_FEED_ID,
)

__all__ = [
    "PythSolUsdOracle",
    "OraclePriceRecord",
    "StaleOraclePriceError",
    "OracleDivergenceAlert",
    "PYTH_SOL_USD_ACCOUNT",
    "PYTH_FEED_ID",
]
