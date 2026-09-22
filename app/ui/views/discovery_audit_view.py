from app.ui.components.help_icon import HelpIcon
"""
Discovery Audit & Ingestion Telemetry View
Audits token capture rate inside $8K-$35K, RPC/WebSocket latencies, and 11 failure cause codes.
Equipped with interactive guides (?), diagnostic metrics, and refresh controls.
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

from app.application.service_locator import ServiceLocator
from app.services.research_service import ResearchService
from app.ui.components.help_icon import QLabel
from app.ui.components.stat_card import StatCard
from app.ui.components.async_helper import run_async_task, animate_refresh_button


class DiscoveryAuditView(QWidget):
    CAUSE_COLS = ["CAUSE CODE", "NAME", "FAILURES (N)", "% OF TOTAL", "DIAGNOSTIC CRITERIA"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.research_svc: ResearchService = ServiceLocator.get(ResearchService)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(12)

        # 1. Top Stat Cards Bar with Guides
        stats_layout = QHBoxLayout()
        self.card_capture_rate = StatCard("Capture Rate", "0.0%", "Discovered in $8K-$35K", "#10b981")
        self.card_miss_rate = StatCard("Miss Rate", "0.0%", "First Seen >$35K", "#ef4444")
        self.card_uncertain_rate = StatCard("Uncertain Rate", "0.0%", "Telemetry Delay >5000ms", "#f59e0b")
        self.card_dqs_captured = StatCard("DQS (Captured)", "0.0/100", "Discovery Quality", "#3b82f6")
        self.card_dqs_full = StatCard("DQS (Full Universe)", "0.0/100", "Includes Missed/Uncertain", "#8b5cf6")

        stats_layout.addWidget(self.card_capture_rate)
        stats_layout.addWidget(self.card_miss_rate)
        stats_layout.addWidget(self.card_uncertain_rate)
        stats_layout.addWidget(self.card_dqs_captured)
        stats_layout.addWidget(self.card_dqs_full)
        layout.addLayout(stats_layout)

        # 2. Ingestion Quality Banner with Help & Refresh
        b_frame = QFrame()
        b_frame.setStyleSheet("background-color: #064e3b; border: 1px solid #10b981; border-radius: 6px; padding: 6px 12px;")
        b_layout = QHBoxLayout(b_frame)
        b_layout.setContentsMargins(4, 2, 4, 2)

        self.banner = QLabel("Ingestion Audit: 100% Invariant Partition (Universe = Captured + Missed + Uncertain)")
        self.banner.setStyleSheet("color: #a7f3d0; font-weight: bold; font-size: 11px;")

        disc_help = HelpIcon(
            "Audits how efficiently the engine captures candidate tokens while they are still in the $8K–$35K window. "
            "Evaluates RPC latency, WebSocket delay, and categorizes 11 discrete failure cause codes.",
            "Discovery Audit Invariant"
        )

        self.btn_refresh = QPushButton("↻ Refresh")
        self.btn_refresh.setCursor(Qt.PointingHandCursor)
        self.btn_refresh.setStyleSheet("background-color: #047857; color: #ffffff; border: 1px solid #34d399; padding: 4px 10px; border-radius: 4px; font-weight: bold;")
        self.btn_refresh.clicked.connect(lambda: self.refresh_data(force=True))

        b_layout.addWidget(self.banner, 1)
        b_layout.addWidget(disc_help)
        b_layout.addWidget(self.btn_refresh)
        layout.addWidget(b_frame)

        # 3. Failure Cause Codes Table
        g_causes = QGroupBox("🔍 11 Granular Discovery Failure Cause Diagnostics")
        l_causes = QVBoxLayout(g_causes)
        self.table_causes = QTableWidget()
        self.table_causes.setColumnCount(len(self.CAUSE_COLS))
        self.table_causes.setHorizontalHeaderLabels(self.CAUSE_COLS)
        self.table_causes.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table_causes.horizontalHeader().setStretchLastSection(True)
        self.table_causes.verticalHeader().setVisible(False)
        self.table_causes.setEditTriggers(QTableWidget.NoEditTriggers)
        l_causes.addWidget(self.table_causes)
        layout.addWidget(g_causes)

        # Defer heavy data load until tab is first shown
        self._needs_refresh = True

    def showEvent(self, event):
        super().showEvent(event)
        if self._needs_refresh:
            self._needs_refresh = False
            self.refresh_data()

    def refresh_data(self, force: bool = False):
        animate_refresh_button(self.btn_refresh, True, "↻ Refresh")
        if force:
            self.research_svc.invalidate_merged_cache()

        def fetch():
            return self.research_svc.get_discovery_audit_summary()

        def on_done(disc):
            self._apply_data(disc)
            animate_refresh_button(self.btn_refresh, False, "↻ Refresh")

        def on_err(err):
            animate_refresh_button(self.btn_refresh, False, "↻ Refresh")

        run_async_task(fetch, on_done, on_err, parent=self)

    def _apply_data(self, disc):
        self.card_capture_rate.update_value(f"{disc.universe_capture_rate_pct:.1f}%", f"{disc.discovery_captured_count}/{disc.total_tokens_evaluated} Tokens")
        self.card_miss_rate.update_value(f"{disc.discovery_miss_rate_pct:.1f}%", f"{disc.discovery_missed_count}/{disc.total_tokens_evaluated} Tokens")
        self.card_uncertain_rate.update_value(f"{disc.discovery_uncertain_rate_pct:.1f}%", f"{disc.discovery_uncertain_count}/{disc.total_tokens_evaluated} Tokens")
        self.card_dqs_captured.update_value(f"{disc.median_dqs_capture_confirmed:.1f}/100")
        self.card_dqs_full.update_value(f"{disc.median_dqs_full_universe:.1f}/100")

        self.table_causes.setUpdatesEnabled(False)
        try:
            self.table_causes.setRowCount(len(disc.failure_causes))
            for row, c in enumerate(disc.failure_causes):
                items = [
                    QTableWidgetItem(c.cause_code),
                    QTableWidgetItem(c.cause_code.replace("_", " ").title()),
                    QTableWidgetItem(str(c.count)),
                    QTableWidgetItem(f"{c.percentage:.1f}%"),
                    QTableWidgetItem(f"Median Latency: {c.median_latency_ms:.0f}ms, Lost: {c.median_time_lost_sec:.0f}s"),
                ]
                for col, itm in enumerate(items):
                    itm.setTextAlignment(Qt.AlignCenter if col in (0, 2, 3) else Qt.AlignLeft | Qt.AlignVCenter)
                    self.table_causes.setItem(row, col, itm)
        finally:
            self.table_causes.setUpdatesEnabled(True)

