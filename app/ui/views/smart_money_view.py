import logging
import webbrowser
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, 
    QTableWidgetItem, QHeaderView, QMenu, QAbstractItemView, QLabel, 
    QLineEdit, QComboBox, QPushButton, QApplication, QProgressBar, QToolTip
)
from PySide6.QtCore import Qt, QTimer, Signal, QThread, QObject
from PySide6.QtGui import QColor, QAction, QFont, QCursor

from app.ui.design_system import DS
from app.application.events import event_bus
from app.application.service_locator import ServiceLocator
from app.services.research_service import ResearchService
from app.ui.components.kpi_strip import KpiStrip
from app.ui.components.empty_state import EmptyState
from app.ui.components.async_helper import run_async_task, animate_refresh_button
from app.ui.components.actions_delegate import ActionButtonsDelegate

logger = logging.getLogger(__name__)

SMART_MONEY_COLUMNS = [
    "WALLET ADDRESS", "INFERRED ROLE", "TRADES", "MATURE", "SHRUNK WR", "3M HIT RATE", "PROFIT FACTOR", "SKILL SCORE", "CONFIDENCE", "TREND", "ACTIONS"
]


class WalletDiscoveryWorker(QObject):
    """Runs AutonomousWalletDiscoveryEngine in a background QThread to prevent UI freeze."""
    finished = Signal(dict)
    error = Signal(str)
    progress = Signal(int, str)

    def __init__(self, research_svc):
        super().__init__()
        self._svc = research_svc

    def run(self):
        try:
            def on_progress(pct: int, msg: str):
                self.progress.emit(pct, msg)

            if hasattr(self._svc, 'trigger_smart_wallet_discovery_scan'):
                result = self._svc.trigger_smart_wallet_discovery_scan(progress_callback=on_progress)
                self.finished.emit(result or {})
            else:
                self.finished.emit({})
        except Exception as exc:
            self.error.emit(str(exc))


class SmartMoneyView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.research_svc = ServiceLocator.get(ResearchService)
        self.wallets = []
        self.filtered_wallets = []
        self.sort_col_idx = 7  # Default sort by Skill Score
        self.sort_ascending = False
        self._max_display_rows = 150
        self._needs_refresh = True
        self.setup_ui()
        self.setup_connections()

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
            {"label": "TRACKED WALLETS", "value": "0", "subtitle": "on-chain registry", "color": "#38bdf8"},
            {"label": "ELIGIBLE SMART MONEY", "value": "0", "subtitle": "signal generators", "color": "#10b981"},
            {"label": "HIGH SKILL COHORT", "value": "0", "subtitle": "edge confirmed", "color": "#c084fc"},
            {"label": "TOP WIN RATE", "value": "0%", "subtitle": "Bayesian shrunk", "color": "#34d399"},
            {"label": "MEDIAN TRADES", "value": "0", "subtitle": "sample depth", "color": "#fbbf24"},
        ])
        layout.addWidget(self.kpi_strip)

        # 2. Controls & Filter Bar
        ctrl_frame = QWidget()
        ctrl_frame.setStyleSheet("background-color: #0b101c; border-bottom: 1px solid #141c2b;")
        ctrl_layout = QHBoxLayout(ctrl_frame)
        ctrl_layout.setContentsMargins(14, 8, 14, 8)
        ctrl_layout.setSpacing(8)

        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("🔍  Search wallet address (0x / So1a)...")
        self.txt_search.setFixedWidth(260)
        self.txt_search.setFixedHeight(28)
        self.txt_search.textChanged.connect(self._apply_filters)
        ctrl_layout.addWidget(self.txt_search)

        self.cmb_role = QComboBox()
        self.cmb_role.setFixedHeight(28)
        self.cmb_role.addItems(["All Roles", "TRADER", "SNIPER", "WHALE", "RETAIL"])
        self.cmb_role.currentTextChanged.connect(self._apply_filters)
        ctrl_layout.addWidget(self.cmb_role)

        self.cmb_eligibility = QComboBox()
        self.cmb_eligibility.setFixedHeight(28)
        self.cmb_eligibility.addItems(["All Wallets", "Eligible Only", "High Skill Only"])
        self.cmb_eligibility.currentTextChanged.connect(self._apply_filters)
        ctrl_layout.addWidget(self.cmb_eligibility)

        self.cmb_limit = QComboBox()
        self.cmb_limit.setFixedHeight(28)
        self.cmb_limit.addItems(["Top 100", "Top 250", "Top 500", "All Wallets"])
        self.cmb_limit.currentTextChanged.connect(self._on_limit_changed)
        ctrl_layout.addWidget(self.cmb_limit)

        ctrl_layout.addStretch()

        self.btn_scan = QPushButton("⚡ Discover New Wallets")
        self.btn_scan.setObjectName("btnPrimary")
        self.btn_scan.setFixedHeight(28)
        self.btn_scan.setCursor(Qt.PointingHandCursor)
        self.btn_scan.clicked.connect(self._on_scan_clicked)
        ctrl_layout.addWidget(self.btn_scan)

        self.btn_refresh = QPushButton("↻ Refresh")
        self.btn_refresh.setObjectName("btnSecondary")
        self.btn_refresh.setFixedHeight(28)
        self.btn_refresh.setCursor(Qt.PointingHandCursor)
        self.btn_refresh.clicked.connect(lambda: self.refresh_data(reset_progress=True, force=True))
        ctrl_layout.addWidget(self.btn_refresh)

        layout.addWidget(ctrl_frame)

        # 3. Progress Bar & Status (hidden when idle)
        self.progress_container = QWidget()
        self.progress_container.setFixedHeight(28)
        self.progress_container.setStyleSheet("background-color: #0b1329; border-bottom: 1px solid #1e293b;")
        prog_layout = QHBoxLayout(self.progress_container)
        prog_layout.setContentsMargins(14, 4, 14, 4)
        prog_layout.setSpacing(10)

        self.lbl_progress_status = QLabel("Scanning on-chain universe...")
        self.lbl_progress_status.setFont(QFont("Segoe UI", 8, QFont.Bold))
        self.lbl_progress_status.setStyleSheet("color: #38bdf8;")
        prog_layout.addWidget(self.lbl_progress_status)

        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 4px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #38bdf8, stop:1 #10b981);
                border-radius: 3px;
            }
        """)
        prog_layout.addWidget(self.progress_bar, 1)

        self.lbl_progress_pct = QLabel("0%")
        self.lbl_progress_pct.setFont(QFont("Consolas", 8, QFont.Bold))
        self.lbl_progress_pct.setStyleSheet("color: #10b981; min-width: 38px;")
        self.lbl_progress_pct.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        prog_layout.addWidget(self.lbl_progress_pct)

        self.progress_container.hide()
        layout.addWidget(self.progress_container)

        # 4. Wallet Table
        self.table = QTableWidget()
        self.table.setColumnCount(len(SMART_MONEY_COLUMNS))
        self._update_header_labels()
        
        header = self.table.horizontalHeader()
        header.setSectionsClickable(True)
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setSectionResizeMode(0, QHeaderView.Interactive)
        header.setSectionResizeMode(10, QHeaderView.Fixed)
        
        self.table.setColumnWidth(0, 160)
        self.table.setColumnWidth(1, 110)
        self.table.setColumnWidth(2, 65)
        self.table.setColumnWidth(3, 65)
        self.table.setColumnWidth(4, 85)
        self.table.setColumnWidth(5, 85)
        self.table.setColumnWidth(6, 95)
        self.table.setColumnWidth(7, 90)
        self.table.setColumnWidth(8, 85)
        self.table.setColumnWidth(9, 65)
        self.table.setColumnWidth(10, 80)
        
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
        
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setDefaultSectionSize(36)
        
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)
        header.sectionClicked.connect(self._on_header_clicked)
        
        # Actions Column Delegate (zero native child widgets)
        self.actions_delegate = ActionButtonsDelegate(
            self.table,
            actions=[
                {"id": "copy", "label": "📋", "fg": "#94a3b8", "bg": "#0f172a", "border": "#1e293b", "tooltip": "Copy Address"},
                {"id": "exp", "label": "🌐", "fg": "#38bdf8", "bg": "#172554", "border": "#1e3a8a", "tooltip": "View On-Chain Explorer"},
            ],
            on_action=self._handle_action
        )
        self.table.setItemDelegateForColumn(10, self.actions_delegate)

        self.empty_state = EmptyState("🕵️", "No Matching Wallets", "Try relaxing your search or role filters.")
        
        table_container = QVBoxLayout()
        table_container.setContentsMargins(0, 0, 0, 0)
        table_container.addWidget(self.table, 1)
        table_container.addWidget(self.empty_state, 1)
        self.empty_state.hide()
        
        layout.addLayout(table_container, 1)

    def _handle_action(self, act_id: str, address: str, row: int):
        if not address:
            return
        if act_id == "copy":
            QApplication.clipboard().setText(address)
            QToolTip.showText(QCursor.pos(), f"✓ Copied Wallet: {address[:6]}...{address[-4:]}", self.table)
        elif act_id == "exp":
            if address.startswith("0x"):
                webbrowser.open(f"https://basescan.org/address/{address}")
            else:
                webbrowser.open(f"https://solscan.io/account/{address}")

    def _update_header_labels(self):
        labels = list(SMART_MONEY_COLUMNS)
        if 0 <= self.sort_col_idx < len(labels) and self.sort_col_idx != 10:
            arrow = " ▲" if self.sort_ascending else " ▼"
            labels[self.sort_col_idx] += arrow
        self.table.setHorizontalHeaderLabels(labels)

    def setup_connections(self):
        event_bus.paper_trade_closed.connect(lambda _: self.refresh_data())

    def _on_scan_clicked(self):
        """Launch wallet discovery scan in a background thread so the UI stays responsive."""
        self.btn_scan.setEnabled(False)
        self.btn_scan.setText("⏳ Discovering...")
        self.progress_bar.setValue(0)
        self.lbl_progress_pct.setText("0%")
        self.lbl_progress_status.setText("Initializing autonomous wallet discovery...")
        self.progress_container.show()

        # Create thread + worker
        self._scan_thread = QThread(self)
        self._scan_worker = WalletDiscoveryWorker(self.research_svc)
        self._scan_worker.moveToThread(self._scan_thread)

        # Wire signals
        self._scan_thread.started.connect(self._scan_worker.run)
        self._scan_worker.progress.connect(self._on_scan_progress)
        self._scan_worker.finished.connect(self._on_scan_finished)
        self._scan_worker.error.connect(self._on_scan_error)
        self._scan_worker.finished.connect(self._scan_thread.quit)
        self._scan_worker.error.connect(self._scan_thread.quit)
        self._scan_thread.finished.connect(self._scan_thread.deleteLater)

        self._scan_thread.start()

    def _on_scan_progress(self, pct: int, msg: str):
        self.progress_bar.setValue(pct)
        self.lbl_progress_pct.setText(f"{pct}%")
        self.lbl_progress_status.setText(msg)

    def _on_scan_finished(self, result: dict):
        new_n = result.get('new_wallets_discovered', 0)
        tot_n = result.get('total_wallets_tracked', 0)
        logger.info(f"Smart wallet discovery scan complete: {new_n} new wallets discovered (total: {tot_n}).")
        self.progress_bar.setValue(100)
        self.lbl_progress_pct.setText("100%")
        if new_n > 0:
            self.lbl_progress_status.setText(f"✓ Discovered {new_n} new smart wallets ({tot_n} total tracked)")
        else:
            self.lbl_progress_status.setText(f"✓ Smart money registry up to date ({tot_n} total tracked)")
        self.btn_scan.setEnabled(True)
        self.btn_scan.setText("⚡ Discover New Wallets")
        QTimer.singleShot(2500, lambda: self.progress_container.hide() if hasattr(self, 'progress_container') else None)
        self.refresh_data(reset_progress=False)

    def _on_scan_error(self, error_msg: str):
        logger.exception(f"Error during smart wallet scan: {error_msg}")
        self.lbl_progress_status.setText(f"⚠ Scan error: {error_msg[:60]}")
        self.btn_scan.setEnabled(True)
        self.btn_scan.setText("⚡ Discover New Wallets")
        QTimer.singleShot(3000, lambda: self.progress_container.hide() if hasattr(self, 'progress_container') else None)

    def _on_header_clicked(self, logical_index):
        if logical_index == 10:
            return
        if self.sort_col_idx == logical_index:
            self.sort_ascending = not self.sort_ascending
        else:
            self.sort_col_idx = logical_index
            self.sort_ascending = logical_index in (0, 1)
        self._update_header_labels()
        self._sort_and_render()

    def _on_limit_changed(self, text):
        if "100" in text:
            self._max_display_rows = 100
        elif "250" in text:
            self._max_display_rows = 250
        elif "500" in text:
            self._max_display_rows = 500
        else:
            self._max_display_rows = 0
        self._sort_and_render()

    def refresh_data(self, reset_progress: bool = True, force: bool = False):
        animate_refresh_button(self.btn_refresh, True, "↻ Refresh")
        if force:
            self.research_svc.invalidate_merged_cache()
        if reset_progress and not self.wallets:
            self.progress_container.show()
            self.progress_bar.setValue(25)
            self.lbl_progress_pct.setText("25%")
            self.lbl_progress_status.setText("Reading smart money database...")

        def fetch():
            if hasattr(self.research_svc, 'get_smart_money_wallets'):
                return self.research_svc.get_smart_money_wallets() or []
            return []

        def on_done(wallets):
            self.wallets = wallets
            self._apply_kpi_and_roles()
            self._apply_filters()
            if reset_progress:
                self.progress_bar.setValue(100)
                self.lbl_progress_pct.setText("100%")
                self.lbl_progress_status.setText(f"✓ Loaded {len(self.filtered_wallets)} active wallets")
                QTimer.singleShot(1600, lambda: self.progress_container.hide() if hasattr(self, 'progress_container') else None)
            animate_refresh_button(self.btn_refresh, False, "↻ Refresh")

        def on_err(err):
            self.lbl_progress_status.setText(f"⚠ Failed to load: {err[:50]}")
            animate_refresh_button(self.btn_refresh, False, "↻ Refresh")
            QTimer.singleShot(2000, lambda: self.progress_container.hide() if hasattr(self, 'progress_container') else None)

        run_async_task(fetch, on_done, on_err, parent=self)

    def _apply_kpi_and_roles(self):
        total = len(self.wallets)
        eligible = sum(1 for w in self.wallets if w.get('is_smart_money_eligible') == 1)
        high_skill = sum(1 for w in self.wallets if float(w.get('risk_adjusted_score', 0) or 0) > 0.05 or float(w.get('skill_7d', 0) or 0) > 80)
        max_wr = max((float(w.get('shrunk_win_rate', 0) or 0) for w in self.wallets), default=0.0)
        trades_counts = sorted([int(w.get('total_trades', 0) or 0) for w in self.wallets])
        med_trades = trades_counts[len(trades_counts)//2] if trades_counts else 0

        self.kpi_strip.update_item(0, str(total), f"{total} in database")
        self.kpi_strip.update_item(1, str(eligible), "Active validators")
        self.kpi_strip.update_item(2, str(high_skill), "Proven track record")
        self.kpi_strip.update_item(3, f"{max_wr:.1f}%", "Max shrunk win rate")
        self.kpi_strip.update_item(4, str(med_trades), "Median trades / wallet")

        from collections import Counter
        role_counts = Counter(str(w.get('primary_role', 'RETAIL')).upper() for w in self.wallets)
        roles_order = ["RETAIL", "TRADER", "SNIPER", "WHALE"]
        current_selection = self.cmb_role.currentText().split()[0].upper() if self.cmb_role.currentText() else "ALL"

        self.cmb_role.blockSignals(True)
        self.cmb_role.clear()
        self.cmb_role.addItem(f"All Roles ({total})")
        for r in roles_order:
            self.cmb_role.addItem(f"{r} ({role_counts.get(r, 0)})")

        for idx in range(self.cmb_role.count()):
            item_role = self.cmb_role.itemText(idx).split()[0].upper()
            if item_role == current_selection:
                self.cmb_role.setCurrentIndex(idx)
                break
        self.cmb_role.blockSignals(False)

    def _reset_filters(self):
        self.txt_search.clear()
        self.cmb_role.setCurrentIndex(0)
        self.cmb_eligibility.setCurrentIndex(0)
        self._apply_filters()

    def _apply_filters(self):
        search = self.txt_search.text().strip().lower()
        raw_role = self.cmb_role.currentText()
        role_filt = raw_role.split()[0].upper() if raw_role else "ALL"
        elig_filt = self.cmb_eligibility.currentText()

        filtered = []
        for w in self.wallets:
            if search and search not in str(w.get('wallet_address', '')).lower():
                continue
            if role_filt != "ALL" and str(w.get('primary_role', 'RETAIL')).upper() != role_filt:
                continue
            if elig_filt == "Eligible Only" and w.get('is_smart_money_eligible') != 1:
                continue
            elif elig_filt == "High Skill Only" and float(w.get('risk_adjusted_score', 0) or 0) <= 0.05:
                continue
            filtered.append(w)

        self.filtered_wallets = filtered
        self._sort_and_render()

    def _sort_and_render(self):
        col = self.sort_col_idx
        asc = self.sort_ascending

        def key_fn(w):
            if col == 0:
                return str(w.get('wallet_address', '')).lower()
            elif col == 1:
                return str(w.get('primary_role', '')).lower()
            elif col == 2:
                return int(w.get('total_trades', 0) or 0)
            elif col == 3:
                return int(w.get('mature_trades', 0) or 0)
            elif col == 4:
                return float(w.get('shrunk_win_rate', 0) or 0)
            elif col == 5:
                return float(w.get('shrunk_target_3m_rate', 0) or 0)
            elif col == 6:
                return float(w.get('profit_factor', 0) or 0)
            elif col == 7:
                return float(w.get('risk_adjusted_score', 0) or 0)
            elif col == 8:
                return float(w.get('skill_confidence', 0) or 0)
            elif col == 9:
                return str(w.get('skill_trend', ''))
            return 0

        self.filtered_wallets.sort(key=key_fn, reverse=not asc)
        self._render_table()

    def _render_table(self):
        if not self.filtered_wallets:
            self.table.hide()
            raw_role = self.cmb_role.currentText()
            role_filt = raw_role.split()[0].upper() if raw_role else "ALL"
            search = self.txt_search.text().strip()
            elig_filt = self.cmb_eligibility.currentText()

            if role_filt != "ALL":
                icon = "🐋" if role_filt == "WHALE" else "🎯" if role_filt == "SNIPER" else "📈" if role_filt == "TRADER" else "🕵️"
                criteria_msg = {
                    "WHALE": "average position sizing >= $1,000 across observed trades",
                    "SNIPER": ">= 60% entries under 1 minute from launch AND >= 5 trades",
                    "TRADER": ">= 15 directional trades and hold duration >= 3 minutes",
                    "RETAIL": "standard discretionary sizing",
                }.get(role_filt, f"{role_filt} behavioral rules")
                title = f"No {role_filt} Wallets in Registry"
                sub = f"No tracked wallets currently meet the {role_filt} criteria ({criteria_msg}). The quantitative model promotes wallets automatically as on-chain trades are observed."
            elif search:
                icon = "🔍"
                title = "Wallet Address Not Found"
                sub = f"No tracked wallets match address '{search}'. Verify the address or clear your search."
            elif elig_filt != "All Wallets":
                icon = "🛡️"
                title = f"No {elig_filt} Found"
                sub = f"No wallets currently match the '{elig_filt}' filter criteria."
            else:
                icon = "🕵️"
                title = "No Wallets Recorded"
                sub = "The on-chain smart money database is currently empty. Click Discover New Wallets to detect early buyers."

            self.empty_state.set_state(
                icon=icon,
                title=title,
                subtitle=sub,
                action_label="Reset All Filters",
                on_action=self._reset_filters
            )
            self.empty_state.show()
            return

        self.empty_state.hide()
        self.table.show()

        display_wallets = self.filtered_wallets[:self._max_display_rows] if self._max_display_rows > 0 else self.filtered_wallets
        self.table.setUpdatesEnabled(False)
        try:
            self.table.setRowCount(len(display_wallets))

            mono_font = QFont("Consolas")
            mono_font.setStyleHint(QFont.Monospace)
            mono_font.setPointSize(9)

            for i, w in enumerate(display_wallets):
                addr = str(w.get('wallet_address', ''))
                short_addr = f"{addr[:5]}...{addr[-4:]}" if len(addr) > 10 else addr

                # 0. WALLET ADDRESS
                it_addr = QTableWidgetItem(short_addr)
                it_addr.setFont(QFont("Consolas", 9, QFont.Bold))
                it_addr.setForeground(QColor("#f8fafc"))
                it_addr.setData(Qt.UserRole, addr)
                it_addr.setToolTip(f"Full Address: {addr}")
                self.table.setItem(i, 0, it_addr)

                # 1. INFERRED ROLE
                role = str(w.get('primary_role', 'RETAIL')).upper()
                role_colors = {
                    "TRADER": ("#38bdf8", "#082f49"),
                    "SNIPER": ("#fbbf24", "#451a03"),
                    "WHALE": ("#c084fc", "#3b0764"),
                    "RETAIL": ("#94a3b8", "#1e293b"),
                }
                col_fg, _ = role_colors.get(role, ("#94a3b8", "#1e293b"))
                it_role = QTableWidgetItem(role)
                it_role.setFont(QFont("Segoe UI", 8, QFont.Bold))
                it_role.setTextAlignment(Qt.AlignCenter)
                it_role.setForeground(QColor(col_fg))
                self.table.setItem(i, 1, it_role)

                # 2. TRADES
                tr = int(w.get('total_trades', 0) or 0)
                it_tr = QTableWidgetItem(str(tr))
                it_tr.setFont(mono_font)
                it_tr.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                it_tr.setForeground(QColor("#cbd5e1"))
                self.table.setItem(i, 2, it_tr)

                # 3. MATURE
                mat = int(w.get('mature_trades', 0) or 0)
                it_mat = QTableWidgetItem(str(mat))
                it_mat.setFont(mono_font)
                it_mat.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                it_mat.setForeground(QColor("#94a3b8"))
                self.table.setItem(i, 3, it_mat)

                # 4. SHRUNK WR
                swr = float(w.get('shrunk_win_rate', 0) or 0)
                it_swr = QTableWidgetItem(f"{swr:.1f}%")
                it_swr.setFont(mono_font)
                it_swr.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                it_swr.setForeground(QColor("#10b981" if swr >= 40 else "#38bdf8" if swr >= 20 else "#94a3b8"))
                self.table.setItem(i, 4, it_swr)

                # 5. 3M HIT RATE
                hr = float(w.get('shrunk_target_3m_rate', 0) or 0)
                it_hr = QTableWidgetItem(f"{hr:.1f}%")
                it_hr.setFont(mono_font)
                it_hr.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                it_hr.setForeground(QColor("#c084fc" if hr >= 15 else "#cbd5e1"))
                self.table.setItem(i, 5, it_hr)

                # 6. PROFIT FACTOR
                pf = float(w.get('profit_factor', 0) or 0)
                it_pf = QTableWidgetItem(f"{pf:.2f}")
                it_pf.setFont(mono_font)
                it_pf.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                it_pf.setForeground(QColor("#10b981" if pf >= 1.5 else "#94a3b8"))
                self.table.setItem(i, 6, it_pf)

                # 7. SKILL SCORE
                score = float(w.get('risk_adjusted_score', 0) or 0)
                it_score = QTableWidgetItem(f"{score:.3f}")
                it_score.setFont(mono_font)
                it_score.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                it_score.setForeground(QColor("#38bdf8" if score > 0.05 else "#64748b"))
                self.table.setItem(i, 7, it_score)

                # 8. CONFIDENCE
                conf = float(w.get('skill_confidence', 0) or 0)
                it_conf = QTableWidgetItem(f"{conf:.1%}")
                it_conf.setFont(mono_font)
                it_conf.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                it_conf.setForeground(QColor("#94a3b8"))
                self.table.setItem(i, 8, it_conf)

                # 9. TREND
                trend = str(w.get('skill_trend', 'NEUTRAL')).upper()
                if 'UP' in trend or 'POSITIVE' in trend:
                    trend_sym, trend_col = "▲ UP", "#10b981"
                elif 'DOWN' in trend or 'NEGATIVE' in trend:
                    trend_sym, trend_col = "▼ DN", "#ef4444"
                else:
                    trend_sym, trend_col = "—", "#64748b"
                it_trend = QTableWidgetItem(trend_sym)
                it_trend.setFont(QFont("Segoe UI", 8, QFont.Bold))
                it_trend.setTextAlignment(Qt.AlignCenter)
                it_trend.setForeground(QColor(trend_col))
                self.table.setItem(i, 9, it_trend)

                # 10. ACTIONS: Zero-overhead delegate item
                it_act = QTableWidgetItem()
                it_act.setData(Qt.UserRole, addr)
                it_act.setToolTip(f"Actions: [📋] Copy · [🌐] Explorer ({addr})")
                self.table.setItem(i, 10, it_act)
        finally:
            self.table.setUpdatesEnabled(True)

    def show_context_menu(self, pos):
        item = self.table.itemAt(pos)
        if not item: return
        addr = self.table.item(item.row(), 0).data(Qt.UserRole)

        menu = QMenu(self)
        menu.setStyleSheet("background-color: #0f172a; color: #f8fafc; border: 1px solid #1e293b;")

        act_copy = QAction("📋 Copy Wallet Address", self)
        act_copy.triggered.connect(lambda: QApplication.clipboard().setText(addr))

        act_exp = QAction("🌐 Open Explorer (Solscan / BaseScan)", self)
        def open_exp():
            if addr.startswith("0x"):
                webbrowser.open(f"https://basescan.org/address/{addr}")
            else:
                webbrowser.open(f"https://solscan.io/account/{addr}")
        act_exp.triggered.connect(open_exp)

        menu.addAction(act_copy)
        menu.addAction(act_exp)
        menu.exec(self.table.viewport().mapToGlobal(pos))
