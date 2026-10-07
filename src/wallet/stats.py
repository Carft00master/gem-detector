"""
Statistical analytics engine for the Virtual Wallet.
Computes daily, weekly, and all-time KPIs, realistic fees vs gross profit ratios,
drawdown tracking, and capital utilization.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
import sqlite3

from src.wallet.store import WalletStore
from src.wallet.models import WalletSessionRecord, WalletPositionRecord


@dataclass
class DailyWalletStats:
    date: str                               # YYYY-MM-DD
    trades_taken: int = 0
    trades_closed: int = 0
    wins: int = 0
    losses: int = 0
    win_rate_pct: float = 0.0
    net_pnl_usd: float = 0.0
    daily_return_pct: float = 0.0
    starting_equity_usd: float = 0.0
    ending_equity_usd: float = 0.0
    total_fees_usd: float = 0.0
    peak_capital_deployed_usd: float = 0.0


@dataclass
class WeeklyWalletStats:
    week_label: str                         # "2026-W40"
    start_date: str                         # YYYY-MM-DD
    end_date: str                           # YYYY-MM-DD
    trades_taken: int = 0
    trades_closed: int = 0
    wins: int = 0
    losses: int = 0
    win_rate_pct: float = 0.0
    net_pnl_usd: float = 0.0
    weekly_return_pct: float = 0.0
    starting_equity_usd: float = 0.0
    ending_equity_usd: float = 0.0
    total_fees_usd: float = 0.0


@dataclass
class WalletSummaryStats:
    session_name: str
    starting_capital_usd: float = 1000.0
    current_cash_usd: float = 1000.0
    current_equity_usd: float = 1000.0
    capital_deployed_usd: float = 0.0
    net_realized_pnl_usd: float = 0.0
    overall_roi_pct: float = 0.0
    peak_equity_usd: float = 1000.0
    max_drawdown_pct: float = 0.0
    total_positions_admitted: int = 0
    open_positions_count: int = 0
    closed_positions_count: int = 0
    skipped_no_capital_count: int = 0
    wins_count: int = 0
    losses_count: int = 0
    win_rate_pct: float = 0.0
    profit_factor: float = 1.0
    total_fees_paid_usd: float = 0.0
    total_slippage_friction_usd: float = 0.0
    top_3_winners_share_pct: float = 0.0
    avg_hold_minutes: float = 0.0
    expectancy_per_trade_usd: float = 0.0
    today_pnl_usd: float = 0.0
    this_week_pnl_usd: float = 0.0


class WalletStatsCalculator:
    def __init__(self, store: WalletStore, tz_offset_hours: int = 1):
        self.store = store
        self.tz_offset_hours = tz_offset_hours

    def _to_local_date(self, iso_ts: str) -> str:
        """Convert UTC timestamp to local day YYYY-MM-DD using timezone offset."""
        if not iso_ts:
            return ""
        try:
            dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
            local_dt = dt + timedelta(hours=self.tz_offset_hours)
            return local_dt.strftime("%Y-%m-%d")
        except Exception:
            return iso_ts[:10]

    def _to_week_label(self, iso_ts: str) -> str:
        """Return ISO calendar week string, e.g. '2026-W40'."""
        if not iso_ts:
            return ""
        try:
            dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
            local_dt = dt + timedelta(hours=self.tz_offset_hours)
            year, week, _ = local_dt.isocalendar()
            return f"{year}-W{week:02d}"
        except Exception:
            return "Unknown"

    def compute_summary_stats(self, session: WalletSessionRecord) -> WalletSummaryStats:
        positions = self.store.get_all_positions(session.session_id, limit=5000)
        open_pos = [p for p in positions if p.status == "OPEN"]
        closed_pos = [p for p in positions if p.status == "CLOSED"]
        skipped_pos = [p for p in positions if p.status == "SKIPPED"]

        gross_profit = sum(p.net_realized_pnl_usd for p in closed_pos if p.net_realized_pnl_usd > 0)
        gross_loss = sum(abs(p.net_realized_pnl_usd) for p in closed_pos if p.net_realized_pnl_usd < 0)
        total_pnl = sum(p.net_realized_pnl_usd for p in closed_pos)

        wins = [p for p in closed_pos if p.net_realized_pnl_usd > 0]
        losses = [p for p in closed_pos if p.net_realized_pnl_usd <= 0]
        win_rate = (len(wins) / len(closed_pos) * 100.0) if closed_pos else 0.0
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (99.0 if gross_profit > 0 else 1.0)

        total_fees = sum(p.entry_fees_usd + p.exit_fees_usd for p in closed_pos)
        avg_hold = (sum(p.hold_duration_seconds for p in closed_pos) / len(closed_pos) / 60.0) if closed_pos else 0.0
        expectancy = (total_pnl / len(closed_pos)) if closed_pos else 0.0

        # Top 3 winners concentration
        sorted_profits = sorted([p.net_realized_pnl_usd for p in wins], reverse=True)
        top_3_sum = sum(sorted_profits[:3])
        top_3_pct = (top_3_sum / gross_profit * 100.0) if gross_profit > 0 else 0.0

        # Current capital deployment
        deployed = sum(p.position_size_usd for p in open_pos)

        # Today and This Week PnL
        now_local_date = self._to_local_date(datetime.now(timezone.utc).isoformat())
        now_week = self._to_week_label(datetime.now(timezone.utc).isoformat())

        today_pnl = sum(
            p.net_realized_pnl_usd for p in closed_pos 
            if self._to_local_date(p.exit_timestamp or p.entry_timestamp) == now_local_date
        )
        week_pnl = sum(
            p.net_realized_pnl_usd for p in closed_pos
            if self._to_week_label(p.exit_timestamp or p.entry_timestamp) == now_week
        )

        roi_pct = ((session.current_equity_usd - session.starting_capital_usd) / session.starting_capital_usd * 100.0) if session.starting_capital_usd > 0 else 0.0

        return WalletSummaryStats(
            session_name=session.name,
            starting_capital_usd=session.starting_capital_usd,
            current_cash_usd=session.current_cash_usd,
            current_equity_usd=session.current_equity_usd,
            capital_deployed_usd=deployed,
            net_realized_pnl_usd=round(total_pnl, 2),
            overall_roi_pct=round(roi_pct, 2),
            peak_equity_usd=round(session.peak_equity_usd, 2),
            max_drawdown_pct=round(session.max_drawdown_pct, 2),
            total_positions_admitted=len(open_pos) + len(closed_pos),
            open_positions_count=len(open_pos),
            closed_positions_count=len(closed_pos),
            skipped_no_capital_count=len(skipped_pos),
            wins_count=len(wins),
            losses_count=len(losses),
            win_rate_pct=round(win_rate, 2),
            profit_factor=round(profit_factor, 2),
            total_fees_paid_usd=round(total_fees, 2),
            top_3_winners_share_pct=round(top_3_pct, 1),
            avg_hold_minutes=round(avg_hold, 1),
            expectancy_per_trade_usd=round(expectancy, 2),
            today_pnl_usd=round(today_pnl, 2),
            this_week_pnl_usd=round(week_pnl, 2),
        )

    def compute_daily_breakdown(self, session_id: str) -> List[DailyWalletStats]:
        positions = self.store.get_all_positions(session_id, limit=5000)
        daily_map: Dict[str, List[WalletPositionRecord]] = {}

        for p in positions:
            d = self._to_local_date(p.exit_timestamp or p.entry_timestamp)
            if d:
                daily_map.setdefault(d, []).append(p)

        stats_list = []
        for date_str in sorted(daily_map.keys(), reverse=True):
            day_positions = daily_map[date_str]
            closed = [p for p in day_positions if p.status == "CLOSED"]
            wins = [p for p in closed if p.net_realized_pnl_usd > 0]
            losses = [p for p in closed if p.net_realized_pnl_usd <= 0]
            day_pnl = sum(p.net_realized_pnl_usd for p in closed)
            day_fees = sum(p.entry_fees_usd + p.exit_fees_usd for p in closed)
            peak_dep = sum(p.position_size_usd for p in day_positions if p.status in ("OPEN", "CLOSED"))

            wr = (len(wins) / len(closed) * 100.0) if closed else 0.0

            # Ending equity from the latest closed trade of that day
            end_eq = closed[0].equity_after_usd if closed else 1000.0
            start_eq = closed[-1].equity_before_usd if closed else 1000.0
            ret_pct = ((end_eq - start_eq) / start_eq * 100.0) if start_eq > 0 else 0.0

            stats_list.append(DailyWalletStats(
                date=date_str,
                trades_taken=len(day_positions),
                trades_closed=len(closed),
                wins=len(wins),
                losses=len(losses),
                win_rate_pct=round(wr, 1),
                net_pnl_usd=round(day_pnl, 2),
                daily_return_pct=round(ret_pct, 2),
                starting_equity_usd=round(start_eq, 2),
                ending_equity_usd=round(end_eq, 2),
                total_fees_usd=round(day_fees, 2),
                peak_capital_deployed_usd=round(peak_dep, 2),
            ))

        return stats_list

    def compute_weekly_breakdown(self, session_id: str) -> List[WeeklyWalletStats]:
        daily_stats = self.compute_daily_breakdown(session_id)
        week_map: Dict[str, List[DailyWalletStats]] = {}

        for d in daily_stats:
            try:
                dt = datetime.strptime(d.date, "%Y-%m-%d")
                year, week, _ = dt.isocalendar()
                w_lbl = f"{year}-W{week:02d}"
                week_map.setdefault(w_lbl, []).append(d)
            except Exception:
                pass

        weekly_list = []
        for w_lbl in sorted(week_map.keys(), reverse=True):
            days = week_map[w_lbl]
            tot_taken = sum(d.trades_taken for d in days)
            tot_closed = sum(d.trades_closed for d in days)
            tot_wins = sum(d.wins for d in days)
            tot_losses = sum(d.losses for d in days)
            tot_pnl = sum(d.net_pnl_usd for d in days)
            tot_fees = sum(d.total_fees_usd for d in days)

            wr = (tot_wins / tot_closed * 100.0) if tot_closed else 0.0
            start_eq = days[-1].starting_equity_usd if days else 1000.0
            end_eq = days[0].ending_equity_usd if days else 1000.0
            ret_pct = ((end_eq - start_eq) / start_eq * 100.0) if start_eq > 0 else 0.0

            # Compute calendar range for week
            dates = [d.date for d in days]
            s_date = min(dates) if dates else ""
            e_date = max(dates) if dates else ""

            weekly_list.append(WeeklyWalletStats(
                week_label=w_lbl,
                start_date=s_date,
                end_date=e_date,
                trades_taken=tot_taken,
                trades_closed=tot_closed,
                wins=tot_wins,
                losses=tot_losses,
                win_rate_pct=round(wr, 1),
                net_pnl_usd=round(tot_pnl, 2),
                weekly_return_pct=round(ret_pct, 2),
                starting_equity_usd=round(start_eq, 2),
                ending_equity_usd=round(end_eq, 2),
                total_fees_usd=round(tot_fees, 2),
            ))

        return weekly_list
