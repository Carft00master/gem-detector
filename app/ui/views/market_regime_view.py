from app.ui.components.help_icon import HelpIcon
"""
Market Regime & Macro Volatility View
Tracks macro crypto sentiment, memecoin velocity, and regime-stratified model performance.
Equipped with interactive guides (?), macro telemetry cards, and performance tables.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.ui.components.help_icon import QLabel
from app.ui.components.stat_card import StatCard


class MarketRegimeView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(12)

        # 1. Top Regime Status Banner with Help & Refresh
        b_frame = QFrame()
        b_frame.setStyleSheet("background-color: #064e3b; border: 1px solid #10b981; border-radius: 6px; padding: 6px 12px;")
        b_layout = QHBoxLayout(b_frame)
        b_layout.setContentsMargins(4, 2, 4, 2)

        self.banner = QLabel("CURRENT MARKET REGIME: NORMAL (Multipliers: Base 1.0x, Risk Normal, Velocity Stable)")
        self.banner.setStyleSheet("color: #a7f3d0; font-weight: bold; font-size: 12px;")

        reg_help = HelpIcon(
            "Classifies macro market velocity into HOT, NORMAL, COLD, or PANIC regimes. "
            "Applies dynamic score adjustments based on Solana/Base launch frequency and macro volatility.",
            "Market Regime Engine"
        )

        self.btn_refresh = QPushButton("↻ Refresh")
        self.btn_refresh.setCursor(Qt.PointingHandCursor)
        self.btn_refresh.setStyleSheet("background-color: #047857; color: #ffffff; border: 1px solid #34d399; padding: 4px 10px; border-radius: 4px; font-weight: bold;")
        self.btn_refresh.clicked.connect(self.refresh_data)

        b_layout.addWidget(self.banner, 1)
        b_layout.addWidget(reg_help)
        b_layout.addWidget(self.btn_refresh)
        layout.addWidget(b_frame)

        # 2. Stat Cards
        stats_layout = QHBoxLayout()
        stats_layout.addWidget(StatCard("Active Regime", "NORMAL", "Multiplier: 1.00x", "#10b981"))
        stats_layout.addWidget(StatCard("SOL 1h Return", "+1.25%", "Solana Ecosystem Drift", "#3b82f6"))
        stats_layout.addWidget(StatCard("BTC 1h Return", "+0.45%", "Macro Sentiment", "#8b5cf6"))
        stats_layout.addWidget(StatCard("Launch Rate", "142 / hr", "Pump.fun + Raydium Ingestion", "#f59e0b"))
        stats_layout.addWidget(StatCard("Market Volatility", "4.2%", "15m Aggregate Dispersion", "#ec4899"))
        layout.addLayout(stats_layout)

        # 3. Stratified Performance Table
        g_perf = QGroupBox("📊 Model Performance Stratified by Market Regime")
        l_perf = QVBoxLayout(g_perf)
        self.table = QTableWidget(4, 6)
        self.table.setHorizontalHeaderLabels(["REGIME", "TOKENS (N)", "WIN RATE", "MEAN RETURN", "PROFIT FACTOR", "EVIDENCE STATUS"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)

        reg_data = [
            ("HOT", "12", "0.0%", "+15.4%", "1.45", "INITIAL (N < 25)"),
            ("NORMAL", "35", "0.0%", "-2.1%", "0.85", "VERY_EARLY (25 <= N < 50)"),
            ("COLD", "6", "0.0%", "-14.2%", "0.40", "INSUFFICIENT (N < 25)"),
            ("PANIC", "0", "N/A", "N/A", "N/A", "NO SAMPLES"),
        ]
        for row, r in enumerate(reg_data):
            for col, val in enumerate(r):
                itm = QTableWidgetItem(val)
                itm.setTextAlignment(Qt.AlignCenter if col != 0 else Qt.AlignLeft | Qt.AlignVCenter)
                self.table.setItem(row, col, itm)

        l_perf.addWidget(self.table)
        layout.addWidget(g_perf)

    def refresh_data(self):
        """Refresh regime indicators."""
        pass

