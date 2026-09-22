"""
Smart-Wallet Behavioral Intelligence & Bayesian Edge Engine (Trader Behavior v1.0.0)
Tracks reference and custom wallets, classifies on-chain roles (TRADER, DEPLOYER, SNIPER, etc.),
builds behavioral fingerprints, preference distributions, and computes WALLET_EDGE_SCORE via Bayesian shrinkage.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import math
from typing import Any, Dict, List, Optional, Set, Tuple


# Primary Reference Wallets identified for benchmarking
REFERENCE_WALLET_A = "GpwbW4ErcUyXFTZW4ozMCtMJSVaony9HFYNrxQjKhXj6"
REFERENCE_WALLET_B = "EBx24uAPtaS1SvHwRhKEktSgzaXdiVEyHuSVpAMVwrcD"


@dataclass
class WalletTradeRecord:
    token_address: str
    symbol: str
    entry_timestamp: str
    entry_market_cap_usd: float
    entry_liquidity_usd: float
    entry_token_age_minutes: float
    entry_curve_progress: Optional[float]
    entry_volume_mc_ratio: float
    entry_activity_density_score: float
    entry_buy_pressure: float
    entry_two_sided_ratio: float
    position_size_usd: float

    # Outcome Data (populated at exit/maturity)
    is_closed: bool = False
    exit_timestamp: Optional[str] = None
    exit_market_cap_usd: Optional[float] = None
    holding_time_minutes: float = 0.0
    realized_pnl_usd: float = 0.0
    realized_return_pct: float = 0.0
    max_favorable_excursion_pct: float = 0.0  # MFE
    max_adverse_excursion_pct: float = 0.0     # MAE

    # Multi-Target Touch Milestones
    reached_50k: bool = False
    reached_100k: bool = False
    reached_500k: bool = False
    reached_1m: bool = False
    reached_3m: bool = False


@dataclass
class WalletPreferenceDistributions:
    mc_buckets: Dict[str, float] = field(default_factory=lambda: {
        "<5K": 0.0, "5K-10K": 0.0, "10K-25K": 0.0, "25K-50K": 0.0, "50K-100K": 0.0, "100K+": 0.0
    })
    age_buckets: Dict[str, float] = field(default_factory=lambda: {
        "<1m": 0.0, "1-5m": 0.0, "5-15m": 0.0, "15-30m": 0.0, "30-60m": 0.0, "60m+": 0.0
    })
    curve_buckets: Dict[str, float] = field(default_factory=lambda: {
        "0-20%": 0.0, "20-40%": 0.0, "40-60%": 0.0, "60-80%": 0.0, "80-100%": 0.0
    })
    median_entry_mc: float = 0.0
    median_entry_progress: float = 0.0
    median_hold_time_min: float = 0.0


@dataclass
class WalletBehaviorProfile:
    wallet_address: str
    role: str = "UNKNOWN"  # TRADER, DEPLOYER, CREATOR, SNIPER, MARKET_MAKER, WHALE, RETAIL, UNKNOWN
    total_trades_observed: int = 0
    mature_trades_count: int = 0
    winning_trades_count: int = 0

    # Target Milestone Rates
    target_50k_rate: float = 0.0
    target_100k_rate: float = 0.0
    target_500k_rate: float = 0.0
    target_1m_rate: float = 0.0
    target_3m_rate: float = 0.0

    # Risk-Adjusted Edge Metrics
    raw_win_rate: float = 0.0
    bayesian_shrunk_win_rate: float = 0.0
    median_mfe: float = 0.0
    median_mae: float = 0.0
    profit_factor: float = 1.0
    sample_confidence: str = "INSUFFICIENT_WALLET_EVIDENCE"  # INSUFFICIENT_WALLET_EVIDENCE | LOW | MEDIUM | HIGH
    wallet_edge_score: float = 50.0

    # Preferences & Distribution
    preferences: WalletPreferenceDistributions = field(default_factory=WalletPreferenceDistributions)
    trades: List[WalletTradeRecord] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "wallet_address": self.wallet_address,
            "role": self.role,
            "total_trades_observed": self.total_trades_observed,
            "mature_trades_count": self.mature_trades_count,
            "winning_trades_count": self.winning_trades_count,
            "raw_win_rate": self.raw_win_rate,
            "bayesian_shrunk_win_rate": self.bayesian_shrunk_win_rate,
            "target_50k_rate": self.target_50k_rate,
            "target_100k_rate": self.target_100k_rate,
            "target_500k_rate": self.target_500k_rate,
            "target_1m_rate": self.target_1m_rate,
            "target_3m_rate": self.target_3m_rate,
            "median_mfe": self.median_mfe,
            "median_mae": self.median_mae,
            "profit_factor": self.profit_factor,
            "sample_confidence": self.sample_confidence,
            "wallet_edge_score": self.wallet_edge_score,
            "preferences": {
                "mc_buckets": self.preferences.mc_buckets,
                "age_buckets": self.preferences.age_buckets,
                "curve_buckets": self.preferences.curve_buckets,
                "median_entry_mc": self.preferences.median_entry_mc,
                "median_entry_progress": self.preferences.median_entry_progress,
                "median_hold_time_min": self.preferences.median_hold_time_min,
            },
        }


class SmartWalletEngine:
    """
    Tracks reference wallets, infers roles, aggregates behavioral distributions,
    and calculates statistically shrunk edge scores.
    """

    MIN_TRADES_FOR_CONFIDENCE = 5
    MIN_MATURE_OUTCOMES = 5
    POPULATION_PRIOR_WIN_RATE = 0.25  # Base rate prior for Bayesian shrinkage
    PRIOR_WEIGHT_K = 10.0             # Pseudo-count strength of the prior

    def __init__(self):
        self.wallets: Dict[str, WalletBehaviorProfile] = {}
        self._init_reference_wallets()

    def _init_reference_wallets(self):
        """Seed reference wallets A and B with structured profiles."""
        self.register_wallet(REFERENCE_WALLET_A, role_hint="TRADER")
        self.register_wallet(REFERENCE_WALLET_B, role_hint="TRADER")

    def register_wallet(self, wallet_address: str, role_hint: str = "UNKNOWN") -> WalletBehaviorProfile:
        addr = wallet_address.strip()
        if addr not in self.wallets:
            profile = WalletBehaviorProfile(wallet_address=addr, role=role_hint)
            self.wallets[addr] = profile
        return self.wallets[addr]

    def record_entry(
        self,
        wallet_address: str,
        token_address: str,
        symbol: str,
        market_cap_usd: float,
        liquidity_usd: float,
        token_age_minutes: float,
        curve_progress: Optional[float],
        volume_mc_ratio: float,
        activity_density_score: float,
        buy_pressure: float,
        two_sided_ratio: float,
        position_size_usd: float = 250.0,
        entry_timestamp: Optional[str] = None,
    ) -> None:
        profile = self.register_wallet(wallet_address)
        ts = entry_timestamp or datetime.now(timezone.utc).isoformat()

        record = WalletTradeRecord(
            token_address=token_address,
            symbol=symbol,
            entry_timestamp=ts,
            entry_market_cap_usd=market_cap_usd,
            entry_liquidity_usd=liquidity_usd,
            entry_token_age_minutes=token_age_minutes,
            entry_curve_progress=curve_progress,
            entry_volume_mc_ratio=volume_mc_ratio,
            entry_activity_density_score=activity_density_score,
            entry_buy_pressure=buy_pressure,
            entry_two_sided_ratio=two_sided_ratio,
            position_size_usd=position_size_usd,
        )
        profile.trades.append(record)
        profile.total_trades_observed = len(profile.trades)

        self._update_profile_statistics(profile)

    def record_exit(
        self,
        wallet_address: str,
        token_address: str,
        exit_market_cap_usd: float,
        realized_return_pct: float,
        mfe_pct: float,
        mae_pct: float,
        exit_timestamp: Optional[str] = None,
    ) -> None:
        profile = self.wallets.get(wallet_address)
        if not profile:
            return

        for t in reversed(profile.trades):
            if t.token_address == token_address and not t.is_closed:
                t.is_closed = True
                t.exit_timestamp = exit_timestamp or datetime.now(timezone.utc).isoformat()
                t.exit_market_cap_usd = exit_market_cap_usd
                t.realized_return_pct = realized_return_pct
                t.realized_pnl_usd = t.position_size_usd * (realized_return_pct / 100.0)
                t.max_favorable_excursion_pct = mfe_pct
                t.max_adverse_excursion_pct = mae_pct

                # Milestone flags
                if exit_market_cap_usd >= 50000.0 or mfe_pct >= 50.0:
                    t.reached_50k = True
                if exit_market_cap_usd >= 100000.0 or mfe_pct >= 200.0:
                    t.reached_100k = True
                if exit_market_cap_usd >= 500000.0 or mfe_pct >= 1000.0:
                    t.reached_500k = True
                if exit_market_cap_usd >= 1000000.0:
                    t.reached_1m = True
                if exit_market_cap_usd >= 3000000.0:
                    t.reached_3m = True
                break

        self._update_profile_statistics(profile)

    def classify_role(self, profile: WalletBehaviorProfile) -> str:
        """
        Infers wallet role:
        - DEPLOYER/CREATOR: creates token contracts or receives initial pool dev allocations
        - SNIPER: consistently enters < 0.5 minutes from launch
        - MARKET_MAKER: very high trade frequency (>50 trades) with tight PnL distribution
        - WHALE: average position size > $5,000
        - TRADER: standard directional momentum trading
        """
        if not profile.trades:
            return profile.role or "UNKNOWN"

        ages = [t.entry_token_age_minutes for t in profile.trades]
        sizes = [t.position_size_usd for t in profile.trades]
        med_age = sorted(ages)[len(ages) // 2] if ages else 10.0
        med_size = sorted(sizes)[len(sizes) // 2] if sizes else 250.0

        if med_age < 0.5:
            return "SNIPER"
        elif med_size >= 5000.0:
            return "WHALE"
        elif len(profile.trades) >= 30 and profile.profit_factor < 1.1:
            return "MARKET_MAKER"
        else:
            return "TRADER"

    def _update_profile_statistics(self, profile: WalletBehaviorProfile) -> None:
        """Recompute distributions, Bayesian shrinkage, and wallet edge score."""
        closed = [t for t in profile.trades if t.is_closed]
        profile.mature_trades_count = len(closed)

        # 1. Update Role
        profile.role = self.classify_role(profile)

        # 2. Preference Distributions
        if profile.trades:
            mc_b = {"<5K": 0, "5K-10K": 0, "10K-25K": 0, "25K-50K": 0, "50K-100K": 0, "100K+": 0}
            age_b = {"<1m": 0, "1-5m": 0, "5-15m": 0, "15-30m": 0, "30-60m": 0, "60m+": 0}
            crv_b = {"0-20%": 0, "20-40%": 0, "40-60%": 0, "60-80%": 0, "80-100%": 0}
            entry_mcs = []
            entry_progs = []

            for t in profile.trades:
                mc = t.entry_market_cap_usd
                entry_mcs.append(mc)
                if mc < 5000.0:
                    mc_b["<5K"] += 1
                elif mc < 10000.0:
                    mc_b["5K-10K"] += 1
                elif mc < 25000.0:
                    mc_b["10K-25K"] += 1
                elif mc < 50000.0:
                    mc_b["25K-50K"] += 1
                elif mc < 100000.0:
                    mc_b["50K-100K"] += 1
                else:
                    mc_b["100K+"] += 1

                age = t.entry_token_age_minutes
                if age < 1.0:
                    age_b["<1m"] += 1
                elif age < 5.0:
                    age_b["1-5m"] += 1
                elif age < 15.0:
                    age_b["5-15m"] += 1
                elif age < 30.0:
                    age_b["15-30m"] += 1
                elif age < 60.0:
                    age_b["30-60m"] += 1
                else:
                    age_b["60m+"] += 1

                if t.entry_curve_progress is not None:
                    p = t.entry_curve_progress
                    entry_progs.append(p)
                    if p < 0.20:
                        crv_b["0-20%"] += 1
                    elif p < 0.40:
                        crv_b["20-40%"] += 1
                    elif p < 0.60:
                        crv_b["40-60%"] += 1
                    elif p < 0.80:
                        crv_b["60-80%"] += 1
                    else:
                        crv_b["80-100%"] += 1

            n = float(len(profile.trades))
            profile.preferences.mc_buckets = {k: v / n for k, v in mc_b.items()}
            profile.preferences.age_buckets = {k: v / n for k, v in age_b.items()}
            profile.preferences.curve_buckets = {k: v / n for k, v in crv_b.items()}
            profile.preferences.median_entry_mc = sorted(entry_mcs)[len(entry_mcs) // 2] if entry_mcs else 0.0
            profile.preferences.median_entry_progress = sorted(entry_progs)[len(entry_progs) // 2] if entry_progs else 0.0

        # 3. Outcomes & Bayesian Shrinkage
        if len(closed) >= 1:
            wins = sum(1 for t in closed if t.realized_return_pct > 0.0)
            profile.winning_trades_count = wins
            profile.raw_win_rate = float(wins) / float(len(closed))

            # Milestone rates
            profile.target_50k_rate = sum(1 for t in closed if t.reached_50k) / float(len(closed))
            profile.target_100k_rate = sum(1 for t in closed if t.reached_100k) / float(len(closed))
            profile.target_500k_rate = sum(1 for t in closed if t.reached_500k) / float(len(closed))
            profile.target_1m_rate = sum(1 for t in closed if t.reached_1m) / float(len(closed))
            profile.target_3m_rate = sum(1 for t in closed if t.reached_3m) / float(len(closed))

            # Median MFE / MAE
            mfes = [t.max_favorable_excursion_pct for t in closed]
            maes = [t.max_adverse_excursion_pct for t in closed]
            profile.median_mfe = sorted(mfes)[len(mfes) // 2]
            profile.median_mae = sorted(maes)[len(maes) // 2]

            # Profit Factor
            gross_win = sum(t.realized_pnl_usd for t in closed if t.realized_pnl_usd > 0.0)
            gross_loss = abs(sum(t.realized_pnl_usd for t in closed if t.realized_pnl_usd < 0.0))
            profile.profit_factor = (gross_win / gross_loss) if gross_loss > 0 else (2.0 if gross_win > 0 else 1.0)

            # Empirical Bayesian Shrinkage Formula:
            # \hat{p}_{shrunk} = \frac{wins + k \cdot prior}{N + k}
            k = self.PRIOR_WEIGHT_K
            prior = self.POPULATION_PRIOR_WIN_RATE
            n_obs = float(len(closed))
            shrunk_p = (float(wins) + k * prior) / (n_obs + k)
            profile.bayesian_shrunk_win_rate = shrunk_p

            # Confidence determination
            if n_obs < self.MIN_MATURE_OUTCOMES:
                profile.sample_confidence = "INSUFFICIENT_WALLET_EVIDENCE"
                profile.wallet_edge_score = 50.0
            elif n_obs < 15:
                profile.sample_confidence = "LOW"
                profile.wallet_edge_score = max(0.0, min(100.0, shrunk_p * 100.0))
            elif n_obs < 40:
                profile.sample_confidence = "MEDIUM"
                profile.wallet_edge_score = max(0.0, min(100.0, shrunk_p * 100.0 + (profile.target_100k_rate * 20.0)))
            else:
                profile.sample_confidence = "HIGH"
                profile.wallet_edge_score = max(0.0, min(100.0, shrunk_p * 100.0 + (profile.target_500k_rate * 30.0)))
        else:
            profile.sample_confidence = "INSUFFICIENT_WALLET_EVIDENCE"
            profile.wallet_edge_score = 50.0

    def evaluate_token_consensus(
        self,
        token_address: str,
        candidate_buyers: List[str],
    ) -> Tuple[str, float, List[Dict[str, Any]]]:
        """
        Evaluates tracked reference wallet participation on a specific token.
        Returns:
        - consensus_state: NONE | OBSERVED | MULTIPLE_TRACKED_WALLETS | STRONG_CONSENSUS
        - composite_wallet_boost: score multiplier/boost (0.0 to 20.0 pts)
        - tracked_hits: list of detected wallet profiles
        """
        tracked_hits = []
        buyer_set = set(str(b).strip() for b in candidate_buyers)

        for addr, profile in self.wallets.items():
            if addr in buyer_set:
                # Do not treat DEPLOYER / CREATOR as smart money
                if profile.role not in ("DEPLOYER", "CREATOR"):
                    tracked_hits.append(profile.to_dict())

        hit_count = len(tracked_hits)
        if hit_count == 0:
            return "NONE", 0.0, []
        elif hit_count == 1:
            state = "OBSERVED"
            boost = 5.0 if tracked_hits[0]["sample_confidence"] != "INSUFFICIENT_WALLET_EVIDENCE" else 0.0
            return state, boost, tracked_hits
        elif hit_count == 2:
            state = "MULTIPLE_TRACKED_WALLETS"
            return state, 10.0, tracked_hits
        else:
            state = "STRONG_CONSENSUS"
            return state, 15.0, tracked_hits
