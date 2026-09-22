"""
Contextual Smart Wallet Performance Engine
Evaluates wallet-specific trading performance partitioned across 5 operational dimensions:
1. Market Regime: HOT, NORMAL, COLD, PANIC
2. Market Cap: <5K, 5–10K, 10–25K, 25–50K, 50–100K
3. Token Age: <1m, 1–5m, 5–15m, 15–30m, 30–60m, 60m+
4. Curve Progress: 0–20%, 20–40%, 40–60%, 60–80%, 80–100%
5. Activity Density: 0–25th, 25–50th, 50–75th, 75–100th percentile
"""

from dataclasses import asdict, dataclass, field
import math
from typing import Any, Dict, List, Optional
import numpy as np


@dataclass
class ContextualCellMetrics:
    context_dimension: str               # REGIME, MARKET_CAP, TOKEN_AGE, CURVE_PROGRESS, ACTIVITY_DENSITY
    context_bucket: str                  # e.g., HOT, 5-10K, 1-5m, etc.
    sample_size: int
    win_rate_pct: float
    target_100k_rate_pct: float
    target_3m_rate_pct: float
    median_return_pct: float
    median_mfe_ratio: float
    median_mae_ratio: float
    matched_lift_pct: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class WalletContextualReport:
    wallet_address: str
    total_trades_evaluated: int
    by_regime: Dict[str, ContextualCellMetrics]
    by_market_cap: Dict[str, ContextualCellMetrics]
    by_token_age: Dict[str, ContextualCellMetrics]
    by_curve_progress: Dict[str, ContextualCellMetrics]
    by_activity_density: Dict[str, ContextualCellMetrics]
    best_regime: str
    best_mc_range: str
    best_age_range: str
    best_curve_range: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "wallet_address": self.wallet_address,
            "total_trades_evaluated": self.total_trades_evaluated,
            "by_regime": {k: v.to_dict() for k, v in self.by_regime.items()},
            "by_market_cap": {k: v.to_dict() for k, v in self.by_market_cap.items()},
            "by_token_age": {k: v.to_dict() for k, v in self.by_token_age.items()},
            "by_curve_progress": {k: v.to_dict() for k, v in self.by_curve_progress.items()},
            "by_activity_density": {k: v.to_dict() for k, v in self.by_activity_density.items()},
            "best_regime": self.best_regime,
            "best_mc_range": self.best_mc_range,
            "best_age_range": self.best_age_range,
            "best_curve_range": self.best_curve_range,
        }


class WalletContextualPerformanceEngine:
    """Computes multidimensional contextual breakdown for individual smart wallets."""

    @classmethod
    def _compute_cell_metrics(
        cls,
        dimension: str,
        bucket: str,
        trades: List[Dict[str, Any]],
        control_win_rate: float = 12.0,
    ) -> ContextualCellMetrics:
        n = len(trades)
        if n == 0:
            return ContextualCellMetrics(
                context_dimension=dimension,
                context_bucket=bucket,
                sample_size=0,
                win_rate_pct=0.0,
                target_100k_rate_pct=0.0,
                target_3m_rate_pct=0.0,
                median_return_pct=0.0,
                median_mfe_ratio=1.0,
                median_mae_ratio=1.0,
                matched_lift_pct=0.0,
            )

        wins = sum(1 for t in trades if float(t.get("realized_pnl_usd", t.get("net_realized_pnl_usd", 0.0)) or 0.0) > 0)
        t100 = sum(1 for t in trades if int(t.get("target_100k", 0) or 0) == 1)
        t3m = sum(1 for t in trades if int(t.get("target_3m", 0) or 0) == 1)
        rets = [float(t.get("realized_return_pct", t.get("net_realized_return_pct", 0.0)) or 0.0) for t in trades]
        mfes = [float(t.get("mfe_ratio", 1.0) or 1.0) for t in trades]
        maes = [float(t.get("mae_ratio", 1.0) or 1.0) for t in trades]

        wr = (wins / n) * 100.0
        lift = wr - control_win_rate

        return ContextualCellMetrics(
            context_dimension=dimension,
            context_bucket=bucket,
            sample_size=n,
            win_rate_pct=round(wr, 2),
            target_100k_rate_pct=round((t100 / n) * 100.0, 2),
            target_3m_rate_pct=round((t3m / n) * 100.0, 2),
            median_return_pct=round(float(np.median(rets)), 2) if rets else 0.0,
            median_mfe_ratio=round(float(np.median(mfes)), 2) if mfes else 1.0,
            median_mae_ratio=round(float(np.median(maes)), 2) if maes else 1.0,
            matched_lift_pct=round(lift, 2),
        )

    @classmethod
    def evaluate_wallet_context(
        cls,
        wallet_address: str,
        interactions: List[Dict[str, Any]],
    ) -> WalletContextualReport:
        # 1. Dimension Buckets
        regimes_map: Dict[str, List[Dict[str, Any]]] = {"HOT": [], "NORMAL": [], "COLD": [], "PANIC": []}
        mc_map: Dict[str, List[Dict[str, Any]]] = {"<5K": [], "5–10K": [], "10–25K": [], "25–50K": [], "50–100K": []}
        age_map: Dict[str, List[Dict[str, Any]]] = {"<1m": [], "1–5m": [], "5–15m": [], "15–30m": [], "30–60m": [], "60m+": []}
        curve_map: Dict[str, List[Dict[str, Any]]] = {"0–20%": [], "20–40%": [], "40–60%": [], "60–80%": [], "80–100%": []}
        density_map: Dict[str, List[Dict[str, Any]]] = {"0–25th": [], "25–50th": [], "50–75th": [], "75–100th": []}

        for inter in interactions:
            reg = str(inter.get("market_regime", "NORMAL")).upper()
            if reg in regimes_map:
                regimes_map[reg].append(inter)
            else:
                regimes_map["NORMAL"].append(inter)

            # MC
            mc = float(inter.get("entry_market_cap_usd", 12000.0) or 12000.0)
            if mc < 5000.0:
                mc_map["<5K"].append(inter)
            elif mc < 10000.0:
                mc_map["5–10K"].append(inter)
            elif mc < 25000.0:
                mc_map["10–25K"].append(inter)
            elif mc < 50000.0:
                mc_map["25–50K"].append(inter)
            else:
                mc_map["50–100K"].append(inter)

            # Age
            age_min = float(inter.get("token_age_minutes", inter.get("token_age_at_entry_sec", 300.0) / 60.0) or 5.0)
            if age_min < 1.0:
                age_map["<1m"].append(inter)
            elif age_min < 5.0:
                age_map["1–5m"].append(inter)
            elif age_min < 15.0:
                age_map["5–15m"].append(inter)
            elif age_min < 30.0:
                age_map["15–30m"].append(inter)
            elif age_min < 60.0:
                age_map["30–60m"].append(inter)
            else:
                age_map["60m+"].append(inter)

            # Curve
            curve = float(inter.get("curve_progress_pct", 25.0) or 25.0)
            if curve < 20.0:
                curve_map["0–20%"].append(inter)
            elif curve < 40.0:
                curve_map["20–40%"].append(inter)
            elif curve < 60.0:
                curve_map["40–60%"].append(inter)
            elif curve < 80.0:
                curve_map["60–80%"].append(inter)
            else:
                curve_map["80–100%"].append(inter)

            # Density
            density = float(inter.get("activity_density_percentile", 50.0) or 50.0)
            if density < 25.0:
                density_map["0–25th"].append(inter)
            elif density < 50.0:
                density_map["25–50th"].append(inter)
            elif density < 75.0:
                density_map["50–75th"].append(inter)
            else:
                density_map["75–100th"].append(inter)

        by_reg = {k: cls._compute_cell_metrics("REGIME", k, v) for k, v in regimes_map.items()}
        by_mc = {k: cls._compute_cell_metrics("MARKET_CAP", k, v) for k, v in mc_map.items()}
        by_age = {k: cls._compute_cell_metrics("TOKEN_AGE", k, v) for k, v in age_map.items()}
        by_curve = {k: cls._compute_cell_metrics("CURVE_PROGRESS", k, v) for k, v in curve_map.items()}
        by_dense = {k: cls._compute_cell_metrics("ACTIVITY_DENSITY", k, v) for k, v in density_map.items()}

        # Identify sweet spots (highest win rate with n >= 2, or highest sample)
        def _get_best(m: Dict[str, ContextualCellMetrics]) -> str:
            candidates = [c for c in m.values() if c.sample_size > 0]
            if not candidates:
                return "NORMAL" if "NORMAL" in m else list(m.keys())[0]
            sorted_c = sorted(candidates, key=lambda c: (c.win_rate_pct, c.sample_size), reverse=True)
            return sorted_c[0].context_bucket

        return WalletContextualReport(
            wallet_address=wallet_address,
            total_trades_evaluated=len(interactions),
            by_regime=by_reg,
            by_market_cap=by_mc,
            by_token_age=by_age,
            by_curve_progress=by_curve,
            by_activity_density=by_dense,
            best_regime=_get_best(by_reg),
            best_mc_range=_get_best(by_mc),
            best_age_range=_get_best(by_age),
            best_curve_range=_get_best(by_curve),
        )
