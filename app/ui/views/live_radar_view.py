import logging
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, 
    QTableWidgetItem, QHeaderView, QMenu, QAbstractItemView, QLabel, QPushButton, QApplication, QToolTip
)
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QAction, QFont

from app.ui.design_system import DS, SIGNAL_STATE_META, rug_risk_level, cabal_risk_level
from app.application.events import event_bus
from app.application.service_locator import ServiceLocator
from app.services.scanner_service import ScannerService
from app.ui.components.kpi_strip import KpiStrip
from app.ui.components.filter_bar import FilterBar
from app.ui.components.status_badge import StatusBadge
from app.ui.components.risk_badge import RiskBadge
from app.ui.components.empty_state import EmptyState
from app.ui.components.skeleton_loader import SkeletonLoader
from app.ui.components.prob_display import ProbCell
from app.ui.components.actions_delegate import ActionButtonsDelegate

logger = logging.getLogger(__name__)

def format_age(age_minutes) -> str:
    try:
        val = float(age_minutes)
    except (ValueError, TypeError):
        return "—"
    if val <= 0:
        return "< 1m"
    if val < 60.0:
        return f"{int(round(val))}m"
    hours = int(val // 60)
    mins = int(round(val % 60))
    if val < 1440.0:
        return f"{hours}h {mins}m" if mins > 0 else f"{hours}h"
    days = int(val // 1440)
    rem_h = int((val % 1440) // 60)
    return f"{days}d {rem_h}h"


def format_usd(val: float) -> str:
    try:
        v = float(val)
    except (ValueError, TypeError):
        return "$0"
    if v >= 1_000_000:
        return f"${v/1_000_000:.2f}M"
    elif v >= 1_000:
        return f"${v/1_000:.1f}K"
    else:
        return f"${v:,.0f}"


def format_signal_badge(sig: str) -> tuple[str, str, str]:
    badges = {
        "EARLY_BREAKOUT":  ("⚡ BREAKOUT", "#38bdf8", "#082f49"),
        "HIGH_CONVICTION": ("★ CONVICTION", "#10b981", "#064e3b"),
        "STRENGTHENING":   ("▲ STRENGTH", "#34d399", "#062b1e"),
        "TARGET_PROGRESS": ("🎯 TARGET", "#fbbf24", "#451a03"),
        "WEAKENING":       ("▼ WEAK", "#fb923c", "#431407"),
        "INVALIDATED":     ("✕ INVALID", "#f87171", "#450a0a"),
        "EXIT":            ("⏹ EXIT", "#c084fc", "#3b0764"),
        "WATCH":           ("◎ WATCH", "#94a3b8", "#1e293b"),
    }
    return badges.get(sig, (sig, "#94a3b8", "#1e293b"))


def _set_radar_cell(table, row: int, col: int, text: str = "", font=None, alignment=None, fg_color=None, data=None, tooltip=None):
    itm = table.item(row, col)
    if itm is None:
        itm = QTableWidgetItem()
        table.setItem(row, col, itm)
    if text != "":
        itm.setText(str(text))
    if font:
        itm.setFont(font)
    if alignment is not None:
        itm.setTextAlignment(alignment)
    if fg_color:
        itm.setForeground(fg_color)
    if data is not None:
        itm.setData(Qt.UserRole, data)
    if tooltip is not None:
        itm.setToolTip(tooltip)
    return itm


BASE_COLUMNS = [
    "TOKEN", "CHAIN", "MARKET CAP", "LIQUIDITY", "AGE", "P(3M)", "RUG RISK", "SIGNAL STATE", "MAX @2%", "ACTIONS"
]


class LiveRadarView(QWidget):
    navigate_to_token_detail = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.scanner_svc = ServiceLocator.get(ScannerService)
        self.candidates = {}
        self.filtered_candidates = []
        self._current_filters = {}
        self.sort_col_idx = 5  # Default sort by P(3M)
        self.sort_ascending = False  # Descending

        # VPS Performance Adaptations
        from app.services.settings_service import SettingsService
        settings_svc = ServiceLocator.try_get(SettingsService)
        is_vps = settings_svc.is_vps_mode_active() if settings_svc else False
        self._max_display_rows = 100 if is_vps else 150
        self._timer_interval = 4000 if is_vps else 2500

        self._dirty = True
        self.setup_ui()
        self.setup_connections()
        self.refresh_data()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 1. KPI Ribbon
        self.kpi_strip = KpiStrip([
            {"label": "ACTIVE POOLS", "value": "0", "subtitle": "monitored", "color": "#38bdf8"},
            {"label": "ALERTS", "value": "0", "subtitle": "signals", "color": "#10b981"},
            {"label": "TOP P(3M)", "value": "0%", "subtitle": "highest probability", "color": "#c084fc"},
            {"label": "SOLANA", "value": "0", "subtitle": "pools", "color": "#38bdf8"},
            {"label": "BNB CHAIN", "value": "0", "subtitle": "pools", "color": "#f59e0b"},
        ])
        layout.addWidget(self.kpi_strip)

        # 2. Filter Bar
        self.filter_bar = FilterBar(
            chains=["All Chains", "Solana", "BNB Chain"],
            states=["All States", "WATCH", "EARLY_BREAKOUT", "STRENGTHENING", "TARGET_PROGRESS", "INVALIDATED"],
            sort_options=["P(3M) Desc", "Market Cap", "Liquidity", "Age"],
            preset_filters=["ALL", "HIGH_CONVICTION", "EARLY_BREAKOUT", "STRENGTHENING", "LOW_RUG", "NEW_TOKENS"]
        )
        layout.addWidget(self.filter_bar)

        # 3. Candidate Table
        self.table = QTableWidget()
        self.table.setColumnCount(len(BASE_COLUMNS))
        self._update_header_labels()
        
        header = self.table.horizontalHeader()
        header.setSectionsClickable(True)
        header.setSectionResizeMode(0, QHeaderView.Interactive)
        header.setSectionResizeMode(1, QHeaderView.Fixed)
        header.setSectionResizeMode(2, QHeaderView.Interactive)
        header.setSectionResizeMode(3, QHeaderView.Interactive)
        header.setSectionResizeMode(4, QHeaderView.Interactive)
        header.setSectionResizeMode(5, QHeaderView.Interactive)
        header.setSectionResizeMode(6, QHeaderView.Interactive)
        header.setSectionResizeMode(7, QHeaderView.Interactive)
        header.setSectionResizeMode(8, QHeaderView.Interactive)
        header.setSectionResizeMode(9, QHeaderView.Fixed)
        
        self.table.setColumnWidth(0, 160)
        self.table.setColumnWidth(1, 68)
        self.table.setColumnWidth(2, 105)
        self.table.setColumnWidth(3, 105)
        self.table.setColumnWidth(4, 75)
        self.table.setColumnWidth(5, 85)
        self.table.setColumnWidth(6, 88)
        self.table.setColumnWidth(7, 130)
        self.table.setColumnWidth(8, 95)
        self.table.setColumnWidth(9, 90)

        # Actions Column Delegate (zero native child QWidgets, prevents GDI exhaustion & stack overflow)
        self.actions_delegate = ActionButtonsDelegate(
            self.table,
            actions=[
                {"id": "view", "label": "⌕", "fg": "#38bdf8", "bg": "#172554", "border": "#1e3a8a", "tooltip": "Inspect Token Detail"},
                {"id": "copy", "label": "📋", "fg": "#94a3b8", "bg": "#0f172a", "border": "#1e293b", "tooltip": "Copy CA"},
            ],
            on_action=self._handle_action
        )
        self.table.setItemDelegateForColumn(9, self.actions_delegate)
        
        header.setStyleSheet(
            "QHeaderView::section {"
            " background-color: #0b101c;"
            " color: #64748b;"
            " font-size: 10px;"
            " font-weight: 700;"
            " padding: 6px 8px;"
            " border: none;"
            " border-bottom: 1px solid #1e293b;"
            " border-right: 1px solid #141c2b;"
            "}"
            "QHeaderView::section:hover {"
            " color: #38bdf8;"
            " background-color: #0e1628;"
            "}"
        )
        
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setDefaultSectionSize(38)
        
        self.empty_state = EmptyState(
            "📡", "No Active Candidates", 
            "Start the scanner from the top bar to monitor Solana, BNB Chain, and Robinhood tokens."
        )
        
        self.table_layout = QVBoxLayout()
        self.table_layout.setContentsMargins(0, 0, 0, 0)
        self.table_layout.addWidget(self.table, 1)
        self.table_layout.addWidget(self.empty_state, 1)
        self.empty_state.hide()
        
        layout.addLayout(self.table_layout, 1)

    def _update_header_labels(self):
        labels = list(BASE_COLUMNS)
        if 0 <= self.sort_col_idx < len(labels) and self.sort_col_idx != 9:
            arrow = " ▲" if self.sort_ascending else " ▼"
            labels[self.sort_col_idx] += arrow
        self.table.setHorizontalHeaderLabels(labels)

    def setup_connections(self):
        self.filter_bar.filter_changed.connect(self._apply_filters)
        self.table.horizontalHeader().sectionClicked.connect(self._on_header_clicked)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)
        self.table.doubleClicked.connect(self.on_double_click)
        event_bus.candidate_updated.connect(self.on_candidate_updated)
        
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._on_timer_tick)
        self.timer.start(getattr(self, '_timer_interval', 2500))

    def showEvent(self, event):
        super().showEvent(event)
        if getattr(self, '_dirty', False):
            self._on_timer_tick()

    def _handle_action(self, act_id: str, address: str, row: int):
        if not address:
            return
        if act_id == "view":
            event_bus.navigate_to_token_detail.emit(address)
        elif act_id == "copy":
            QApplication.clipboard().setText(address)
            QToolTip.showText(QCursor.pos(), f"✓ Copied CA: {address[:6]}...{address[-4:]}", self.table)

    def _on_timer_tick(self):
        if not self.isVisible() or not getattr(self, '_dirty', False):
            return
        if getattr(self, '_updating', False):
            return
        self._updating = True
        try:
            self._apply_filters(self.filter_bar.get_filter())
            self._update_kpis()
            self._update_table_view()
            self._dirty = False
        finally:
            self._updating = False

    def _on_header_clicked(self, logical_index):
        if logical_index == 9:
            return
        if self.sort_col_idx == logical_index:
            self.sort_ascending = not self.sort_ascending
        else:
            self.sort_col_idx = logical_index
            self.sort_ascending = logical_index in (0, 1, 4, 6)
        self._update_header_labels()
        self._sort_filtered_candidates()
        self._update_table_view()

    def refresh_data(self):
        if hasattr(self.scanner_svc, 'get_active_candidates'):
            raw_candidates = self.scanner_svc.get_active_candidates()
            self.candidates = {c['token_address']: c for c in raw_candidates}
            if len(self.candidates) > 300:
                excess = len(self.candidates) - 300
                for k in list(self.candidates.keys())[:excess]:
                    del self.candidates[k]
        self._apply_filters(self.filter_bar.get_filter())
        self._update_kpis()
        self._update_table_view()
        self._dirty = False

    def on_candidate_updated(self, candidate):
        if 'token_address' in candidate:
            self.candidates[candidate['token_address']] = candidate
            # Keep memory capped at 300 candidates to prevent UI bloat/lag over long runs
            if len(self.candidates) > 300:
                excess = len(self.candidates) - 300
                for k in list(self.candidates.keys())[:excess]:
                    del self.candidates[k]
            self._dirty = True

    def _apply_filters(self, filters=None):
        if filters is None:
            filters = self.filter_bar.get_filter()
        self._current_filters = filters
        
        preset = filters.get("preset", "ALL")
        search = filters.get("search", "").strip().lower()
        chain = filters.get("chain", "All Chains")
        state = filters.get("state", "All States")
        
        filtered = []
        for c in self.candidates.values():
            if search:
                sym = str(c.get('symbol', '')).lower()
                addr = str(c.get('token_address', '')).lower()
                name = str(c.get('name', '')).lower()
                if search not in sym and search not in addr and search not in name:
                    continue
                    
            if chain != "All Chains":
                cand_chain = str(c.get('chain', '')).lower()
                if chain == "Solana" and "sol" not in cand_chain:
                    continue
                elif chain == "BNB Chain" and not any(k in cand_chain for k in ("bsc", "bnb")):
                    continue
                elif chain == "Robinhood" and not any(k in cand_chain for k in ("robinhood", "rh")):
                    continue
                elif chain not in ("Solana", "BNB Chain", "Robinhood") and cand_chain != chain.lower():
                    continue
                
            if state != "All States" and c.get('signal_state', '') != state:
                continue
            
            if preset == "HIGH_CONVICTION":
                if c.get('signal_state') != "HIGH_CONVICTION" and float(c.get('p_reach_3m', 0)) < 0.14:
                    continue
            elif preset == "EARLY_BREAKOUT" and c.get('signal_state') != "EARLY_BREAKOUT":
                continue
            elif preset == "STRENGTHENING" and c.get('signal_state') != "STRENGTHENING":
                continue
            elif preset == "LOW_RUG" and float(c.get('p_rug', 1.0)) >= 0.20:
                continue
            elif preset == "NEW_TOKENS" and float(c.get('token_age_minutes', 999)) > 30.0:
                continue
                
            filtered.append(c)
            
        self.filtered_candidates = filtered
        self._sort_filtered_candidates()
        self._update_table_view()

    def _sort_filtered_candidates(self):
        col = self.sort_col_idx
        asc = self.sort_ascending

        def sort_key(c):
            if col == 0:
                return str(c.get('symbol', '')).lower()
            elif col == 1:
                return str(c.get('chain', '')).lower()
            elif col == 2:
                return float(c.get('market_cap_usd', 0) or 0)
            elif col == 3:
                return float(c.get('liquidity_usd', 0) or 0)
            elif col == 4:
                return float(c.get('token_age_minutes', 0) or 0)
            elif col == 5:
                return float(c.get('p_reach_3m', 0) or 0)
            elif col == 6:
                return float(c.get('p_rug', 0) or 0)
            elif col == 7:
                priority = {'HIGH_CONVICTION': 0, 'EARLY_BREAKOUT': 1, 'STRENGTHENING': 2, 'TARGET_PROGRESS': 3, 'WATCH': 4, 'WEAKENING': 5, 'INVALIDATED': 6, 'EXIT': 7}
                return priority.get(c.get('signal_state', 'WATCH'), 99)
            elif col == 8:
                cap2 = float(c.get('max_position_2pct_usd', 0) or 0)
                if cap2 <= 0:
                    cap2 = float(c.get('liquidity_usd', 0) or 0) * 0.02
                return cap2
            return 0

        self.filtered_candidates.sort(key=sort_key, reverse=not asc)

    def _update_kpis(self):
        active = len(self.candidates)
        alerts = sum(1 for c in self.candidates.values() if c.get('signal_state') in ['EARLY_BREAKOUT', 'HIGH_CONVICTION', 'STRENGTHENING'])
        max_p = max((float(c.get('p_reach_3m', 0)) for c in self.candidates.values()), default=0.0)
        sol_count = sum(1 for c in self.candidates.values() if 'sol' in str(c.get('chain', '')).lower())
        bnb_count = sum(1 for c in self.candidates.values() if any(k in str(c.get('chain', '')).lower() for k in ('bsc', 'bnb')))
        
        self.kpi_strip.update_item(0, str(active), f"{sol_count} Sol · {bnb_count} BNB")
        self.kpi_strip.update_item(1, str(alerts), "Active Signals")
        self.kpi_strip.update_item(2, f"{max_p:.1%}", "Highest Model Prob")
        self.kpi_strip.update_item(3, str(sol_count), "Solana Pools")
        self.kpi_strip.update_item(4, str(bnb_count), "BNB Chain Pools")

    def _update_table_view(self):
        if not self.filtered_candidates:
            self.table.hide()
            self.empty_state.show()
            return
            
        self.empty_state.hide()
        self.table.show()
        self.table.setUpdatesEnabled(False)
        self.table.setSortingEnabled(False)
        try:
            display_candidates = self.filtered_candidates[:self._max_display_rows] if getattr(self, '_max_display_rows', 0) > 0 else self.filtered_candidates
            self.table.setRowCount(len(display_candidates))
            
            mono_font = QFont("Consolas")
            mono_font.setStyleHint(QFont.Monospace)
            mono_font.setPointSize(9)
            bold_font = QFont("Segoe UI", 9, QFont.Bold)
            sm_bold_font = QFont("Segoe UI", 8, QFont.Bold)
        
            for i, c in enumerate(display_candidates):
                sym = c.get('symbol', 'UNK')
                addr = c.get('token_address', '')
                short_addr = f"· {addr[:4]}..{addr[-4:]}" if len(addr) > 8 else ""
                _set_radar_cell(self.table, i, 0, f"{sym}  {short_addr}".strip(), font=bold_font, fg_color=QColor("#f8fafc"), data=addr)
                
                chain_raw = str(c.get('chain', 'UNK')).lower()
                if "sol" in chain_raw:
                    chain_short = "SOL"
                    chain_color = "#38bdf8"
                elif "bsc" in chain_raw or "bnb" in chain_raw:
                    chain_short = "BNB"
                    chain_color = "#f59e0b"
                elif "robinhood" in chain_raw or "rh" in chain_raw:
                    chain_short = "RH"
                    chain_color = "#10b981"
                elif "base" in chain_raw:
                    chain_short = "BASE"
                    chain_color = "#60a5fa"
                else:
                    chain_short = chain_raw[:4].upper()
                    chain_color = "#94a3b8"

                _set_radar_cell(self.table, i, 1, chain_short, font=sm_bold_font, alignment=Qt.AlignCenter, fg_color=QColor(chain_color))
                
                mc = float(c.get('market_cap_usd', 0) or 0)
                _set_radar_cell(self.table, i, 2, format_usd(mc), font=mono_font, alignment=Qt.AlignRight | Qt.AlignVCenter, fg_color=QColor("#e2e8f0"))
                
                liq = float(c.get('liquidity_usd', 0) or 0)
                _set_radar_cell(self.table, i, 3, format_usd(liq), font=mono_font, alignment=Qt.AlignRight | Qt.AlignVCenter, fg_color=QColor("#cbd5e1"))
                
                age_mins = c.get('token_age_minutes', 0)
                _set_radar_cell(self.table, i, 4, format_age(age_mins), font=mono_font, alignment=Qt.AlignRight | Qt.AlignVCenter, fg_color=QColor("#94a3b8"))
                
                p3m = float(c.get('p_reach_3m', 0) or 0)
                p3m_color = QColor("#10b981" if p3m >= 0.14 else "#38bdf8" if p3m >= 0.08 else "#64748b")
                _set_radar_cell(self.table, i, 5, f"{p3m:.1%}", font=mono_font, alignment=Qt.AlignRight | Qt.AlignVCenter, fg_color=p3m_color)
                
                rug = float(c.get('p_rug', 0) or 0)
                if rug < 0.20:
                    rug_lbl = "● LOW"
                    rug_col = "#10b981"
                elif rug < 0.45:
                    rug_lbl = "● MED"
                    rug_col = "#fbbf24"
                else:
                    rug_lbl = "● HIGH"
                    rug_col = "#ef4444"
                _set_radar_cell(self.table, i, 6, rug_lbl, font=sm_bold_font, alignment=Qt.AlignCenter, fg_color=QColor(rug_col), tooltip=f"Rug Risk: {rug:.1%}")
                
                sig = c.get('signal_state', 'WATCH')
                badge_text, sig_color, _ = format_signal_badge(sig)
                _set_radar_cell(self.table, i, 7, badge_text, font=sm_bold_font, alignment=Qt.AlignCenter, fg_color=QColor(sig_color))
                
                cap2 = float(c.get('max_position_2pct_usd', 0) or 0)
                if cap2 <= 0 and liq > 0:
                    cap2 = liq * 0.02
                _set_radar_cell(self.table, i, 8, format_usd(cap2) if cap2 > 0 else "—", font=mono_font, alignment=Qt.AlignRight | Qt.AlignVCenter, fg_color=QColor("#fbbf24" if cap2 > 500 else "#94a3b8"))
    
                # 9. ACTIONS: Zero-overhead delegate item
                _set_radar_cell(self.table, i, 9, "", data=addr, tooltip=f"Actions: [⌕] View Detail · [📋] Copy CA ({addr})")
        finally:
            self.table.setUpdatesEnabled(True)

    def on_double_click(self, index):
        item = self.table.item(index.row(), 0)
        if item:
            addr = item.data(Qt.UserRole)
            if addr:
                event_bus.navigate_to_token_detail.emit(addr)

    def show_context_menu(self, pos):
        item = self.table.itemAt(pos)
        if not item: return
        addr = self.table.item(item.row(), 0).data(Qt.UserRole)
        
        menu = QMenu(self)
        menu.setStyleSheet("background-color: #0f172a; color: #f8fafc; border: 1px solid #1e293b;")
        
        act_open = QAction("🔍 Open Token Detail", self)
        act_open.triggered.connect(lambda: event_bus.navigate_to_token_detail.emit(addr))
        
        act_explorer = QAction("🌐 Open Explorer (Solscan / BscScan / Robinhood)", self)
        import webbrowser
        def open_exp():
            cand = self.candidates.get(addr, {})
            ch = str(cand.get('chain', '')).lower()
            if "bsc" in ch or "bnb" in ch:
                webbrowser.open(f"https://bscscan.com/token/{addr}")
            elif "robinhood" in ch or "rh" in ch:
                webbrowser.open(f"https://dexscreener.com/robinhood/{addr}")
            elif "base" in ch:
                webbrowser.open(f"https://basescan.org/token/{addr}")
            elif addr.startswith("0x"):
                webbrowser.open(f"https://bscscan.com/token/{addr}")
            else:
                webbrowser.open(f"https://solscan.io/token/{addr}")
        act_explorer.triggered.connect(open_exp)
        
        act_dex = QAction("📈 Open DexScreener", self)
        def open_dex():
            webbrowser.open(f"https://dexscreener.com/search?q={addr}")
        act_dex.triggered.connect(open_dex)
        
        act_copy = QAction("📋 Copy Token Address", self)
        act_copy.triggered.connect(lambda: QApplication.clipboard().setText(addr))
        
        menu.addAction(act_open)
        menu.addAction(act_explorer)
        menu.addAction(act_dex)
        menu.addSeparator()
        menu.addAction(act_copy)
        
        menu.exec(self.table.viewport().mapToGlobal(pos))
