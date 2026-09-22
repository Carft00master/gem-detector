import csv
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, 
    QTableWidgetItem, QHeaderView, QMenu, QAbstractItemView, QTabWidget, QLabel, 
    QLineEdit, QComboBox, QPushButton, QMessageBox, QApplication,
    QDialog, QFormLayout, QGroupBox, QFrame
)
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QAction, QFont

from app.ui.design_system import DS
from app.application.events import event_bus
from app.application.service_locator import ServiceLocator
from app.services.paper_trading_service import PaperTradingService
from app.services.export_service import ExportService
from app.ui.components.kpi_strip import KpiStrip
from app.ui.components.empty_state import EmptyState
from app.ui.components.async_helper import run_async_task

logger = logging.getLogger(__name__)


def _set_cell(table, row: int, col: int, text: str, font=None, alignment=None, fg_color=None, data=None, tooltip=None):
    item = table.item(row, col)
    if item is None:
        item = QTableWidgetItem()
        table.setItem(row, col, item)
    item.setText(str(text))
    if font:
        item.setFont(font)
    if alignment is not None:
        item.setTextAlignment(alignment)
    if fg_color:
        item.setForeground(fg_color)
    if data is not None:
        item.setData(Qt.UserRole, data)
    if tooltip is not None:
        item.setToolTip(tooltip)
    return item


BLOTTER_COLUMNS = [
    "TIME", "TOKEN", "ENTRY MC", "EXIT MC", "HOLD", "P(3M)", "POLICY", "NET P&L", "RETURN%", "STATUS"
]

PRESET_DEFINITIONS = [
    ("ALL", "All Trades"),
    ("WINS", "★ Wins Only"),
    ("LOSSES", "✕ Losses Only"),
    ("BIG_WINS", "🚀 Big Wins (>20%)"),
    ("RUNNERS", "💎 Runners (>100%)"),
    ("STOPPED", "🛡️ Stopped (< -10%)"),
    ("SCALPS", "⚡ Scalps (<15m)"),
    ("SWINGS", "⏳ Swings (>1h)"),
    ("HIGH_P3M", "★ High P(3M) (≥10%)"),
]


def _get_trade_return_pct(t: dict) -> float:
    for k in ("net_realized_return_pct", "return_pct", "realized_return_pct"):
        v = t.get(k)
        if v is not None:
            try:
                return float(v)
            except (ValueError, TypeError):
                pass
    return 0.0


def _get_trade_pnl(t: dict) -> float:
    for k in ("net_realized_pnl_usd", "pnl", "realized_pnl_usd"):
        v = t.get(k)
        if v is not None:
            try:
                return float(v)
            except (ValueError, TypeError):
                pass
    return 0.0


def _get_trade_hold_minutes(t: dict) -> float:
    if t.get("hold_duration_minutes") is not None:
        try:
            return float(t["hold_duration_minutes"])
        except (ValueError, TypeError):
            pass
    if t.get("hold_duration_seconds") is not None:
        try:
            return float(t["hold_duration_seconds"]) / 60.0
        except (ValueError, TypeError):
            pass
    if t.get("hold_time_minutes") is not None:
        try:
            return float(t["hold_time_minutes"])
        except (ValueError, TypeError):
            pass
    return 0.0


def _get_trade_entry_mc(t: dict) -> float:
    for k in ("entry_market_cap_usd", "entry_mc", "market_cap_usd"):
        v = t.get(k)
        if v is not None:
            try:
                return float(v)
            except (ValueError, TypeError):
                pass
    return 0.0


def _get_trade_exit_mc(t: dict) -> float:
    for k in ("exit_market_cap_usd", "exit_mc"):
        v = t.get(k)
        if v is not None:
            try:
                return float(v)
            except (ValueError, TypeError):
                pass
    return 0.0


def _get_trade_timestamp(t: dict) -> str:
    return str(t.get("exit_timestamp") or t.get("entry_timestamp") or t.get("timestamp") or "")


class CustomFilterDialog(QDialog):
    """
    Advanced multi-variable parameter filter dialog for paper trades.
    Allows filtering by return %, P&L, entry market cap, hold duration,
    probability, chain, policy, outcome, and time horizon.
    """
    def __init__(self, current_filters: dict = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Custom Blotter Parameters Filter")
        self.setFixedWidth(460)
        self.setStyleSheet("""
            QDialog {
                background-color: #0b101c;
                color: #f8fafc;
                border: 1px solid #1e293b;
                border-radius: 8px;
            }
            QGroupBox {
                font-weight: 700;
                font-size: 11px;
                color: #38bdf8;
                border: 1px solid #1e293b;
                border-radius: 6px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 6px;
                background-color: #0b101c;
            }
            QLabel {
                color: #94a3b8;
                font-size: 11px;
                font-weight: 500;
            }
            QLineEdit, QComboBox {
                background-color: #0f172a;
                border: 1px solid #1e293b;
                border-radius: 4px;
                padding: 4px 8px;
                color: #f8fafc;
                font-size: 11px;
            }
            QLineEdit:focus, QComboBox:focus {
                border-color: #38bdf8;
            }
            QPushButton#btnPrimary {
                background-color: #2563eb;
                color: #ffffff;
                font-weight: 700;
                font-size: 11px;
                border-radius: 4px;
                padding: 6px 16px;
                border: none;
            }
            QPushButton#btnPrimary:hover {
                background-color: #1d4ed8;
            }
            QPushButton#btnSecondary {
                background-color: #1e293b;
                color: #94a3b8;
                font-weight: 600;
                font-size: 11px;
                border-radius: 4px;
                padding: 6px 14px;
                border: 1px solid #334155;
            }
            QPushButton#btnSecondary:hover {
                background-color: #334155;
                color: #f8fafc;
            }
        """)
        self.filters = dict(current_filters or {})
        self._setup_ui()
        self._load_filters()

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # Header Title
        title_lbl = QLabel("⚙ Custom Paper Trading Filters")
        title_lbl.setStyleSheet("font-size: 14px; font-weight: 700; color: #f8fafc;")
        root.addWidget(title_lbl)

        subtitle_lbl = QLabel("Set quantitative parameters to refine and search blotter records.")
        subtitle_lbl.setStyleSheet("font-size: 10px; color: #64748b; margin-bottom: 4px;")
        root.addWidget(subtitle_lbl)

        # 1. Performance Group
        grp_perf = QGroupBox("RETURN & P&L THRESHOLDS")
        f_perf = QFormLayout(grp_perf)
        f_perf.setContentsMargins(12, 12, 12, 10)
        f_perf.setSpacing(8)

        self.txt_min_ret = QLineEdit()
        self.txt_min_ret.setPlaceholderText("e.g. -20.0 or 10.0 (in %)")
        f_perf.addRow("Min Return (%):", self.txt_min_ret)

        self.txt_max_ret = QLineEdit()
        self.txt_max_ret.setPlaceholderText("e.g. 100.0 (in %)")
        f_perf.addRow("Max Return (%):", self.txt_max_ret)

        self.txt_min_pnl = QLineEdit()
        self.txt_min_pnl.setPlaceholderText("e.g. -50.0 or 100.0 (in USD)")
        f_perf.addRow("Min Net P&L ($):", self.txt_min_pnl)

        self.txt_max_pnl = QLineEdit()
        self.txt_max_pnl.setPlaceholderText("e.g. 5000.0 (in USD)")
        f_perf.addRow("Max Net P&L ($):", self.txt_max_pnl)

        root.addWidget(grp_perf)

        # 2. Market Cap & Duration Group
        grp_mkt = QGroupBox("MARKET CAP & HOLD DURATION")
        f_mkt = QFormLayout(grp_mkt)
        f_mkt.setContentsMargins(12, 12, 12, 10)
        f_mkt.setSpacing(8)

        self.txt_min_mc = QLineEdit()
        self.txt_min_mc.setPlaceholderText("e.g. 20000 (in USD)")
        f_mkt.addRow("Min Entry MC ($):", self.txt_min_mc)

        self.txt_max_mc = QLineEdit()
        self.txt_max_mc.setPlaceholderText("e.g. 500000 (in USD)")
        f_mkt.addRow("Max Entry MC ($):", self.txt_max_mc)

        self.txt_min_hold = QLineEdit()
        self.txt_min_hold.setPlaceholderText("e.g. 5 (in minutes)")
        f_mkt.addRow("Min Hold (Mins):", self.txt_min_hold)

        self.txt_max_hold = QLineEdit()
        self.txt_max_hold.setPlaceholderText("e.g. 60 (in minutes)")
        f_mkt.addRow("Max Hold (Mins):", self.txt_max_hold)

        root.addWidget(grp_mkt)

        # 3. Model & Strategy Filters
        grp_strat = QGroupBox("STRATEGY, PROBABILITY & TIME HORIZON")
        f_strat = QFormLayout(grp_strat)
        f_strat.setContentsMargins(12, 12, 12, 10)
        f_strat.setSpacing(8)

        self.cmb_min_p3m = QComboBox()
        self.cmb_min_p3m.addItems([
            "Any Probability", "≥ 5% P(3M)", "≥ 8% P(3M)", "≥ 10% P(3M)", "≥ 15% P(3M)", "≥ 20% P(3M)"
        ])
        f_strat.addRow("Min P(3M):", self.cmb_min_p3m)

        self.cmb_chain = QComboBox()
        self.cmb_chain.addItems(["All Chains", "Solana", "BNB Chain", "Robinhood", "Base (Historical)"])
        f_strat.addRow("Chain:", self.cmb_chain)

        self.cmb_policy = QComboBox()
        self.cmb_policy.addItems([
            "All Policies", "TRAILING_STOP", "STAGED_EXITS", "FIXED_TARGETS", "TIME_BASED", "RISK_INVALIDATION"
        ])
        f_strat.addRow("Exit Policy:", self.cmb_policy)

        self.cmb_horizon = QComboBox()
        self.cmb_horizon.addItems([
            "All Time", "Last 24 Hours", "Last 3 Days", "Last 7 Days", "Last 30 Days"
        ])
        f_strat.addRow("Time Horizon:", self.cmb_horizon)

        root.addWidget(grp_strat)

        # Action Buttons
        btn_box = QHBoxLayout()
        btn_box.setSpacing(8)

        btn_reset = QPushButton("Reset All")
        btn_reset.setObjectName("btnSecondary")
        btn_reset.setCursor(Qt.PointingHandCursor)
        btn_reset.clicked.connect(self._reset_all)
        btn_box.addWidget(btn_reset)

        btn_box.addStretch()

        btn_cancel = QPushButton("Cancel")
        btn_cancel.setObjectName("btnSecondary")
        btn_cancel.setCursor(Qt.PointingHandCursor)
        btn_cancel.clicked.connect(self.reject)
        btn_box.addWidget(btn_cancel)

        btn_apply = QPushButton("Apply Filters")
        btn_apply.setObjectName("btnPrimary")
        btn_apply.setCursor(Qt.PointingHandCursor)
        btn_apply.clicked.connect(self._apply)
        btn_box.addWidget(btn_apply)

        root.addLayout(btn_box)

    def _load_filters(self):
        f = self.filters
        if "min_return" in f and f["min_return"] is not None:
            self.txt_min_ret.setText(str(f["min_return"]))
        if "max_return" in f and f["max_return"] is not None:
            self.txt_max_ret.setText(str(f["max_return"]))
        if "min_pnl" in f and f["min_pnl"] is not None:
            self.txt_min_pnl.setText(str(f["min_pnl"]))
        if "max_pnl" in f and f["max_pnl"] is not None:
            self.txt_max_pnl.setText(str(f["max_pnl"]))
        if "min_mc" in f and f["min_mc"] is not None:
            self.txt_min_mc.setText(str(f["min_mc"]))
        if "max_mc" in f and f["max_mc"] is not None:
            self.txt_max_mc.setText(str(f["max_mc"]))
        if "min_hold" in f and f["min_hold"] is not None:
            self.txt_min_hold.setText(str(f["min_hold"]))
        if "max_hold" in f and f["max_hold"] is not None:
            self.txt_max_hold.setText(str(f["max_hold"]))

        if "min_p3m" in f and f["min_p3m"] is not None:
            val = f["min_p3m"]
            idx = self.cmb_min_p3m.findText(f"≥ {int(round(val*100))}% P(3M)")
            if idx >= 0:
                self.cmb_min_p3m.setCurrentIndex(idx)

        if f.get("chain"):
            idx = self.cmb_chain.findText(f["chain"])
            if idx >= 0:
                self.cmb_chain.setCurrentIndex(idx)

        if f.get("policy"):
            idx = self.cmb_policy.findText(f["policy"])
            if idx >= 0:
                self.cmb_policy.setCurrentIndex(idx)

        if f.get("time_horizon"):
            idx = self.cmb_horizon.findText(f["time_horizon"])
            if idx >= 0:
                self.cmb_horizon.setCurrentIndex(idx)

    def _parse_float(self, text):
        cleaned = text.replace("$", "").replace("%", "").replace(",", "").strip()
        if not cleaned:
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None

    def _reset_all(self):
        self.txt_min_ret.clear()
        self.txt_max_ret.clear()
        self.txt_min_pnl.clear()
        self.txt_max_pnl.clear()
        self.txt_min_mc.clear()
        self.txt_max_mc.clear()
        self.txt_min_hold.clear()
        self.txt_max_hold.clear()
        self.cmb_min_p3m.setCurrentIndex(0)
        self.cmb_chain.setCurrentIndex(0)
        self.cmb_policy.setCurrentIndex(0)
        self.cmb_horizon.setCurrentIndex(0)

    def _apply(self):
        f = {}
        f["min_return"] = self._parse_float(self.txt_min_ret.text())
        f["max_return"] = self._parse_float(self.txt_max_ret.text())
        f["min_pnl"] = self._parse_float(self.txt_min_pnl.text())
        f["max_pnl"] = self._parse_float(self.txt_max_pnl.text())
        f["min_mc"] = self._parse_float(self.txt_min_mc.text())
        f["max_mc"] = self._parse_float(self.txt_max_mc.text())
        f["min_hold"] = self._parse_float(self.txt_min_hold.text())
        f["max_hold"] = self._parse_float(self.txt_max_hold.text())

        p3m_text = self.cmb_min_p3m.currentText()
        if "≥" in p3m_text:
            num = p3m_text.replace("≥", "").replace("% P(3M)", "").strip()
            f["min_p3m"] = float(num) / 100.0
        else:
            f["min_p3m"] = None

        chain_txt = self.cmb_chain.currentText()
        f["chain"] = chain_txt if chain_txt != "All Chains" else None

        policy_txt = self.cmb_policy.currentText()
        f["policy"] = policy_txt if policy_txt != "All Policies" else None

        horizon_txt = self.cmb_horizon.currentText()
        f["time_horizon"] = horizon_txt if horizon_txt != "All Time" else None

        self.filters = f
        self.accept()

    def get_filters(self) -> dict:
        return self.filters


class PaperTradingView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.trading_svc = ServiceLocator.get(PaperTradingService)
        self.trades = []
        self.sort_col_idx = 0
        self.sort_ascending = False
        
        # Filter States
        self._filter_search = ""
        self._filter_chain = "All Chains"
        self._filter_policy = "All Policies"
        self._filter_outcome = "All Outcomes"
        self.active_preset = "ALL"
        self.custom_filters = {}
        self._max_display_rows = 100
        self._dirty = True
        self._loading = False
        self._cached_stats = None
        
        # Filtered Sets
        self._filtered_all = []
        self._filtered_open = []
        self._filtered_closed = []
        
        self.setup_ui()
        self.setup_connections()
        self.refresh_data()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 1. KPI Ribbon
        self.kpi_strip = KpiStrip([
            {"label": "TOTAL TRADES", "value": "0", "subtitle": "executed", "color": "#38bdf8"},
            {"label": "OPEN POSITIONS", "value": "0", "subtitle": "live active", "color": "#10b981"},
            {"label": "WIN RATE", "value": "0%", "subtitle": "closed winners", "color": "#34d399"},
            {"label": "CUMUL P&L", "value": "$0", "subtitle": "net realized", "color": "#f8fafc"},
            {"label": "PROFIT FACTOR", "value": "0.0", "subtitle": "win/loss ratio", "color": "#c084fc"},
        ])
        layout.addWidget(self.kpi_strip)

        # 2. Main Control Bar
        ctrl_frame = QWidget()
        ctrl_frame.setObjectName("paperCtrlFrame")
        ctrl_frame.setStyleSheet("""
            QWidget#paperCtrlFrame {
                background-color: #0b101c;
                border-bottom: 1px solid #141c2b;
            }
        """)
        ctrl_layout = QHBoxLayout(ctrl_frame)
        ctrl_layout.setContentsMargins(14, 8, 14, 6)
        ctrl_layout.setSpacing(8)

        # Search Bar
        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("🔍  Search symbol, address, or trade ID...")
        self.txt_search.setFixedWidth(230)
        self.txt_search.setFixedHeight(28)
        self.txt_search.textChanged.connect(self._on_search_changed)
        ctrl_layout.addWidget(self.txt_search)

        # Chain Dropdown
        self.cmb_chain = QComboBox()
        self.cmb_chain.setFixedHeight(28)
        self.cmb_chain.setFixedWidth(135)
        self.cmb_chain.addItems(["All Chains", "Solana", "BNB Chain", "Robinhood", "Base (Historical)"])
        self.cmb_chain.currentTextChanged.connect(self._on_chain_changed)
        ctrl_layout.addWidget(self.cmb_chain)

        # Policy Dropdown
        self.cmb_policy = QComboBox()
        self.cmb_policy.setFixedHeight(28)
        self.cmb_policy.setFixedWidth(130)
        self.cmb_policy.addItems([
            "All Policies", "TRAILING_STOP", "STAGED_EXITS", "FIXED_TARGETS", "TIME_BASED", "RISK_INVALIDATION"
        ])
        self.cmb_policy.currentTextChanged.connect(self._on_filter_changed)
        ctrl_layout.addWidget(self.cmb_policy)

        # Outcome Dropdown
        self.cmb_outcome = QComboBox()
        self.cmb_outcome.setFixedHeight(28)
        self.cmb_outcome.setFixedWidth(115)
        self.cmb_outcome.addItems(["All Outcomes", "Wins (+P&L)", "Losses (-P&L)"])
        self.cmb_outcome.currentTextChanged.connect(self._on_filter_changed)
        ctrl_layout.addWidget(self.cmb_outcome)

        # Custom Filter Button
        self.btn_custom_filter = QPushButton("⚙ Custom Filters")
        self.btn_custom_filter.setObjectName("btnCustomFilter")
        self.btn_custom_filter.setFixedHeight(28)
        self.btn_custom_filter.setCursor(Qt.PointingHandCursor)
        self.btn_custom_filter.setStyleSheet("""
            QPushButton#btnCustomFilter {
                background-color: #1e293b;
                color: #94a3b8;
                border: 1px solid #334155;
                font-weight: 600;
                font-size: 11px;
                border-radius: 4px;
                padding: 0 10px;
            }
            QPushButton#btnCustomFilter:hover {
                background-color: #334155;
                color: #f8fafc;
            }
        """)
        self.btn_custom_filter.clicked.connect(self._open_custom_filter_dialog)
        ctrl_layout.addWidget(self.btn_custom_filter)

        # Limit Dropdown
        self.cmb_limit = QComboBox()
        self.cmb_limit.setFixedHeight(28)
        self.cmb_limit.setFixedWidth(105)
        self.cmb_limit.addItems(["Latest 100", "Latest 250", "Latest 500", "All Trades"])
        self.cmb_limit.setCurrentIndex(1)
        self.cmb_limit.currentTextChanged.connect(self._on_limit_changed)
        ctrl_layout.addWidget(self.cmb_limit)

        ctrl_layout.addStretch()

        # CSV Export
        self.btn_export = QPushButton("📥 Export CSV")
        self.btn_export.setObjectName("btnSecondary")
        self.btn_export.setFixedHeight(28)
        self.btn_export.setCursor(Qt.PointingHandCursor)
        self.btn_export.clicked.connect(self._export_csv)
        ctrl_layout.addWidget(self.btn_export)

        # Refresh
        self.btn_refresh = QPushButton("↻ Refresh")
        self.btn_refresh.setObjectName("btnSecondary")
        self.btn_refresh.setFixedHeight(28)
        self.btn_refresh.setCursor(Qt.PointingHandCursor)
        self.btn_refresh.clicked.connect(self.refresh_data)
        ctrl_layout.addWidget(self.btn_refresh)

        layout.addWidget(ctrl_frame)

        # 3. Quick Preset Filter Pills Row
        pills_frame = QWidget()
        pills_frame.setObjectName("paperPillsFrame")
        pills_frame.setStyleSheet("""
            QWidget#paperPillsFrame {
                background-color: #0b101c;
                border-bottom: 1px solid #141c2b;
            }
        """)
        pills_layout = QHBoxLayout(pills_frame)
        pills_layout.setContentsMargins(14, 0, 14, 6)
        pills_layout.setSpacing(6)

        lbl_presets = QLabel("QUICK FILTERS:")
        lbl_presets.setStyleSheet("color: #475569; font-size: 10px; font-weight: 700; margin-right: 4px;")
        pills_layout.addWidget(lbl_presets)

        self.preset_buttons = {}
        for pid, plabel in PRESET_DEFINITIONS:
            btn = QPushButton(plabel)
            btn.setFixedHeight(24)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _, p=pid: self._on_preset_clicked(p))
            pills_layout.addWidget(btn)
            self.preset_buttons[pid] = btn

        pills_layout.addStretch()
        self._refresh_preset_pills()
        layout.addWidget(pills_frame)

        # 4. Active Filters Notification Strip
        self.filter_banner = QFrame()
        self.filter_banner.setObjectName("filterBanner")
        self.filter_banner.setStyleSheet("""
            QFrame#filterBanner {
                background-color: #0d1e38;
                border-bottom: 1px solid #1d4ed8;
                padding: 4px 14px;
            }
        """)
        banner_layout = QHBoxLayout(self.filter_banner)
        banner_layout.setContentsMargins(14, 3, 14, 3)
        banner_layout.setSpacing(8)

        self.lbl_active_filters = QLabel("")
        self.lbl_active_filters.setStyleSheet("color: #38bdf8; font-size: 11px; font-weight: 600;")
        banner_layout.addWidget(self.lbl_active_filters)

        banner_layout.addStretch()

        self.btn_clear_all_filters = QPushButton("✕ Clear All Filters")
        self.btn_clear_all_filters.setFixedHeight(22)
        self.btn_clear_all_filters.setCursor(Qt.PointingHandCursor)
        self.btn_clear_all_filters.setStyleSheet("""
            QPushButton {
                background-color: #1e3a8a;
                color: #93c5fd;
                border: 1px solid #2563eb;
                font-size: 10px;
                font-weight: 700;
                border-radius: 3px;
                padding: 2px 8px;
            }
            QPushButton:hover {
                background-color: #2563eb;
                color: #ffffff;
            }
        """)
        self.btn_clear_all_filters.clicked.connect(self._clear_all_filters)
        banner_layout.addWidget(self.btn_clear_all_filters)

        self.filter_banner.hide()
        layout.addWidget(self.filter_banner)

        # 5. Blotter Tabs
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(f"""
            QTabWidget::pane {{ border: none; background-color: #080c14; }}
            QTabBar::tab {{ background: #0b101c; color: #64748b; padding: 8px 18px; border: none; font-weight: 600; font-size: 11px; }}
            QTabBar::tab:selected {{ background: #0f172a; color: #38bdf8; border-bottom: 2px solid #38bdf8; }}
            QTabBar::tab:hover {{ color: #f8fafc; }}
        """)
        
        self.tab_open = QWidget()
        self.tab_closed = QWidget()
        self.tab_all = QWidget()
        
        self.tabs.addTab(self.tab_open, "Open Positions")
        self.tabs.addTab(self.tab_closed, "Closed Trades")
        self.tabs.addTab(self.tab_all, "All Blotter Trades")
        
        self._setup_blotter_tab(self.tab_open, "open", "No Active Positions", "Paper trades open automatically when high-conviction signals trigger.")
        self._setup_blotter_tab(self.tab_closed, "closed", "No Closed Trades", "Positions will close upon reaching trailing stop or staged targets.")
        self._setup_blotter_tab(self.tab_all, "all", "Blotter Empty", "No paper trades recorded yet.")
        
        layout.addWidget(self.tabs)

    def _setup_blotter_tab(self, parent_widget, category, empty_title, empty_sub):
        vbox = QVBoxLayout(parent_widget)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)
        
        table = QTableWidget()
        table.setColumnCount(len(BLOTTER_COLUMNS))
        table.setHorizontalHeaderLabels(BLOTTER_COLUMNS)
        
        header = table.horizontalHeader()
        header.setSectionsClickable(True)
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
            QHeaderView::section:hover {
                color: #38bdf8;
                background-color: #0e1628;
            }
        """)
        
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setShowGrid(False)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setDefaultSectionSize(36)
        
        col_widths = [75, 180, 90, 90, 65, 70, 105, 90, 85, 85]
        for c_idx, w in enumerate(col_widths):
            table.setColumnWidth(c_idx, w)
        
        table.setContextMenuPolicy(Qt.CustomContextMenu)
        table.customContextMenuRequested.connect(lambda pos, t=table: self.show_context_menu(pos, t))
        table.doubleClicked.connect(self._on_table_double_click)
        header.sectionClicked.connect(lambda idx, cat=category: self._on_header_clicked(idx, cat))
        
        empty_widget = EmptyState("📑", empty_title, empty_sub)
        
        vbox.addWidget(table)
        vbox.addWidget(empty_widget)
        
        setattr(self, f"table_{category}", table)
        setattr(self, f"empty_{category}", empty_widget)

    def setup_connections(self):
        event_bus.paper_trade_opened.connect(lambda _: self._on_trade_event())
        event_bus.paper_trade_closed.connect(lambda _: self._on_trade_event())
        self.tabs.currentChanged.connect(lambda _: self._update_active_table())
        
        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(10000)
        self.poll_timer.timeout.connect(self._on_poll_timeout)
        self.poll_timer.start()

    def showEvent(self, event):
        super().showEvent(event)
        if getattr(self, '_dirty', False) or not self.trades:
            self.refresh_data()

    def _on_poll_timeout(self):
        if self.isVisible() and getattr(self, '_dirty', False):
            self.refresh_data()

    def _on_trade_event(self):
        self._dirty = True
        if hasattr(self.trading_svc, 'invalidate_cache'):
            self.trading_svc.invalidate_cache()
        if self.isVisible():
            self.refresh_data(force=True)

    def _has_active_filters(self) -> bool:
        if self._filter_search:
            return True
        if self._filter_chain != "All Chains":
            return True
        if self._filter_policy != "All Policies":
            return True
        if self._filter_outcome != "All Outcomes":
            return True
        if self.active_preset != "ALL":
            return True
        cf = self.custom_filters
        for k in ("min_return", "max_return", "min_pnl", "max_pnl", "min_mc", "max_mc", "min_hold", "max_hold", "min_p3m"):
            if cf.get(k) is not None:
                return True
        if cf.get("chain") or cf.get("policy") or cf.get("time_horizon"):
            return True
        return False

    def _refresh_preset_pills(self):
        for pid, btn in self.preset_buttons.items():
            if pid == self.active_preset:
                btn.setStyleSheet("""
                    QPushButton {
                        background-color: #1e3a8a;
                        color: #38bdf8;
                        border: 1px solid #3b82f6;
                        font-weight: 700;
                        font-size: 10px;
                        border-radius: 12px;
                        padding: 2px 10px;
                    }
                """)
            else:
                btn.setStyleSheet("""
                    QPushButton {
                        background-color: #0f172a;
                        color: #64748b;
                        border: 1px solid #1e293b;
                        font-weight: 500;
                        font-size: 10px;
                        border-radius: 12px;
                        padding: 2px 10px;
                    }
                    QPushButton:hover {
                        background-color: #1e293b;
                        color: #cbd5e1;
                        border-color: #334155;
                    }
                """)

    def _on_preset_clicked(self, preset_id: str):
        if self.active_preset == preset_id:
            self.active_preset = "ALL"
        else:
            self.active_preset = preset_id
        self._refresh_preset_pills()
        self._update_all_tables()

    def _open_custom_filter_dialog(self):
        dlg = CustomFilterDialog(self.custom_filters, self)
        if dlg.exec():
            self.custom_filters = dlg.get_filters()
            self._update_all_tables()

    def _clear_all_filters(self):
        self._filter_search = ""
        self.txt_search.blockSignals(True)
        self.txt_search.clear()
        self.txt_search.blockSignals(False)

        self._filter_chain = "All Chains"
        self.cmb_chain.blockSignals(True)
        self.cmb_chain.setCurrentIndex(0)
        self.cmb_chain.blockSignals(False)

        self._filter_policy = "All Policies"
        self.cmb_policy.blockSignals(True)
        self.cmb_policy.setCurrentIndex(0)
        self.cmb_policy.blockSignals(False)

        self._filter_outcome = "All Outcomes"
        self.cmb_outcome.blockSignals(True)
        self.cmb_outcome.setCurrentIndex(0)
        self.cmb_outcome.blockSignals(False)

        self.active_preset = "ALL"
        self._refresh_preset_pills()
        self.custom_filters = {}

        self._update_all_tables()

    def _on_limit_changed(self, text):
        if "100" in text:
            self._max_display_rows = 100
        elif "250" in text:
            self._max_display_rows = 250
        elif "500" in text:
            self._max_display_rows = 500
        else:
            self._max_display_rows = 999999
        self._update_active_table()

    def _on_search_changed(self, text):
        self._filter_search = text.strip().lower()
        self._update_all_tables()

    def _on_chain_changed(self, text):
        self._filter_chain = text
        self._update_all_tables()

    def _on_filter_changed(self):
        self._filter_policy = self.cmb_policy.currentText()
        self._filter_outcome = self.cmb_outcome.currentText()
        self._update_all_tables()

    def _on_header_clicked(self, col_idx, category):
        if self.sort_col_idx == col_idx:
            self.sort_ascending = not self.sort_ascending
        else:
            self.sort_col_idx = col_idx
            self.sort_ascending = col_idx in (0, 1, 4)
        self._update_all_tables()

    def refresh_data(self, force: bool = False):
        if getattr(self, '_loading', False):
            return

        def fetch():
            trades = self.trading_svc.get_all_trades(force_refresh=force)
            stats = self.trading_svc.calculate_aggregate_stats(trades=trades)
            return trades, stats

        def on_done(res):
            self.trades, self._cached_stats = res
            self._loading = False
            self._dirty = False
            self._update_all_tables()

        def on_err(err):
            self._loading = False
            logger.warning(f"Error fetching paper trades: {err}")

        self._loading = True
        run_async_task(fetch, on_done, on_err, parent=self)

    def _filter_trades(self, trades):
        now_utc = datetime.now(timezone.utc)
        out = []
        cf = self.custom_filters

        for t in trades:
            # 1. Search filter
            if self._filter_search:
                sym = str(t.get('symbol', '')).lower()
                tid = str(t.get('trade_id', '')).lower()
                addr = str(t.get('token_address', '')).lower()
                pol_s = str(t.get('exit_policy', '')).lower()
                if (self._filter_search not in sym and 
                    self._filter_search not in tid and 
                    self._filter_search not in addr and 
                    self._filter_search not in pol_s):
                    continue

            # 2. Chain filter
            if self._filter_chain != "All Chains":
                ch = str(t.get('chain') or '').lower()
                sel = self._filter_chain.lower()
                if "sol" in sel:
                    if "sol" not in ch:
                        continue
                elif "bnb" in sel or "bsc" in sel:
                    if not any(k in ch for k in ("bsc", "bnb")):
                        continue
                elif "robinhood" in sel or "rh" in sel:
                    if not any(k in ch for k in ("robinhood", "rh")):
                        continue
                elif "base" in sel:
                    if "base" not in ch:
                        continue
                elif sel not in ch:
                    continue

            # 3. Policy filter
            if self._filter_policy != "All Policies":
                pol = str(t.get('exit_policy') or t.get('policy') or '')
                if self._filter_policy.lower() not in pol.lower():
                    continue

            # Metric extractions
            pnl = _get_trade_pnl(t)
            ret = _get_trade_return_pct(t)
            h_min = _get_trade_hold_minutes(t)
            emc = _get_trade_entry_mc(t)
            p3m = float(t.get('p_reach_3m') or t.get('p3m') or 0.0)

            # 4. Outcome dropdown filter
            if self._filter_outcome == "Wins (+P&L)":
                if pnl <= 0 and ret <= 0:
                    continue
            elif self._filter_outcome == "Losses (-P&L)":
                if pnl >= 0 and ret >= 0:
                    continue

            # 5. Quick Preset filter
            if self.active_preset == "WINS":
                if pnl <= 0 and ret <= 0:
                    continue
            elif self.active_preset == "LOSSES":
                if pnl >= 0 and ret >= 0:
                    continue
            elif self.active_preset == "BIG_WINS":
                if ret < 20.0:
                    continue
            elif self.active_preset == "RUNNERS":
                if ret < 100.0:
                    continue
            elif self.active_preset == "STOPPED":
                if ret > -10.0:
                    continue
            elif self.active_preset == "SCALPS":
                if h_min <= 0 or h_min > 15.0:
                    continue
            elif self.active_preset == "SWINGS":
                if h_min < 60.0:
                    continue
            elif self.active_preset == "HIGH_P3M":
                if p3m < 0.10:
                    continue

            # 6. Custom Multi-Parameter Dialog Filters
            if cf:
                if cf.get("min_return") is not None and ret < cf["min_return"]:
                    continue
                if cf.get("max_return") is not None and ret > cf["max_return"]:
                    continue
                if cf.get("min_pnl") is not None and pnl < cf["min_pnl"]:
                    continue
                if cf.get("max_pnl") is not None and pnl > cf["max_pnl"]:
                    continue
                if cf.get("min_mc") is not None and emc < cf["min_mc"]:
                    continue
                if cf.get("max_mc") is not None and emc > cf["max_mc"]:
                    continue
                if cf.get("min_hold") is not None and h_min < cf["min_hold"]:
                    continue
                if cf.get("max_hold") is not None and h_min > cf["max_hold"]:
                    continue
                if cf.get("min_p3m") is not None and p3m < cf["min_p3m"]:
                    continue
                if cf.get("chain"):
                    c_val = str(t.get('chain') or '').lower()
                    cf_c = cf["chain"].lower()
                    if "sol" in cf_c and "sol" not in c_val:
                        continue
                    elif ("bnb" in cf_c or "bsc" in cf_c) and not any(k in c_val for k in ("bsc", "bnb")):
                        continue
                    elif ("robinhood" in cf_c or "rh" in cf_c) and not any(k in c_val for k in ("robinhood", "rh")):
                        continue
                    elif "base" in cf_c and "base" not in c_val:
                        continue
                    elif cf_c not in c_val:
                        continue
                if cf.get("policy"):
                    p_val = str(t.get('exit_policy') or t.get('policy') or '').lower()
                    if cf["policy"].lower() not in p_val:
                        continue
                if cf.get("time_horizon"):
                    hz = cf["time_horizon"]
                    t_str = _get_trade_timestamp(t)
                    if t_str:
                        try:
                            t_clean = t_str.replace("Z", "+00:00")
                            t_dt = datetime.fromisoformat(t_clean)
                            if t_dt.tzinfo is None:
                                t_dt = t_dt.replace(tzinfo=timezone.utc)
                            delta = now_utc - t_dt
                            if hz == "Last 24 Hours" and delta > timedelta(hours=24):
                                continue
                            elif hz == "Last 3 Days" and delta > timedelta(days=3):
                                continue
                            elif hz == "Last 7 Days" and delta > timedelta(days=7):
                                continue
                            elif hz == "Last 30 Days" and delta > timedelta(days=30):
                                continue
                        except Exception:
                            pass

            out.append(t)
        return out

    def _sort_trades(self, trades):
        col = self.sort_col_idx
        asc = self.sort_ascending

        def key_fn(t):
            if col == 0:
                return _get_trade_timestamp(t)
            elif col == 1:
                return str(t.get('symbol', '')).lower()
            elif col == 2:
                return _get_trade_entry_mc(t)
            elif col == 3:
                return _get_trade_exit_mc(t)
            elif col == 4:
                return _get_trade_hold_minutes(t)
            elif col == 5:
                return float(t.get('p_reach_3m') or t.get('p3m') or 0.0)
            elif col == 6:
                return str(t.get('exit_policy') or t.get('policy') or '')
            elif col == 7:
                return _get_trade_pnl(t)
            elif col == 8:
                return _get_trade_return_pct(t)
            elif col == 9:
                return str(t.get('status') or '')
            return 0

        return sorted(trades, key=key_fn, reverse=not asc)

    def _update_filter_banner(self):
        tags = []
        if self._filter_search:
            tags.append(f'Search: "{self._filter_search}"')
        if self.active_preset != "ALL":
            for pid, label in PRESET_DEFINITIONS:
                if pid == self.active_preset:
                    tags.append(f'{label}')
                    break
        if self._filter_chain != "All Chains":
            tags.append(f'Chain: {self._filter_chain}')
        if self._filter_policy != "All Policies":
            tags.append(f'Policy: {self._filter_policy}')
        if self._filter_outcome != "All Outcomes":
            tags.append(f'Outcome: {self._filter_outcome}')

        cf = self.custom_filters
        if cf.get("min_return") is not None:
            tags.append(f'Return ≥ {cf["min_return"]:+.1f}%')
        if cf.get("max_return") is not None:
            tags.append(f'Return ≤ {cf["max_return"]:+.1f}%')
        if cf.get("min_pnl") is not None:
            tags.append(f'P&L ≥ ${cf["min_pnl"]:+,.0f}')
        if cf.get("max_pnl") is not None:
            tags.append(f'P&L ≤ ${cf["max_pnl"]:+,.0f}')
        if cf.get("min_mc") is not None:
            tags.append(f'Entry MC ≥ ${cf["min_mc"]:,.0f}')
        if cf.get("max_mc") is not None:
            tags.append(f'Entry MC ≤ ${cf["max_mc"]:,.0f}')
        if cf.get("min_hold") is not None:
            tags.append(f'Hold ≥ {cf["min_hold"]:.0f}m')
        if cf.get("max_hold") is not None:
            tags.append(f'Hold ≤ {cf["max_hold"]:.0f}m')
        if cf.get("min_p3m") is not None:
            tags.append(f'P(3M) ≥ {cf["min_p3m"]*100:.0f}%')
        if cf.get("chain"):
            tags.append(f'Chain: {cf["chain"]}')
        if cf.get("policy"):
            tags.append(f'Policy: {cf["policy"]}')
        if cf.get("time_horizon"):
            tags.append(f'Horizon: {cf["time_horizon"]}')

        if tags:
            self.lbl_active_filters.setText("🔍 ACTIVE FILTERS:  " + "   •   ".join(tags))
            self.filter_banner.show()
            active_count = len([k for k, v in cf.items() if v is not None])
            txt = f"⚙ Custom Filters ({active_count})" if active_count > 0 else "⚙ Custom Filters (Active)"
            self.btn_custom_filter.setText(txt)
            self.btn_custom_filter.setStyleSheet("""
                QPushButton#btnCustomFilter {
                    background-color: #1e3a8a;
                    color: #38bdf8;
                    border: 1px solid #3b82f6;
                    font-weight: 700;
                    font-size: 11px;
                    border-radius: 4px;
                    padding: 0 10px;
                }
            """)
        else:
            self.filter_banner.hide()
            self.btn_custom_filter.setText("⚙ Custom Filters")
            self.btn_custom_filter.setStyleSheet("""
                QPushButton#btnCustomFilter {
                    background-color: #1e293b;
                    color: #94a3b8;
                    border: 1px solid #334155;
                    font-weight: 600;
                    font-size: 11px;
                    border-radius: 4px;
                    padding: 0 10px;
                }
                QPushButton#btnCustomFilter:hover {
                    background-color: #334155;
                    color: #f8fafc;
                }
            """)

    def _update_kpi_strip(self):
        if not self._has_active_filters():
            stats = getattr(self, '_cached_stats', None)
            if stats is None and hasattr(self.trading_svc, 'calculate_aggregate_stats'):
                stats = self.trading_svc.calculate_aggregate_stats(trades=self.trades)
            if stats:
                total_tr = getattr(stats, 'total_trades', 0)
                open_pos = getattr(stats, 'open_trades_count', 0)
                wr = getattr(stats, 'win_rate_pct', 0.0)
                pnl = getattr(stats, 'total_realized_pnl_usd', 0.0)
                pf = getattr(stats, 'profit_factor', 0.0)
                
                self.kpi_strip.update_item(0, str(total_tr), "Blotter entries")
                self.kpi_strip.update_item(1, str(open_pos), "Active now")
                self.kpi_strip.update_item(2, f"{wr:.1f}%", f"{int(total_tr * wr / 100)} winners")
                pnl_str = f"+${pnl:,.2f}" if pnl >= 0 else f"-${abs(pnl):,.2f}"
                self.kpi_strip.update_item(3, pnl_str, "Realized performance")
                self.kpi_strip.update_item(4, f"{pf:.2f}", "Profit / loss factor")
        else:
            closed = self._filtered_closed
            pnls = [_get_trade_pnl(t) for t in closed]
            wins = [p for p in pnls if p > 0]
            losses = [p for p in pnls if p < 0]
            win_count = len(wins)
            wr = (win_count / len(closed) * 100.0) if closed else 0.0
            tot_pnl = sum(pnls)
            gross_win = sum(wins)
            gross_loss = abs(sum(losses))
            pf = (gross_win / gross_loss) if gross_loss > 0 else (10.0 if gross_win > 0 else 0.0)

            self.kpi_strip.update_item(0, f"{len(self._filtered_all)}", f"{len(self._filtered_all)} matching filter")
            self.kpi_strip.update_item(1, f"{len(self._filtered_open)}", "Filtered active")
            self.kpi_strip.update_item(2, f"{wr:.1f}%", f"{win_count} of {len(closed)} closed")
            pnl_str = f"+${tot_pnl:,.2f}" if tot_pnl >= 0 else f"-${abs(tot_pnl):,.2f}"
            self.kpi_strip.update_item(3, pnl_str, "Filtered P&L")
            self.kpi_strip.update_item(4, f"{pf:.2f}", "Filtered PF")

    def _update_all_tables(self):
        self._filtered_all = self._sort_trades(self._filter_trades(self.trades))
        self._filtered_open = [t for t in self._filtered_all if t.get('status') == 'OPEN']
        self._filtered_closed = [t for t in self._filtered_all if t.get('status') != 'OPEN']
        
        # Dynamic tab badges
        total_open_all = len([t for t in self.trades if t.get('status') == 'OPEN'])
        total_closed_all = len([t for t in self.trades if t.get('status') != 'OPEN'])
        
        cnt_open = len(self._filtered_open)
        cnt_closed = len(self._filtered_closed)
        cnt_all = len(self._filtered_all)

        if self._has_active_filters():
            self.tabs.setTabText(0, f"Open Positions ({cnt_open})")
            self.tabs.setTabText(1, f"Closed Trades ({cnt_closed} / {total_closed_all})")
            self.tabs.setTabText(2, f"All Blotter Trades ({cnt_all} / {len(self.trades)})")
        else:
            self.tabs.setTabText(0, f"Open Positions ({cnt_open})")
            self.tabs.setTabText(1, f"Closed Trades ({cnt_closed})")
            self.tabs.setTabText(2, f"All Blotter Trades ({cnt_all})")

        self._update_kpi_strip()
        self._update_filter_banner()
        self._update_active_table()

    def _update_active_table(self):
        if not self.isVisible():
            return
        idx = self.tabs.currentIndex()
        if idx == 0:
            self._populate_table(self.table_open, self.empty_open, getattr(self, '_filtered_open', []))
        elif idx == 1:
            self._populate_table(self.table_closed, self.empty_closed, getattr(self, '_filtered_closed', [])[:self._max_display_rows])
        else:
            self._populate_table(self.table_all, self.empty_all, getattr(self, '_filtered_all', [])[:self._max_display_rows])

    def _populate_table(self, table, empty_widget, trades):
        if not trades:
            table.hide()
            empty_widget.show()
            return
            
        empty_widget.hide()
        table.show()
        table.setUpdatesEnabled(False)
        table.setSortingEnabled(False)
        try:
            table.setRowCount(len(trades))
            
            mono_font = QFont("Consolas")
            mono_font.setStyleHint(QFont.Monospace)
            mono_font.setPointSize(9)
            bold_font = QFont("Segoe UI", 9, QFont.Bold)
            policy_font = QFont("Segoe UI", 8, QFont.Bold)
        
            for i, t in enumerate(trades):
                # 0. TIME
                time_val = _get_trade_timestamp(t)
                clean_time = time_val[11:19] if len(time_val) >= 19 else time_val
                _set_cell(table, i, 0, clean_time, font=mono_font, data=t.get('trade_id', ''), tooltip=time_val)
                
                # 1. TOKEN
                sym = str(t.get('symbol') or 'UNK').upper()
                addr = str(t.get('token_address', ''))
                short_addr = f"· {addr[:4]}..{addr[-4:]}" if len(addr) > 8 else ""
                _set_cell(table, i, 1, f"{sym}  {short_addr}".strip(), font=bold_font, fg_color=QColor("#f8fafc"), data=addr, tooltip=f"{sym} ({addr})" if addr else sym)
                
                # 2. ENTRY MC
                emc = _get_trade_entry_mc(t)
                _set_cell(table, i, 2, f"${emc:,.0f}" if emc > 0 else "—", font=mono_font, alignment=Qt.AlignRight | Qt.AlignVCenter, fg_color=QColor("#cbd5e1"))
                
                # 3. EXIT MC
                xmc = _get_trade_exit_mc(t)
                _set_cell(table, i, 3, f"${xmc:,.0f}" if xmc > 0 else "—", font=mono_font, alignment=Qt.AlignRight | Qt.AlignVCenter, fg_color=QColor("#cbd5e1"))
                
                # 4. HOLD DURATION
                h_min = _get_trade_hold_minutes(t)
                status_raw = str(t.get('status') or 'OPEN').upper()
                if h_min <= 0 and status_raw == 'OPEN':
                    h_str = "<1m"
                elif h_min < 1.0:
                    h_str = f"{max(1, int(h_min * 60))}s"
                elif h_min < 60.0:
                    h_str = f"{int(h_min)}m"
                elif h_min < 1440.0:
                    h_str = f"{int(h_min // 60)}h {int(h_min % 60)}m"
                else:
                    h_str = f"{h_min / 1440.0:.1f}d"
                _set_cell(table, i, 4, h_str, font=mono_font, alignment=Qt.AlignRight | Qt.AlignVCenter, fg_color=QColor("#94a3b8"), tooltip=f"{h_min:.1f} minutes ({h_min*60:.0f} seconds)")
                
                # 5. P(3M)
                p3 = float(t.get('p_reach_3m') or t.get('p3m') or 0.0)
                p3_color = QColor("#10b981" if p3 >= 0.14 else "#38bdf8" if p3 >= 0.08 else "#64748b")
                _set_cell(table, i, 5, f"{p3:.1%}", font=mono_font, alignment=Qt.AlignRight | Qt.AlignVCenter, fg_color=p3_color)
                
                # 6. POLICY
                pol = str(t.get('exit_policy') or t.get('policy') or 'TRAIL_STOP')
                _set_cell(table, i, 6, pol, font=policy_font, alignment=Qt.AlignCenter, fg_color=QColor("#c084fc"))
                
                # 7. NET P&L
                pnl = _get_trade_pnl(t)
                pnl_str = f"+${pnl:,.2f}" if pnl >= 0 else f"-${abs(pnl):,.2f}"
                pnl_color = QColor("#10b981" if pnl >= 0 else "#ef4444")
                _set_cell(table, i, 7, pnl_str, font=mono_font, alignment=Qt.AlignRight | Qt.AlignVCenter, fg_color=pnl_color)
                
                # 8. RETURN%
                ret = _get_trade_return_pct(t)
                ret_color = QColor("#10b981" if ret >= 0 else "#ef4444")
                _set_cell(table, i, 8, f"{ret:+.2f}%", font=mono_font, alignment=Qt.AlignRight | Qt.AlignVCenter, fg_color=ret_color)
                
                # 9. STATUS
                status = str(t.get('status') or 'OPEN').upper()
                if status == 'OPEN':
                    st_badge = "● OPEN"
                    st_color = "#38bdf8"
                elif pnl > 0 or ret > 0 or 'WIN' in status:
                    st_badge = "✓ WIN"
                    st_color = "#10b981"
                else:
                    st_badge = "✕ LOSS"
                    st_color = "#ef4444"
                _set_cell(table, i, 9, st_badge, font=policy_font, alignment=Qt.AlignCenter, fg_color=QColor(st_color))
        finally:
            table.setUpdatesEnabled(True)

    def _on_table_double_click(self, index):
        table = self.sender()
        if not table: return
        item = table.item(index.row(), 1)
        if item:
            addr = item.data(Qt.UserRole)
            if addr:
                event_bus.navigate_to_token_detail.emit(addr)

    def show_context_menu(self, pos, table):
        item = table.itemAt(pos)
        if not item: return
        row = item.row()
        trade_id = table.item(row, 0).data(Qt.UserRole)
        addr = table.item(row, 1).data(Qt.UserRole)
        
        menu = QMenu(self)
        menu.setStyleSheet("background-color: #0f172a; color: #f8fafc; border: 1px solid #1e293b;")
        
        act_view = QAction("🔍 View Token Research", self)
        act_view.triggered.connect(lambda: event_bus.navigate_to_token_detail.emit(addr))
        
        act_copy_id = QAction("📋 Copy Trade ID", self)
        act_copy_id.triggered.connect(lambda: QApplication.clipboard().setText(str(trade_id)))
        
        act_copy_addr = QAction("📋 Copy Token Address", self)
        act_copy_addr.triggered.connect(lambda: QApplication.clipboard().setText(str(addr)))
        
        menu.addAction(act_view)
        menu.addSeparator()
        menu.addAction(act_copy_id)
        menu.addAction(act_copy_addr)
        menu.exec(table.viewport().mapToGlobal(pos))

    def _export_csv(self):
        try:
            export_path = Path("exports") / "blotter_paper_trades.csv"
            export_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(export_path, mode="w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(BLOTTER_COLUMNS)
                for t in self.trades:
                    time_val = _get_trade_timestamp(t)
                    sym = str(t.get('symbol') or '')
                    emc = _get_trade_entry_mc(t)
                    xmc = _get_trade_exit_mc(t)
                    hold_min = round(_get_trade_hold_minutes(t), 2)
                    p3 = float(t.get('p_reach_3m') or t.get('p3m') or 0.0)
                    pol = str(t.get('exit_policy') or t.get('policy') or '')
                    pnl = _get_trade_pnl(t)
                    ret = _get_trade_return_pct(t)
                    status = str(t.get('status') or '')
                    writer.writerow([time_val, sym, emc, xmc, hold_min, p3, pol, pnl, ret, status])
                    
            QMessageBox.information(
                self, "Export Successful",
                f"Paper trading blotter exported successfully to:\n\n{export_path.resolve()}"
            )
        except Exception as e:
            QMessageBox.warning(self, "Export Failed", f"Could not export CSV: {e}")
