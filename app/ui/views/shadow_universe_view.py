from app.ui.components.help_icon import HelpIcon
"""
Shadow Universe Denominator View
Complete denominator population browser preventing survivorship bias.
Equipped with interactive guides (?), search filters, and population classifiers.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.application.service_locator import ServiceLocator
from app.services.research_service import ResearchService
from app.ui.components.help_icon import QLabel
from app.ui.components.stat_card import StatCard
from app.ui.components.async_helper import run_async_task


class ShadowUniverseView(QWidget):
    COLS = [
        "TOKEN", "CHAIN", "DISCOVERY STATUS", "DQS", "ELIGIBLE", "ALERTED", 
        "TRADEABLE", "OUTCOME STATUS", "MARKET CAP", "LIQUIDITY", "P(3M)", "REGIME"
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.research_svc = ServiceLocator.get(ResearchService)
        self.tokens = []
        self._loading = False
        self._setup_ui()
        self.refresh_data()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Header
        header = QLabel("🌌  Shadow Universe Denominator & Discovery Population")
        header.setStyleSheet("font-size: 16px; font-weight: bold; color: #f8fafc;")
        layout.addWidget(header)

        # Controls
        ctrl_layout = QHBoxLayout()
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Filter by symbol or address...")
        self.search_box.textChanged.connect(self._apply_filter)
        ctrl_layout.addWidget(self.search_box)

        self.status_filter = QComboBox()
        self.status_filter.addItems(["ALL", "CAPTURE_CONFIRMED", "DISCOVERY_MISSED", "DISCOVERY_UNCERTAIN", "MODEL_ELIGIBLE", "FIRST_ALERT"])
        self.status_filter.currentTextChanged.connect(self._apply_filter)
        ctrl_layout.addWidget(self.status_filter)

        btn_refresh = QPushButton("↻ Refresh")
        btn_refresh.clicked.connect(self.refresh_data)
        ctrl_layout.addWidget(btn_refresh)

        layout.addLayout(ctrl_layout)

        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table)

    def _apply_filter(self):
        self._render_table()

    def refresh_data(self):
        if getattr(self, '_loading', False):
            return

        def fetch():
            return self.research_svc.get_shadow_tokens() or []

        def on_done(tokens):
            self._loading = False
            self.tokens = tokens
            self._render_table()

        def on_err(err):
            self._loading = False

        self._loading = True
        run_async_task(fetch, on_done, on_err, parent=self)

    def _render_table(self):
        search = self.search_box.text().strip().lower()
        filter_status = self.status_filter.currentText()

        filtered = []
        for t in self.tokens:
            sym = str(t.get("symbol", "")).lower()
            addr = str(t.get("token_address", "")).lower()
            if search and (search not in sym and search not in addr):
                continue
            if filter_status == "CAPTURE_CONFIRMED" and t.get("discovery_status") != "CAPTURE_CONFIRMED":
                continue
            elif filter_status == "DISCOVERY_MISSED" and t.get("discovery_status") != "DISCOVERY_MISSED":
                continue
            elif filter_status == "DISCOVERY_UNCERTAIN" and t.get("discovery_status") != "DISCOVERY_UNCERTAIN":
                continue
            elif filter_status == "MODEL_ELIGIBLE" and not t.get("is_model_eligible"):
                continue
            elif filter_status == "FIRST_ALERT" and not t.get("is_first_alert"):
                continue
            filtered.append(t)

        display_tokens = filtered[:100]
        self.table.setUpdatesEnabled(False)
        try:
            self.table.setRowCount(len(display_tokens))
            for row, t in enumerate(display_tokens):
                row_data = [
                    (f"{t.get('symbol', 'SYM')} ({t.get('token_address', '')[:6]})", Qt.AlignLeft | Qt.AlignVCenter),
                    (str(t.get("chain", "solana")).upper(), Qt.AlignCenter),
                    (str(t.get("discovery_status", "CAPTURE_CONFIRMED")), Qt.AlignCenter),
                    (f"{float(t.get('discovery_quality_score', 85.0) or 85.0):.0f}/100", Qt.AlignCenter),
                    ("ELIGIBLE" if t.get("is_model_eligible", True) else "INCOMPLETE", Qt.AlignCenter),
                    ("ALERTED" if t.get("is_alerted", False) else "-", Qt.AlignCenter),
                    ("YES" if t.get("is_tradeable", False) else "NO", Qt.AlignCenter),
                    (str(t.get("outcome_status", "PENDING")), Qt.AlignCenter),
                    (f"${float(t.get('market_cap_usd', 0.0) or 0.0):,.0f}", Qt.AlignRight | Qt.AlignVCenter),
                    (f"${float(t.get('liquidity_usd', 0.0) or 0.0):,.0f}", Qt.AlignRight | Qt.AlignVCenter),
                    (f"{float(t.get('p_reach_3m', 0.05) or 0.05):.1%}", Qt.AlignCenter),
                    (str(t.get("regime", "NORMAL")), Qt.AlignCenter),
                ]
                for col, (text, align) in enumerate(row_data):
                    itm = self.table.item(row, col)
                    if itm is None:
                        itm = QTableWidgetItem()
                        self.table.setItem(row, col, itm)
                    itm.setText(text)
                    itm.setTextAlignment(align)
        finally:
            self.table.setUpdatesEnabled(True)
