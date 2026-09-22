"""
Interactive Terminal Dashboard
Renders real-time breakout candidates, scores, and order flow metrics using Rich.
"""

from datetime import datetime
import os
import sys
from typing import List, Optional
from rich.console import Console, Group
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from src.config import AppConfig
from src.feeds.base_feed import ScoredToken


class TerminalDashboard:
    def __init__(self, config: AppConfig):
        self.config = config
        self.console = Console(legacy_windows=False, force_terminal=True)
        self.total_scanned = 0
        self.gems_detected = 0
        self.last_scan_time = datetime.now()

    def format_score_badge(self, score: float) -> str:
        if score >= 80:
            return f"[bold green]{score:4.1f} ★[/bold green]"
        elif score >= 70:
            return f"[bold cyan]{score:4.1f} 🟢[/bold cyan]"
        elif score >= 55:
            return f"[yellow]{score:4.1f} 🟡[/yellow]"
        else:
            return f"[dim]{score:4.1f}[/dim]"

    def format_signals(self, scored_token: ScoredToken) -> str:
        s = scored_token.score
        items = []
        for sig in s.signals[:3]:
            short_sig = sig.replace("_", " ").title()
            items.append(f"[green]✓[/green] {short_sig}")
        if s.warnings:
            for w in s.warnings[:2]:
                items.append(f"[red]![/red] {w[:18]}")
        return " | ".join(items) if items else "[dim]Normal[/dim]"

    def format_socials(self, scored_token: ScoredToken) -> str:
        soc = scored_token.token.socials
        icons = []
        if soc.twitter:
            icons.append("[cyan]𝕏[/cyan]")
        if soc.telegram:
            icons.append("[blue]TG[/blue]")
        if soc.website:
            icons.append("[white]WEB[/white]")
        return " ".join(icons) if icons else "[dim]--[/dim]"

    def create_table(self, candidates: List[ScoredToken]) -> Table:
        table = Table(
            show_header=True,
            header_style="bold magenta",
            border_style="bright_black",
            expand=True,
            box=None,
            padding=(0, 1),
        )

        table.add_column("Score", justify="center", no_wrap=True)
        table.add_column("Token", justify="left", no_wrap=True)
        table.add_column("Chain", justify="center", no_wrap=True)
        table.add_column("MC", justify="right", no_wrap=True)
        table.add_column("Liquidity", justify="right", no_wrap=True)
        table.add_column("5m Vol", justify="right", no_wrap=True)
        table.add_column("B/S", justify="center", no_wrap=True)
        table.add_column("Buyers", justify="right", no_wrap=True)
        table.add_column("Top10", justify="right", no_wrap=True)
        table.add_column("Age", justify="right", no_wrap=True)
        table.add_column("Socials", justify="center", no_wrap=True)
        table.add_column("Signals & Safety", justify="left")

        limit = self.config.scanner.dashboard_display_limit
        sorted_candidates = sorted(
            candidates,
            key=lambda c: (c.passed_filters, c.score.total_gem_score),
            reverse=True,
        )[:limit]

        for sc in sorted_candidates:
            t = sc.token
            score_badge = self.format_score_badge(sc.score.total_gem_score)
            sym_style = "bold white" if sc.passed_filters else "dim"
            sym_text = f"[{sym_style}]${t.symbol[:9]}[/{sym_style}]"

            chain_color = "bright_cyan" if t.chain == "solana" else "blue"
            chain_text = f"[{chain_color}]{t.chain.upper()[:4]}[/{chain_color}]"

            mc_text = f"${t.market_cap_usd:,.0f}" if t.market_cap_usd > 0 else "$0"
            liq_val = max(0.0, t.liquidity_usd)
            liq_ratio = max(0.0, t.liquidity_mc_ratio)
            liq_text = f"${liq_val:,.0f} [dim]({liq_ratio:.0%})[/dim]"

            vol_ratio = max(0.0, t.volume_mc_ratio_5m * 12.0)
            vol_color = "green" if 0.8 <= vol_ratio <= 3.5 else ("yellow" if vol_ratio > 3.5 else "dim")
            vol_text = f"${t.volume_5m_usd:,.0f} [{vol_color}]({vol_ratio:.1f}x)[/{vol_color}]"

            effective_bs = max(t.buy_sell_ratio_5m, t.buy_sell_ratio_1h)
            bs_color = "bold green" if effective_bs >= 1.6 else ("green" if effective_bs >= 1.2 else "red")
            bs_text = f"[{bs_color}]{effective_bs:.2f}x[/{bs_color}]"

            buyers_color = "bold green" if t.unique_buyers_1h >= 40 else "white"
            buyers_text = f"[{buyers_color}]{t.unique_buyers_1h}[/{buyers_color}]"

            top10_color = "green" if t.security.top10_holder_pct <= 20.0 else ("yellow" if t.security.top10_holder_pct <= 28.0 else "red")
            top10_text = f"[{top10_color}]{t.security.top10_holder_pct:.1f}%[/{top10_color}]"

            age_str = f"{int(t.age_minutes)}m" if t.age_minutes < 60 else f"{t.age_minutes/60:.1f}h"
            soc_text = self.format_socials(sc)
            signals_text = self.format_signals(sc)

            table.add_row(
                score_badge,
                sym_text,
                chain_text,
                mc_text,
                liq_text,
                vol_text,
                bs_text,
                buyers_text,
                top10_text,
                age_str,
                soc_text,
                signals_text,
            )

        return table

    def render(self, candidates: List[ScoredToken]) -> Layout:
        """Construct full screen layout."""
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=4),
            Layout(name="main", ratio=1),
            Layout(name="footer", size=3),
        )

        # Header
        passed_count = sum(1 for c in candidates if c.passed_filters and c.score.total_gem_score >= self.config.scoring.alert_score_threshold)
        chains_str = ", ".join(self.config.scanner.active_chains).upper()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        header_text = Text()
        header_text.append("💎 GEM DETECTOR | Sub-$10K to $3M+ Breakout Scanner\n", style="bold cyan")
        header_text.append(f"Chains: {chains_str}  │  Alert Score Threshold: ≥{self.config.scoring.alert_score_threshold}  │  Active Candidates: {len(candidates)}  │  🎯 High-Probability Gems: {passed_count}  │  {now_str}", style="dim white")
        layout["header"].update(Panel(header_text, border_style="cyan"))

        # Main Table
        table = self.create_table(candidates)
        layout["main"].update(Panel(table, title="[bold]Real-Time Breakout Radar[/bold]", border_style="blue"))

        # Footer Status
        footer_text = (
            "[dim]Heuristics: MC $8K-$50K • LP/MC > 15% • Buy/Sell > 1.4x • Top10 < 25% • Dev Clean Exit • Vol/MC 0.8x-3.5x[/dim]\n"
            "[yellow]Press Ctrl+C to stop scanner | Auto-refreshes every "
            f"{self.config.scanner.poll_interval_sec}s[/yellow]"
        )
        layout["footer"].update(Panel(footer_text, border_style="bright_black"))

        return layout

    def print_snapshot(self, candidates: List[ScoredToken]) -> None:
        """Print a static snapshot to the terminal."""
        passed_count = sum(1 for c in candidates if c.passed_filters and c.score.total_gem_score >= self.config.scoring.alert_score_threshold)
        chains_str = ", ".join(self.config.scanner.active_chains).upper()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        header_text = Text()
        header_text.append("💎 GEM DETECTOR | Sub-$10K to $3M+ Breakout Scanner\n", style="bold cyan")
        header_text.append(f"Chains: {chains_str}  │  Alert Score Threshold: ≥{self.config.scoring.alert_score_threshold}  │  Active Candidates: {len(candidates)}  │  🎯 High-Probability Gems: {passed_count}  │  {now_str}", style="dim white")
        self.console.print(Panel(header_text, border_style="cyan"))

        table = self.create_table(candidates)
        self.console.print(Panel(table, title="[bold]Real-Time Breakout Radar[/bold]", border_style="blue"))

        footer_text = (
            "[dim]Heuristics: MC $8K-$50K • LP/MC > 15% • Buy/Sell > 1.4x • Top10 < 25% • Dev Clean Exit • Vol/MC 0.8x-3.5x[/dim]"
        )
        self.console.print(Panel(footer_text, border_style="bright_black"))
