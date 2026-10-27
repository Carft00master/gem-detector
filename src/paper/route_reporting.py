"""
Per-Route Performance Reporting with Bootstrap Confidence Intervals (Phase 1g)
Strict separation of Route A (Organic Breakout) and Route B (First-Block Migration Sniper) ledgers.
Computes:
1. Win Rate (%) with 95% bootstrap CI (1,000 resamples)
2. Profit Factor with 95% bootstrap CI (1,000 resamples)
3. Median MFE ratio with 95% bootstrap CI (1,000 resamples)
4. Median MAE ratio with 95% bootstrap CI (1,000 resamples)
5. Total Realized P&L ($) with 95% bootstrap CI (1,000 resamples)
6. Fixed cost / priority fee as % of position size
"""

from dataclasses import asdict, dataclass
import logging
import math
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

from src.paper.ledger import PaperTradingLedger

logger = logging.getLogger(__name__)


@dataclass
class BootstrapMetric:
    point_estimate: float
    ci_lower: float
    ci_upper: float
    confidence_level: float = 0.95

    def to_dict(self) -> Dict[str, float]:
        return asdict(self)


@dataclass
class RouteMetricsReport:
    route: str
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: BootstrapMetric
    profit_factor: BootstrapMetric
    median_mfe: BootstrapMetric
    median_mae: BootstrapMetric
    total_realized_pnl_usd: BootstrapMetric
    avg_trade_pnl_usd: float
    avg_position_size_usd: float
    fixed_cost_pct_of_size: float
    is_latency_upper_bound: bool = False
    provider_tier: str = "FREE"
    detection_mode: str = "polled, not streamed"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "route": self.route,
            "provider_tier": self.provider_tier,
            "detection_mode": self.detection_mode,
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate": self.win_rate.to_dict(),
            "profit_factor": self.profit_factor.to_dict(),
            "median_mfe": self.median_mfe.to_dict(),
            "median_mae": self.median_mae.to_dict(),
            "total_realized_pnl_usd": self.total_realized_pnl_usd.to_dict(),
            "avg_trade_pnl_usd": self.avg_trade_pnl_usd,
            "avg_position_size_usd": self.avg_position_size_usd,
            "fixed_cost_pct_of_size": self.fixed_cost_pct_of_size,
            "is_latency_upper_bound": self.is_latency_upper_bound,
        }


class RoutePerformanceReporter:
    """
    Generates isolated per-route performance reports with rigorous 1,000-resample bootstrap CIs.
    """
    def __init__(self, ledger: Optional[PaperTradingLedger] = None, n_resamples: int = 1000, random_seed: int = 42):
        self.ledger = ledger or PaperTradingLedger()
        self.n_resamples = n_resamples
        self.random_seed = random_seed

    def generate_report_for_route(
        self,
        route: str,
        trades: Optional[List[Dict[str, Any]]] = None,
        is_latency_upper_bound: bool = False,
        provider_tier: str = "FREE",
        detection_mode: str = "polled, not streamed",
    ) -> RouteMetricsReport:
        """
        Generate statistical performance report for a specific route.
        """
        if trades is None:
            trades = self.ledger.load_all_trades()
        
        route_trades = [t for t in trades if str(t.get("route", "ROUTE_A")).upper() == route.upper()]
        if route_trades:
            provider_tier = str(route_trades[0].get("provider_tier") or provider_tier)
            detection_mode = str(route_trades[0].get("detection_mode") or detection_mode)

        # Filter to closed trades with valid P&L
        closed_trades = [t for t in route_trades if t.get("status") == "CLOSED"]
        n_trades = len(closed_trades)

        if n_trades == 0:
            zero_metric = BootstrapMetric(point_estimate=0.0, ci_lower=0.0, ci_upper=0.0)
            return RouteMetricsReport(
                route=route,
                total_trades=0,
                winning_trades=0,
                losing_trades=0,
                win_rate=zero_metric,
                profit_factor=zero_metric,
                median_mfe=BootstrapMetric(1.0, 1.0, 1.0),
                median_mae=BootstrapMetric(1.0, 1.0, 1.0),
                total_realized_pnl_usd=zero_metric,
                avg_trade_pnl_usd=0.0,
                avg_position_size_usd=0.0,
                fixed_cost_pct_of_size=0.0,
                is_latency_upper_bound=is_latency_upper_bound,
                provider_tier=provider_tier,
                detection_mode=detection_mode,
            )

        pnls = np.array([float(t.get("net_realized_pnl_usd", 0.0) or 0.0) for t in closed_trades])
        sizes = np.array([float(t.get("position_size_usd", 100.0) or 100.0) for t in closed_trades])
        mfes = np.array([float(t.get("mfe_ratio", 1.0) or 1.0) for t in closed_trades])
        maes = np.array([float(t.get("mae_ratio", 1.0) or 1.0) for t in closed_trades])
        network_costs = np.array([
            float(t.get("network_cost_usd", 0.0) or (t.get("total_fees_usd", 0.0) or 0.0))
            for t in closed_trades
        ])

        wins = pnls > 0
        n_wins = int(np.sum(wins))
        n_losses = int(np.sum(pnls <= 0))

        # Point estimates
        point_win_rate = (n_wins / n_trades) * 100.0
        gross_profit = float(np.sum(pnls[wins])) if n_wins > 0 else 0.0
        gross_loss = float(abs(np.sum(pnls[pnls < 0]))) if n_losses > 0 else 0.0
        point_pf = (gross_profit / gross_loss) if gross_loss > 0 else (99.0 if gross_profit > 0 else 0.0)
        point_median_mfe = float(np.median(mfes))
        point_median_mae = float(np.median(maes))
        point_total_pnl = float(np.sum(pnls))

        avg_size = float(np.mean(sizes)) if len(sizes) > 0 else 100.0
        avg_cost = float(np.mean(network_costs)) if len(network_costs) > 0 else 0.0
        fixed_cost_pct = (avg_cost / avg_size * 100.0) if avg_size > 0 else 0.0

        # Run 1,000 bootstrap resamples
        rng = np.random.RandomState(self.random_seed)
        boot_win_rates = []
        boot_pfs = []
        boot_mfes = []
        boot_maes = []
        boot_pnls = []

        for _ in range(self.n_resamples):
            sample_idx = rng.choice(n_trades, size=n_trades, replace=True)
            s_pnls = pnls[sample_idx]
            s_mfes = mfes[sample_idx]
            s_maes = maes[sample_idx]

            s_wins = s_pnls > 0
            boot_win_rates.append((np.sum(s_wins) / n_trades) * 100.0)
            gp = np.sum(s_pnls[s_wins]) if np.any(s_wins) else 0.0
            gl = abs(np.sum(s_pnls[s_pnls < 0])) if np.any(s_pnls < 0) else 0.0
            boot_pfs.append((gp / gl) if gl > 0 else (99.0 if gp > 0 else 0.0))
            boot_mfes.append(float(np.median(s_mfes)))
            boot_maes.append(float(np.median(s_maes)))
            boot_pnls.append(float(np.sum(s_pnls)))

        def calc_ci(point: float, boot_samples: List[float]) -> BootstrapMetric:
            lo = float(np.percentile(boot_samples, 2.5))
            hi = float(np.percentile(boot_samples, 97.5))
            return BootstrapMetric(
                point_estimate=round(point, 2),
                ci_lower=round(lo, 2),
                ci_upper=round(hi, 2),
            )

        return RouteMetricsReport(
            route=route,
            total_trades=n_trades,
            winning_trades=n_wins,
            losing_trades=n_losses,
            win_rate=calc_ci(point_win_rate, boot_win_rates),
            profit_factor=calc_ci(point_pf, boot_pfs),
            median_mfe=calc_ci(point_median_mfe, boot_mfes),
            median_mae=calc_ci(point_median_mae, boot_maes),
            total_realized_pnl_usd=calc_ci(point_total_pnl, boot_pnls),
            avg_trade_pnl_usd=round(point_total_pnl / n_trades, 2),
            avg_position_size_usd=round(avg_size, 2),
            fixed_cost_pct_of_size=round(fixed_cost_pct, 2),
            is_latency_upper_bound=is_latency_upper_bound,
            provider_tier=provider_tier,
            detection_mode=detection_mode,
        )

    def generate_full_comparison_report(self) -> Dict[str, Any]:
        """
        Generate separate isolated reports for Route A and Route B.
        """
        all_trades = self.ledger.load_all_trades()
        trades_a = [t for t in all_trades if str(t.get("route", "ROUTE_A")).upper() == "ROUTE_A"]
        trades_b = [t for t in all_trades if str(t.get("route", "ROUTE_A")).upper() == "ROUTE_B"]

        rep_a = self.generate_report_for_route("ROUTE_A", trades=trades_a, is_latency_upper_bound=False)
        rep_b = self.generate_report_for_route("ROUTE_B", trades=trades_b, is_latency_upper_bound=True)

        return {
            "ROUTE_A": rep_a.to_dict(),
            "ROUTE_B": rep_b.to_dict(),
        }
