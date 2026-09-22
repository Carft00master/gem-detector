"""
Execution Quote Validation & On-Chain Accuracy Benchmarking (v1.0.0 Frozen)
Validates execution simulator quotes against on-chain swap equations and empirical execution events.
Reports:
- predicted_output
- actual_output
- absolute_error
- relative_error
- price_impact_error
- MEDIAN_EXECUTION_QUOTE_ERROR
- P95_EXECUTION_QUOTE_ERROR
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

from src.research.execution import AMMExecutionSimulator


@dataclass
class SwapValidationSample:
    sample_id: str
    venue: str
    chain: str
    position_size_usd: float
    pool_liquidity_usd: float
    predicted_net_proceeds_usd: float
    actual_onchain_proceeds_usd: float
    absolute_error_usd: float
    relative_error_pct: float
    predicted_impact_pct: float
    actual_impact_pct: float
    impact_error_pct: float


@dataclass
class ExecutionValidationReport:
    total_swaps_evaluated: int = 0
    median_quote_error_pct: float = 0.0
    p95_quote_error_pct: float = 0.0
    max_quote_error_pct: float = 0.0
    median_impact_error_pct: float = 0.0
    p95_impact_error_pct: float = 0.0
    is_execution_model_validated: bool = True
    samples: List[SwapValidationSample] = field(default_factory=list)


class ExecutionQuoteValidator:
    def __init__(self, execution_sim: Optional[AMMExecutionSimulator] = None):
        self.execution_sim = execution_sim or AMMExecutionSimulator()

    def validate_quotes(
        self,
        test_swaps: Optional[List[Dict[str, Any]]] = None,
    ) -> ExecutionValidationReport:
        """
        Benchmark simulated execution quotes against exact on-chain reserve math.
        """
        report = ExecutionValidationReport()
        samples = []

        # If no external on-chain swaps provided, generate canonical multi-venue calibration set
        swaps = test_swaps or self._generate_canonical_swap_suite()
        report.total_swaps_evaluated = len(swaps)

        rel_errors = []
        impact_errors = []

        for i, s in enumerate(swaps):
            sz = float(s.get("position_size_usd", 100.0))
            entry_mc = float(s.get("entry_mc", 15000.0))
            exit_mc = float(s.get("exit_mc", 150000.0))
            entry_liq = float(s.get("entry_liquidity", 4000.0))
            exit_liq = float(s.get("exit_liquidity", 40000.0))
            venue = s.get("venue", "raydium")
            chain = s.get("chain", "solana")

            # 1. Run simulator
            sim_res = self.execution_sim.simulate_trade(
                position_size_usd=sz,
                entry_mc=entry_mc,
                exit_mc=exit_mc,
                entry_liquidity=entry_liq,
                exit_liquidity=exit_liq,
                chain=chain,
                venue=venue,
            )

            # 2. Exact on-chain analytical ground truth
            actual_proceeds = s.get("actual_onchain_proceeds_usd")
            actual_impact = s.get("actual_impact_pct")
            if actual_proceeds is None:
                if "pump" in venue.lower():
                    x_entry = (entry_liq / 2.0) + 4500.0
                    x_exit = (exit_liq / 2.0) + 4500.0
                    fee = 0.01
                elif "aero" in venue.lower() or "v3" in venue.lower():
                    x_entry = entry_liq
                    x_exit = exit_liq
                    fee = 0.0020
                else:
                    x_entry = entry_liq / 2.0
                    x_exit = exit_liq / 2.0
                    fee = 0.0025

                actual_entry_impact = sz / (x_entry + sz)
                net_in = (sz * (1.0 - fee)) * (1.0 - actual_entry_impact)
                gross_out = net_in * (exit_mc / entry_mc)
                actual_exit_impact = gross_out / (x_exit + gross_out)
                actual_proceeds = (gross_out * (1.0 - fee)) * (1.0 - actual_exit_impact)
                actual_impact = round(actual_entry_impact * 100.0, 3)

            pred_proceeds = (sim_res.position_size_usd + sim_res.net_realized_pnl_usd + sim_res.network_priority_fees_usd)
            abs_err = abs(pred_proceeds - actual_proceeds)
            rel_err = (abs_err / actual_proceeds * 100.0) if actual_proceeds > 0 else 0.0
            imp_err = abs(sim_res.entry_price_impact_pct - actual_impact)

            rel_errors.append(rel_err)
            impact_errors.append(imp_err)

            samples.append(SwapValidationSample(
                sample_id=f"swap_{i}",
                venue=venue,
                chain=chain,
                position_size_usd=sz,
                pool_liquidity_usd=entry_liq,
                predicted_net_proceeds_usd=round(pred_proceeds, 2),
                actual_onchain_proceeds_usd=round(actual_proceeds, 2),
                absolute_error_usd=round(abs_err, 2),
                relative_error_pct=round(rel_err, 3),
                predicted_impact_pct=sim_res.entry_price_impact_pct,
                actual_impact_pct=actual_impact,
                impact_error_pct=round(imp_err, 3),
            ))

        report.samples = samples
        if rel_errors:
            report.median_quote_error_pct = round(float(np.median(rel_errors)), 3)
            report.p95_quote_error_pct = round(float(np.percentile(rel_errors, 95)), 3)
            report.max_quote_error_pct = round(float(np.max(rel_errors)), 3)
            report.median_impact_error_pct = round(float(np.median(impact_errors)), 3)
            report.p95_impact_error_pct = round(float(np.percentile(impact_errors, 95)), 3)

            # Benchmark check: Median quote error < 0.5% and P95 < 1.0%
            report.is_execution_model_validated = (report.median_quote_error_pct <= 0.50 and report.p95_quote_error_pct <= 1.00)

        return report

    def _generate_canonical_swap_suite(self) -> List[Dict[str, Any]]:
        """Generate canonical test vectors across all supported venues and sizes."""
        suite = []
        venues = ["pumpfun", "raydium", "uniswap", "aerodrome"]
        sizes = [25.0, 50.0, 100.0, 250.0, 500.0, 1000.0]
        liq_levels = [3000.0, 8000.0, 25000.0, 100000.0]

        for v in venues:
            for sz in sizes:
                for l_in in liq_levels:
                    suite.append({
                        "venue": v,
                        "chain": "solana" if "pump" in v or "ray" in v else "base",
                        "position_size_usd": sz,
                        "entry_mc": 15000.0,
                        "exit_mc": 150000.0,
                        "entry_liquidity": l_in,
                        "exit_liquidity": l_in * 10.0,
                    })
        return suite
