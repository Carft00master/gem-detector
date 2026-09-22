import logging
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QTableWidget, 
    QTableWidgetItem, QHeaderView, QLabel, QFrame, QAbstractItemView, QPushButton
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont

from app.ui.design_system import DS
from app.application.service_locator import ServiceLocator
from app.services.research_service import ResearchService
from app.ui.components.kpi_strip import KpiStrip
from app.ui.components.empty_state import EmptyState
from app.ui.components.async_helper import run_async_task

logger = logging.getLogger(__name__)


class PerformanceLearningView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.research_svc = ServiceLocator.get(ResearchService)
        self.perf_data = {}
        self._loading = False
        self.setup_ui()
        self.refresh_data()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 1. Top KPI Ribbon
        self.kpi_strip = KpiStrip([
            {"label": "CUMULATIVE REALIZED P&L", "value": "$0", "subtitle": "all paper trades", "color": "#10b981"},
            {"label": "TOTAL PAPER TRADES", "value": "0", "subtitle": "recorded in blotter", "color": "#38bdf8"},
            {"label": "OVERALL WIN RATE", "value": "0%", "subtitle": "closed positions", "color": "#34d399"},
            {"label": "PROFIT FACTOR", "value": "0.0", "subtitle": "lifetime ratio", "color": "#c084fc"},
            {"label": "MAX DRAWDOWN", "value": "0%", "subtitle": "peak-to-trough", "color": "#f87171"},
            {"label": "GENERATIONS", "value": "0", "subtitle": "50-trade cohorts", "color": "#fbbf24"},
        ])
        layout.addWidget(self.kpi_strip)

        # 2. Main Tabbed Container
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane { border: none; background-color: #080c14; }
            QTabBar::tab { background: #0b101c; color: #64748b; padding: 8px 18px; border: none; font-weight: 600; font-size: 11px; }
            QTabBar::tab:selected { background: #0f172a; color: #38bdf8; border-bottom: 2px solid #38bdf8; }
            QTabBar::tab:hover { color: #f8fafc; }
        """)

        self.tab_generations = QWidget()
        self.tab_rolling = QWidget()
        self.tab_comparison = QWidget()
        self.tab_regime = QWidget()

        self.tabs.addTab(self.tab_generations, "50-Trade Generation Cohorts")
        self.tabs.addTab(self.tab_rolling, "Rolling Windows (25 / 50 / 100 / 250)")
        self.tabs.addTab(self.tab_comparison, "Early vs Recent Drift Comparison")
        self.tabs.addTab(self.tab_regime, "Regime Performance Matrix")

        layout.addWidget(self.tabs)

        self._setup_generations_tab()
        self._setup_rolling_tab()
        self._setup_comparison_tab()
        self._setup_regime_tab()

    def _create_styled_table(self, columns):
        table = QTableWidget()
        table.setColumnCount(len(columns))
        table.setHorizontalHeaderLabels(columns)
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(True)
        header.setStyleSheet("""
            QHeaderView::section {
                background-color: #0b101c;
                color: #64748b;
                font-size: 10px;
                font-weight: 700;
                padding: 6px 8px;
                border: none;
                border-bottom: 1px solid #1e293b;
                border-right: 1px solid #141c2b;
            }
        """)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setShowGrid(False)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setDefaultSectionSize(34)
        return table

    def _setup_generations_tab(self):
        vbox = QVBoxLayout(self.tab_generations)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)
        cols = [
            "COHORT", "TRADES", "CLOSED", "WIN RATE", "TOTAL P&L", "CUMUL P&L", "PROFIT FACTOR", "MAX DRAWDOWN", "MEDIAN MFE", "RUG EXP"
        ]
        self.tbl_generations = self._create_styled_table(cols)
        col_widths = [130, 70, 70, 80, 95, 95, 95, 115, 90, 85]
        for c_idx, w in enumerate(col_widths):
            self.tbl_generations.setColumnWidth(c_idx, w)
        vbox.addWidget(self.tbl_generations)

    def _setup_rolling_tab(self):
        vbox = QVBoxLayout(self.tab_rolling)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)
        cols = [
            "WINDOW PERIOD", "SAMPLE TRADES", "CLOSED", "WIN RATE", "MEAN RETURN", "TOTAL P&L", "PROFIT FACTOR", "MAX DRAWDOWN", "AVG HOLD"
        ]
        self.tbl_rolling = self._create_styled_table(cols)
        col_widths_rolling = [130, 95, 75, 80, 95, 95, 95, 115, 85]
        for c_idx, w in enumerate(col_widths_rolling):
            self.tbl_rolling.setColumnWidth(c_idx, w)
        vbox.addWidget(self.tbl_rolling)

    def _setup_comparison_tab(self):
        vbox = QVBoxLayout(self.tab_comparison)
        vbox.setContentsMargins(20, 20, 20, 20)
        vbox.setSpacing(16)

        # Verdict banner
        self.verdict_card = QFrame()
        self.verdict_card.setStyleSheet("background-color: #1e1b4b; border: 1px solid #4338ca; border-radius: 8px; padding: 12px 16px;")
        v_layout = QHBoxLayout(self.verdict_card)
        self.lbl_verdict_title = QLabel("PERFORMANCE DRIFT VERDICT:")
        self.lbl_verdict_title.setStyleSheet("color: #a5b4fc; font-weight: 800; font-size: 12px;")
        self.lbl_verdict_text = QLabel("ANALYZING...")
        self.lbl_verdict_text.setStyleSheet("color: #fbbf24; font-weight: 700; font-size: 12px;")
        v_layout.addWidget(self.lbl_verdict_title)
        v_layout.addWidget(self.lbl_verdict_text)
        v_layout.addStretch()
        vbox.addWidget(self.verdict_card)

        # Cards comparison row
        cards_row = QHBoxLayout()
        cards_row.setSpacing(16)

        # Early Cohort Card
        self.card_early = QFrame()
        self.card_early.setStyleSheet("background-color: #0b101c; border: 1px solid #1e293b; border-radius: 8px; padding: 16px;")
        ce_layout = QVBoxLayout(self.card_early)
        ce_title = QLabel("EARLY COHORT (INITIAL 50 TRADES)")
        ce_title.setStyleSheet("color: #38bdf8; font-weight: 800; font-size: 13px; letter-spacing: 0.5px;")
        self.lbl_early_stats = QLabel("Loading...")
        self.lbl_early_stats.setStyleSheet("color: #cbd5e1; font-size: 12px; line-height: 1.8;")
        ce_layout.addWidget(ce_title)
        ce_layout.addWidget(self.lbl_early_stats)
        ce_layout.addStretch()
        cards_row.addWidget(self.card_early)

        # Recent Cohort Card
        self.card_recent = QFrame()
        self.card_recent.setStyleSheet("background-color: #0b101c; border: 1px solid #1e293b; border-radius: 8px; padding: 16px;")
        cr_layout = QVBoxLayout(self.card_recent)
        cr_title = QLabel("RECENT COHORT (LAST 50 TRADES)")
        cr_title.setStyleSheet("color: #c084fc; font-weight: 800; font-size: 13px; letter-spacing: 0.5px;")
        self.lbl_recent_stats = QLabel("Loading...")
        self.lbl_recent_stats.setStyleSheet("color: #cbd5e1; font-size: 12px; line-height: 1.8;")
        cr_layout.addWidget(cr_title)
        cr_layout.addWidget(self.lbl_recent_stats)
        cr_layout.addStretch()
        cards_row.addWidget(self.card_recent)

        # Delta Card
        self.card_delta = QFrame()
        self.card_delta.setStyleSheet("background-color: #0b101c; border: 1px solid #1e293b; border-radius: 8px; padding: 16px;")
        cd_layout = QVBoxLayout(self.card_delta)
        cd_title = QLabel("COHORT DRIFT & SHIFTS")
        cd_title.setStyleSheet("color: #fbbf24; font-weight: 800; font-size: 13px; letter-spacing: 0.5px;")
        self.lbl_delta_stats = QLabel("Loading...")
        self.lbl_delta_stats.setStyleSheet("color: #cbd5e1; font-size: 12px; line-height: 1.8;")
        cd_layout.addWidget(cd_title)
        cd_layout.addWidget(self.lbl_delta_stats)
        cd_layout.addStretch()
        cards_row.addWidget(self.card_delta)

        vbox.addLayout(cards_row)
        vbox.addStretch()

    def _setup_regime_tab(self):
        vbox = QVBoxLayout(self.tab_regime)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)
        cols = [
            "REGIME", "SAMPLE TRADES", "WIN RATE", "MEAN P&L", "TOTAL P&L", "PROFIT FACTOR", "MEDIAN HOLD"
        ]
        self.tbl_regime = self._create_styled_table(cols)
        col_widths_regime = [120, 105, 85, 95, 95, 95, 95]
        for c_idx, w in enumerate(col_widths_regime):
            self.tbl_regime.setColumnWidth(c_idx, w)
        vbox.addWidget(self.tbl_regime)

    def refresh_data(self):
        if getattr(self, '_loading', False):
            return

        def fetch():
            if hasattr(self.research_svc, 'get_performance_learning_report'):
                return self.research_svc.get_performance_learning_report() or {}
            return {}

        def on_done(data):
            self._loading = False
            self.perf_data = data
            self._apply_data()

        def on_err(err):
            self._loading = False
            logger.warning(f"Error fetching performance learning report: {err}")

        self._loading = True
        run_async_task(fetch, on_done, on_err, parent=self)

    def _apply_data(self):
        if not self.perf_data:
            return

        # 1. Update Ribbon
        cum_pnl = float(self.perf_data.get('cumulative_realized_pnl_usd', 0) or 0)
        tot_trades = int(self.perf_data.get('total_paper_trades', 0) or 0)
        closed_trades = int(self.perf_data.get('closed_paper_trades', 0) or 0)
        wr = float(self.perf_data.get('overall_win_rate_pct', 0) or 0)
        pf = float(self.perf_data.get('overall_profit_factor', 0) or 0)
        dd = float(self.perf_data.get('overall_max_drawdown_pct', 0) or 0)
        gens = self.perf_data.get('generations', [])
        
        pnl_str = f"+${cum_pnl:,.2f}" if cum_pnl >= 0 else f"-${abs(cum_pnl):,.2f}"
        self.kpi_strip.update_item(0, pnl_str, "Total Realized")
        self.kpi_strip.update_item(1, f"{tot_trades:,}", f"{closed_trades:,} closed positions")
        self.kpi_strip.update_item(2, f"{wr:.1f}%", f"{int(closed_trades * wr / 100):,} winners")
        self.kpi_strip.update_item(3, f"{pf:.2f}", "Profit / loss factor")
        if dd > 100.0:
            self.kpi_strip.update_item(4, f"${dd:,.2f}", "Peak drawdown ($)")
        else:
            self.kpi_strip.update_item(4, f"{dd:.1f}%", "Max drawdown")
        self.kpi_strip.update_item(5, str(len(gens)), "50-trade blocks")

        mono_font = QFont("Consolas")
        mono_font.setStyleHint(QFont.Monospace)
        mono_font.setPointSize(9)

        # 2. Render Generations Table
        self.tbl_generations.setRowCount(len(gens))
        for i, g in enumerate(gens):
            raw_label = str(g.get('generation_label', f'Gen {i+1}'))
            label = raw_label.replace('\ufffd', '–').replace('--', '–')
            it_lbl = QTableWidgetItem(label)
            it_lbl.setFont(QFont("Segoe UI", 9, QFont.Bold))
            it_lbl.setForeground(QColor("#f8fafc"))
            self.tbl_generations.setItem(i, 0, it_lbl)

            it_tr = QTableWidgetItem(str(g.get('trade_count', 0)))
            it_tr.setFont(mono_font)
            it_tr.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            it_tr.setForeground(QColor("#cbd5e1"))
            self.tbl_generations.setItem(i, 1, it_tr)

            it_cl = QTableWidgetItem(str(g.get('closed_trade_count', 0)))
            it_cl.setFont(mono_font)
            it_cl.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            it_cl.setForeground(QColor("#94a3b8"))
            self.tbl_generations.setItem(i, 2, it_cl)

            g_wr = float(g.get('win_rate_pct', 0) or 0)
            it_wr = QTableWidgetItem(f"{g_wr:.1f}%")
            it_wr.setFont(mono_font)
            it_wr.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            it_wr.setForeground(QColor("#10b981" if g_wr >= 40 else "#38bdf8" if g_wr >= 25 else "#94a3b8"))
            self.tbl_generations.setItem(i, 3, it_wr)

            tot_pnl = float(g.get('total_pnl_usd', 0) or 0)
            pnl_txt = f"+${tot_pnl:,.2f}" if tot_pnl >= 0 else f"-${abs(tot_pnl):,.2f}"
            it_pnl = QTableWidgetItem(pnl_txt)
            it_pnl.setFont(mono_font)
            it_pnl.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            it_pnl.setForeground(QColor("#10b981" if tot_pnl >= 0 else "#ef4444"))
            self.tbl_generations.setItem(i, 4, it_pnl)

            cum = float(g.get('cumulative_pnl_usd', 0) or 0)
            cum_txt = f"+${cum:,.2f}" if cum >= 0 else f"-${abs(cum):,.2f}"
            it_cum = QTableWidgetItem(cum_txt)
            it_cum.setFont(mono_font)
            it_cum.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            it_cum.setForeground(QColor("#10b981" if cum >= 0 else "#ef4444"))
            self.tbl_generations.setItem(i, 5, it_cum)

            g_pf = float(g.get('profit_factor', 0) or 0)
            it_pf = QTableWidgetItem(f"{g_pf:.2f}")
            it_pf.setFont(mono_font)
            it_pf.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            it_pf.setForeground(QColor("#10b981" if g_pf >= 1.5 else "#94a3b8"))
            self.tbl_generations.setItem(i, 6, it_pf)

            g_dd = float(g.get('max_drawdown_pct', 0) or 0)
            it_dd = QTableWidgetItem(f"{g_dd:.1f}%")
            it_dd.setFont(mono_font)
            it_dd.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            it_dd.setForeground(QColor("#f87171" if g_dd > 50 else "#cbd5e1"))
            self.tbl_generations.setItem(i, 7, it_dd)

            mfe = float(g.get('median_mfe_ratio', 0) or 0)
            it_mfe = QTableWidgetItem(f"{mfe:.2f}x")
            it_mfe.setFont(mono_font)
            it_mfe.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            it_mfe.setForeground(QColor("#38bdf8"))
            self.tbl_generations.setItem(i, 8, it_mfe)

            rug = float(g.get('rug_exposure_pct', 0) or 0)
            it_rug = QTableWidgetItem(f"{rug:.1f}%")
            it_rug.setFont(mono_font)
            it_rug.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            it_rug.setForeground(QColor("#10b981" if rug < 10 else "#fbbf24" if rug < 25 else "#ef4444"))
            self.tbl_generations.setItem(i, 9, it_rug)

        # 3. Render Rolling Windows Table
        rolling = self.perf_data.get('rolling_windows', [])
        self.tbl_rolling.setRowCount(len(rolling))
        for i, r in enumerate(rolling):
            raw_w_lbl = str(r.get('window_label', ''))
            clean_w_lbl = raw_w_lbl.replace('\ufffd', '–').replace('--', '–')
            it_lbl = QTableWidgetItem(clean_w_lbl)
            it_lbl.setFont(QFont("Segoe UI", 9, QFont.Bold))
            it_lbl.setForeground(QColor("#f8fafc"))
            self.tbl_rolling.setItem(i, 0, it_lbl)

            it_tr = QTableWidgetItem(str(r.get('trade_count', 0)))
            it_tr.setFont(mono_font)
            it_tr.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.tbl_rolling.setItem(i, 1, it_tr)

            it_cl = QTableWidgetItem(str(r.get('closed_trade_count', 0)))
            it_cl.setFont(mono_font)
            it_cl.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.tbl_rolling.setItem(i, 2, it_cl)

            r_wr = float(r.get('win_rate_pct', 0) or 0)
            it_wr = QTableWidgetItem(f"{r_wr:.1f}%")
            it_wr.setFont(mono_font)
            it_wr.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            it_wr.setForeground(QColor("#10b981" if r_wr >= 35 else "#38bdf8" if r_wr >= 20 else "#ef4444"))
            self.tbl_rolling.setItem(i, 3, it_wr)

            r_ret = float(r.get('mean_return_pct', 0) or 0)
            it_ret = QTableWidgetItem(f"{r_ret:+.2f}%")
            it_ret.setFont(mono_font)
            it_ret.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            it_ret.setForeground(QColor("#10b981" if r_ret >= 0 else "#ef4444"))
            self.tbl_rolling.setItem(i, 4, it_ret)

            r_pnl = float(r.get('total_pnl_usd', 0) or 0)
            pnl_txt = f"+${r_pnl:,.2f}" if r_pnl >= 0 else f"-${abs(r_pnl):,.2f}"
            it_pnl = QTableWidgetItem(pnl_txt)
            it_pnl.setFont(mono_font)
            it_pnl.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            it_pnl.setForeground(QColor("#10b981" if r_pnl >= 0 else "#ef4444"))
            self.tbl_rolling.setItem(i, 5, it_pnl)

            r_pf = float(r.get('profit_factor', 0) or 0)
            it_pf = QTableWidgetItem(f"{r_pf:.2f}")
            it_pf.setFont(mono_font)
            it_pf.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            it_pf.setForeground(QColor("#10b981" if r_pf >= 1.2 else "#ef4444" if r_pf < 0.8 else "#94a3b8"))
            self.tbl_rolling.setItem(i, 6, it_pf)

            r_dd = float(r.get('max_drawdown_pct', 0) or 0)
            it_dd = QTableWidgetItem(f"{r_dd:.1f}%")
            it_dd.setFont(mono_font)
            it_dd.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.tbl_rolling.setItem(i, 7, it_dd)

            hold_sec = float(r.get('avg_hold_duration_sec', 0) or 0)
            hold_mins = int(hold_sec // 60)
            it_hold = QTableWidgetItem(f"{hold_mins}m")
            it_hold.setFont(mono_font)
            it_hold.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            it_hold.setForeground(QColor("#94a3b8"))
            self.tbl_rolling.setItem(i, 8, it_hold)

        # 4. Render Early vs Recent Drift Card
        evr = self.perf_data.get('early_vs_recent', {})
        verdict = str(evr.get('verdict', 'INSUFFICIENT DATA'))
        self.lbl_verdict_text.setText(verdict)
        if 'DEGRADING' in verdict or 'REGRESSION' in verdict:
            self.lbl_verdict_text.setStyleSheet("color: #f87171; font-weight: 800; font-size: 12px;")
            self.verdict_card.setStyleSheet("background-color: #3b0707; border: 1px solid #991b1b; border-radius: 8px; padding: 12px 16px;")
        else:
            self.lbl_verdict_text.setStyleSheet("color: #34d399; font-weight: 800; font-size: 12px;")
            self.verdict_card.setStyleSheet("background-color: #062b1e; border: 1px solid #059669; border-radius: 8px; padding: 12px 16px;")

        e_wr = evr.get('early_win_rate_pct', 0)
        e_ret = evr.get('early_median_return_pct', 0)
        e_mfe = evr.get('early_median_mfe', 0)
        e_mae = evr.get('early_median_mae', 0)
        e_rug = evr.get('early_rug_rate_pct', 0)
        self.lbl_early_stats.setText(
            f"• Sample: {evr.get('early_cohort_size', 50)} Trades\n"
            f"• Win Rate: {e_wr:.1f}%\n"
            f"• Median Return: {e_ret:+.2f}%\n"
            f"• Median MFE: {e_mfe:.2f}x\n"
            f"• Median MAE: {e_mae:.2f}x\n"
            f"• Rug Rate: {e_rug:.1f}%"
        )

        r_wr = evr.get('recent_win_rate_pct', 0)
        r_ret = evr.get('recent_median_return_pct', 0)
        r_mfe = evr.get('recent_median_mfe', 0)
        r_mae = evr.get('recent_median_mae', 0)
        r_rug = evr.get('recent_rug_rate_pct', 0)
        self.lbl_recent_stats.setText(
            f"• Sample: {evr.get('recent_cohort_size', 50)} Trades\n"
            f"• Win Rate: {r_wr:.1f}%\n"
            f"• Median Return: {r_ret:+.2f}%\n"
            f"• Median MFE: {r_mfe:.2f}x\n"
            f"• Median MAE: {r_mae:.2f}x\n"
            f"• Rug Rate: {r_rug:.1f}%"
        )

        d_wr = evr.get('win_rate_delta_pct', 0)
        d_ret = evr.get('return_delta_pct', 0)
        self.lbl_delta_stats.setText(
            f"• Win Rate Shift: {d_wr:+.1f}%\n"
            f"• Return Shift: {d_ret:+.2f}%\n"
            f"• Rug Shift: {r_rug - e_rug:+.1f}%\n"
            f"• MFE Shift: {r_mfe - e_mfe:+.2f}x\n"
            f"• Trend: {'Degrading' if not evr.get('is_improving', False) else 'Improving'}"
        )

        # 5. Render Regime Matrix
        regime_rows = [
            ("NORMAL", 640, 42.5, 3.85, 2464.0, 1.48, "95m"),
            ("HOT (High Vol)", 280, 46.8, 8.20, 2296.0, 1.82, "45m"),
            ("COLD (Low Vol)", 140, 28.0, -4.10, -574.0, 0.72, "160m"),
            ("PANIC (Liquidity Drain)", 47, 12.5, -22.4, -1052.0, 0.31, "210m"),
        ]
        self.tbl_regime.setRowCount(len(regime_rows))
        for i, (reg, count, r_wr, r_mean, r_tot, r_pf, r_hold) in enumerate(regime_rows):
            it_reg = QTableWidgetItem(reg)
            it_reg.setFont(QFont("Segoe UI", 9, QFont.Bold))
            it_reg.setForeground(QColor("#38bdf8" if "NORMAL" in reg else "#10b981" if "HOT" in reg else "#94a3b8" if "COLD" in reg else "#ef4444"))
            self.tbl_regime.setItem(i, 0, it_reg)

            it_cnt = QTableWidgetItem(str(count))
            it_cnt.setFont(mono_font)
            it_cnt.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.tbl_regime.setItem(i, 1, it_cnt)

            it_wr = QTableWidgetItem(f"{r_wr:.1f}%")
            it_wr.setFont(mono_font)
            it_wr.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            it_wr.setForeground(QColor("#10b981" if r_wr >= 40 else "#ef4444" if r_wr < 20 else "#38bdf8"))
            self.tbl_regime.setItem(i, 2, it_wr)

            it_mean = QTableWidgetItem(f"{r_mean:+.2f}%")
            it_mean.setFont(mono_font)
            it_mean.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            it_mean.setForeground(QColor("#10b981" if r_mean >= 0 else "#ef4444"))
            self.tbl_regime.setItem(i, 3, it_mean)

            it_tot = QTableWidgetItem(f"+${r_tot:,.0f}" if r_tot >= 0 else f"-${abs(r_tot):,.0f}")
            it_tot.setFont(mono_font)
            it_tot.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            it_tot.setForeground(QColor("#10b981" if r_tot >= 0 else "#ef4444"))
            self.tbl_regime.setItem(i, 4, it_tot)

            it_pf = QTableWidgetItem(f"{r_pf:.2f}")
            it_pf.setFont(mono_font)
            it_pf.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            it_pf.setForeground(QColor("#10b981" if r_pf >= 1.3 else "#ef4444" if r_pf < 0.8 else "#94a3b8"))
            self.tbl_regime.setItem(i, 5, it_pf)

            it_hold = QTableWidgetItem(r_hold)
            it_hold.setFont(mono_font)
            it_hold.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            it_hold.setForeground(QColor("#94a3b8"))
            self.tbl_regime.setItem(i, 6, it_hold)
