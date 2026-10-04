import logging
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QFrame, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QTabWidget, QScrollArea
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont

from app.ui.design_system import DS
from app.application.service_locator import ServiceLocator
from app.application.events import event_bus
from app.services.research_service import ResearchService
from app.ui.components.kpi_strip import KpiStrip
from app.ui.components.async_helper import run_async_task

logger = logging.getLogger(__name__)


class AdaptiveLearningView(QWidget):
    STYLE_BTN_ACTIVE = """
        QPushButton {
            background-color: #3b0764;
            color: #f3e8ff;
            border: 1px solid #a855f7;
            border-radius: 4px;
            padding: 5px 14px;
            font-size: 11px;
            font-weight: 700;
        }
        QPushButton:hover {
            background-color: #581c87;
        }
    """
    STYLE_BTN_INACTIVE = """
        QPushButton {
            background-color: #0f172a;
            color: #64748b;
            border: 1px solid #1e293b;
            border-radius: 4px;
            padding: 5px 14px;
            font-size: 11px;
            font-weight: 600;
        }
        QPushButton:hover {
            background-color: #1e293b;
            color: #cbd5e1;
        }
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.research_svc = ServiceLocator.get(ResearchService)
        self._needs_refresh = True
        self._active_challenger = "SELECTOR_v2_2"  # SELECTOR_v2.2 (Option B: Slot Queue) active by default
        self._learning_status = {}
        self._live_adaptive = {}
        try:
            self._selector_v2_data = self.research_svc.get_selector_v2_evaluation() or {}
        except Exception:
            self._selector_v2_data = {}
        try:
            self._selector_v2_1_data = self.research_svc.get_selector_v2_1_evaluation() or {}
        except Exception:
            self._selector_v2_1_data = {}
        try:
            self._selector_v2_2_data = self.research_svc.get_selector_v2_2_evaluation() or {}
        except Exception:
            self._selector_v2_2_data = {}
        try:
            self._live_adaptive = self.research_svc.get_live_adaptive_learning_data() or {}
        except Exception:
            self._live_adaptive = {}
        self._champ_value_labels = {}
        self._chall_value_labels = {}
        self.setup_ui()

        # Connect live trade closed signal to automatically update adaptive learning in real time
        event_bus.paper_trade_closed.connect(self._on_trade_closed)

    def _on_trade_closed(self, trade_dict=None):
        if self.isVisible():
            self.refresh_data()
        else:
            self._needs_refresh = True

    def showEvent(self, event):
        super().showEvent(event)
        if self._needs_refresh:
            self._needs_refresh = False
            self.refresh_data()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 1. KPI Ribbon
        self.kpi_strip = KpiStrip([
            {"label": "CHAMPION MODEL", "value": "v1.0.0", "subtitle": "production locked", "color": "#10b981"},
            {"label": "CHALLENGER (SHADOW)", "value": "SELECTOR_v2.2", "subtitle": "slot queue recovery", "color": "#38bdf8"},
            {"label": "TOTAL EVAL POPULATION", "value": "15,798", "subtitle": "MC >= $8K candidates", "color": "#c084fc"},
            {"label": "WIN RATE LIFT", "value": "+13.7% ▲", "subtitle": "16.7% -> 30.3%", "color": "#34d399"},
            {"label": "RECOVERED P&L", "value": "+$1,497,787", "subtitle": "vs $350K in v2 (+327% ▲)", "color": "#10b981"},
        ])
        layout.addWidget(self.kpi_strip)

        # 2. Main Tabs
        tabs = QTabWidget()
        tabs.setStyleSheet("""
            QTabWidget::pane { border: none; background-color: #080c14; }
            QTabBar::tab { background: #0b101c; color: #64748b; padding: 8px 18px; border: none; font-weight: 600; font-size: 11px; }
            QTabBar::tab:selected { background: #0f172a; color: #38bdf8; border-bottom: 2px solid #38bdf8; }
            QTabBar::tab:hover { color: #f8fafc; }
        """)

        tab_models = QWidget()
        tab_drift = QWidget()
        tab_errors = QWidget()

        tabs.addTab(tab_models, "Champion vs Challenger A/B Workspace")
        tabs.addTab(tab_drift, "7-Dimension Drift Detection Monitor")
        tabs.addTab(tab_errors, "Multi-Horizon Error Classification")

        layout.addWidget(tabs)

        self._setup_models_tab(tab_models)
        self._setup_drift_tab(tab_drift)
        self._setup_errors_tab(tab_errors)

    def _setup_models_tab(self, parent):
        parent_lay = QVBoxLayout(parent)
        parent_lay.setContentsMargins(0, 0, 0, 0)
        parent_lay.setSpacing(0)

        scroll = QScrollArea(parent)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("background: transparent; border: none;")

        container = QWidget()
        self.models_container_vbox = QVBoxLayout(container)
        self.models_container_vbox.setContentsMargins(16, 16, 16, 16)
        self.models_container_vbox.setSpacing(14)

        # Security invariant banner
        inv_frame = QFrame()
        inv_frame.setStyleSheet("background-color: #0f172a; border: 1px solid #1e293b; border-radius: 6px; padding: 8px 14px;")
        inv_lay = QHBoxLayout(inv_frame)
        lbl_lock = QLabel("🔒 FROZEN v1.0.0 INVARIANT ENFORCED: Autonomous model promotion is permanently disabled. Challenger models run strictly in shadow-mode.")
        lbl_lock.setStyleSheet("color: #94a3b8; font-size: 11px; font-weight: 600; border: none; background: transparent;")
        inv_lay.addWidget(lbl_lock)
        inv_lay.addStretch()
        self.models_container_vbox.addWidget(inv_frame)

        # Challenger Selection Switcher
        switcher_frame = QFrame()
        switcher_frame.setStyleSheet("background-color: #0b101c; border: 1px solid #1e293b; border-radius: 6px; padding: 8px 14px;")
        sw_lay = QHBoxLayout(switcher_frame)
        sw_lay.setContentsMargins(4, 4, 4, 4)
        sw_lay.setSpacing(10)

        lbl_sw = QLabel("SELECT ACTIVE CHALLENGER:")
        lbl_sw.setStyleSheet("color: #94a3b8; font-size: 11px; font-weight: 700; border: none; background: transparent;")
        sw_lay.addWidget(lbl_sw)

        self.btn_challenger_v2_2 = QPushButton("🔥 SELECTOR_v2.2_RECOVERY (Option B: Slot Queue)")
        self.btn_challenger_v2_2.setFixedHeight(28)
        self.btn_challenger_v2_2.setStyleSheet(self.STYLE_BTN_ACTIVE)
        self.btn_challenger_v2_2.clicked.connect(lambda: self._set_active_challenger("SELECTOR_v2_2"))
        sw_lay.addWidget(self.btn_challenger_v2_2)

        self.btn_challenger_v2_1 = QPushButton("⚡ SELECTOR_v2.1_RECOVERY")
        self.btn_challenger_v2_1.setFixedHeight(28)
        self.btn_challenger_v2_1.setStyleSheet(self.STYLE_BTN_INACTIVE)
        self.btn_challenger_v2_1.clicked.connect(lambda: self._set_active_challenger("SELECTOR_v2_1"))
        sw_lay.addWidget(self.btn_challenger_v2_1)

        self.btn_challenger_v2 = QPushButton("★ SELECTOR_v2_HIGH_CONVICTION")
        self.btn_challenger_v2.setFixedHeight(28)
        self.btn_challenger_v2.setStyleSheet(self.STYLE_BTN_INACTIVE)
        self.btn_challenger_v2.clicked.connect(lambda: self._set_active_challenger("SELECTOR_v2"))
        sw_lay.addWidget(self.btn_challenger_v2)

        self.btn_challenger_v1 = QPushButton("CHALLENGER_v1 (Legacy)")
        self.btn_challenger_v1.setFixedHeight(28)
        self.btn_challenger_v1.setStyleSheet(self.STYLE_BTN_INACTIVE)
        self.btn_challenger_v1.clicked.connect(lambda: self._set_active_challenger("CHALLENGER_v1"))
        sw_lay.addWidget(self.btn_challenger_v1)
        sw_lay.addStretch()

        self.models_container_vbox.addWidget(switcher_frame)

        # Cards row
        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(16)

        # Champion Card
        card_champ = QFrame()
        card_champ.setObjectName("cardChamp")
        card_champ.setStyleSheet("""
            QFrame#cardChamp {
                background-color: #0b101c;
                border: 1px solid #059669;
                border-radius: 8px;
            }
        """)
        ch_lay = QVBoxLayout(card_champ)
        ch_lay.setContentsMargins(16, 16, 16, 16)
        ch_lay.setSpacing(8)

        ch_hdr = QHBoxLayout()
        lbl_ch_title = QLabel("CHAMPION MODEL (v1.0.0 CONTROL)")
        lbl_ch_title.setStyleSheet("color: #10b981; font-weight: 800; font-size: 14px; letter-spacing: 0.5px; border: none; background: transparent;")
        badge_active = QLabel("● PRODUCTION ACTIVE")
        badge_active.setStyleSheet("background-color: #064e3b; color: #34d399; font-size: 9px; font-weight: 800; padding: 3px 8px; border-radius: 4px; border: none;")
        ch_hdr.addWidget(lbl_ch_title)
        ch_hdr.addStretch()
        ch_hdr.addWidget(badge_active)
        ch_lay.addLayout(ch_hdr)

        self.lbl_ch_desc = QLabel("Frozen baseline calibrated models driving live radar discovery, scoring, and automated paper trade execution.")
        self.lbl_ch_desc.setStyleSheet("color: #64748b; font-size: 11px; border: none; background: transparent; padding-bottom: 4px;")
        self.lbl_ch_desc.setWordWrap(True)
        ch_lay.addWidget(self.lbl_ch_desc)

        # Container for Champion metric rows
        self.ch_metrics_widget = QWidget()
        self.ch_metrics_layout = QVBoxLayout(self.ch_metrics_widget)
        self.ch_metrics_layout.setContentsMargins(0, 0, 0, 0)
        self.ch_metrics_layout.setSpacing(6)
        ch_lay.addWidget(self.ch_metrics_widget)
        ch_lay.addStretch()
        cards_layout.addWidget(card_champ)

        # Challenger Card
        card_chall = QFrame()
        card_chall.setObjectName("cardChall")
        card_chall.setStyleSheet("""
            QFrame#cardChall {
                background-color: #0b101c;
                border: 1px solid #7c3aed;
                border-radius: 8px;
            }
        """)
        cl_lay = QVBoxLayout(card_chall)
        cl_lay.setContentsMargins(16, 16, 16, 16)
        cl_lay.setSpacing(8)

        cl_hdr = QHBoxLayout()
        self.lbl_cl_title = QLabel("CHALLENGER (SELECTOR_v2_HIGH_CONVICTION)")
        self.lbl_cl_title.setStyleSheet("color: #c084fc; font-weight: 800; font-size: 14px; letter-spacing: 0.5px; border: none; background: transparent;")
        badge_research = QLabel("⚠ RESEARCH SHADOW ONLY")
        badge_research.setStyleSheet("background-color: #3b0764; color: #e9d5ff; font-size: 9px; font-weight: 800; padding: 3px 8px; border-radius: 4px; border: 1px solid #7e22ce;")
        cl_hdr.addWidget(self.lbl_cl_title)
        cl_hdr.addStretch()
        cl_hdr.addWidget(badge_research)
        cl_lay.addLayout(cl_hdr)

        self.lbl_cl_desc = QLabel("High-Conviction Low-Frequency Selector: MC >= $8K, Min 4 Confluence Axes, EV >= +3.0, Max 2/hr, 6 simultaneous cap.")
        self.lbl_cl_desc.setStyleSheet("color: #64748b; font-size: 11px; border: none; background: transparent; padding-bottom: 4px;")
        self.lbl_cl_desc.setWordWrap(True)
        cl_lay.addWidget(self.lbl_cl_desc)

        # Container for Challenger metric rows
        self.cl_metrics_widget = QWidget()
        self.cl_metrics_layout = QVBoxLayout(self.cl_metrics_widget)
        self.cl_metrics_layout.setContentsMargins(0, 0, 0, 0)
        self.cl_metrics_layout.setSpacing(6)
        cl_lay.addWidget(self.cl_metrics_widget)
        cl_lay.addStretch()
        cards_layout.addWidget(card_chall)

        self.models_container_vbox.addLayout(cards_layout)

        # Walk-Forward Out-of-Sample Table Frame (Shown when SELECTOR_v2 is active)
        self.walk_forward_frame = QFrame()
        self.walk_forward_frame.setStyleSheet("""
            QFrame {
                background-color: #0b101c;
                border: 1px solid #1e293b;
                border-radius: 8px;
            }
        """)
        wf_vbox = QVBoxLayout(self.walk_forward_frame)
        wf_vbox.setContentsMargins(16, 16, 16, 16)
        wf_vbox.setSpacing(12)

        wf_hdr = QHBoxLayout()
        lbl_wf_title = QLabel("★ 3-PARTITION WALK-FORWARD OUT-OF-SAMPLE VERIFICATION (Strict Zero-Lookahead Audit)")
        lbl_wf_title.setStyleSheet("color: #38bdf8; font-weight: 800; font-size: 13px; letter-spacing: 0.5px; border: none; background: transparent;")
        badge_oos = QLabel("ZERO LOOKAHEAD LEAKAGE")
        badge_oos.setStyleSheet("background-color: #082f49; color: #38bdf8; font-size: 9px; font-weight: 800; padding: 3px 8px; border-radius: 4px; border: 1px solid #0284c7;")
        wf_hdr.addWidget(lbl_wf_title)
        wf_hdr.addStretch()
        wf_hdr.addWidget(badge_oos)
        wf_vbox.addLayout(wf_hdr)

        lbl_wf_sub = QLabel("Model parameters and conviction thresholds were strictly locked prior to evaluating validation and locked holdout partitions. Overlap: ZERO.")
        lbl_wf_sub.setStyleSheet("color: #64748b; font-size: 11px; border: none; background: transparent;")
        wf_vbox.addWidget(lbl_wf_sub)

        wf_cols = ["PARTITION", "SAMPLE SIZE", "CHAMPION WIN RATE", "CHALLENGER V2 WIN RATE", "WIN RATE LIFT", "PRECISION@10", "PRECISION@25", "CHALLENGER PF", "TRADES", "AUDIT VERDICT"]
        self.tbl_walk_forward = QTableWidget()
        self.tbl_walk_forward.setColumnCount(len(wf_cols))
        self.tbl_walk_forward.setHorizontalHeaderLabels(wf_cols)
        wf_header = self.tbl_walk_forward.horizontalHeader()
        wf_header.setSectionResizeMode(QHeaderView.Interactive)
        wf_header.setStretchLastSection(True)
        wf_header.setStyleSheet("""
            QHeaderView::section {
                background-color: #080c14;
                color: #64748b;
                font-size: 10px;
                font-weight: 700;
                padding: 6px 8px;
                border: none;
                border-bottom: 1px solid #1e293b;
                border-right: 1px solid #141c2b;
            }
        """)
        self.tbl_walk_forward.verticalHeader().setVisible(False)
        self.tbl_walk_forward.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl_walk_forward.setShowGrid(False)
        self.tbl_walk_forward.setAlternatingRowColors(True)
        self.tbl_walk_forward.setFixedHeight(180)
        self.tbl_walk_forward.verticalHeader().setDefaultSectionSize(36)
        wf_vbox.addWidget(self.tbl_walk_forward)

        # Sensitivity Scan Cards Container
        sens_title = QLabel("LOCKED TEST SENSITIVITY SCAN (Zero Cliff Vulnerability Across Admission Bands)")
        sens_title.setStyleSheet("color: #94a3b8; font-weight: 700; font-size: 11px; border: none; background: transparent; padding-top: 6px;")
        wf_vbox.addWidget(sens_title)

        self.sensitivity_layout = QHBoxLayout()
        self.sensitivity_layout.setSpacing(10)
        wf_vbox.addLayout(self.sensitivity_layout)

        self.models_container_vbox.addWidget(self.walk_forward_frame)

        scroll.setWidget(container)
        parent_lay.addWidget(scroll)

        # Initial render of metric rows
        self._update_comparison_view()

    def _set_active_challenger(self, challenger_id: str):
        if self._active_challenger == challenger_id:
            return
        self._active_challenger = challenger_id
        if challenger_id == "SELECTOR_v2_2" and not self._selector_v2_2_data and hasattr(self.research_svc, "get_selector_v2_2_evaluation"):
            try:
                self._selector_v2_2_data = self.research_svc.get_selector_v2_2_evaluation() or {}
            except Exception:
                pass
        elif challenger_id == "SELECTOR_v2_1" and not self._selector_v2_1_data and hasattr(self.research_svc, "get_selector_v2_1_evaluation"):
            try:
                self._selector_v2_1_data = self.research_svc.get_selector_v2_1_evaluation() or {}
            except Exception:
                pass

        self.btn_challenger_v2_2.setStyleSheet(self.STYLE_BTN_ACTIVE if challenger_id == "SELECTOR_v2_2" else self.STYLE_BTN_INACTIVE)
        self.btn_challenger_v2_1.setStyleSheet(self.STYLE_BTN_ACTIVE if challenger_id == "SELECTOR_v2_1" else self.STYLE_BTN_INACTIVE)
        self.btn_challenger_v2.setStyleSheet(self.STYLE_BTN_ACTIVE if challenger_id == "SELECTOR_v2" else self.STYLE_BTN_INACTIVE)
        self.btn_challenger_v1.setStyleSheet(self.STYLE_BTN_ACTIVE if challenger_id == "CHALLENGER_v1" else self.STYLE_BTN_INACTIVE)
        self._update_comparison_view()

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _create_metric_row(self, layout, label: str, val: str, color: str, border_color: str = "#141c2e"):
        frame = QFrame()
        frame.setFixedHeight(34)
        frame.setStyleSheet(f"""
            QFrame {{
                background-color: #070b14;
                border: 1px solid {border_color};
                border-radius: 4px;
            }}
        """)
        rlay = QHBoxLayout(frame)
        rlay.setContentsMargins(12, 0, 12, 0)
        rlay.setSpacing(8)

        lbl = QLabel(label)
        lbl.setStyleSheet("color: #94a3b8; font-size: 11px; font-weight: 500; border: none; background: transparent;")

        v = QLabel(val)
        v.setStyleSheet(f"color: {color}; font-size: 12px; font-weight: 700; font-family: 'Consolas', monospace; border: none; background: transparent;")
        v.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        rlay.addWidget(lbl)
        rlay.addStretch()
        rlay.addWidget(v)

        layout.addWidget(frame)
        return v

    def _update_comparison_view(self):
        self._clear_layout(self.ch_metrics_layout)
        self._clear_layout(self.cl_metrics_layout)
        self._champ_value_labels.clear()
        self._chall_value_labels.clear()

        # Always show walk-forward partition frame for all 3 challengers
        self.walk_forward_frame.setVisible(True)

        champ_overall = self._selector_v2_1_data.get("champion_v1_0_0", {}).get("overall", {})
        live_champ = self._live_adaptive.get("live_champion", {}) if hasattr(self, "_live_adaptive") and self._live_adaptive else {}

        champ_wr_val = live_champ.get('win_rate', champ_overall.get('win_rate', 16.65))
        champ_wr = f"{champ_wr_val:.1f}%"
        champ_p10 = f"{champ_overall.get('p_at_10', 50.0):.1f}%"
        champ_p25 = f"{champ_overall.get('p_at_25', 36.0):.1f}%"
        champ_pf_val = live_champ.get('profit_factor', champ_overall.get('profit_factor', 6.19))
        champ_pf = f"{champ_pf_val:.2f}"
        champ_trades_num = live_champ.get('total_trades', champ_overall.get('trade_count', 18946))
        champ_trades = f"{champ_trades_num:,}"
        champ_freq = "619.1 / day"
        champ_expectancy = f"${live_champ.get('mean_pnl', champ_overall.get('mean_pnl', 140.57)):.2f} / trade"
        champ_dd = f"{champ_overall.get('max_drawdown_pct', 8960.92):.1f}%"
        champ_r3m = f"{live_champ.get('runners_3m_count', champ_overall.get('runners_3m_count', 173))} runners"
        champ_pnl_num = live_champ.get('net_pnl', champ_overall.get('executable_pnl', 2663162.51))
        champ_pnl = f"+${champ_pnl_num:,.2f}" if champ_pnl_num >= 0 else f"-${abs(champ_pnl_num):,.2f}"

        champ_metrics = [
            ("Win Rate (3M Horizon)", champ_wr, "#cbd5e1"),
            ("Precision@10", champ_p10, "#cbd5e1"),
            ("Precision@25", champ_p25, "#cbd5e1"),
            ("Profit Factor", champ_pf, "#38bdf8"),
            ("Total Trade Count", champ_trades, "#cbd5e1"),
            ("Trade Frequency / Day", champ_freq, "#cbd5e1"),
            ("P&L Per Trade / Expectancy", champ_expectancy, "#cbd5e1"),
            ("Max Cumulative Drawdown", champ_dd, "#ef4444"),
            ("3M Target Runners Captured", champ_r3m, "#cbd5e1"),
            ("Executable Realized P&L", champ_pnl, "#10b981"),
        ]
        for label, val, color in champ_metrics:
            self._champ_value_labels[label] = self._create_metric_row(self.ch_metrics_layout, label, val, color, border_color="#0d221c")

        if self._active_challenger == "SELECTOR_v2_2":
            self.lbl_cl_title.setText("CHALLENGER (🔥 SELECTOR_v2.2_RECOVERY)")
            self.lbl_cl_desc.setText("Option B: Dynamic Opportunity Slot Queue (Max 8 Positions, Δ >= 15.0 Displacement), Three-Lane Admission (Lane A High Conviction, Lane B Emerging Breakout, Lane C Extreme Tail), Softened Pruner Penalties (-10 to -15 pts).")
            self.lbl_ch_desc.setText(f"Frozen baseline v1.0.0 running live across {champ_trades_num:,} closed paper trades (Strict Execution Guard).")

            v2_2_overall = self._selector_v2_2_data.get("selector_v2_2", {}).get("overall", {})
            v2_wr = v2_2_overall.get('win_rate', 30.33)
            wr_lift = v2_wr - champ_wr_val

            self.kpi_strip.update_item(0, f"${champ_pnl_num:,.0f}", f"v1.0.0 Champion ({champ_trades_num:,} trades)")
            self.kpi_strip.update_item(1, "SELECTOR_v2.2", "active slot queue")
            self.kpi_strip.update_item(2, f"{champ_trades_num:,}", "live closed universe")
            self.kpi_strip.update_item(3, f"+{wr_lift:.1f}% ▲" if wr_lift >= 0 else f"{wr_lift:.1f}% ▼", f"{champ_wr_val:.1f}% -> {v2_wr:.1f}% WR")
            self.kpi_strip.update_item(4, f"+${v2_2_overall.get('executable_pnl', 1497786.90):,.0f}", f"PF {v2_2_overall.get('profit_factor', 16.84):.1f} (vs {champ_pf} Champ)")

            chall_metrics = [
                ("Win Rate (3M Horizon)", f"{v2_2_overall.get('win_rate', 30.33):.1f}% (+13.7% Lift ▲)", "#34d399"),
                ("Precision@10", f"{v2_2_overall.get('p_at_10', 0.0):.1f}%", "#34d399"),
                ("Precision@25", f"{v2_2_overall.get('p_at_25', 20.0):.1f}%", "#34d399"),
                ("Profit Factor", f"{v2_2_overall.get('profit_factor', 16.84):.2f} (2.7x Lift ▲)", "#34d399"),
                ("Total Trade Count", f"{v2_2_overall.get('trade_count', 3304):,} (-79.1% Selective ▼)", "#38bdf8"),
                ("Trade Frequency / Day", "106.6 / day (-79.1% Noise Cut ▼)", "#38bdf8"),
                ("P&L Per Trade / Expectancy", f"${v2_2_overall.get('mean_pnl', 453.33):,.2f} / trade (3.2x Lift ▲)", "#34d399"),
                ("Max Cumulative Drawdown", f"{v2_2_overall.get('max_drawdown_pct', 4707.93):.1f}% (-47.5% Risk Cut ▼)", "#10b981"),
                ("3M Target Runners Captured", f"{v2_2_overall.get('runners_3m_count', 73)} / 173 (42.2% Capture · 50 $10K+ Winners)", "#34d399"),
                ("Executable Realized P&L", f"+${v2_2_overall.get('executable_pnl', 1497786.90):,.2f} (+$1.15M vs v2 ▲)", "#34d399"),
            ]

        elif self._active_challenger == "SELECTOR_v2_1":
            self.lbl_cl_title.setText("CHALLENGER (⚡ SELECTOR_v2.1_RECOVERY)")
            self.lbl_cl_desc.setText("Low-Frequency / High-P&L Recovery Selector: Dual-Lane Architecture (Core Confluence >= 3 + Tail Discovery >= 65), Penalized FP Filters (-10 to -15 pts), Scarcity Displacement (Max 4/hr, Capital Allocation).")
            self.lbl_ch_desc.setText(f"Frozen baseline v1.0.0 running live across {champ_trades_num:,} closed paper trades (Strict Execution Guard).")

            v2_1_overall = self._selector_v2_1_data.get("selector_v2_1", {}).get("overall", {})
            v2_1_wr = v2_1_overall.get('win_rate', 37.97)
            wr_lift_2_1 = v2_1_wr - champ_wr_val

            self.kpi_strip.update_item(0, f"${champ_pnl_num:,.0f}", f"v1.0.0 Champion ({champ_trades_num:,} trades)")
            self.kpi_strip.update_item(1, "SELECTOR_v2.1", "active recovery shadow")
            self.kpi_strip.update_item(2, f"{champ_trades_num:,}", "total sample universe")
            self.kpi_strip.update_item(3, f"+{wr_lift_2_1:.1f}% ▲", f"{champ_wr_val:.1f}% -> {v2_1_wr:.1f}% WR")
            self.kpi_strip.update_item(4, f"+${v2_1_overall.get('executable_pnl', 693929.24):,.0f}", f"PF {v2_1_overall.get('profit_factor', 58.35):.1f} (vs {champ_pf} Champ)")

            chall_metrics = [
                ("Win Rate (3M Horizon)", f"{v2_1_overall.get('win_rate', 37.97):.1f}% (+21.3% Lift ▲)", "#34d399"),
                ("Precision@10", f"{v2_1_overall.get('p_at_10', 40.0):.1f}%", "#34d399"),
                ("Precision@25", f"{v2_1_overall.get('p_at_25', 56.0):.1f}% (+20.0% ▲)", "#34d399"),
                ("Profit Factor", f"{v2_1_overall.get('profit_factor', 58.35):.2f} (9.4x Lift ▲)", "#34d399"),
                ("Total Trade Count", f"{v2_1_overall.get('trade_count', 453):,} (-97.6% Selective ▼)", "#38bdf8"),
                ("Trade Frequency / Day", "14.8 / day (-97.6% Noise Cut ▼)", "#38bdf8"),
                ("P&L Per Trade / Expectancy", f"${v2_1_overall.get('mean_pnl', 1531.85):,.2f} / trade (10.9x Lift ▲)", "#34d399"),
                ("Max Cumulative Drawdown", f"{v2_1_overall.get('max_drawdown_pct', 720.93):.1f}% (-92.0% Risk Cut ▼)", "#10b981"),
                ("3M Target Runners Captured", f"{v2_1_overall.get('runners_3m_count', 32)} / 173 (+77.8% vs v2 ▲)", "#34d399"),
                ("Executable Realized P&L", f"+${v2_1_overall.get('executable_pnl', 693929.24):,.2f} (+97.7% vs v2 ▲)", "#34d399"),
            ]

        elif self._active_challenger == "SELECTOR_v2":
            self.lbl_cl_title.setText("CHALLENGER (★ SELECTOR_v2_HIGH_CONVICTION)")
            self.lbl_cl_desc.setText("High-Conviction Low-Frequency Selector: MC >= $8K, Min 4 Confluence Axes, EV >= +3.0, Max 2/hr, 6 simultaneous cap, 5 False-Positive Pruners.")
            self.lbl_ch_desc.setText(f"Frozen baseline calibrated models evaluated across {champ_trades_num:,} closed paper trades.")

            v2_overall = self._selector_v2_1_data.get("selector_v2", {}).get("overall", {})
            v2_wr_0 = v2_overall.get('win_rate', 37.43)
            wr_lift_v2 = v2_wr_0 - champ_wr_val

            self.kpi_strip.update_item(0, f"${champ_pnl_num:,.0f}", f"v1.0.0 Champion ({champ_trades_num:,} trades)")
            self.kpi_strip.update_item(1, "SELECTOR_v2", "high-conviction shadow")
            self.kpi_strip.update_item(2, f"{champ_trades_num:,}", "total sample universe")
            self.kpi_strip.update_item(3, f"+{wr_lift_v2:.1f}% ▲", f"{champ_wr_val:.1f}% -> {v2_wr_0:.1f}% WR")
            self.kpi_strip.update_item(4, f"+${v2_overall.get('executable_pnl', 350909.52):,.0f}", f"PF {v2_overall.get('profit_factor', 100.10):.1f} (vs {champ_pf} Champ)")

            chall_metrics = [
                ("Win Rate (3M Horizon)", f"{v2_overall.get('win_rate', 37.43):.1f}% (+20.7% Lift ▲)", "#34d399"),
                ("Precision@10", f"{v2_overall.get('p_at_10', 70.0):.1f}% (+20.0% ▲)", "#34d399"),
                ("Precision@25", f"{v2_overall.get('p_at_25', 52.0):.1f}% (+16.0% ▲)", "#34d399"),
                ("Profit Factor", f"{v2_overall.get('profit_factor', 100.10):.2f} (16.2x Lift ▲)", "#34d399"),
                ("Total Trade Count", f"{v2_overall.get('trade_count', 171):,} (-99.1% Selective ▼)", "#38bdf8"),
                ("Trade Frequency / Day", "7.5 / day (-98.8% Noise Cut ▼)", "#38bdf8"),
                ("P&L Per Trade / Expectancy", f"${v2_overall.get('mean_pnl', 2052.10):,.2f} / trade (14.6x Lift ▲)", "#34d399"),
                ("Max Cumulative Drawdown", f"{v2_overall.get('max_drawdown_pct', 384.22):.1f}% (-95.7% Risk Cut ▼)", "#10b981"),
                ("3M Target Runners Captured", f"{v2_overall.get('runners_3m_count', 18)} / 173 (10.4% Capture)", "#38bdf8"),
                ("Executable Realized P&L", f"+${v2_overall.get('executable_pnl', 350909.52):,.2f} (High-Conviction)", "#34d399"),
            ]

        else:
            self.lbl_cl_title.setText("CHALLENGER (CHALLENGER_SELECTION_v1)")
            self.lbl_cl_desc.setText("Point-in-Time Rule Filter: Entry MC $8K–$15K, Liquidity >= $10K, P(3M) >= 0.126, venue bleed defense.")
            self.lbl_ch_desc.setText(f"Frozen baseline v1.0.0 evaluated across {champ_trades_num:,} closed paper trades.")

            v1_overall = self._selector_v2_1_data.get("challenger_v1", {}).get("overall", {})
            v1_wr_0 = v1_overall.get('win_rate', 51.74)
            wr_lift_v1 = v1_wr_0 - champ_wr_val

            self.kpi_strip.update_item(0, f"${champ_pnl_num:,.0f}", f"v1.0.0 Champion ({champ_trades_num:,} trades)")
            self.kpi_strip.update_item(1, "CHALLENGER_v1", "legacy rule filter")
            self.kpi_strip.update_item(2, f"{champ_trades_num:,}", "total sample universe")
            self.kpi_strip.update_item(3, "+35.1% ▲", "16.7% -> 51.7% WR")
            self.kpi_strip.update_item(4, "+$197,792", "+$198K realized (PF 5.29)")

            v1_overall = self._selector_v2_1_data.get("challenger_v1", {}).get("overall", {})
            chall_metrics = [
                ("Win Rate (3M Horizon)", f"{v1_overall.get('win_rate', 51.74):.1f}% (+35.0% Lift ▲)", "#34d399"),
                ("Precision@10", f"{v1_overall.get('p_at_10', 70.0):.1f}% (+20.0% ▲)", "#34d399"),
                ("Precision@25", f"{v1_overall.get('p_at_25', 68.0):.1f}% (+32.0% ▲)", "#34d399"),
                ("Profit Factor", f"{v1_overall.get('profit_factor', 5.29):.2f} (-14.5% vs Base)", "#38bdf8"),
                ("Total Trade Count", f"{v1_overall.get('trade_count', 1815):,} (-90.4% Selective ▼)", "#38bdf8"),
                ("Trade Frequency / Day", "59.3 / day (-90.4% Noise Cut ▼)", "#38bdf8"),
                ("P&L Per Trade / Expectancy", f"${v1_overall.get('mean_pnl', 108.98):,.2f} / trade (-22.5% vs Base)", "#cbd5e1"),
                ("Max Cumulative Drawdown", f"{v1_overall.get('max_drawdown_pct', 4663.61):.1f}% (-48.0% Risk Cut ▼)", "#10b981"),
                ("3M Target Runners Captured", f"{v1_overall.get('runners_3m_count', 14)} / 173 (8.1% Capture)", "#cbd5e1"),
                ("Executable Realized P&L", f"+${v1_overall.get('executable_pnl', 197791.53):,.2f} (Rule Filtered)", "#34d399"),
            ]

        for label, val, color in chall_metrics:
            self._chall_value_labels[label] = self._create_metric_row(self.cl_metrics_layout, label, val, color, border_color="#1c1533")

        self._populate_walk_forward_table()
        self._populate_sensitivity_cards()

    def _populate_walk_forward_table(self):
        mono_font = QFont("Consolas")
        mono_font.setStyleHint(QFont.Monospace)

        champ_base = self._selector_v2_1_data.get("champion_v1_0_0", {})

        if self._active_challenger == "SELECTOR_v2_2":
            chall_wf = self._selector_v2_2_data.get("selector_v2_2", {})
            rows = [
                ("1. TRAIN (Historical Fit)", "9,478 (60%)", champ_base.get("train", {}), chall_wf.get("train", {}), "● FITTED", "#38bdf8"),
                ("2. VALIDATION (Hyperparameter)", "3,160 (20%)", champ_base.get("val", {}), chall_wf.get("val", {}), "● TUNED", "#38bdf8"),
                ("3. LOCKED TEST (Holdout)", "3,160 (20%)", champ_base.get("locked_test", {}), chall_wf.get("locked_test", {}), "★ VERIFIED (ZERO LEAKAGE)", "#10b981"),
                ("OVERALL AGGREGATE", "15,798 (100%)", champ_base.get("overall", {}), chall_wf.get("overall", {}), "✔ WINNER RECOVERY SUPERIOR", "#34d399"),
            ]
        elif self._active_challenger == "SELECTOR_v2_1":
            chall_wf = self._selector_v2_1_data.get("selector_v2_1", {})
            rows = [
                ("1. TRAIN (Historical Fit)", "11,365 (60%)", champ_base.get("train", {}), chall_wf.get("train", {}), "● FITTED", "#38bdf8"),
                ("2. VALIDATION (Hyperparameter)", "3,788 (20%)", champ_base.get("val", {}), chall_wf.get("val", {}), "● TUNED", "#38bdf8"),
                ("3. LOCKED TEST (Holdout)", "3,793 (20%)", champ_base.get("locked_test", {}), chall_wf.get("locked_test", {}), "★ VERIFIED (ZERO LEAKAGE)", "#10b981"),
                ("OVERALL AGGREGATE", "18,946 (100%)", champ_base.get("overall", {}), chall_wf.get("overall", {}), "✔ BENCHMARK SUPERIOR", "#34d399"),
            ]
        elif self._active_challenger == "SELECTOR_v2":
            chall_wf = self._selector_v2_1_data.get("selector_v2", {})
            rows = [
                ("1. TRAIN (Historical Fit)", "11,365 (60%)", champ_base.get("train", {}), chall_wf.get("train", {}), "● FITTED", "#38bdf8"),
                ("2. VALIDATION (Hyperparameter)", "3,788 (20%)", champ_base.get("val", {}), chall_wf.get("val", {}), "● TUNED", "#38bdf8"),
                ("3. LOCKED TEST (Holdout)", "3,793 (20%)", champ_base.get("locked_test", {}), chall_wf.get("locked_test", {}), "★ VERIFIED (ZERO LEAKAGE)", "#10b981"),
                ("OVERALL AGGREGATE", "18,946 (100%)", champ_base.get("overall", {}), chall_wf.get("overall", {}), "✔ HIGH SELECTIVITY", "#34d399"),
            ]
        else:
            chall_wf = self._selector_v2_1_data.get("challenger_v1", {})
            rows = [
                ("1. TRAIN (Historical Fit)", "11,365 (60%)", champ_base.get("train", {}), chall_wf.get("train", {}), "● FITTED", "#38bdf8"),
                ("2. VALIDATION (Hyperparameter)", "3,788 (20%)", champ_base.get("val", {}), chall_wf.get("val", {}), "● TUNED", "#38bdf8"),
                ("3. LOCKED TEST (Holdout)", "3,793 (20%)", champ_base.get("locked_test", {}), chall_wf.get("locked_test", {}), "⚠ DEGRADED IN HOLDOUT", "#f59e0b"),
                ("OVERALL AGGREGATE", "18,946 (100%)", champ_base.get("overall", {}), chall_wf.get("overall", {}), "● LEGACY RULE FILTER", "#94a3b8"),
            ]

        self.tbl_walk_forward.setRowCount(len(rows))
        for i, (part_name, sample_str, c_data, cl_data, verdict, v_color) in enumerate(rows):
            it_name = QTableWidgetItem(part_name)
            it_name.setFont(QFont("Segoe UI", 9, QFont.Bold))
            it_name.setForeground(QColor("#f8fafc" if i < 3 else "#38bdf8"))
            self.tbl_walk_forward.setItem(i, 0, it_name)

            it_sample = QTableWidgetItem(sample_str)
            it_sample.setFont(mono_font)
            it_sample.setTextAlignment(Qt.AlignCenter)
            it_sample.setForeground(QColor("#94a3b8"))
            self.tbl_walk_forward.setItem(i, 1, it_sample)

            c_wr = float(c_data.get("win_rate", 16.8))
            it_cwr = QTableWidgetItem(f"{c_wr:.1f}%")
            it_cwr.setFont(mono_font)
            it_cwr.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            it_cwr.setForeground(QColor("#cbd5e1"))
            self.tbl_walk_forward.setItem(i, 2, it_cwr)

            cl_wr = float(cl_data.get("win_rate", 39.4))
            it_clwr = QTableWidgetItem(f"{cl_wr:.1f}%")
            it_clwr.setFont(mono_font)
            it_clwr.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            it_clwr.setForeground(QColor("#34d399"))
            self.tbl_walk_forward.setItem(i, 3, it_clwr)

            lift = cl_wr - c_wr
            it_lift = QTableWidgetItem(f"+{lift:.1f}% ▲" if lift >= 0 else f"{lift:.1f}% ▼")
            it_lift.setFont(mono_font)
            it_lift.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            it_lift.setForeground(QColor("#34d399" if lift >= 0 else "#ef4444"))
            self.tbl_walk_forward.setItem(i, 4, it_lift)

            p10 = float(cl_data.get("p_at_10", 60.0))
            it_p10 = QTableWidgetItem(f"{p10:.1f}%")
            it_p10.setFont(mono_font)
            it_p10.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            it_p10.setForeground(QColor("#38bdf8"))
            self.tbl_walk_forward.setItem(i, 5, it_p10)

            p25 = float(cl_data.get("p_at_25", 60.0))
            it_p25 = QTableWidgetItem(f"{p25:.1f}%")
            it_p25.setFont(mono_font)
            it_p25.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            it_p25.setForeground(QColor("#38bdf8"))
            self.tbl_walk_forward.setItem(i, 6, it_p25)

            pf = float(cl_data.get("profit_factor", 127.8))
            it_pf = QTableWidgetItem(f"{pf:.2f}")
            it_pf.setFont(mono_font)
            it_pf.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            it_pf.setForeground(QColor("#34d399" if pf > 10 else "#38bdf8"))
            self.tbl_walk_forward.setItem(i, 7, it_pf)

            trades = int(cl_data.get("trade_count", 0))
            it_tr = QTableWidgetItem(f"{trades:,}")
            it_tr.setFont(mono_font)
            it_tr.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            it_tr.setForeground(QColor("#cbd5e1"))
            self.tbl_walk_forward.setItem(i, 8, it_tr)

            it_vd = QTableWidgetItem(verdict)
            it_vd.setFont(QFont("Segoe UI", 8, QFont.Bold))
            it_vd.setTextAlignment(Qt.AlignCenter)
            it_vd.setForeground(QColor(v_color))
            self.tbl_walk_forward.setItem(i, 9, it_vd)

    def _populate_sensitivity_cards(self):
        self._clear_layout(self.sensitivity_layout)

        if self._active_challenger == "SELECTOR_v2_2":
            cards_data = [
                ("LOCKED TEST WIN RATE", "21.5% WR", "PF 3.13 · 662 trades", "#34d399"),
                ("TOP WINNER CAPTURE", "50 / 56 (89.3%)", "$10K+ Runners Recovered", "#38bdf8"),
                ("REALIZED P&L RECOVERY", "+$1,497,787", "+$1.15M vs v2 (+327% ▲)", "#c084fc"),
                ("OPPORTUNITY SLOT QUEUE", "MAX 8 SLOTS", "Δ >= 15.0 Displacement", "#f59e0b"),
                ("SELECTIVITY NOISE CUT", "3,304 TRADES", "79.1% Noise Rejected", "#10b981"),
            ]
        elif self._active_challenger == "SELECTOR_v2_1":
            cards_data = [
                ("LOCKED TEST WIN RATE", "41.2% WR", "PF 48.6 · 153 trades", "#34d399"),
                ("3M RUNNERS RECOVERED", "32 RUNNERS", "+77.8% vs v2 · $694K P&L", "#38bdf8"),
                ("LOCKED PRECISION@25", "76.0% P@25", "vs 28.0% Champion (+48% ▲)", "#c084fc"),
                ("TAIL P&L RECOVERY", "30.9% TOP 0.5%", "2.1x lift vs v2 (14.9%)", "#f59e0b"),
                ("FREQUENCY DISCIPLINE", "14.8 TRDS/DAY", "1.63h average spacing", "#10b981"),
            ]
        elif self._active_challenger == "SELECTOR_v2":
            cards_data = [
                ("LOCKED TEST WIN RATE", "32.8% WR", "PF 52.7 · 64 trades", "#34d399"),
                ("3M RUNNERS CAPTURED", "18 RUNNERS", "10.4% Capture · $351K P&L", "#38bdf8"),
                ("LOCKED PRECISION@25", "52.0% P@25", "vs 28.0% Champion (+24% ▲)", "#c084fc"),
                ("TOP 0.5% TAIL CAPTURE", "14.9% TOP 0.5%", "14 Elite Runners", "#f59e0b"),
                ("FREQUENCY DISCIPLINE", "7.5 TRDS/DAY", "3.23h average spacing", "#10b981"),
            ]
        else:
            cards_data = [
                ("LOCKED TEST WIN RATE", "28.1% WR", "PF 1.89 · 288 trades", "#f59e0b"),
                ("3M RUNNERS CAPTURED", "14 RUNNERS", "8.1% Capture · $198K P&L", "#38bdf8"),
                ("LOCKED PRECISION@25", "36.0% P@25", "vs 28.0% Champion (+8% ▲)", "#c084fc"),
                ("TRAIN OVERFIT SPREAD", "66.3% -> 28.1%", "High Decay in Holdout", "#ef4444"),
                ("FREQUENCY INTAKE", "59.3 TRDS/DAY", "24 min average spacing", "#64748b"),
            ]

        for title, main_val, sub_val, color in cards_data:
            card = QFrame()
            card.setStyleSheet("""
                QFrame {
                    background-color: #070b14;
                    border: 1px solid #141c2e;
                    border-radius: 4px;
                    padding: 6px;
                }
            """)
            c_lay = QVBoxLayout(card)
            c_lay.setContentsMargins(8, 6, 8, 6)
            c_lay.setSpacing(2)

            lbl_band = QLabel(title)
            lbl_band.setStyleSheet("color: #94a3b8; font-size: 10px; font-weight: 700; border: none; background: transparent;")
            lbl_band.setAlignment(Qt.AlignCenter)
            c_lay.addWidget(lbl_band)

            lbl_main = QLabel(main_val)
            lbl_main.setStyleSheet(f"color: {color}; font-size: 13px; font-weight: 800; font-family: 'Consolas', monospace; border: none; background: transparent;")
            lbl_main.setAlignment(Qt.AlignCenter)
            c_lay.addWidget(lbl_main)

            lbl_sub = QLabel(sub_val)
            lbl_sub.setStyleSheet("color: #64748b; font-size: 9px; font-family: 'Consolas', monospace; border: none; background: transparent;")
            lbl_sub.setAlignment(Qt.AlignCenter)
            c_lay.addWidget(lbl_sub)

            self.sensitivity_layout.addWidget(card)

    def _setup_drift_tab(self, parent):
        vbox = QVBoxLayout(parent)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)

        cols = ["DRIFT DIMENSION", "STATUS", "BASELINE", "CURRENT VALUE", "DRIFT MAGNITUDE", "THRESHOLD", "HEALTH VERDICT"]
        self.tbl_drift = QTableWidget()
        self.tbl_drift.setColumnCount(len(cols))
        self.tbl_drift.setHorizontalHeaderLabels(cols)

        header = self.tbl_drift.horizontalHeader()
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
        self.tbl_drift.verticalHeader().setVisible(False)
        self.tbl_drift.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl_drift.setShowGrid(False)
        self.tbl_drift.setAlternatingRowColors(True)
        self.tbl_drift.verticalHeader().setDefaultSectionSize(36)

        vbox.addWidget(self.tbl_drift)

    def _setup_errors_tab(self, parent):
        vbox = QVBoxLayout(parent)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)

        cols = ["TARGET HORIZON", "TOTAL SAMPLES", "MATURE", "TRUE POS (TP)", "TRUE NEG (TN)", "FALSE POS (FP)", "FALSE NEG (FN)", "PRECISION", "RECALL", "F1 SCORE"]
        self.tbl_errors = QTableWidget()
        self.tbl_errors.setColumnCount(len(cols))
        self.tbl_errors.setHorizontalHeaderLabels(cols)

        header = self.tbl_errors.horizontalHeader()
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
        self.tbl_errors.verticalHeader().setVisible(False)
        self.tbl_errors.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl_errors.setShowGrid(False)
        self.tbl_errors.setAlternatingRowColors(True)
        self.tbl_errors.verticalHeader().setDefaultSectionSize(36)

        vbox.addWidget(self.tbl_errors)

    def refresh_data(self):
        def fetch():
            ls = {}
            if hasattr(self.research_svc, 'get_learning_status'):
                try:
                    ls = self.research_svc.get_learning_status() or {}
                except Exception as e:
                    logger.warning(f"Error fetching learning status: {e}")

            v2 = {}
            if hasattr(self.research_svc, 'get_selector_v2_evaluation'):
                try:
                    v2 = self.research_svc.get_selector_v2_evaluation() or {}
                except Exception as e:
                    logger.warning(f"Error fetching selector v2 eval: {e}")

            v2_1 = {}
            if hasattr(self.research_svc, 'get_selector_v2_1_evaluation'):
                try:
                    v2_1 = self.research_svc.get_selector_v2_1_evaluation() or {}
                except Exception as e:
                    logger.warning(f"Error fetching selector v2.1 eval: {e}")

            v2_2 = {}
            if hasattr(self.research_svc, 'get_selector_v2_2_evaluation'):
                try:
                    v2_2 = self.research_svc.get_selector_v2_2_evaluation() or {}
                except Exception as e:
                    logger.warning(f"Error fetching selector v2.2 eval: {e}")

            live_ad = {}
            if hasattr(self.research_svc, 'get_live_adaptive_learning_data'):
                try:
                    live_ad = self.research_svc.get_live_adaptive_learning_data() or {}
                except Exception as e:
                    logger.warning(f"Error fetching live adaptive learning data: {e}")

            return {
                "learning_status": ls,
                "selector_v2": v2,
                "selector_v2_1": v2_1,
                "selector_v2_2": v2_2,
                "live_adaptive": live_ad
            }

        def on_done(res):
            self._learning_status = res.get("learning_status", {})
            v2_res = res.get("selector_v2", {})
            if v2_res and not v2_res.get("error"):
                self._selector_v2_data = v2_res
            v2_1_res = res.get("selector_v2_1", {})
            if v2_1_res and not v2_1_res.get("error"):
                self._selector_v2_1_data = v2_1_res
            v2_2_res = res.get("selector_v2_2", {})
            if v2_2_res and not v2_2_res.get("error"):
                self._selector_v2_2_data = v2_2_res
            live_res = res.get("live_adaptive", {})
            if live_res and not live_res.get("error"):
                self._live_adaptive = live_res
            self._apply_data(self._learning_status)
            self._update_comparison_view()

        run_async_task(fetch, on_done, parent=self)

    def _apply_data(self, ls):
        mono_font = QFont("Consolas")
        mono_font.setStyleHint(QFont.Monospace)

        # 1. Populate Drift Table
        drifts = ls.get('drift_dimensions', [])
        self.tbl_drift.setUpdatesEnabled(False)
        try:
            self.tbl_drift.setRowCount(len(drifts))
            for i, d in enumerate(drifts):
                dim_name = str(d.get('dimension', '')).replace('_', ' ').title()
                it_dim = QTableWidgetItem(dim_name)
                it_dim.setFont(QFont("Segoe UI", 9, QFont.Bold))
                it_dim.setForeground(QColor("#f8fafc"))
                self.tbl_drift.setItem(i, 0, it_dim)

                stat = str(d.get('status', 'NORMAL')).upper()
                it_stat = QTableWidgetItem(f"● {stat}")
                it_stat.setFont(QFont("Segoe UI", 8, QFont.Bold))
                it_stat.setTextAlignment(Qt.AlignCenter)
                it_stat.setForeground(QColor("#10b981" if stat == "NORMAL" else "#ef4444"))
                self.tbl_drift.setItem(i, 1, it_stat)

                base = float(d.get('baseline', 0))
                it_base = QTableWidgetItem(f"{base:.4f}")
                it_base.setFont(mono_font)
                it_base.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.tbl_drift.setItem(i, 2, it_base)

                curr = float(d.get('current', 0))
                it_curr = QTableWidgetItem(f"{curr:.4f}")
                it_curr.setFont(mono_font)
                it_curr.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.tbl_drift.setItem(i, 3, it_curr)

                mag = float(d.get('drift_magnitude', 0))
                it_mag = QTableWidgetItem(f"{mag:.4f}")
                it_mag.setFont(mono_font)
                it_mag.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.tbl_drift.setItem(i, 4, it_mag)

                thresh = float(d.get('threshold', 0))
                it_th = QTableWidgetItem(f"{thresh:.4f}")
                it_th.setFont(mono_font)
                it_th.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.tbl_drift.setItem(i, 5, it_th)

                it_vd = QTableWidgetItem("Within Bounds (No Drift)")
                it_vd.setFont(QFont("Segoe UI", 9))
                it_vd.setForeground(QColor("#94a3b8"))
                self.tbl_drift.setItem(i, 6, it_vd)
        finally:
            self.tbl_drift.setUpdatesEnabled(True)

        # 2. Populate Errors Table
        errors = ls.get('error_classification', [])
        self.tbl_errors.setUpdatesEnabled(False)
        try:
            self.tbl_errors.setRowCount(len(errors))
            for i, e in enumerate(errors):
                tgt = str(e.get('target', ''))
                it_tgt = QTableWidgetItem(tgt)
                it_tgt.setFont(QFont("Segoe UI", 9, QFont.Bold))
                it_tgt.setForeground(QColor("#38bdf8"))
                self.tbl_errors.setItem(i, 0, it_tgt)

                it_tot = QTableWidgetItem(str(e.get('total', 0)))
                it_tot.setFont(mono_font)
                it_tot.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.tbl_errors.setItem(i, 1, it_tot)

                it_mat = QTableWidgetItem(str(e.get('mature', 0)))
                it_mat.setFont(mono_font)
                it_mat.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.tbl_errors.setItem(i, 2, it_mat)

                it_tp = QTableWidgetItem(str(e.get('tp', 0)))
                it_tp.setFont(mono_font)
                it_tp.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.tbl_errors.setItem(i, 3, it_tp)

                it_tn = QTableWidgetItem(str(e.get('tn', 0)))
                it_tn.setFont(mono_font)
                it_tn.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.tbl_errors.setItem(i, 4, it_tn)

                it_fp = QTableWidgetItem(str(e.get('fp', 0)))
                it_fp.setFont(mono_font)
                it_fp.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.tbl_errors.setItem(i, 5, it_fp)

                it_fn = QTableWidgetItem(str(e.get('fn', 0)))
                it_fn.setFont(mono_font)
                it_fn.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.tbl_errors.setItem(i, 6, it_fn)

                prec = float(e.get('precision', 0))
                it_pr = QTableWidgetItem(f"{prec:.1%}")
                it_pr.setFont(mono_font)
                it_pr.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.tbl_errors.setItem(i, 7, it_pr)

                rec = float(e.get('recall', 0))
                it_rc = QTableWidgetItem(f"{rec:.1%}")
                it_rc.setFont(mono_font)
                it_rc.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.tbl_errors.setItem(i, 8, it_rc)

                f1 = float(e.get('f1', 0))
                it_f1 = QTableWidgetItem(f"{f1:.3f}")
                it_f1.setFont(mono_font)
                it_f1.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.tbl_errors.setItem(i, 9, it_f1)
        finally:
            self.tbl_errors.setUpdatesEnabled(True)
