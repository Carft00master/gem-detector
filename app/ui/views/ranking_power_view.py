from app.ui.components.help_icon import HelpIcon
"""
Ranking Power & Selection Lift View
Evaluates calibrated model decile lift, Wilson confidence intervals, and zero-positive guardrails.
Equipped with interactive guides (?), scope selectors, and decile lift analysis.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
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


class RankingPowerView(QWidget):
    COLS = [
        "PERCENTILE TIER", "POPULATION (N)", "MATURE (N)", "PENDING (N)", "3M WINNERS",
        "TIER TARGET RATE", "BASE RATE", "SELECTION LIFT", "95% CONF INTERVAL", "EVIDENCE STATUS"
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.research_svc: ResearchService = ServiceLocator.get(ResearchService)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(12)

        # 1. Top Controls Bar with (?) Guide
        ctrl_frame = QFrame()
        ctrl_frame.setStyleSheet("background-color: #0f141c; border: 1px solid #1f2937; border-radius: 6px; padding: 6px;")
        ctrl_layout = QHBoxLayout(ctrl_frame)

        lbl_scope = QLabel("Select Population Scope:")
        lbl_scope.setStyleSheet("font-weight: bold; color: #f3f4f6;")
        self.scope_combo = QComboBox()
        self.scope_combo.addItems([
            "FIRST_ALERT_OPPORTUNITIES (Primary Strategy Target)",
            "MODEL_ELIGIBLE (Feature-Complete Ingestion)",
            "CAPTURE_CONFIRMED (Discovered in Range)",
            "FULL_UNIVERSE (Complete Ingested Denominator)",
        ])
        self.scope_combo.currentIndexChanged.connect(self._on_scope_changed)

        scope_help = HelpIcon(
            "Stratifies candidate tokens into deciles to evaluate whether top-predicted tiers produce higher empirical "
            "win rates (Selection Lift) compared to the unranked population base rate.",
            "Ranking Power & Lift"
        )

        self.btn_refresh = QPushButton("↻ Refresh")
        self.btn_refresh.setCursor(Qt.PointingHandCursor)
        self.btn_refresh.clicked.connect(lambda: self.refresh_data(force=True))

        ctrl_layout.addWidget(lbl_scope)
        ctrl_layout.addWidget(self.scope_combo, 1)
        ctrl_layout.addWidget(scope_help)
        ctrl_layout.addWidget(self.btn_refresh)
        layout.addWidget(ctrl_frame)

        # 2. Scope Summary Cards
        stats_layout = QHBoxLayout()
        self.card_total_n = StatCard("Population Size", "0", "Evaluated Denominator", "#3b82f6")
        self.card_mature = StatCard("Mature Samples", "0", "Excluded In-Flight Pending", "#10b981")
        self.card_base_rate = StatCard("Empirical Base Rate", "0.0%", "Observed Prevalence", "#8b5cf6")
        self.card_pr_auc = StatCard("PR-AUC Metric", "N/A", "Zero-Positive Protected", "#f59e0b")

        stats_layout.addWidget(self.card_total_n)
        stats_layout.addWidget(self.card_mature)
        stats_layout.addWidget(self.card_base_rate)
        stats_layout.addWidget(self.card_pr_auc)
        layout.addLayout(stats_layout)

        # 3. Decile / Percentile Lift Table
        g_table = QGroupBox("📈 Calibrated Model Decile Stratification & Empirical Lift (Mature Evaluated)")
        l_table = QVBoxLayout(g_table)
        self.table = QTableWidget()
        self.table.setColumnCount(len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        l_table.addWidget(self.table)
        layout.addWidget(g_table)

        # Defer heavy data load until tab is first shown
        self._needs_refresh = True

    def showEvent(self, event):
        super().showEvent(event)
        if self._needs_refresh:
            self._needs_refresh = False
            self.refresh_data()

    def _on_scope_changed(self):
        self.refresh_data()

    def refresh_data(self, force: bool = False):
        animate_refresh_button(self.btn_refresh, True, "↻ Refresh")
        if force:
            self.research_svc.invalidate_merged_cache()

        def fetch():
            return self.research_svc.get_ranking_power_report()

        def on_done(multi):
            self._apply_data(multi)
            animate_refresh_button(self.btn_refresh, False, "↻ Refresh")

        def on_err(err):
            animate_refresh_button(self.btn_refresh, False, "↻ Refresh")

        run_async_task(fetch, on_done, on_err, parent=self)

    def _apply_data(self, multi):
        scope_text = self.scope_combo.currentText()

        if "FIRST_ALERT" in scope_text:
            rep = multi.first_alert_report
        elif "MODEL_ELIGIBLE" in scope_text:
            rep = multi.model_eligible_report
        elif "CAPTURE_CONFIRMED" in scope_text:
            rep = multi.capture_confirmed_report
        else:
            rep = multi.full_universe_report

        self.card_total_n.update_value(f"N = {rep.total_population_n}")
        self.card_mature.update_value(f"N = {rep.n_mature}", f"Pending: {rep.n_pending}")
        self.card_base_rate.update_value(f"{rep.population_base_rate:.2%}")
        self.card_pr_auc.update_value(rep.formatted_pr_auc)

        self.table.setUpdatesEnabled(False)
        try:
            self.table.setRowCount(len(rep.tiers))
            for row, t in enumerate(rep.tiers):
                ci_str = f"[{t.wilson_ci_95[0]:.1%}, {t.wilson_ci_95[1]:.1%}]" if (t.wilson_ci_95 and t.wilson_ci_95 != (0.0, 0.0)) else "[N/A]"
                items = [
                    QTableWidgetItem(t.tier_label),
                    QTableWidgetItem(str(t.total_candidates)),
                    QTableWidgetItem(str(rep.n_mature)),
                    QTableWidgetItem(str(rep.n_pending)),
                    QTableWidgetItem(str(t.hit_count_3m)),
                    QTableWidgetItem(f"{t.empirical_hit_rate:.1%}"),
                    QTableWidgetItem(f"{rep.population_base_rate:.2%}"),
                    QTableWidgetItem(t.formatted_lift),
                    QTableWidgetItem(ci_str),
                    QTableWidgetItem(rep.sample_guardrail_status),
                ]
                for col, itm in enumerate(items):
                    itm.setTextAlignment(Qt.AlignCenter if col != 0 else Qt.AlignLeft | Qt.AlignVCenter)
                    self.table.setItem(row, col, itm)
        finally:
            self.table.setUpdatesEnabled(True)


