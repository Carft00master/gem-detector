"""
Virtual Wallet Management & Real-World Feasibility Terminal View.
Monitors $1,000 virtual capital allocation, real-sized AMM execution,
daily/weekly P&L attribution, fee drag analysis, and capital growth.
"""

import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QTabWidget, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QDialog, QLineEdit, QComboBox, QFormLayout, QMessageBox, QScrollArea, QSplitter,
    QProgressBar
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont

from app.ui.design_system import DS
from app.ui.components.kpi_strip import KpiStrip
from app.ui.components.empty_state import EmptyState
from app.ui.components.async_helper import run_async_task, animate_refresh_button
from app.application.service_locator import ServiceLocator
from app.application.events import event_bus
from app.services.wallet_service import WalletService

logger = logging.getLogger(__name__)


def _format_price(price: float) -> str:
    try:
        val = float(price or 0.0)
    except Exception:
        return "$0.00"
    if val <= 0:
        return "$0.00"
    if val < 0.00001:
        return f"${val:.8f}"
    elif val < 0.01:
        return f"${val:.6f}"
    elif val < 1.0:
        return f"${val:.4f}"
    else:
        return f"${val:,.2f}"


class VirtualWalletView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.wallet_svc: WalletService = ServiceLocator.get(WalletService)
        self._summary = None
        self._daily = []
        self._weekly = []
        self._open_positions = []
        self._all_positions = []
        self._ledger = []
        self._loading = False
        
        self.setup_ui()
        self.refresh_data()

        # Connect live updates
        if hasattr(event_bus, "wallet_updated"):
            event_bus.wallet_updated.connect(self._on_wallet_updated)
        event_bus.paper_trade_opened.connect(lambda _: self._on_wallet_updated())
        event_bus.paper_trade_closed.connect(lambda _: self._on_wallet_updated())

        # Auto-refresh timer every 10 seconds for real-time responsiveness
        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self._on_poll_tick)
        self.poll_timer.start(10000)

    def _on_poll_tick(self):
        if self.isVisible():
            self.refresh_data()

    def _on_wallet_updated(self):
        if self.isVisible():
            self.refresh_data()

    def refresh(self):
        self.refresh_data()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 1. Top KPI Ribbon
        self.kpi_strip = KpiStrip([
            {"label": "WALLET EQUITY", "value": "$1,000.00", "subtitle": "Starting: $1,000.00", "color": "#10b981"},
            {"label": "TODAY P&L", "value": "$0.00", "subtitle": "0 trades today", "color": "#38bdf8"},
            {"label": "THIS WEEK P&L", "value": "$0.00", "subtitle": "Current week", "color": "#34d399"},
            {"label": "OVERALL WIN RATE", "value": "0.0%", "subtitle": "0W / 0L", "color": "#fbbf24"},
            {"label": "MAX DRAWDOWN", "value": "0.0%", "subtitle": "Peak $1,000.00", "color": "#f87171"},
            {"label": "CAPITAL STATUS", "value": "$1,000 Free", "subtitle": "$0 deployed (0 open)", "color": "#a855f7"},
        ])
        layout.addWidget(self.kpi_strip)

        # 2. Control & Sub-header Bar
        ctrl_bar = QFrame()
        ctrl_bar.setFixedHeight(44)
        ctrl_bar.setStyleSheet("""
            QFrame {
                background-color: #0b101c;
                border-bottom: 1px solid #141c2b;
            }
        """)
        c_lay = QHBoxLayout(ctrl_bar)
        c_lay.setContentsMargins(14, 0, 14, 0)
        c_lay.setSpacing(10)

        self.lbl_session_title = QLabel("💰 ACTIVE SESSION: Live Forward Test ($1,000 @ 5% Compounding)")
        self.lbl_session_title.setStyleSheet("color: #38bdf8; font-weight: 700; font-size: 11px;")
        c_lay.addWidget(self.lbl_session_title)
        c_lay.addStretch()

        self.btn_new_session = QPushButton("+ New Session")
        self.btn_new_session.setStyleSheet("""
            QPushButton {
                background-color: #1e1b4b;
                color: #c7d2fe;
                border: 1px solid #4338ca;
                border-radius: 4px;
                padding: 4px 10px;
                font-size: 10px;
                font-weight: 700;
            }
            QPushButton:hover { background-color: #312e81; color: #ffffff; }
        """)
        self.btn_new_session.clicked.connect(self._show_new_session_dialog)
        c_lay.addWidget(self.btn_new_session)

        self.btn_reconcile = QPushButton("⚙ Reconcile")
        self.btn_reconcile.setToolTip("Reconcile open wallet positions against paper trade ledger")
        self.btn_reconcile.setStyleSheet("""
            QPushButton {
                background-color: #0f172a;
                color: #94a3b8;
                border: 1px solid #1e293b;
                border-radius: 4px;
                padding: 4px 10px;
                font-size: 10px;
                font-weight: 600;
            }
            QPushButton:hover { background-color: #1e293b; color: #f8fafc; }
        """)
        self.btn_reconcile.clicked.connect(self._on_reconcile_clicked)
        c_lay.addWidget(self.btn_reconcile)

        self.btn_refresh = QPushButton("↻ Refresh")
        self.btn_refresh.setStyleSheet("""
            QPushButton {
                background-color: #0f172a;
                color: #38bdf8;
                border: 1px solid #0284c7;
                border-radius: 4px;
                padding: 4px 12px;
                font-size: 10px;
                font-weight: 700;
            }
            QPushButton:hover { background-color: #0284c7; color: #ffffff; }
        """)
        self.btn_refresh.clicked.connect(self.refresh_data)
        c_lay.addWidget(self.btn_refresh)

        layout.addWidget(ctrl_bar)

        # 3. Main Workspace Tabs
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane { border: none; background-color: #080c14; }
            QTabBar::tab { background: #0b101c; color: #64748b; padding: 8px 18px; border: none; font-weight: 600; font-size: 11px; }
            QTabBar::tab:selected { background: #0f172a; color: #38bdf8; border-bottom: 2px solid #38bdf8; }
            QTabBar::tab:hover { color: #f8fafc; }
        """)

        self.tab_open = QWidget()
        self.tab_closed = QWidget()
        self.tab_daily = QWidget()
        self.tab_weekly = QWidget()
        self.tab_realism = QWidget()
        self.tab_ledger = QWidget()

        self.tabs.addTab(self.tab_open, "Open Positions")
        self.tabs.addTab(self.tab_closed, "Trade History")
        self.tabs.addTab(self.tab_daily, "Daily Breakdown")
        self.tabs.addTab(self.tab_weekly, "Weekly Breakdown")
        self.tabs.addTab(self.tab_realism, "Realism & Friction Costs")
        self.tabs.addTab(self.tab_ledger, "Cash Ledger")

        layout.addWidget(self.tabs)

        self._setup_open_tab(self.tab_open)
        self._setup_closed_tab(self.tab_closed)
        self._setup_daily_tab(self.tab_daily)
        self._setup_weekly_tab(self.tab_weekly)
        self._setup_realism_tab(self.tab_realism)
        self._setup_ledger_tab(self.tab_ledger)

    def _setup_open_tab(self, parent):
        lay = QVBoxLayout(parent)
        lay.setContentsMargins(12, 12, 12, 12)
        cols = ["TIME", "SYMBOL", "CHAIN", "VENUE", "WALLET SIZE", "FILL PRICE", "ENTRY MC", "ENTRY LIQ", "IMPACT %", "ENTRY FEES", "STATUS"]
        self.tbl_open = self._create_table(cols)
        lay.addWidget(self.tbl_open)

    def _setup_closed_tab(self, parent):
        lay = QVBoxLayout(parent)
        lay.setContentsMargins(12, 12, 12, 12)
        cols = ["TIME", "SYMBOL", "SIZE", "ENTRY FILL", "EXIT FILL", "HOLD", "REASON", "TOTAL FEES", "NET P&L ($)", "RETURN %", "EQUITY AFTER"]
        self.tbl_closed = self._create_table(cols)
        lay.addWidget(self.tbl_closed)

    def _setup_daily_tab(self, parent):
        lay = QVBoxLayout(parent)
        lay.setContentsMargins(12, 12, 12, 12)
        cols = ["DATE (LOCAL)", "TRADES TAKEN", "CLOSED", "WINS", "LOSSES", "WIN RATE", "NET P&L ($)", "DAILY RETURN %", "START EQUITY", "END EQUITY", "TOTAL FEES"]
        self.tbl_daily = self._create_table(cols)
        lay.addWidget(self.tbl_daily)

    def _setup_weekly_tab(self, parent):
        lay = QVBoxLayout(parent)
        lay.setContentsMargins(12, 12, 12, 12)
        cols = ["WEEK", "DATE RANGE", "TRADES TAKEN", "CLOSED", "WINS", "LOSSES", "WIN RATE", "NET P&L ($)", "WEEKLY RETURN %", "START EQUITY", "END EQUITY", "TOTAL FEES"]
        self.tbl_weekly = self._create_table(cols)
        lay.addWidget(self.tbl_weekly)

    def _create_telemetry_kpi_card(self, title: str, value: str, subtitle: str, color: str) -> QFrame:
        card = QFrame()
        card.setFixedHeight(68)
        card.setStyleSheet(f"""
            QFrame {{
                background-color: #0b101c;
                border: 1px solid #1e293b;
                border-left: 3px solid {color};
                border-radius: 4px;
            }}
        """)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(2)

        lbl_t = QLabel(title)
        lbl_t.setStyleSheet("color: #64748b; font-size: 9px; font-weight: 700; letter-spacing: 0.5px;")
        lbl_v = QLabel(value)
        lbl_v.setStyleSheet(f"color: {color}; font-size: 15px; font-weight: 800; font-family: 'Consolas', monospace;")
        lbl_s = QLabel(subtitle)
        lbl_s.setStyleSheet("color: #475569; font-size: 9px;")

        lay.addWidget(lbl_t)
        lay.addWidget(lbl_v)
        lay.addWidget(lbl_s)

        card.lbl_val = lbl_v
        card.lbl_sub = lbl_s
        return card

    def _setup_realism_tab(self, parent):
        lay = QVBoxLayout(parent)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(12)

        # 1. Header info box
        info_box = QFrame()
        info_box.setStyleSheet("background-color: #0b101c; border: 1px solid #1e293b; border-radius: 6px; padding: 12px;")
        ib_lay = QVBoxLayout(info_box)
        
        lbl_h = QLabel("🔬 REAL-WORLD EXECUTION & FRICTION COST AUDIT")
        lbl_h.setStyleSheet("color: #38bdf8; font-weight: 800; font-size: 13px;")
        ib_lay.addWidget(lbl_h)

        lbl_desc = QLabel(
            "Every virtual wallet trade is strictly modeled with actual position size constraints, "
            "pool-depth price impact, DEX swap fees, network priority tip overhead, and cash availability limits. "
            "This telemetry measures the exact friction drag against idealized paper trading."
        )
        lbl_desc.setStyleSheet("color: #94a3b8; font-size: 11px;")
        lbl_desc.setWordWrap(True)
        ib_lay.addWidget(lbl_desc)
        lay.addWidget(info_box)

        # 2. Telemetry Status & Progress Bar Card
        telemetry_status_card = QFrame()
        telemetry_status_card.setStyleSheet("background-color: #0b101c; border: 1px solid #1e293b; border-radius: 6px; padding: 12px;")
        tc_lay = QVBoxLayout(telemetry_status_card)
        tc_lay.setContentsMargins(12, 10, 12, 10)
        tc_lay.setSpacing(8)

        status_top_lay = QHBoxLayout()
        self.lbl_telemetry_status = QLabel("● Telemetry Engine Active (Synchronizing execution data...)")
        self.lbl_telemetry_status.setStyleSheet("color: #38bdf8; font-weight: 700; font-size: 11px;")
        status_top_lay.addWidget(self.lbl_telemetry_status)
        status_top_lay.addStretch()

        self.lbl_telemetry_time = QLabel("Live Execution Model: 100% Intact")
        self.lbl_telemetry_time.setStyleSheet("color: #64748b; font-size: 10px; font-family: 'Consolas', monospace;")
        status_top_lay.addWidget(self.lbl_telemetry_time)
        tc_lay.addLayout(status_top_lay)

        self.telemetry_progress = QProgressBar()
        self.telemetry_progress.setFixedHeight(14)
        self.telemetry_progress.setRange(0, 100)
        self.telemetry_progress.setValue(100)
        self.telemetry_progress.setTextVisible(True)
        self.telemetry_progress.setFormat("%p% Telemetry Synchronized")
        self.telemetry_progress.setStyleSheet("""
            QProgressBar {
                background-color: #080c14;
                border: 1px solid #141c2b;
                border-radius: 4px;
                text-align: center;
                color: #e2e8f0;
                font-family: 'Consolas', monospace;
                font-size: 9px;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0284c7, stop:1 #38bdf8);
                border-radius: 3px;
            }
        """)
        tc_lay.addWidget(self.telemetry_progress)
        lay.addWidget(telemetry_status_card)

        # 3. Mini KPI Cards Row
        kpi_row = QHBoxLayout()
        kpi_row.setSpacing(10)

        self.card_fee_drag = self._create_telemetry_kpi_card("TOTAL FRICTION", "$0.00", "DEX Swap & Priority Fees", "#f87171")
        self.card_drag_pct = self._create_telemetry_kpi_card("FEE DRAG RATIO", "0.0%", "Friction vs Gross Profit", "#fbbf24")
        self.card_gated = self._create_telemetry_kpi_card("CASH GATED", "0 Trades", "Protected by Zero-Cash Gate", "#38bdf8")
        self.card_top3 = self._create_telemetry_kpi_card("TOP 3 CONCENTRATION", "0.0%", "Share of Total Profit", "#a855f7")

        kpi_row.addWidget(self.card_fee_drag)
        kpi_row.addWidget(self.card_drag_pct)
        kpi_row.addWidget(self.card_gated)
        kpi_row.addWidget(self.card_top3)
        lay.addLayout(kpi_row)

        # 4. Detailed Monospace Telemetry Grid
        self.realism_grid = QFrame()
        self.realism_grid.setStyleSheet("background-color: #080c14; border: 1px solid #141c2b; border-radius: 6px; padding: 14px;")
        rg_lay = QVBoxLayout(self.realism_grid)
        self.lbl_realism_stats = QLabel("Calculating friction telemetry...")
        self.lbl_realism_stats.setStyleSheet("color: #f8fafc; font-family: 'Consolas', monospace; font-size: 12px; line-height: 1.6;")
        rg_lay.addWidget(self.lbl_realism_stats)
        lay.addWidget(self.realism_grid)
        lay.addStretch()

    def _setup_ledger_tab(self, parent):
        lay = QVBoxLayout(parent)
        lay.setContentsMargins(12, 12, 12, 12)
        cols = ["TIMESTAMP", "TYPE", "AMOUNT ($)", "BALANCE AFTER ($)", "POSITION ID", "NOTES"]
        self.tbl_ledger = self._create_table(cols)
        lay.addWidget(self.tbl_ledger)

    def _create_table(self, cols: List[str]) -> QTableWidget:
        tbl = QTableWidget()
        tbl.setColumnCount(len(cols))
        tbl.setHorizontalHeaderLabels(cols)
        hdr = tbl.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.Interactive)
        hdr.setStretchLastSection(True)
        hdr.setStyleSheet("""
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
        tbl.verticalHeader().setVisible(False)
        tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        tbl.setShowGrid(False)
        tbl.setAlternatingRowColors(True)
        tbl.setStyleSheet("""
            QTableWidget {
                background-color: #080c14;
                alternate-background-color: #0b101c;
                border: 1px solid #141c2b;
                border-radius: 4px;
            }
            QTableWidget::item:selected {
                background-color: #1e293b;
                color: #38bdf8;
            }
        """)
        return tbl

    # --- Data Fetching & Rendering ---

    def refresh_data(self):
        if self._loading:
            return
        self._loading = True
        animate_refresh_button(self.btn_refresh, True)
        if hasattr(self, "telemetry_progress"):
            self.telemetry_progress.setRange(0, 0)  # indeterminate pulsing while calculating
        if hasattr(self, "lbl_telemetry_status"):
            self.lbl_telemetry_status.setText("⚡ Auditing real-world fills, liquidity impact & DEX fee drag...")

        def fetch():
            sess = self.wallet_svc.get_active_session()
            summary = self.wallet_svc.get_summary_stats()
            daily = self.wallet_svc.get_daily_breakdown()
            weekly = self.wallet_svc.get_weekly_breakdown()
            open_pos = self.wallet_svc.get_open_positions()
            all_pos = self.wallet_svc.get_all_positions(limit=1000)
            ledger = self.wallet_svc.store.get_ledger_entries(sess.session_id, limit=300)
            return {
                "session": sess,
                "summary": summary,
                "daily": daily,
                "weekly": weekly,
                "open_pos": open_pos,
                "all_pos": all_pos,
                "ledger": ledger,
            }

        def on_done(res):
            self._loading = False
            animate_refresh_button(self.btn_refresh, False)
            try:
                self._apply_data(res)
            except Exception as e:
                logger.error(f"Error applying wallet data to UI: {e}", exc_info=True)
                if hasattr(self, "telemetry_progress"):
                    self.telemetry_progress.setRange(0, 100)
                    self.telemetry_progress.setValue(100)
                if hasattr(self, "lbl_telemetry_status"):
                    self.lbl_telemetry_status.setText(f"⚠ UI render notice: {e}")

        def on_err(err):
            self._loading = False
            animate_refresh_button(self.btn_refresh, False)
            logger.warning(f"Error fetching wallet data: {err}")
            if hasattr(self, "telemetry_progress"):
                self.telemetry_progress.setRange(0, 100)
                self.telemetry_progress.setValue(100)
            if hasattr(self, "lbl_telemetry_status"):
                self.lbl_telemetry_status.setText(f"⚠ Telemetry sync notice: {err}")

        run_async_task(fetch, on_done, on_err, parent=self)

    def _apply_data(self, data: Dict[str, Any]):
        sess = data["session"]
        summary = data["summary"]
        daily = data["daily"]
        weekly = data["weekly"]
        open_pos = data["open_pos"]
        all_pos = data["all_pos"]
        ledger = data["ledger"]

        mono_font = QFont("Consolas")
        mono_font.setStyleHint(QFont.Monospace)

        # 1. Update Title and KPI Strip
        self.lbl_session_title.setText(
            f"💰 ACTIVE SESSION: {sess.name} "
            f"| Mode: {sess.sizing_mode} @ {sess.risk_pct * 100:.0f}%"
        )

        roi_txt = f"{summary.overall_roi_pct:+.1f}% ROI"
        self.kpi_strip.update_item(0, f"${summary.current_equity_usd:,.2f}", f"{roi_txt} (Start: ${summary.starting_capital_usd:,.0f})")
        
        td_txt = f"+${summary.today_pnl_usd:,.2f}" if summary.today_pnl_usd >= 0 else f"-${abs(summary.today_pnl_usd):,.2f}"
        now_local_date = self.wallet_svc.stats_calculator._to_local_date(datetime.now(timezone.utc).isoformat())
        today_item = next((d for d in daily if d.date == now_local_date), None)
        today_trades_cnt = today_item.trades_taken if today_item else 0
        self.kpi_strip.update_item(1, td_txt, f"{today_trades_cnt} trades today")

        wk_txt = f"+${summary.this_week_pnl_usd:,.2f}" if summary.this_week_pnl_usd >= 0 else f"-${abs(summary.this_week_pnl_usd):,.2f}"
        self.kpi_strip.update_item(2, wk_txt, "Current calendar week")

        self.kpi_strip.update_item(3, f"{summary.win_rate_pct:.1f}%", f"{summary.wins_count}W / {summary.losses_count}L (PF {summary.profit_factor:.2f})")
        self.kpi_strip.update_item(4, f"{summary.max_drawdown_pct:.1f}%", f"Peak: ${summary.peak_equity_usd:,.2f}")

        status_txt = f"${summary.current_cash_usd:,.2f} Free"
        dep_txt = f"${summary.capital_deployed_usd:,.2f} deployed ({summary.open_positions_count} open)"
        self.kpi_strip.update_item(5, status_txt, dep_txt)

        # 2. Render Open Positions Table
        self.tbl_open.setRowCount(len(open_pos))
        for i, p in enumerate(open_pos):
            t_str = p.get("entry_timestamp", "")[11:19]
            self.tbl_open.setItem(i, 0, QTableWidgetItem(t_str))
            
            it_sym = QTableWidgetItem(p.get("symbol", ""))
            it_sym.setForeground(QColor("#38bdf8"))
            it_sym.setFont(QFont("Segoe UI", 9, QFont.Bold))
            self.tbl_open.setItem(i, 1, it_sym)

            self.tbl_open.setItem(i, 2, QTableWidgetItem(str(p.get("chain", "")).upper()))
            self.tbl_open.setItem(i, 3, QTableWidgetItem(str(p.get("venue", "")).upper()))

            it_sz = QTableWidgetItem(f"${p.get('position_size_usd', 0):,.2f}")
            it_sz.setFont(mono_font)
            it_sz.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.tbl_open.setItem(i, 4, it_sz)

            it_fp = QTableWidgetItem(_format_price(p.get("simulated_fill_price_usd", 0)))
            it_fp.setFont(mono_font)
            it_fp.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.tbl_open.setItem(i, 5, it_fp)

            it_mc = QTableWidgetItem(f"${p.get('entry_market_cap_usd', 0):,.0f}")
            it_mc.setFont(mono_font)
            it_mc.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.tbl_open.setItem(i, 6, it_mc)

            it_liq = QTableWidgetItem(f"${p.get('entry_liquidity_usd', 0):,.0f}")
            it_liq.setFont(mono_font)
            it_liq.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.tbl_open.setItem(i, 7, it_liq)

            it_imp = QTableWidgetItem(f"{p.get('entry_price_impact_pct', 0):.2f}%")
            it_imp.setFont(mono_font)
            it_imp.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.tbl_open.setItem(i, 8, it_imp)

            it_fee = QTableWidgetItem(f"${p.get('entry_fees_usd', 0):.2f}")
            it_fee.setFont(mono_font)
            it_fee.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.tbl_open.setItem(i, 9, it_fee)

            it_st = QTableWidgetItem("● OPEN")
            it_st.setForeground(QColor("#10b981"))
            it_st.setFont(QFont("Segoe UI", 8, QFont.Bold))
            it_st.setTextAlignment(Qt.AlignCenter)
            self.tbl_open.setItem(i, 10, it_st)

        # 3. Render Closed Trades History
        closed_trades = [p for p in all_pos if p.get("status") == "CLOSED"]
        self.tbl_closed.setRowCount(len(closed_trades))
        for i, p in enumerate(closed_trades):
            t_str = p.get("exit_timestamp", p.get("entry_timestamp", ""))[11:19]
            self.tbl_closed.setItem(i, 0, QTableWidgetItem(t_str))

            it_sym = QTableWidgetItem(p.get("symbol", ""))
            it_sym.setFont(QFont("Segoe UI", 9, QFont.Bold))
            it_sym.setForeground(QColor("#f8fafc"))
            self.tbl_closed.setItem(i, 1, it_sym)

            it_sz = QTableWidgetItem(f"${p.get('position_size_usd', 0):,.2f}")
            it_sz.setFont(mono_font)
            it_sz.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.tbl_closed.setItem(i, 2, it_sz)

            it_ef = QTableWidgetItem(_format_price(p.get("simulated_fill_price_usd", 0)))
            it_ef.setFont(mono_font)
            it_ef.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.tbl_closed.setItem(i, 3, it_ef)

            it_xf = QTableWidgetItem(_format_price(p.get("exit_price_usd", 0)))
            it_xf.setFont(mono_font)
            it_xf.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.tbl_closed.setItem(i, 4, it_xf)

            hold_m = p.get("hold_duration_seconds", 0) / 60.0
            it_h = QTableWidgetItem(f"{hold_m:.1f}m")
            it_h.setFont(mono_font)
            it_h.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.tbl_closed.setItem(i, 5, it_h)

            it_rs = QTableWidgetItem(p.get("exit_reason", "")[:18])
            it_rs.setForeground(QColor("#94a3b8"))
            self.tbl_closed.setItem(i, 6, it_rs)

            tot_f = p.get("exit_fees_usd") or p.get("entry_fees_usd", 0.0)
            it_tf = QTableWidgetItem(f"${tot_f:.2f}")
            it_tf.setFont(mono_font)
            it_tf.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.tbl_closed.setItem(i, 7, it_tf)

            pnl = p.get("net_realized_pnl_usd", 0.0)
            pnl_txt = f"+${pnl:,.2f}" if pnl >= 0 else f"-${abs(pnl):,.2f}"
            it_pnl = QTableWidgetItem(pnl_txt)
            it_pnl.setFont(mono_font)
            it_pnl.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            it_pnl.setForeground(QColor("#10b981" if pnl >= 0 else "#ef4444"))
            self.tbl_closed.setItem(i, 8, it_pnl)

            ret = p.get("net_realized_return_pct", 0.0)
            it_ret = QTableWidgetItem(f"{ret:+.1f}%")
            it_ret.setFont(mono_font)
            it_ret.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            it_ret.setForeground(QColor("#10b981" if ret >= 0 else "#ef4444"))
            self.tbl_closed.setItem(i, 9, it_ret)

            eq_after = p.get("equity_after_usd", 1000.0)
            it_eq = QTableWidgetItem(f"${eq_after:,.2f}")
            it_eq.setFont(mono_font)
            it_eq.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.tbl_closed.setItem(i, 10, it_eq)

        # 4. Render Daily Table
        self.tbl_daily.setRowCount(len(daily))
        for i, d in enumerate(daily):
            it_d = QTableWidgetItem(d.date)
            it_d.setFont(QFont("Segoe UI", 9, QFont.Bold))
            self.tbl_daily.setItem(i, 0, it_d)

            self.tbl_daily.setItem(i, 1, self._mono_item(str(d.trades_taken)))
            self.tbl_daily.setItem(i, 2, self._mono_item(str(d.trades_closed)))
            self.tbl_daily.setItem(i, 3, self._mono_item(str(d.wins), color="#10b981"))
            self.tbl_daily.setItem(i, 4, self._mono_item(str(d.losses), color="#ef4444" if d.losses > 0 else "#64748b"))
            self.tbl_daily.setItem(i, 5, self._mono_item(f"{d.win_rate_pct:.1f}%"))

            pnl_txt = f"+${d.net_pnl_usd:,.2f}" if d.net_pnl_usd >= 0 else f"-${abs(d.net_pnl_usd):,.2f}"
            self.tbl_daily.setItem(i, 6, self._mono_item(pnl_txt, color="#10b981" if d.net_pnl_usd >= 0 else "#ef4444"))
            self.tbl_daily.setItem(i, 7, self._mono_item(f"{d.daily_return_pct:+.2f}%", color="#10b981" if d.daily_return_pct >= 0 else "#ef4444"))
            self.tbl_daily.setItem(i, 8, self._mono_item(f"${d.starting_equity_usd:,.2f}"))
            self.tbl_daily.setItem(i, 9, self._mono_item(f"${d.ending_equity_usd:,.2f}"))
            self.tbl_daily.setItem(i, 10, self._mono_item(f"${d.total_fees_usd:.2f}"))

        # 5. Render Weekly Table
        self.tbl_weekly.setRowCount(len(weekly))
        for i, w in enumerate(weekly):
            it_w = QTableWidgetItem(w.week_label)
            it_w.setFont(QFont("Segoe UI", 9, QFont.Bold))
            it_w.setForeground(QColor("#38bdf8"))
            self.tbl_weekly.setItem(i, 0, it_w)

            range_txt = f"{w.start_date} → {w.end_date}"
            self.tbl_weekly.setItem(i, 1, QTableWidgetItem(range_txt))
            self.tbl_weekly.setItem(i, 2, self._mono_item(str(w.trades_taken)))
            self.tbl_weekly.setItem(i, 3, self._mono_item(str(w.trades_closed)))
            self.tbl_weekly.setItem(i, 4, self._mono_item(str(w.wins), color="#10b981"))
            self.tbl_weekly.setItem(i, 5, self._mono_item(str(w.losses), color="#ef4444" if w.losses > 0 else "#64748b"))
            self.tbl_weekly.setItem(i, 6, self._mono_item(f"{w.win_rate_pct:.1f}%"))

            pnl_txt = f"+${w.net_pnl_usd:,.2f}" if w.net_pnl_usd >= 0 else f"-${abs(w.net_pnl_usd):,.2f}"
            self.tbl_weekly.setItem(i, 7, self._mono_item(pnl_txt, color="#10b981" if w.net_pnl_usd >= 0 else "#ef4444"))
            self.tbl_weekly.setItem(i, 8, self._mono_item(f"{w.weekly_return_pct:+.2f}%", color="#10b981" if w.weekly_return_pct >= 0 else "#ef4444"))
            self.tbl_weekly.setItem(i, 9, self._mono_item(f"${w.starting_equity_usd:,.2f}"))
            self.tbl_weekly.setItem(i, 10, self._mono_item(f"${w.ending_equity_usd:,.2f}"))
            self.tbl_weekly.setItem(i, 11, self._mono_item(f"${w.total_fees_usd:.2f}"))

        # 6. Render Realism Telemetry & Progress
        if hasattr(self, "telemetry_progress"):
            self.telemetry_progress.setRange(0, 100)
            self.telemetry_progress.setValue(100)
        if hasattr(self, "lbl_telemetry_status"):
            total_audited = len(all_pos)
            self.lbl_telemetry_status.setText(f"● Telemetry Synchronized • {total_audited} positions audited (100% complete)")
        if hasattr(self, "lbl_telemetry_time"):
            self.lbl_telemetry_time.setText(f"Last sync: {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}")

        gross_pnl = summary.net_realized_pnl_usd + summary.total_fees_paid_usd
        fee_ratio = (summary.total_fees_paid_usd / gross_pnl * 100.0) if gross_pnl > 0 else 0.0

        if hasattr(self, "card_fee_drag"):
            self.card_fee_drag.lbl_val.setText(f"${summary.total_fees_paid_usd:,.2f}")
        if hasattr(self, "card_drag_pct"):
            self.card_drag_pct.lbl_val.setText(f"{fee_ratio:.1f}%")
        if hasattr(self, "card_gated"):
            self.card_gated.lbl_val.setText(f"{summary.skipped_no_capital_count} Trades")
        if hasattr(self, "card_top3"):
            self.card_top3.lbl_val.setText(f"{summary.top_3_winners_share_pct:.1f}%")

        pnl_sign = f"+${summary.net_realized_pnl_usd:,.2f}" if summary.net_realized_pnl_usd >= 0 else f"-${abs(summary.net_realized_pnl_usd):,.2f}"
        self.lbl_realism_stats.setText(
            f"• Initial Virtual Capital:    ${summary.starting_capital_usd:,.2f}\n"
            f"• Current Liquid Cash:         ${summary.current_cash_usd:,.2f}\n"
            f"• Current Net Equity:          ${summary.current_equity_usd:,.2f}\n"
            f"• Net Realized Profit:         {pnl_sign} ({summary.overall_roi_pct:+.2f}% ROI)\n"
            f"• Total Fees & Priority Tips:  -${summary.total_fees_paid_usd:,.2f} ({fee_ratio:.1f}% fee drag against gross profit)\n"
            f"• Profit Factor:               {summary.profit_factor:.2f}\n"
            f"• Average Expectancy / Trade:  ${summary.expectancy_per_trade_usd:+.2f}\n"
            f"• Average Position Hold Time:  {summary.avg_hold_minutes:.1f} minutes\n"
            f"• Top 3 Winners Profit Share:  {summary.top_3_winners_share_pct:.1f}% of all gross profit\n"
            f"• Skipped (Zero Cash Gate):    {summary.skipped_no_capital_count} trades (capital conservation protected)"
        )

        # 7. Render Cash Ledger Table
        self.tbl_ledger.setRowCount(len(ledger))
        for i, l in enumerate(ledger):
            t_str = l.timestamp[11:19] if len(l.timestamp) >= 19 else l.timestamp
            self.tbl_ledger.setItem(i, 0, QTableWidgetItem(t_str))

            it_tp = QTableWidgetItem(l.entry_type)
            it_tp.setFont(QFont("Segoe UI", 9, QFont.Bold))
            it_tp.setForeground(QColor("#10b981" if l.entry_type in ("INITIAL_DEPOSIT", "SELL") else "#ef4444"))
            self.tbl_ledger.setItem(i, 1, it_tp)

            amt_txt = f"+${l.amount_usd:,.2f}" if l.amount_usd >= 0 else f"-${abs(l.amount_usd):,.2f}"
            self.tbl_ledger.setItem(i, 2, self._mono_item(amt_txt, color="#10b981" if l.amount_usd >= 0 else "#ef4444"))
            self.tbl_ledger.setItem(i, 3, self._mono_item(f"${l.cash_balance_after_usd:,.2f}"))
            self.tbl_ledger.setItem(i, 4, QTableWidgetItem(str(l.position_id or "")[:12]))
            self.tbl_ledger.setItem(i, 5, QTableWidgetItem(str(l.notes or "")))

    def _mono_item(self, text: str, color: str = "#cbd5e1") -> QTableWidgetItem:
        it = QTableWidgetItem(text)
        it.setFont(QFont("Consolas"))
        it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        it.setForeground(QColor(color))
        return it

    def _on_reconcile_clicked(self):
        count = self.wallet_svc.reconcile()
        QMessageBox.information(
            self,
            "Reconciliation Complete",
            f"Reconciliation checked all open positions against paper_trading.db.\n"
            f"Positions settled: {count}"
        )
        self.refresh_data()

    def _show_new_session_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Initialize New Virtual Wallet Session")
        dialog.setFixedWidth(420)
        dialog.setStyleSheet("""
            QDialog { background-color: #0b101c; color: #f8fafc; }
            QLabel { color: #94a3b8; font-size: 11px; }
            QLineEdit, QComboBox {
                background-color: #080c14;
                color: #f8fafc;
                border: 1px solid #1e293b;
                border-radius: 4px;
                padding: 6px;
                font-size: 11px;
            }
        """)

        d_lay = QVBoxLayout(dialog)
        d_lay.setSpacing(12)

        form = QFormLayout()
        txt_name = QLineEdit("Forward Test ($1,000 @ 5%)")
        txt_cap = QLineEdit("1000")
        cmb_risk = QComboBox()
        cmb_risk.addItems(["5% per trade", "10% per trade", "2.5% per trade"])
        cmb_mode = QComboBox()
        cmb_mode.addItems(["COMPOUNDING (Dynamic % of Equity)", "FIXED (Static % of Initial Capital)"])

        form.addRow("Session Name:", txt_name)
        form.addRow("Starting Capital ($):", txt_cap)
        form.addRow("Allocation Risk:", cmb_risk)
        form.addRow("Sizing Mode:", cmb_mode)
        d_lay.addLayout(form)

        btn_box = QHBoxLayout()
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(dialog.reject)
        btn_create = QPushButton("Create Session")
        btn_create.setStyleSheet("""
            background-color: #0284c7; color: #ffffff; font-weight: 700;
            padding: 6px 14px; border-radius: 4px; border: none;
        """)

        def on_create():
            try:
                cap = float(txt_cap.text().strip())
                r_str = cmb_risk.currentText()
                r_val = 0.05 if "5%" in r_str else (0.10 if "10%" in r_str else 0.025)
                m_val = "COMPOUNDING" if "COMPOUNDING" in cmb_mode.currentText() else "FIXED"
                self.wallet_svc.create_new_session(
                    name=txt_name.text().strip() or "Forward Test Session",
                    starting_capital=cap,
                    risk_pct=r_val,
                    sizing_mode=m_val,
                )
                dialog.accept()
                self.refresh_data()
            except Exception as e:
                QMessageBox.warning(dialog, "Invalid Input", f"Please check inputs:\n{e}")

        btn_create.clicked.connect(on_create)
        btn_box.addStretch()
        btn_box.addWidget(btn_cancel)
        btn_box.addWidget(btn_create)
        d_lay.addLayout(btn_box)

        dialog.exec()
