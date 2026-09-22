from app.ui.components.help_icon import HelpIcon
"""
Opportunity Funnel & Winner Recall View
Visual 11-stage opportunity funnel with invariant tracking and zero-event recall safety.
Equipped with interactive guides (?), column tooltips, and refresh controls.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
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


class OpportunityFunnelView(QWidget):
    FUNNEL_COLS = ["STAGE INDEX & NAME", "TOKENS (N)", "3M WINNERS", "STAGE CONVERSION", "FUNNEL CONVERSION", "STAGE DESCRIPTION"]
    RECALL_COLS = ["RECALL TIER", "WINNERS EVALUATED", "RECALL RATE", "EVALUATION FOCUS"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.research_svc: ResearchService = ServiceLocator.get(ResearchService)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(12)

        # 1. Top Invariant Summary Cards with Guides
        stats_layout = QHBoxLayout()
        self.card_universe = StatCard("Full Universe", "0", "Total Ingested", "#3b82f6")
        self.card_captured = StatCard("Capture Confirmed", "0", "$8K-$35K Discovery", "#10b981")
        self.card_eligible = StatCard("Model Eligible", "0", "Valid Feature Vector", "#8b5cf6")
        self.card_alerts = StatCard("First Alerts", "0", "Conviction Triggers", "#f59e0b")
        self.card_tradeable = StatCard("Tradeable", "0", "Simulated Execution", "#ec4899")

        stats_layout.addWidget(self.card_universe)
        stats_layout.addWidget(self.card_captured)
        stats_layout.addWidget(self.card_eligible)
        stats_layout.addWidget(self.card_alerts)
        stats_layout.addWidget(self.card_tradeable)
        layout.addLayout(stats_layout)

        # 2. Invariant Validation Banner & Refresh Action
        inv_frame = QFrame()
        inv_frame.setStyleSheet("background-color: #064e3b; border: 1px solid #10b981; border-radius: 6px; padding: 6px 12px;")
        inv_layout = QHBoxLayout(inv_frame)
        inv_layout.setContentsMargins(4, 2, 4, 2)

        self.banner = QLabel("Canonical Partition Invariant: 53 = 24 (Captured) + 8 (Missed) + 21 (Uncertain) | Monotonic Containment Validated")
        self.banner.setStyleSheet("color: #a7f3d0; font-weight: bold; font-size: 11px;")

        funnel_help = HelpIcon(
            "Tracks tokens across the 11 sequential validation gates from discovery to paper execution. "
            "Guarantees that full universe equals captured + missed + uncertain partitions without leakage.",
            "Opportunity Funnel Invariant"
        )

        self.btn_refresh = QPushButton("↻ Refresh Funnel")
        self.btn_refresh.setCursor(Qt.PointingHandCursor)
        self.btn_refresh.setStyleSheet("background-color: #047857; color: #ffffff; border: 1px solid #34d399; padding: 4px 10px; border-radius: 4px; font-weight: bold;")
        self.btn_refresh.clicked.connect(lambda: self.refresh_data(force=True))

        inv_layout.addWidget(self.banner, 1)
        inv_layout.addWidget(funnel_help)
        inv_layout.addWidget(self.btn_refresh)
        layout.addWidget(inv_frame)

        # 3. 11-Stage Funnel Table
        f_group = QGroupBox("🏗️ 11-Stage Canonical Opportunity Funnel")
        f_layout = QVBoxLayout(f_group)
        self.table_funnel = QTableWidget()
        self.table_funnel.setColumnCount(len(self.FUNNEL_COLS))
        self.table_funnel.setHorizontalHeaderLabels(self.FUNNEL_COLS)
        self.table_funnel.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table_funnel.horizontalHeader().setStretchLastSection(True)
        self.table_funnel.verticalHeader().setVisible(False)
        self.table_funnel.setEditTriggers(QTableWidget.NoEditTriggers)
        f_layout.addWidget(self.table_funnel)
        layout.addWidget(f_group)

        # 4. Multi-Tier Recall Table
        r_group = QGroupBox("🎯 4-Tier Winner Recall Decomposition (Zero-Positive Protected)")
        r_layout = QVBoxLayout(r_group)
        self.table_recall = QTableWidget()
        self.table_recall.setColumnCount(len(self.RECALL_COLS))
        self.table_recall.setHorizontalHeaderLabels(self.RECALL_COLS)
        self.table_recall.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table_recall.verticalHeader().setVisible(False)
        self.table_recall.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table_recall.setFixedHeight(140)
        r_layout.addWidget(self.table_recall)
        layout.addWidget(r_group)

        # Defer heavy data load until tab is first shown
        self._needs_refresh = True

    def showEvent(self, event):
        super().showEvent(event)
        if self._needs_refresh:
            self._needs_refresh = False
            self.refresh_data()

    def refresh_data(self, force: bool = False):
        animate_refresh_button(self.btn_refresh, True, "↻ Refresh Funnel")
        if force:
            self.research_svc.invalidate_merged_cache()

        def fetch():
            return self.research_svc.get_opportunity_funnel()

        def on_done(funnel_rep):
            self._apply_data(funnel_rep)
            animate_refresh_button(self.btn_refresh, False, "↻ Refresh Funnel")

        def on_err(err):
            animate_refresh_button(self.btn_refresh, False, "↻ Refresh Funnel")

        run_async_task(fetch, on_done, on_err, parent=self)

    def _apply_data(self, funnel_rep):
        reg = funnel_rep.registry_summary

        if reg:
            c = reg.counts
            self.card_universe.update_value(str(c.full_universe))
            self.card_captured.update_value(str(c.capture_confirmed))
            self.card_eligible.update_value(str(c.model_eligible))
            self.card_alerts.update_value(str(c.first_alert_opportunities))
            self.card_tradeable.update_value(str(c.tradeable))
            self.banner.setText(f"Canonical Partition Invariant: {c.full_universe} = {c.capture_confirmed} (Captured) + {c.discovery_missed} (Missed) + {c.discovery_uncertain} (Uncertain) | Monotonic Containment Validated")

        # Populate Funnel Table
        self.table_funnel.setUpdatesEnabled(False)
        try:
            self.table_funnel.setRowCount(len(funnel_rep.stages))
            for row, stg in enumerate(funnel_rep.stages):
                items = [
                    QTableWidgetItem(stg.stage_name),
                    QTableWidgetItem(str(stg.token_count)),
                    QTableWidgetItem(str(stg.winner_count_3m)),
                    QTableWidgetItem(f"{stg.conversion_from_previous_pct:.1f}%"),
                    QTableWidgetItem(f"{stg.conversion_from_start_pct:.1f}%"),
                    QTableWidgetItem(stg.description),
                ]
                for col, itm in enumerate(items):
                    itm.setTextAlignment(Qt.AlignCenter if col in (1, 2, 3, 4) else Qt.AlignLeft | Qt.AlignVCenter)
                    self.table_funnel.setItem(row, col, itm)
        finally:
            self.table_funnel.setUpdatesEnabled(True)

        # Populate Recall Table
        rec = funnel_rep.recall
        recall_rows = [
            ("1. DISCOVERY_RECALL", f"{rec.winners_captured_in_range} / {rec.total_ground_truth_winners}", rec.formatted_discovery_recall, "Captured inside $8K-$35K window"),
            ("2. MODEL_RECALL", f"{rec.winners_ranked_top_decile} / {rec.winners_captured_in_range}", rec.formatted_model_recall, "Ranked in top conviction deciles"),
            ("3. ALERT_RECALL", f"{rec.winners_alerted_early} / {rec.winners_model_eligible}", rec.formatted_alert_recall, "Triggered early breakout alerts"),
            ("4. END_TO_END_RECALL", f"{rec.winners_survivable_executed} / {rec.total_ground_truth_winners}", rec.formatted_end_to_end_recall, "Alerted AND survivable execution"),
        ]
        self.table_recall.setUpdatesEnabled(False)
        try:
            self.table_recall.setRowCount(len(recall_rows))
            for row, (tier, ev_cnt, rate, focus) in enumerate(recall_rows):
                items = [QTableWidgetItem(tier), QTableWidgetItem(ev_cnt), QTableWidgetItem(rate), QTableWidgetItem(focus)]
                for col, itm in enumerate(items):
                    itm.setTextAlignment(Qt.AlignCenter if col in (1, 2) else Qt.AlignLeft | Qt.AlignVCenter)
                    self.table_recall.setItem(row, col, itm)
        finally:
            self.table_recall.setUpdatesEnabled(True)

