"""
Peer-Cohort Normalized Trade-Size Entropy Engine
Calculates trade entropy relative to peer cohorts grouped by venue, age, market cap, and trade volume.
"""

from collections import defaultdict
from dataclasses import dataclass, field
import math
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class NormalizedEntropyResult:
    absolute_entropy: float = 1.0
    cohort_key: str = "default"
    cohort_mean_entropy: float = 1.0
    cohort_entropy_std: float = 0.3
    entropy_z_score: float = 0.0          # (H - mu) / sigma
    cohort_percentile: float = 50.0       # Percentile rank (0 to 100)
    cohort_sample_size: int = 1
    is_statistically_abnormal_bot: bool = False
    signals: List[str] = field(default_factory=list)


class CohortEntropyNormalizer:
    # Standard empirical distribution reference table per cohort
    # Format: (mean_entropy, std_entropy)
    DEFAULT_COHORT_BASELINES: Dict[str, Tuple[float, float]] = {
        ("pump_curve", "early", "micro", "low"): (0.75, 0.25),
        ("pump_curve", "early", "micro", "high"): (1.10, 0.28),
        ("pump_curve", "mature", "mid", "high"): (1.35, 0.30),
        ("raydium_amm", "early", "micro", "low"): (0.85, 0.26),
        ("raydium_amm", "mature", "mid", "high"): (1.40, 0.25),
        ("uniswap_amm", "mature", "mid", "high"): (1.30, 0.28),
    }

    @classmethod
    def get_cohort_key(
        cls,
        venue: str,
        age_minutes: float,
        market_cap_usd: float,
        trade_count: int,
    ) -> Tuple[str, str, str, str]:
        """Classify candidate into standard peer cohort."""
        v_class = "pump_curve" if "pump" in venue.lower() else ("raydium_amm" if "raydium" in venue.lower() else "uniswap_amm")
        age_class = "early" if age_minutes <= 20.0 else "mature"
        mc_class = "micro" if market_cap_usd <= 20000.0 else "mid"
        vol_class = "low" if trade_count <= 25 else "high"
        return (v_class, age_class, mc_class, vol_class)

    @classmethod
    def normalize_entropy(
        cls,
        absolute_entropy: float,
        venue: str,
        age_minutes: float,
        market_cap_usd: float,
        trade_count: int,
        custom_cohort_stats: Optional[Dict[Tuple[str, str, str, str], Tuple[float, float, int]]] = None,
    ) -> NormalizedEntropyResult:
        """
        Normalize absolute Shannon entropy against peer cohort baseline.
        """
        res = NormalizedEntropyResult(absolute_entropy=round(absolute_entropy, 3))
        key = cls.get_cohort_key(venue, age_minutes, market_cap_usd, trade_count)
        res.cohort_key = ":".join(key)

        mu = 1.05
        sigma = 0.28
        n_samples = 50

        if custom_cohort_stats and key in custom_cohort_stats:
            mu, sigma, n_samples = custom_cohort_stats[key]
        elif (key[0], key[1], key[2], key[3]) in cls.DEFAULT_COHORT_BASELINES:
            mu, sigma = cls.DEFAULT_COHORT_BASELINES[(key[0], key[1], key[2], key[3])]
        elif (key[0], key[1], key[2], "high") in cls.DEFAULT_COHORT_BASELINES:
            mu, sigma = cls.DEFAULT_COHORT_BASELINES[(key[0], key[1], key[2], "high")]

        res.cohort_mean_entropy = round(mu, 3)
        res.cohort_entropy_std = round(sigma, 3)
        res.cohort_sample_size = n_samples

        # Calculate Z-score
        z = (absolute_entropy - mu) / max(0.05, sigma)
        res.entropy_z_score = round(z, 2)

        # Approximate percentile from Gaussian CDF
        # Phi(z) = 0.5 * (1 + erf(z / sqrt(2)))
        phi = 0.5 * (1.0 + math.erf(z / math.sqrt(2)))
        res.cohort_percentile = round(phi * 100.0, 1)

        signals = []
        if z <= -2.0:
            res.is_statistically_abnormal_bot = True
            signals.append("ABNORMAL_LOW_ENTROPY_PEER_COHORT")
        elif z >= 1.2:
            signals.append("ORGANIC_ENTROPY_SIGNIFICANT_OUTPERFORMER")

        res.signals = signals
        return res
