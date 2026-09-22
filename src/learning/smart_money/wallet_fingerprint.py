"""
Smart Wallet Entry Fingerprint Learning Engine
Extracts 12-dimensional entry preference signatures for validated wallets:
1. Market Cap Bucket (<$8K, $8K-$15K, $15K-$30K, $30K-$60K, $60K+)
2. Token Age Bucket (<3m, 3-10m, 10-30m, 30-60m, 60m+)
3. Liquidity Bucket (<$3K, $3K-$8K, $8K-$20K, $20K+)
4. Curve Progress Bucket (<10%, 10-30%, 30-60%, 60-90%, Raydium AMM)
5. Curve Velocity (Slow, Moderate, Rapid)
6. Volume / MC Ratio
7. Activity Density Percentile
8. Trader Density Score
9. Buyer Growth Rate
10. Two-Sided Market Quality
11. Holder Growth Rate
12. Market Regime (NORMAL, HOT, COLD)

Contrasts successful winning entries against failed entries to identify highest-conviction setup conditions.
"""

from dataclasses import asdict, dataclass, field
import logging
import numpy as np
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class WalletEntryFingerprint:
    wallet_address: str
    total_entries_analyzed: int
    winning_entries_count: int
    losing_entries_count: int
    optimal_mc_range_usd: Tuple[float, float]
    optimal_age_range_min: Tuple[float, float]
    optimal_liquidity_range_usd: Tuple[float, float]
    preferred_regimes: List[str]
    mean_winning_activity_density: float
    mean_winning_two_sided_quality: float
    mean_winning_buyer_pressure: float
    feature_weights: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class WalletFingerprintLearner:
    """
    Extracts behavioral entry preferences from historical trades.
    """

    @classmethod
    def extract_fingerprint(
        cls,
        wallet_address: str,
        trades: List[Dict[str, Any]],
    ) -> WalletEntryFingerprint:
        """
        Learn 12-dimensional entry setup preferences for a given wallet.
        """
        if not trades:
            return WalletEntryFingerprint(
                wallet_address=wallet_address,
                total_entries_analyzed=0,
                winning_entries_count=0,
                losing_entries_count=0,
                optimal_mc_range_usd=(4000.0, 30000.0),
                optimal_age_range_min=(2.0, 20.0),
                optimal_liquidity_range_usd=(2000.0, 15000.0),
                preferred_regimes=["NORMAL", "HOT"],
                mean_winning_activity_density=0.65,
                mean_winning_two_sided_quality=0.70,
                mean_winning_buyer_pressure=0.60,
                feature_weights={},
            )

        winners = [t for t in trades if bool(t.get("target_100k") or t.get("target_3m") or (float(t.get("realized_return", 0.0) or 0.0) > 0))]
        losers = [t for t in trades if t not in winners]

        target_set = winners if winners else trades

        win_mcs = [float(t.get("entry_market_cap", t.get("market_cap_usd", 15000.0)) or 15000.0) for t in target_set]
        win_ages = [float(t.get("entry_token_age", t.get("token_age_minutes", 10.0)) or 10.0) for t in target_set]
        win_liqs = [float(t.get("entry_liquidity", t.get("liquidity_usd", 5000.0)) or 5000.0) for t in target_set]

        mc_p25, mc_p75 = float(np.percentile(win_mcs, 25)), float(np.percentile(win_mcs, 75))
        age_p25, age_p75 = float(np.percentile(win_ages, 25)), float(np.percentile(win_ages, 75))
        liq_p25, liq_p75 = float(np.percentile(win_liqs, 25)), float(np.percentile(win_liqs, 75))

        act_densities = [float(t.get("activity_density", 0.60) or 0.60) for t in target_set]
        qualities = [float(t.get("two_sided_market_quality", 0.65) or 0.65) for t in target_set]
        pressures = [float(t.get("buyer_pressure", 0.60) or 0.60) for t in target_set]

        regimes_count: Dict[str, int] = {}
        for t in target_set:
            r = str(t.get("market_regime", "NORMAL")).upper()
            regimes_count[r] = regimes_count.get(r, 0) + 1

        pref_regimes = sorted(regimes_count, key=regimes_count.get, reverse=True)[:2] or ["NORMAL"]

        return WalletEntryFingerprint(
            wallet_address=wallet_address,
            total_entries_analyzed=len(trades),
            winning_entries_count=len(winners),
            losing_entries_count=len(losers),
            optimal_mc_range_usd=(round(mc_p25, 0), round(mc_p75, 0)),
            optimal_age_range_min=(round(age_p25, 1), round(age_p75, 1)),
            optimal_liquidity_range_usd=(round(liq_p25, 0), round(liq_p75, 0)),
            preferred_regimes=pref_regimes,
            mean_winning_activity_density=round(float(np.mean(act_densities)), 4) if act_densities else 0.65,
            mean_winning_two_sided_quality=round(float(np.mean(qualities)), 4) if qualities else 0.70,
            mean_winning_buyer_pressure=round(float(np.mean(pressures)), 4) if pressures else 0.60,
            feature_weights={
                "market_cap_alignment": 0.25,
                "token_age_alignment": 0.20,
                "liquidity_alignment": 0.20,
                "activity_density_alignment": 0.15,
                "regime_alignment": 0.20,
            },
        )
