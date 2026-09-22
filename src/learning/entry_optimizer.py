"""
Entry Policy Optimizer (Adaptive Learning Engine)
Evaluates 6 non-anticipative candidate entry policies per first-alert opportunity across
market regimes, token age buckets, and pool liquidity buckets.

The 6 Candidate Entry Policies:
1. IMMEDIATE: Enter at first alert price (price = alert_price, slippage = 1.5%, delay = 0 min)
2. CONFIRMATION: Wait for +5% price confirmation (price = alert_price * 1.05, slippage = 1.0%, delay = 2 min)
3. FIRST_PULLBACK: Wait for first -10% pullback (price = alert_price * 0.90, slippage = 0.8%, delay = 5 min)
4. HIGHER_LOW_CONFIRMATION: Wait for higher low after pullback (price = alert_price * 0.95, slippage = 1.0%, delay = 8 min)
5. LIQUIDITY_EXPANSION: Enter only when liquidity increases >20% (price = alert_price * 1.02, slippage = 0.5%, delay = 10 min)
6. MOMENTUM_REENTRY: Wait for volume acceleration after consolidation (price = alert_price * 1.08, slippage = 1.2%, delay = 15 min)
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import logging
import math
import statistics
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Canonical Policy Identifiers
POLICY_IMMEDIATE: str = "IMMEDIATE"
POLICY_CONFIRMATION: str = "CONFIRMATION"
POLICY_FIRST_PULLBACK: str = "FIRST_PULLBACK"
POLICY_HIGHER_LOW_CONFIRMATION: str = "HIGHER_LOW_CONFIRMATION"
POLICY_LIQUIDITY_EXPANSION: str = "LIQUIDITY_EXPANSION"
POLICY_MOMENTUM_REENTRY: str = "MOMENTUM_REENTRY"

ALL_ENTRY_POLICIES: List[str] = [
    POLICY_IMMEDIATE,
    POLICY_CONFIRMATION,
    POLICY_FIRST_PULLBACK,
    POLICY_HIGHER_LOW_CONFIRMATION,
    POLICY_LIQUIDITY_EXPANSION,
    POLICY_MOMENTUM_REENTRY,
]

# Canonical Age Buckets
AGE_BUCKET_UNDER_5M: str = "<5m"
AGE_BUCKET_5_TO_15M: str = "5-15m"
AGE_BUCKET_15_TO_30M: str = "15-30m"
AGE_BUCKET_30_TO_60M: str = "30-60m"
AGE_BUCKET_60M_PLUS: str = "60m+"

ALL_AGE_BUCKETS: List[str] = [
    AGE_BUCKET_UNDER_5M,
    AGE_BUCKET_5_TO_15M,
    AGE_BUCKET_15_TO_30M,
    AGE_BUCKET_30_TO_60M,
    AGE_BUCKET_60M_PLUS,
]

# Canonical Liquidity Buckets
LIQUIDITY_BUCKET_UNDER_2K: str = "<2K"
LIQUIDITY_BUCKET_2K_TO_5K: str = "2K-5K"
LIQUIDITY_BUCKET_5K_TO_15K: str = "5K-15K"
LIQUIDITY_BUCKET_15K_PLUS: str = "15K+"

ALL_LIQUIDITY_BUCKETS: List[str] = [
    LIQUIDITY_BUCKET_UNDER_2K,
    LIQUIDITY_BUCKET_2K_TO_5K,
    LIQUIDITY_BUCKET_5K_TO_15K,
    LIQUIDITY_BUCKET_15K_PLUS,
]

# Canonical Market Regimes
REGIME_NORMAL: str = "NORMAL"
REGIME_HOT: str = "HOT"
REGIME_COLD: str = "COLD"
REGIME_PANIC: str = "PANIC"

ALL_MARKET_REGIMES: List[str] = [
    REGIME_NORMAL,
    REGIME_HOT,
    REGIME_COLD,
    REGIME_PANIC,
]

# Entry Quality Classifications
QUALITY_GOOD_ENTRY: str = "GOOD_ENTRY"
QUALITY_EARLY_ENTRY: str = "EARLY_ENTRY"
QUALITY_LATE_ENTRY: str = "LATE_ENTRY"
QUALITY_FALSE_BREAKOUT_ENTRY: str = "FALSE_BREAKOUT_ENTRY"
QUALITY_HIGH_SLIPPAGE_ENTRY: str = "HIGH_SLIPPAGE_ENTRY"
QUALITY_MODERATE_ENTRY: str = "MODERATE_ENTRY"


@dataclass(frozen=True)
class PolicyConfig:
    """Configuration definition for an entry execution policy."""

    name: str
    price_multiplier: float
    base_slippage_pct: float
    delay_minutes: float
    description: str


DEFAULT_POLICY_CONFIGS: Dict[str, PolicyConfig] = {
    POLICY_IMMEDIATE: PolicyConfig(
        name=POLICY_IMMEDIATE,
        price_multiplier=1.00,
        base_slippage_pct=1.5,
        delay_minutes=0.0,
        description="Enter at first alert price (price = alert_price, slippage = 1.5%)",
    ),
    POLICY_CONFIRMATION: PolicyConfig(
        name=POLICY_CONFIRMATION,
        price_multiplier=1.05,
        base_slippage_pct=1.0,
        delay_minutes=2.0,
        description="Wait for +5% price confirmation (price = alert_price * 1.05, slippage = 1.0%, delay = 2 min)",
    ),
    POLICY_FIRST_PULLBACK: PolicyConfig(
        name=POLICY_FIRST_PULLBACK,
        price_multiplier=0.90,
        base_slippage_pct=0.8,
        delay_minutes=5.0,
        description="Wait for first -10% pullback (price = alert_price * 0.90, slippage = 0.8%, delay = 5 min)",
    ),
    POLICY_HIGHER_LOW_CONFIRMATION: PolicyConfig(
        name=POLICY_HIGHER_LOW_CONFIRMATION,
        price_multiplier=0.95,
        base_slippage_pct=1.0,
        delay_minutes=8.0,
        description="Wait for higher low after pullback (price = alert_price * 0.95, slippage = 1.0%, delay = 8 min)",
    ),
    POLICY_LIQUIDITY_EXPANSION: PolicyConfig(
        name=POLICY_LIQUIDITY_EXPANSION,
        price_multiplier=1.02,
        base_slippage_pct=0.5,
        delay_minutes=10.0,
        description="Enter only when liquidity increases >20% (price = alert_price * 1.02, slippage = 0.5%, delay = 10 min)",
    ),
    POLICY_MOMENTUM_REENTRY: PolicyConfig(
        name=POLICY_MOMENTUM_REENTRY,
        price_multiplier=1.08,
        base_slippage_pct=1.2,
        delay_minutes=15.0,
        description="Wait for volume acceleration after consolidation (price = alert_price * 1.08, slippage = 1.2%, delay = 15 min)",
    ),
}


@dataclass
class EntryPolicyEvaluation:
    """
    Evaluation metrics for a single simulated entry policy on a token opportunity.
    """

    policy: str
    entry_price_usd: float
    entry_market_cap_usd: float = 0.0
    entry_slippage_pct: float = 0.0
    entry_delay_minutes: float = 0.0
    mfe_pct: float = 0.0  # Max Favorable Excursion from entry
    mae_pct: float = 0.0  # Max Adverse Excursion from entry (negative or zero)
    time_to_target_min: float = 0.0
    max_drawdown_pct: float = 0.0  # min(mae_pct, 0.0)
    net_executable_return_pct: float = 0.0
    entry_quality_label: str = "UNKNOWN"

    def to_dict(self) -> Dict[str, Any]:
        """Convert entry policy evaluation to dictionary."""
        return asdict(self)


@dataclass
class ContextualEntryResult:
    """
    Aggregated entry policy performance across a specific context group.
    """

    context_type: str  # e.g. 'market_regime', 'age_bucket', 'liquidity_bucket'
    context_value: str  # e.g. 'HOT', '5-15m', '2K-5K'
    policy_performance: Dict[str, float]  # policy -> avg net executable return
    best_policy: str
    sample_size: int

    def to_dict(self) -> Dict[str, Any]:
        """Convert contextual entry result to dictionary."""
        return asdict(self)


@dataclass
class EntryOptimizationReport:
    """
    Comprehensive optimization report across candidate entry policies and context segments.
    """

    token_address: str
    best_policy_overall: str
    best_policy_by_regime: Dict[str, str]
    best_policy_by_age_bucket: Dict[str, str]
    best_policy_by_liquidity_bucket: Dict[str, str]
    evaluations: List[EntryPolicyEvaluation]
    total_tokens_evaluated: int
    conditional_policy_rankings: Dict[str, List[Tuple[str, float]]]  # context -> [(policy, avg_return)]

    def to_dict(self) -> Dict[str, Any]:
        """Convert report to dictionary."""
        return {
            "token_address": self.token_address,
            "best_policy_overall": self.best_policy_overall,
            "best_policy_by_regime": dict(self.best_policy_by_regime),
            "best_policy_by_age_bucket": dict(self.best_policy_by_age_bucket),
            "best_policy_by_liquidity_bucket": dict(self.best_policy_by_liquidity_bucket),
            "evaluations": [e.to_dict() for e in self.evaluations],
            "total_tokens_evaluated": self.total_tokens_evaluated,
            "conditional_policy_rankings": {
                k: [(p, round(r, 4)) for p, r in v]
                for k, v in self.conditional_policy_rankings.items()
            },
        }


class EntryPolicyOptimizer:
    """
    Optimizes and simulates non-anticipative entry policies for memecoin breakout opportunities.
    Evaluates 6 discrete candidate execution strategies under various market conditions,
    liquidity tiers, and token maturity stages.
    """

    def __init__(
        self,
        policy_configs: Optional[Dict[str, PolicyConfig]] = None,
        adjust_slippage_by_liquidity: bool = True,
    ) -> None:
        """
        Initialize the EntryPolicyOptimizer.

        Args:
            policy_configs: Optional custom dictionary of policy configurations. Defaults to DEFAULT_POLICY_CONFIGS.
            adjust_slippage_by_liquidity: If True, dynamically scales slippage for thin liquidity pools.
        """
        self.policy_configs = policy_configs or DEFAULT_POLICY_CONFIGS
        self.adjust_slippage_by_liquidity = adjust_slippage_by_liquidity

    @staticmethod
    def get_age_bucket(token_age_minutes: float) -> str:
        """
        Map token age in minutes to standard age cohort bucket.

        Buckets:
            '<5m': < 5 min
            '5-15m': 5 <= age < 15 min
            '15-30m': 15 <= age < 30 min
            '30-60m': 30 <= age < 60 min
            '60m+': >= 60 min
        """
        age = max(0.0, float(token_age_minutes))
        if age < 5.0:
            return AGE_BUCKET_UNDER_5M
        elif age < 15.0:
            return AGE_BUCKET_5_TO_15M
        elif age < 30.0:
            return AGE_BUCKET_15_TO_30M
        elif age < 60.0:
            return AGE_BUCKET_30_TO_60M
        else:
            return AGE_BUCKET_60M_PLUS

    @staticmethod
    def get_liquidity_bucket(liquidity_usd: float) -> str:
        """
        Map pool liquidity in USD to standard liquidity tier bucket.

        Buckets:
            '<2K': < $2,000
            '2K-5K': $2,000 <= liq < $5,000
            '5K-15K': $5,000 <= liq < $15,000
            '15K+': >= $15,000
        """
        liq = max(0.0, float(liquidity_usd))
        if liq < 2000.0:
            return LIQUIDITY_BUCKET_UNDER_2K
        elif liq < 5000.0:
            return LIQUIDITY_BUCKET_2K_TO_5K
        elif liq < 15000.0:
            return LIQUIDITY_BUCKET_5K_TO_15K
        else:
            return LIQUIDITY_BUCKET_15K_PLUS

    @staticmethod
    def normalize_regime(regime: Optional[str]) -> str:
        """
        Normalize arbitrary regime string into canonical regime enum.

        Regimes: 'NORMAL', 'HOT', 'COLD', 'PANIC'
        """
        if not regime:
            return REGIME_NORMAL
        r = str(regime).strip().upper()
        if r in (REGIME_NORMAL, REGIME_HOT, REGIME_COLD, REGIME_PANIC):
            return r
        if any(w in r for w in ("HOT", "BULL", "PUMP", "BREAKOUT", "EXPANSION", "MANIA")):
            return REGIME_HOT
        if any(w in r for w in ("PANIC", "RUG", "CRASH", "CAPITULATION", "DUMP")):
            return REGIME_PANIC
        if any(w in r for w in ("COLD", "BEAR", "DISTRIBUTION", "CHOP", "STAGNANT")):
            return REGIME_COLD
        return REGIME_NORMAL

    @staticmethod
    def classify_entry_quality(
        mfe_pct: float,
        mae_pct: float,
        slippage_pct: float,
    ) -> str:
        """
        Label entry quality using non-anticipative classification logic:
        - HIGH_SLIPPAGE_ENTRY: slippage > 5%
        - FALSE_BREAKOUT_ENTRY: mae < -40% AND mfe < 15%
        - GOOD_ENTRY: mfe > 50% AND mae > -20% AND slippage < 3%
        - EARLY_ENTRY: mae < -30% but mfe > 30%
        - LATE_ENTRY: mfe < 20%
        - MODERATE_ENTRY: standard baseline entry
        """
        if slippage_pct > 5.0:
            return QUALITY_HIGH_SLIPPAGE_ENTRY
        if mae_pct < -40.0 and mfe_pct < 15.0:
            return QUALITY_FALSE_BREAKOUT_ENTRY
        if mfe_pct > 50.0 and mae_pct > -20.0 and slippage_pct < 3.0:
            return QUALITY_GOOD_ENTRY
        if mae_pct < -30.0 and mfe_pct > 30.0:
            return QUALITY_EARLY_ENTRY
        if mfe_pct < 20.0:
            return QUALITY_LATE_ENTRY
        return QUALITY_MODERATE_ENTRY

    def compute_effective_slippage(
        self,
        base_slippage_pct: float,
        liquidity_usd: float,
        position_size_usd: float = 250.0,
    ) -> float:
        """
        Compute liquidity-adjusted execution slippage.

        Args:
            base_slippage_pct: Nominal policy slippage percentage.
            liquidity_usd: Pool liquidity in USD.
            position_size_usd: Intended position size in USD.

        Returns:
            Adjusted slippage percentage.
        """
        if not self.adjust_slippage_by_liquidity or liquidity_usd <= 0:
            return max(0.1, round(base_slippage_pct, 4))

        # Liquidity scaling factor: thinner pools suffer larger execution friction
        liq_scale = (5000.0 / max(100.0, liquidity_usd)) ** 0.5
        liq_scale = max(0.5, min(3.0, liq_scale))

        # Micro-impact from position size relative to available liquidity
        impact_pct = (position_size_usd / max(1000.0, liquidity_usd)) * 5.0
        impact_pct = max(0.0, min(5.0, impact_pct))

        effective_slippage = (base_slippage_pct * liq_scale) + impact_pct
        return max(0.1, round(effective_slippage, 4))

    def evaluate_entry_policies(
        self,
        alert_price: float,
        peak_price: float,
        trough_price: float,
        final_price: float,
        liquidity_usd: float,
        token_age_minutes: float,
        position_size_usd: float = 250.0,
        time_to_target_min: Optional[float] = None,
        alert_market_cap_usd: float = 0.0,
    ) -> List[EntryPolicyEvaluation]:
        """
        Evaluate all 6 candidate entry policies for an opportunity.

        For each policy:
        - Calculate entry price based on policy multiplier
        - MFE = (peak_price - entry_price) / entry_price * 100 (0 if peak <= entry)
        - MAE = (trough_price - entry_price) / entry_price * 100 (0 if trough >= entry)
        - net_executable_return = (final_price - entry_price) / entry_price * 100 - slippage
        - max_drawdown = min(MAE, 0)
        - Label entry quality

        Args:
            alert_price: Token price in USD at initial alert.
            peak_price: Highest price in USD achieved during observation window.
            trough_price: Lowest price in USD reached during observation window.
            final_price: Resolution or final price in USD.
            liquidity_usd: Pool liquidity at alert time in USD.
            token_age_minutes: Age of the token at alert time in minutes.
            position_size_usd: Position size in USD for slippage simulation.
            time_to_target_min: Optional base time to reach primary target in minutes.
            alert_market_cap_usd: Market capitalization at alert trigger.

        Returns:
            List of 6 EntryPolicyEvaluation records.
        """
        safe_alert_price = max(1e-9, float(alert_price)) if alert_price > 0 else 1e-9
        safe_liquidity = max(0.0, float(liquidity_usd))
        safe_age = max(0.0, float(token_age_minutes))
        safe_alert_mc = max(0.0, float(alert_market_cap_usd))

        evaluations: List[EntryPolicyEvaluation] = []

        for policy_name in ALL_ENTRY_POLICIES:
            cfg = self.policy_configs.get(policy_name, DEFAULT_POLICY_CONFIGS[policy_name])

            # 1. Entry price based on policy logic
            entry_price = safe_alert_price * cfg.price_multiplier
            entry_mc = safe_alert_mc * cfg.price_multiplier if safe_alert_mc > 0 else 0.0

            # 2. Slippage calculation
            slippage_pct = self.compute_effective_slippage(
                base_slippage_pct=cfg.base_slippage_pct,
                liquidity_usd=safe_liquidity,
                position_size_usd=position_size_usd,
            )

            # 3. Excursion metrics calculation with safe defaults
            if entry_price <= 0:
                mfe_pct = 0.0
                mae_pct = 0.0
                net_return_pct = 0.0
                max_dd_pct = 0.0
            else:
                # MFE: 0 if peak <= entry
                if peak_price <= entry_price:
                    mfe_pct = 0.0
                else:
                    mfe_pct = ((peak_price - entry_price) / entry_price) * 100.0

                # MAE: 0 if trough >= entry, otherwise negative percentage
                if trough_price >= entry_price:
                    mae_pct = 0.0
                else:
                    mae_pct = ((trough_price - entry_price) / entry_price) * 100.0

                # Net executable return factoring execution friction
                raw_return_pct = ((final_price - entry_price) / entry_price) * 100.0
                net_return_pct = raw_return_pct - slippage_pct

                # Max drawdown: min(MAE, 0)
                max_dd_pct = min(mae_pct, 0.0)

            # Time to target adjusted for entry delay
            if time_to_target_min is not None and time_to_target_min > 0:
                adjusted_time = max(0.0, float(time_to_target_min) - cfg.delay_minutes)
            else:
                adjusted_time = float(cfg.delay_minutes)

            # 4. Entry quality classification
            quality_label = self.classify_entry_quality(
                mfe_pct=mfe_pct,
                mae_pct=mae_pct,
                slippage_pct=slippage_pct,
            )

            eval_record = EntryPolicyEvaluation(
                policy=policy_name,
                entry_price_usd=round(entry_price, 8),
                entry_market_cap_usd=round(entry_mc, 2),
                entry_slippage_pct=round(slippage_pct, 4),
                entry_delay_minutes=round(cfg.delay_minutes, 2),
                mfe_pct=round(mfe_pct, 4),
                mae_pct=round(mae_pct, 4),
                time_to_target_min=round(adjusted_time, 2),
                max_drawdown_pct=round(max_dd_pct, 4),
                net_executable_return_pct=round(net_return_pct, 4),
                entry_quality_label=quality_label,
            )
            evaluations.append(eval_record)

        return evaluations

    @classmethod
    def _extract_token_features(cls, token: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract and sanitize token parameters from heterogeneous dictionary representations.

        Args:
            token: Token dictionary record.

        Returns:
            Normalized dictionary of feature parameters.
        """
        addr = str(
            token.get("token_address")
            or token.get("address")
            or token.get("mint")
            or "UNKNOWN"
        )

        alert_price = float(
            token.get("alert_price")
            or token.get("alert_price_usd")
            or token.get("price_usd")
            or token.get("price")
            or token.get("entry_price_usd")
            or 0.0001
        )
        alert_price = max(1e-9, alert_price)

        alert_mc = float(
            token.get("alert_market_cap_usd")
            or token.get("market_cap_usd")
            or 15000.0
        )
        alert_mc = max(1.0, alert_mc)

        liquidity_usd = float(
            token.get("alert_liquidity_usd")
            or token.get("liquidity_usd")
            or token.get("liquidity")
            or 5000.0
        )
        liquidity_usd = max(0.0, liquidity_usd)

        # Peak price extraction or estimation from peak market cap / MFE ratio
        peak_price = token.get("peak_price") or token.get("peak_price_usd")
        if peak_price is not None:
            peak_price = float(peak_price)
        else:
            peak_mc = token.get("peak_market_cap_usd") or token.get("peak_mc")
            if peak_mc is not None and alert_mc > 0:
                peak_price = alert_price * (float(peak_mc) / alert_mc)
            else:
                mfe_ratio = float(token.get("mfe_ratio", 1.0))
                peak_price = alert_price * max(1.0, mfe_ratio)

        # Trough price extraction or estimation from trough market cap / MAE ratio
        trough_price = token.get("trough_price") or token.get("trough_price_usd")
        if trough_price is not None:
            trough_price = float(trough_price)
        else:
            trough_mc = token.get("trough_market_cap_usd") or token.get("trough_mc")
            if trough_mc is not None and alert_mc > 0:
                trough_price = alert_price * (float(trough_mc) / alert_mc)
            else:
                mae_ratio = float(token.get("mae_ratio", 0.8))
                trough_price = alert_price * max(0.01, mae_ratio)

        # Final price extraction or estimation
        final_price = (
            token.get("final_price")
            or token.get("final_price_usd")
            or token.get("close_price")
            or token.get("current_price")
        )
        if final_price is not None:
            final_price = float(final_price)
        else:
            final_mc = token.get("final_market_cap_usd") or token.get("final_mc")
            if final_mc is not None and alert_mc > 0:
                final_price = alert_price * (float(final_mc) / alert_mc)
            else:
                # Default estimation based on outcome or fallback to alert price
                final_price = peak_price * 0.50 if peak_price > alert_price else alert_price

        token_age_minutes = float(
            token.get("token_age_minutes")
            or token.get("token_age")
            or token.get("age_minutes")
            or 10.0
        )
        token_age_minutes = max(0.0, token_age_minutes)

        market_regime = cls.normalize_regime(
            token.get("market_regime") or token.get("regime") or "NORMAL"
        )
        position_size_usd = float(
            token.get("position_size_usd") or token.get("position_size") or 250.0
        )
        time_to_target_min = (
            token.get("time_to_target_min")
            or token.get("time_to_target")
            or token.get("time_to_3m_min")
        )
        if time_to_target_min is not None:
            time_to_target_min = float(time_to_target_min)

        return {
            "token_address": addr,
            "alert_price": alert_price,
            "peak_price": peak_price,
            "trough_price": trough_price,
            "final_price": final_price,
            "liquidity_usd": liquidity_usd,
            "token_age_minutes": token_age_minutes,
            "market_regime": market_regime,
            "position_size_usd": position_size_usd,
            "time_to_target_min": time_to_target_min,
        }

    def evaluate_contextual_performance(
        self,
        tokens: List[Dict[str, Any]],
    ) -> List[ContextualEntryResult]:
        """
        Group tokens by market_regime, age_bucket, and liquidity_bucket.
        For each group, evaluate all 6 entry policies and determine the highest-performing policy.

        Args:
            tokens: List of token opportunity dictionaries.

        Returns:
            List of ContextualEntryResult records.
        """
        if not tokens:
            return []

        # Pre-evaluate all tokens to get entry policy returns
        parsed_evaluations: List[Tuple[Dict[str, Any], List[EntryPolicyEvaluation]]] = []
        for t in tokens:
            parsed = self._extract_token_features(t)
            evals = self.evaluate_entry_policies(
                alert_price=parsed["alert_price"],
                peak_price=parsed["peak_price"],
                trough_price=parsed["trough_price"],
                final_price=parsed["final_price"],
                liquidity_usd=parsed["liquidity_usd"],
                token_age_minutes=parsed["token_age_minutes"],
                position_size_usd=parsed["position_size_usd"],
                time_to_target_min=parsed["time_to_target_min"],
            )
            parsed_evaluations.append((parsed, evals))

        results: List[ContextualEntryResult] = []

        # 1. Market Regime Contexts
        regime_groups: Dict[str, List[List[EntryPolicyEvaluation]]] = {
            r: [] for r in ALL_MARKET_REGIMES
        }
        for parsed, evals in parsed_evaluations:
            regime = parsed["market_regime"]
            if regime not in regime_groups:
                regime_groups[regime] = []
            regime_groups[regime].append(evals)

        for regime, eval_lists in regime_groups.items():
            if not eval_lists:
                continue
            ctx_res = self._build_context_result(
                context_type="market_regime",
                context_value=regime,
                eval_lists=eval_lists,
            )
            results.append(ctx_res)

        # 2. Age Bucket Contexts
        age_groups: Dict[str, List[List[EntryPolicyEvaluation]]] = {
            b: [] for b in ALL_AGE_BUCKETS
        }
        for parsed, evals in parsed_evaluations:
            bucket = self.get_age_bucket(parsed["token_age_minutes"])
            if bucket not in age_groups:
                age_groups[bucket] = []
            age_groups[bucket].append(evals)

        for bucket, eval_lists in age_groups.items():
            if not eval_lists:
                continue
            ctx_res = self._build_context_result(
                context_type="age_bucket",
                context_value=bucket,
                eval_lists=eval_lists,
            )
            results.append(ctx_res)

        # 3. Liquidity Bucket Contexts
        liq_groups: Dict[str, List[List[EntryPolicyEvaluation]]] = {
            b: [] for b in ALL_LIQUIDITY_BUCKETS
        }
        for parsed, evals in parsed_evaluations:
            bucket = self.get_liquidity_bucket(parsed["liquidity_usd"])
            if bucket not in liq_groups:
                liq_groups[bucket] = []
            liq_groups[bucket].append(evals)

        for bucket, eval_lists in liq_groups.items():
            if not eval_lists:
                continue
            ctx_res = self._build_context_result(
                context_type="liquidity_bucket",
                context_value=bucket,
                eval_lists=eval_lists,
            )
            results.append(ctx_res)

        return results

    @classmethod
    def _build_context_result(
        cls,
        context_type: str,
        context_value: str,
        eval_lists: List[List[EntryPolicyEvaluation]],
    ) -> ContextualEntryResult:
        """
        Aggregate policy performance across evaluated observations in a context group.
        """
        sample_size = len(eval_lists)
        if sample_size == 0:
            return ContextualEntryResult(
                context_type=context_type,
                context_value=context_value,
                policy_performance={p: 0.0 for p in ALL_ENTRY_POLICIES},
                best_policy=POLICY_IMMEDIATE,
                sample_size=0,
            )

        policy_returns: Dict[str, List[float]] = {p: [] for p in ALL_ENTRY_POLICIES}
        for evals in eval_lists:
            for ev in evals:
                if ev.policy in policy_returns:
                    policy_returns[ev.policy].append(ev.net_executable_return_pct)

        policy_performance: Dict[str, float] = {}
        for policy, returns in policy_returns.items():
            if returns:
                avg_ret = float(statistics.mean(returns))
            else:
                avg_ret = 0.0
            policy_performance[policy] = round(avg_ret, 4)

        # Determine best policy by highest net executable return
        best_policy = max(
            policy_performance.keys(),
            key=lambda p: policy_performance.get(p, -float("inf")),
        )

        return ContextualEntryResult(
            context_type=context_type,
            context_value=context_value,
            policy_performance=policy_performance,
            best_policy=best_policy,
            sample_size=sample_size,
        )

    def generate_entry_optimization_report(
        self,
        tokens: List[Dict[str, Any]],
    ) -> EntryOptimizationReport:
        """
        Generate a comprehensive entry optimization report across single or multiple tokens.

        Args:
            tokens: List of token opportunity dictionaries.

        Returns:
            EntryOptimizationReport containing global rankings, regime policies,
            age/liquidity cohort policies, and granular evaluations.
        """
        if not tokens:
            return EntryOptimizationReport(
                token_address="UNKNOWN",
                best_policy_overall=POLICY_IMMEDIATE,
                best_policy_by_regime={},
                best_policy_by_age_bucket={},
                best_policy_by_liquidity_bucket={},
                evaluations=[],
                total_tokens_evaluated=0,
                conditional_policy_rankings={},
            )

        # 1. Evaluate individual token opportunities
        all_evaluations: List[EntryPolicyEvaluation] = []
        token_address = (
            str(tokens[0].get("token_address") or tokens[0].get("address") or "PORTFOLIO")
            if len(tokens) == 1
            else "AGGREGATE"
        )

        for t in tokens:
            parsed = self._extract_token_features(t)
            evals = self.evaluate_entry_policies(
                alert_price=parsed["alert_price"],
                peak_price=parsed["peak_price"],
                trough_price=parsed["trough_price"],
                final_price=parsed["final_price"],
                liquidity_usd=parsed["liquidity_usd"],
                token_age_minutes=parsed["token_age_minutes"],
                position_size_usd=parsed["position_size_usd"],
                time_to_target_min=parsed["time_to_target_min"],
            )
            all_evaluations.extend(evals)

        # 2. Contextual Evaluations
        contextual_results = self.evaluate_contextual_performance(tokens)

        best_policy_by_regime: Dict[str, str] = {}
        best_policy_by_age_bucket: Dict[str, str] = {}
        best_policy_by_liquidity_bucket: Dict[str, str] = {}
        conditional_policy_rankings: Dict[str, List[Tuple[str, float]]] = {}

        for cr in contextual_results:
            # Map best policies
            if cr.context_type == "market_regime":
                best_policy_by_regime[cr.context_value] = cr.best_policy
            elif cr.context_type == "age_bucket":
                best_policy_by_age_bucket[cr.context_value] = cr.best_policy
            elif cr.context_type == "liquidity_bucket":
                best_policy_by_liquidity_bucket[cr.context_value] = cr.best_policy

            # Map sorted rankings
            sorted_rankings = sorted(
                cr.policy_performance.items(),
                key=lambda item: item[1],
                reverse=True,
            )
            context_key = f"{cr.context_type}:{cr.context_value}"
            conditional_policy_rankings[context_key] = sorted_rankings

        # 3. Overall Performance Calculation
        overall_policy_returns: Dict[str, List[float]] = {p: [] for p in ALL_ENTRY_POLICIES}
        for ev in all_evaluations:
            if ev.policy in overall_policy_returns:
                overall_policy_returns[ev.policy].append(ev.net_executable_return_pct)

        overall_policy_avg: Dict[str, float] = {}
        for policy, rets in overall_policy_returns.items():
            if rets:
                overall_policy_avg[policy] = round(float(statistics.mean(rets)), 4)
            else:
                overall_policy_avg[policy] = 0.0

        overall_sorted = sorted(
            overall_policy_avg.items(),
            key=lambda item: item[1],
            reverse=True,
        )
        conditional_policy_rankings["overall"] = overall_sorted

        best_policy_overall = overall_sorted[0][0] if overall_sorted else POLICY_IMMEDIATE

        logger.info(
            f"Entry Optimization Report generated for {len(tokens)} token(s). "
            f"Best overall policy: {best_policy_overall}"
        )

        return EntryOptimizationReport(
            token_address=token_address,
            best_policy_overall=best_policy_overall,
            best_policy_by_regime=best_policy_by_regime,
            best_policy_by_age_bucket=best_policy_by_age_bucket,
            best_policy_by_liquidity_bucket=best_policy_by_liquidity_bucket,
            evaluations=all_evaluations,
            total_tokens_evaluated=len(tokens),
            conditional_policy_rankings=conditional_policy_rankings,
        )
