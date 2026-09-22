"""
Trade Event Timeline & State Reconstruction View (PyQt6 Desktop View)
Allows visual step-by-step reconstruction of any paper trade from DISCOVERY to EXIT.
"""

from datetime import datetime
import logging
from typing import Any, Dict, List, Optional
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt
from app.services.research_service import ResearchService
from app.ui.components.async_helper import run_async_task

logger = logging.getLogger(__name__)



class TradeTimelineView(QtWidgets.QWidget):
    """
    Renders chronological event progression, state transitions, and entry risk snapshots for paper trades.
    """

    def __init__(self, service: Optional[ResearchService] = None, parent=None):
        super().__init__(parent)
        self.service = service or ResearchService()
        self.trades: List[Dict[str, Any]] = []
        self._init_ui()
        self.refresh_trades()

    def _init_ui(self):
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        # Header Card
        header = QtWidgets.QFrame()
        header.setStyleSheet("background-color: #1a1d24; border-radius: 8px; padding: 8px;")
        h_layout = QtWidgets.QHBoxLayout(header)

        title_box = QtWidgets.QVBoxLayout()
        title = QtWidgets.QLabel("⏳  Trade Event Timeline & Lifecycle Journal")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #60a5fa;")
        subtitle = QtWidgets.QLabel("Chronological point-in-time state reconstruction from discovery to exit.")
        subtitle.setStyleSheet("font-size: 11px; color: #9ca3af;")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        h_layout.addLayout(title_box)

        h_layout.addStretch()

        # Trade Selector
        lbl_select = QtWidgets.QLabel("Select Trade:")
        lbl_select.setStyleSheet("color: #e5e7eb; font-weight: bold;")
        self.trade_combo = QtWidgets.QComboBox()
        self.trade_combo.setMinimumWidth(320)
        self.trade_combo.setStyleSheet("background-color: #242933; color: #ffffff; padding: 4px; border: 1px solid #374151; border-radius: 4px;")
        self.trade_combo.currentIndexChanged.connect(self._on_trade_selected)

        btn_refresh = QtWidgets.QPushButton("🔄 Refresh")
        btn_refresh.setStyleSheet("background-color: #3b82f6; color: #ffffff; font-weight: bold; padding: 6px 14px; border-radius: 4px;")
        btn_refresh.clicked.connect(self.refresh_trades)

        h_layout.addWidget(lbl_select)
        h_layout.addWidget(self.trade_combo)
        h_layout.addWidget(btn_refresh)

        main_layout.addWidget(header)

        # Summary Metrics Bar
        self.metrics_frame = QtWidgets.QFrame()
        self.metrics_frame.setStyleSheet("background-color: #111827; border-radius: 8px; padding: 12px; border: 1px solid #1f2937;")
        m_layout = QtWidgets.QGridLayout(self.metrics_frame)

        self.lbl_token = QtWidgets.QLabel("-")
        self.lbl_entry_mc = QtWidgets.QLabel("-")
        self.lbl_exit_mc = QtWidgets.QLabel("-")
        self.lbl_entry_price = QtWidgets.QLabel("-")
        self.lbl_exit_price = QtWidgets.QLabel("-")
        self.lbl_hold_dur = QtWidgets.QLabel("-")
        self.lbl_p3m = QtWidgets.QLabel("-")
        self.lbl_risk = QtWidgets.QLabel("-")
        self.lbl_pnl = QtWidgets.QLabel("-")

        for lbl in (self.lbl_token, self.lbl_entry_mc, self.lbl_exit_mc, self.lbl_entry_price,
                    self.lbl_exit_price, self.lbl_hold_dur, self.lbl_p3m, self.lbl_risk, self.lbl_pnl):
            lbl.setStyleSheet("font-size: 13px; font-weight: bold; color: #ffffff;")

        m_layout.addWidget(self._make_metric_tile("Token / Symbol", self.lbl_token), 0, 0)
        m_layout.addWidget(self._make_metric_tile("Entry Market Cap", self.lbl_entry_mc), 0, 1)
        m_layout.addWidget(self._make_metric_tile("Exit Market Cap", self.lbl_exit_mc), 0, 2)
        m_layout.addWidget(self._make_metric_tile("Entry Price", self.lbl_entry_price), 0, 3)
        m_layout.addWidget(self._make_metric_tile("Exit Price", self.lbl_exit_price), 0, 4)
        m_layout.addWidget(self._make_metric_tile("Hold Duration", self.lbl_hold_dur), 1, 0)
        m_layout.addWidget(self._make_metric_tile("P(3M) at Entry", self.lbl_p3m), 1, 1)
        m_layout.addWidget(self._make_metric_tile("Risk Profile at Entry", self.lbl_risk), 1, 2)
        m_layout.addWidget(self._make_metric_tile("Net Realized P&L", self.lbl_pnl), 1, 3, 1, 2)

        main_layout.addWidget(self.metrics_frame)

        # Timeline Split / Table Layout
        body_splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)

        # Left: Visual Timeline Stepper Card
        stepper_card = QtWidgets.QFrame()
        stepper_card.setStyleSheet("background-color: #1e2430; border-radius: 8px; padding: 12px;")
        s_layout = QtWidgets.QVBoxLayout(stepper_card)
        s_title = QtWidgets.QLabel("📍 Visual Lifecycle Stepper")
        s_title.setStyleSheet("font-size: 13px; font-weight: bold; color: #38bdf8; margin-bottom: 8px;")
        s_layout.addWidget(s_title)

        self.timeline_text = QtWidgets.QTextBrowser()
        self.timeline_text.setStyleSheet("background-color: #111827; color: #e5e7eb; border-radius: 6px; font-family: monospace; font-size: 11px; padding: 8px;")
        s_layout.addWidget(self.timeline_text)
        body_splitter.addWidget(stepper_card)

        # Right: Granular Event Table
        table_card = QtWidgets.QFrame()
        table_card.setStyleSheet("background-color: #1e2430; border-radius: 8px; padding: 12px;")
        t_layout = QtWidgets.QVBoxLayout(table_card)
        t_title = QtWidgets.QLabel("📋 Event Log Telemetry")
        t_title.setStyleSheet("font-size: 13px; font-weight: bold; color: #a78bfa; margin-bottom: 8px;")
        t_layout.addWidget(t_title)

        self.event_table = QtWidgets.QTableWidget(0, 6)
        self.event_table.setHorizontalHeaderLabels([
            "Timestamp (UTC)", "Event Type", "Market Cap", "Liquidity", "Signal State", "Details"
        ])
        self.event_table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.event_table.setStyleSheet("background-color: #111827; color: #e5e7eb; gridline-color: #374151; font-size: 11px;")
        self.event_table.verticalHeader().setVisible(False)
        t_layout.addWidget(self.event_table)
        body_splitter.addWidget(table_card)

        body_splitter.setSizes([380, 580])
        main_layout.addWidget(body_splitter, stretch=1)

    def _make_metric_tile(self, title: str, val_label: QtWidgets.QLabel) -> QtWidgets.QFrame:
        tile = QtWidgets.QFrame()
        tile.setStyleSheet("background-color: #1f2937; border-radius: 6px; padding: 6px;")
        lay = QtWidgets.QVBoxLayout(tile)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(2)
        t_lbl = QtWidgets.QLabel(title)
        t_lbl.setStyleSheet("font-size: 10px; color: #9ca3af;")
        lay.addWidget(t_lbl)
        lay.addWidget(val_label)
        return tile

    def refresh_data(self):
        self.refresh_trades()

    def refresh_trades(self):
        def fetch():
            trades = self.service.get_all_trade_journal(limit=150)
            initial_events = []
            if trades:
                latest = trades[-1]
                tid = latest.get("trade_id") or latest.get("signal_id", "")
                if tid:
                    try:
                        initial_events = self.service.get_trade_timeline(tid)
                    except Exception:
                        initial_events = []
            return trades, initial_events

        def on_done(result):
            trades, initial_events = result
            self._apply_trades(trades, initial_events)

        run_async_task(fetch, on_done, parent=self)

    def _apply_trades(self, trades, initial_events=None):
        self.trades = trades
        self.trade_combo.blockSignals(True)
        self.trade_combo.clear()

        if not self.trades:
            self.trade_combo.addItem("No paper trades recorded", None)
        else:
            for t in reversed(self.trades):  # Show most recent first
                sym = t.get("symbol", "UNKNOWN")
                pnl = float(t.get("net_realized_pnl_usd", 0.0) or 0.0)
                status = t.get("status", "OPEN")
                tid = t.get("trade_id") or t.get("signal_id", "")
                pnl_str = f"+${pnl:.2f}" if pnl > 0 else (f"-${abs(pnl):.2f}" if pnl < 0 else "$0.00")
                item_text = f"[{status}] {sym} ({tid[:8]}) — P&L: {pnl_str}"
                self.trade_combo.addItem(item_text, t)

        self.trade_combo.blockSignals(False)
        if self.trade_combo.count() > 0:
            self.trade_combo.setCurrentIndex(0)
            self._on_trade_selected(0, preloaded_events=initial_events)

    def _on_trade_selected(self, index: int, preloaded_events: Optional[List[Dict[str, Any]]] = None):
        trade = self.trade_combo.itemData(index)
        if not trade:
            return

        sym = trade.get("symbol", "UNKNOWN")
        addr = trade.get("token_address", "")
        self.lbl_token.setText(f"{sym} ({addr[:4]}...{addr[-4:]})" if len(addr) > 8 else sym)

        entry_mc = float(trade.get("entry_market_cap_usd") or trade.get("market_cap_usd") or 0.0)
        exit_mc = float(trade.get("exit_market_cap_usd") or 0.0)
        self.lbl_entry_mc.setText(f"${entry_mc:,.0f}" if entry_mc > 0 else "-")
        self.lbl_exit_mc.setText(f"${exit_mc:,.0f}" if exit_mc > 0 else ("OPEN" if trade.get("status") == "OPEN" else "-"))

        e_price = float(trade.get("simulated_fill_price_usd") or trade.get("entry_price_usd") or 0.0)
        x_price = float(trade.get("exit_price_usd") or 0.0)
        self.lbl_entry_price.setText(f"${e_price:.6f}" if e_price > 0 else "-")
        self.lbl_exit_price.setText(f"${x_price:.6f}" if x_price > 0 else "-")

        dur = float(trade.get("hold_duration_seconds", 0.0) or 0.0)
        dur_str = f"{dur/60.0:.1f} min" if dur >= 60 else f"{dur:.0f} sec"
        self.lbl_hold_dur.setText(dur_str)

        p3m = float(trade.get("p_reach_3m_at_entry") or trade.get("p_reach_3m") or 0.0)
        self.lbl_p3m.setText(f"{p3m * 100.0:.1f}%")

        p_rug = float(trade.get("rug_risk_at_entry") or trade.get("p_rug") or 0.0)
        self.lbl_risk.setText(f"Rug: {p_rug*100.0:.1f}% | Conf: {float(trade.get('data_confidence', 1.0))*100.0:.0f}%")

        pnl = float(trade.get("net_realized_pnl_usd", 0.0) or 0.0)
        ret = float(trade.get("net_realized_return_pct", 0.0) or 0.0)
        if trade.get("status") == "OPEN":
            self.lbl_pnl.setText("IN FLIGHT (OPEN)")
            self.lbl_pnl.setStyleSheet("font-size: 13px; font-weight: bold; color: #38bdf8;")
        elif pnl > 0:
            self.lbl_pnl.setText(f"+${pnl:.2f} (+{ret:.1f}%)")
            self.lbl_pnl.setStyleSheet("font-size: 13px; font-weight: bold; color: #4ade80;")
        else:
            self.lbl_pnl.setText(f"-${abs(pnl):.2f} ({ret:.1f}%)")
            self.lbl_pnl.setStyleSheet("font-size: 13px; font-weight: bold; color: #f87171;")

        # Load timeline events
        tid = trade.get("trade_id") or trade.get("signal_id", "")
        if preloaded_events is not None:
            events = preloaded_events
        else:
            events = self.service.get_trade_timeline(tid)

        # Build visual stepper text
        stepper_lines = []
        stepper_lines.append(f"<div style='color: #60a5fa; font-weight: bold;'>TIMELINE FOR {sym} ({tid[:8]}):</div><br/>")

        if not events:
            # Reconstruct synthetic stepper from trade record if table empty
            t_in = trade.get("discovery_timestamp") or trade.get("timestamp") or "N/A"
            stepper_lines.append(f"<span style='color:#9ca3af;'>{t_in[11:19]}</span> <b style='color:#38bdf8;'>DISCOVERED</b> (MC: ${entry_mc:,.0f})")
            stepper_lines.append("<span style='color:#6b7280;'>&nbsp;&nbsp;↓</span>")
            stepper_lines.append(f"<span style='color:#9ca3af;'>{t_in[11:19]}</span> <b style='color:#4ade80;'>PAPER_ENTRY</b> (Fill: ${e_price:.6f} | Size: ${float(trade.get('position_size_usd', 250.0)):.0f})")

            if trade.get("status") == "CLOSED":
                t_out = trade.get("exit_timestamp") or "N/A"
                stepper_lines.append("<span style='color:#6b7280;'>&nbsp;&nbsp;↓</span>")
                stepper_lines.append(f"<span style='color:#9ca3af;'>{t_out[11:19]}</span> <b style='color:#f87171;'>EXIT ({trade.get('exit_reason', 'STOP')})</b> (MC: ${exit_mc:,.0f} | P&L: ${pnl:.2f})")
            else:
                stepper_lines.append("<span style='color:#6b7280;'>&nbsp;&nbsp;↓</span>")
                stepper_lines.append("<b style='color:#fbbf24;'>ACTIVE / IN-FLIGHT MONITORING...</b>")
        else:
            for idx, e in enumerate(events):
                ts = str(e.get("timestamp", ""))
                time_part = ts[11:19] if len(ts) >= 19 else ts
                etype = str(e.get("event_type", "EVENT"))
                mc = float(e.get("market_cap_usd", 0.0) or 0.0)
                color = "#38bdf8"
                if "ENTRY" in etype:
                    color = "#4ade80"
                elif "EXIT" in etype:
                    color = "#f87171"
                elif "TARGET" in etype:
                    color = "#a78bfa"
                elif "RISK" in etype:
                    color = "#fbbf24"

                stepper_lines.append(f"<span style='color:#9ca3af;'>{time_part}</span> <b style='color:{color};'>{etype}</b> (MC: ${mc:,.0f})")
                if idx < len(events) - 1:
                    stepper_lines.append("<span style='color:#6b7280;'>&nbsp;&nbsp;↓</span>")

        self.timeline_text.setHtml("<br/>".join(stepper_lines))

        # Populate Event Table
        self.event_table.setRowCount(0)
        display_events = events if events else [
            {"timestamp": trade.get("timestamp"), "event_type": "PAPER_ENTRY", "market_cap_usd": entry_mc, "liquidity_usd": trade.get("liquidity_usd"), "signal_state": "PAPER_ENTRY", "details": {"policy": trade.get("exit_policy")}}
        ]
        if trade.get("status") == "CLOSED" and not events:
            display_events.append({
                "timestamp": trade.get("exit_timestamp"), "event_type": "EXIT", "market_cap_usd": exit_mc, "liquidity_usd": trade.get("exit_liquidity_usd"), "signal_state": "EXIT", "details": {"reason": trade.get("exit_reason"), "pnl": pnl}
            })

        for row_idx, ev in enumerate(display_events):
            self.event_table.insertRow(row_idx)
            self.event_table.setItem(row_idx, 0, QtWidgets.QTableWidgetItem(str(ev.get("timestamp", ""))))
            self.event_table.setItem(row_idx, 1, QtWidgets.QTableWidgetItem(str(ev.get("event_type", ""))))
            self.event_table.setItem(row_idx, 2, QtWidgets.QTableWidgetItem(f"${float(ev.get('market_cap_usd', 0.0) or 0.0):,.0f}"))
            self.event_table.setItem(row_idx, 3, QtWidgets.QTableWidgetItem(f"${float(ev.get('liquidity_usd', 0.0) or 0.0):,.0f}"))
            self.event_table.setItem(row_idx, 4, QtWidgets.QTableWidgetItem(str(ev.get("signal_state", ""))))
            self.event_table.setItem(row_idx, 5, QtWidgets.QTableWidgetItem(str(ev.get("details", ""))))

