"""
Quantitative Research Radar Dashboard v2
Renders multi-target calibrated probabilities, decoupled risk vectors,
raw vs effective top 10 concentration, and discrete alert states.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from src.config import AppConfig
from src.feeds.base_feed import TokenCandidate
from src.models.predictor import BreakoutPredictionOutput


class QuantitativeDashboard:
    def __init__(self, config: AppConfig):
        self.config = config
        self.console = Console(legacy_windows=False, force_terminal=True)
        self.total_scanned = 0
        self.high_conviction_count = 0

    @staticmethod
    def format_state_badge(state: str) -> str:
        if state == "HIGH_CONVICTION":
            return "[bold black on bright_green] ★ HIGH CONV [/]"
        elif state == "EARLY_BREAKOUT":
            return "[bold black on green] 🟢 BREAKOUT  [/]"
        elif state == "WATCH":
            return "[cyan] 🟡 WATCH     [/]"
        elif state == "MANIPULATION_WARNING":
            return "[bold black on yellow] ⚠️ MANIP     [/]"
        elif state == "RUG_WARNING":
            return "[bold white on red] 🚨 RUG WARN  [/]"
        elif state == "EXIT_INVALIDATION":
            return "[dim red] ❌ INVALID   [/]"
        return f"[dim]{state[:10]}[/dim]"

    @staticmethod
    def format_prob_badge(prob: float) -> str:
        pct = prob * 100.0
        if pct >= 15.0:
            return f"[bold green]{pct:4.1f}%[/bold green]"
        elif pct >= 8.0:
            return f"[green]{pct:4.1f}%[/green]"
        elif pct >= 3.0:
            return f"[yellow]{pct:4.1f}%[/yellow]"
        else:
            return f"[dim]{pct:4.1f}%[/dim]"

    @staticmethod
    def format_risk_badge(risk: float) -> str:
        pct = risk * 100.0
        if pct >= 50.0:
            return f"[bold red]{pct:3.0f}%[/bold red]"
        elif pct >= 25.0:
            return f"[yellow]{pct:3.0f}%[/yellow]"
        else:
            return f"[green]{pct:3.0f}%[/green]"

    def create_table(self, candidates_with_preds: List[Tuple[TokenCandidate, BreakoutPredictionOutput, Dict[str, Any]]]) -> Table:
        table = Table(
            show_header=True,
            header_style="bold magenta",
            border_style="bright_black",
            expand=True,
            box=None,
            padding=(0, 1),
        )

        table.add_column("State", justify="center", no_wrap=True)
        table.add_column("Token", justify="left", no_wrap=True)
        table.add_column("Chain/DEX", justify="center", no_wrap=True)
        table.add_column("MC", justify="right", no_wrap=True)
        table.add_column("Liquidity", justify="right", no_wrap=True)
        table.add_column("P(3M)", justify="right", no_wrap=True)
        table.add_column("P(100K)", justify="right", no_wrap=True)
        table.add_column("Rug%", justify="center", no_wrap=True)
        table.add_column("Cabal%", justify="center", no_wrap=True)
        table.add_column("Wash%", justify="center", no_wrap=True)
        table.add_column("Top10(R/E)", justify="right", no_wrap=True)
        table.add_column("Dev", justify="center", no_wrap=True)
        table.add_column("Signals & Key Drivers", justify="left")

        # Sort priority: HIGH_CONVICTION -> EARLY_BREAKOUT -> P(3M) -> Score
        state_priority = {
            "HIGH_CONVICTION": 1,
            "EARLY_BREAKOUT": 2,
            "WATCH": 3,
            "MANIPULATION_WARNING": 4,
            "EXIT_INVALIDATION": 5,
            "RUG_WARNING": 6,
        }

        sorted_items = sorted(
            candidates_with_preds,
            key=lambda item: (state_priority.get(item[1].alert_state, 10), -item[1].p_reach_3m, -item[1].model_score),
        )[: self.config.scanner.dashboard_display_limit]

        for t, p, meta in sorted_items:
            badge = self.format_state_badge(p.alert_state)
            token_text = f"[bold white]${t.symbol[:8]}[/bold white]"

            chain_col = "bright_cyan" if t.chain == "solana" else "blue"
            chain_text = f"[{chain_col}]{t.chain[:3].upper()}[/{chain_col}] [dim]{t.dex_id[:4]}[/dim]"

            mc_text = f"${t.market_cap_usd:,.0f}" if t.market_cap_usd > 0 else "$0"
            liq_val = max(0.0, t.liquidity_usd)
            liq_ratio = max(0.0, t.liquidity_mc_ratio)
            liq_text = f"${liq_val:,.0f} [dim]({liq_ratio:.0%})[/dim]"

            p3m_text = self.format_prob_badge(p.p_reach_3m)
            p100k_text = self.format_prob_badge(p.p_reach_100k)

            rug_text = self.format_risk_badge(p.p_rug)
            cabal_text = self.format_risk_badge(p.p_cabal)
            wash_text = self.format_risk_badge(p.p_manipulation)

            raw_top10 = t.security.top10_holder_pct
            eff_top10 = meta.get("effective_top10_pct", raw_top10)
            top10_col = "green" if eff_top10 <= 20.0 else ("yellow" if eff_top10 <= 30.0 else "red")
            top10_text = f"[{top10_col}]{raw_top10:.0f}/{eff_top10:.0f}%[/{top10_col}]"

            dev_pct = t.security.dev_holding_pct
            dev_col = "green" if dev_pct <= 1.0 else ("yellow" if dev_pct <= 4.0 else "red")
            dev_class = meta.get("dev_classification", "NEUTRAL")[:3]
            dev_text = f"[{dev_col}]{dev_pct:.1f}% [{dev_class}][/{dev_col}]"

            # Signals
            sig_list = []
            for s in p.signals[:2]:
                sig_list.append(f"[green]✓[/green] {s.replace('_', ' ').title()[:20]}")
            for w in p.risk_warnings[:1]:
                sig_list.append(f"[red]![/red] {w.replace('_', ' ').title()[:20]}")
            signals_text = " | ".join(sig_list) if sig_list else "[dim]Nominal[/dim]"

            table.add_row(
                badge,
                token_text,
                chain_text,
                mc_text,
                liq_text,
                p3m_text,
                p100k_text,
                rug_text,
                cabal_text,
                wash_text,
                top10_text,
                dev_text,
                signals_text,
            )

        return table

    def print_snapshot(self, candidates_with_preds: List[Tuple[TokenCandidate, BreakoutPredictionOutput, Dict[str, Any]]]) -> None:
        """Print rich quantitative snapshot to the terminal."""
        high_conv = sum(1 for _, p, _ in candidates_with_preds if p.alert_state == "HIGH_CONVICTION")
        breakouts = sum(1 for _, p, _ in candidates_with_preds if p.alert_state == "EARLY_BREAKOUT")
        chains_str = ", ".join(self.config.scanner.active_chains).upper()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        header_text = Text()
        header_text.append("💎 QUANTITATIVE BREAKOUT RADAR | Sub-$10K to $3M+ Research Scanner\n", style="bold cyan")
        header_text.append(f"Chains: {chains_str}  │  Eligible Tokens: {len(candidates_with_preds)}  │  🎯 High-Conviction: {high_conv}  │  🟢 Breakouts: {breakouts}  │  {now_str}", style="dim white")
        self.console.print(Panel(header_text, border_style="cyan"))

        table = self.create_table(candidates_with_preds)
        self.console.print(Panel(table, title="[bold]Calibrated Multi-Target Radar[/bold]", border_style="blue"))

        footer_text = (
            "[dim]Probabilities: P(3M), P(100K) Calibrated vs Base Population • Top10: Raw / Effective Cluster Concentration • Wash: Capital Turnover & Loop Penalty[/dim]"
        )
        self.console.print(Panel(footer_text, border_style="bright_black"))
