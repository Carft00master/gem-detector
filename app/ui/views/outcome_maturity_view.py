from app.ui.components.help_icon import HelpIcon
"""
Outcome Maturity & Survival Analysis View
Displays horizon-specific maturity states, 4x7 target matrix, and Kaplan-Meier survival curves.
Equipped with interactive guides (?), column tooltips, and refresh controls.
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
from app.ui.components.async_helper import run_async_task, animate_refresh_button
from app.ui.components.stat_card import StatCard


class OutcomeMaturityView(QWidget):
    MATURITY_COLS = ["HORIZON", "TOTAL (N)", "MATURE", "PENDING", "CENSORED", "SUCCESS", "FAILURE", "RATE / MODEL", "EVIDENCE STATUS"]
    MATRIX_COLS = ["TARGET LEVEL", "HORIZON", "MATURE", "PENDING", "CENSORED", "SUCCESS", "FAILURE", "SUCCESS RATE / MODEL"]
    SURVIVAL_COLS = ["INTERVAL (t)", "AT RISK", "TARGET EVENTS", "TERMINAL RUGS", "CENSORED/PENDING", "SURVIVAL S(t)", "CUM TARGET PROB F(t)", "CUM RUG INCIDENCE"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.research_svc: ResearchService = ServiceLocator.get(ResearchService)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(12)

        # 1. Top Summary Banner with Help Guide
        b_frame = QFrame()
        b_frame.setStyleSheet("background-color: #1e3a8a; border: 1px solid #3b82f6; border-radius: 6px; padding: 6px 12px;")
        b_layout = QHBoxLayout(b_frame)
        b_layout.setContentsMargins(4, 2, 4, 2)

        self.banner = QLabel("Target 3M Outcome Maturity | Overall Evidence Status: INSUFFICIENT (N=0 < 25 at 24h)")
        self.banner.setStyleSheet("color: #93c5fd; font-weight: bold; font-size: 12px;")

        mat_help = HelpIcon(
            "Rigorous survival analysis framework. Active tokens are kept in PENDING state to prevent right-censoring "
            "bias until a terminal failure (rug/dump) or target touch occurs.",
            "Outcome Maturity Invariant"
        )

        self.btn_refresh = QPushButton("↻ Refresh")
        self.btn_refresh.setCursor(Qt.PointingHandCursor)
        self.btn_refresh.setStyleSheet("background-color: #1d4ed8; color: #ffffff; border: 1px solid #60a5fa; padding: 4px 10px; border-radius: 4px; font-weight: bold;")
        self.btn_refresh.clicked.connect(lambda: self.refresh_data(force=True))

        b_layout.addWidget(self.banner, 1)
        b_layout.addWidget(mat_help)
        b_layout.addWidget(self.btn_refresh)
        layout.addWidget(b_frame)

        # 2. Table: Primary Target 3M Outcome Maturity
        g_mat = QGroupBox("⏳ Primary Target $3M Outcome Maturity Dashboard across Horizons")
        l_mat = QVBoxLayout(g_mat)
        self.table_mat = QTableWidget()
        self.table_mat.setColumnCount(len(self.MATURITY_COLS))
        self.table_mat.setHorizontalHeaderLabels(self.MATURITY_COLS)
        self.table_mat.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table_mat.horizontalHeader().setStretchLastSection(True)
        self.table_mat.verticalHeader().setVisible(False)
        self.table_mat.setEditTriggers(QTableWidget.NoEditTriggers)
        l_mat.addWidget(self.table_mat)
        layout.addWidget(g_mat)

        # 3. Table: Kaplan-Meier Survival Analysis
        g_surv = QGroupBox("📈 Non-Parametric Kaplan-Meier & Competing-Risk Survival Curve")
        l_surv = QVBoxLayout(g_surv)
        self.table_surv = QTableWidget()
        self.table_surv.setColumnCount(len(self.SURVIVAL_COLS))
        self.table_surv.setHorizontalHeaderLabels(self.SURVIVAL_COLS)
        self.table_surv.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table_surv.verticalHeader().setVisible(False)
        self.table_surv.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table_surv.setFixedHeight(170)
        l_surv.addWidget(self.table_surv)
        layout.addWidget(g_surv)

        # 4. Table: 4x7 Empirical Matrix
        g_grid = QGroupBox("🎯 4x7 Multi-Target × Multi-Horizon Empirical Matrix")
        l_grid = QVBoxLayout(g_grid)
        self.table_grid = QTableWidget()
        self.table_grid.setColumnCount(len(self.MATRIX_COLS))
        self.table_grid.setHorizontalHeaderLabels(self.MATRIX_COLS)
        self.table_grid.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table_grid.horizontalHeader().setStretchLastSection(True)
        self.table_grid.verticalHeader().setVisible(False)
        self.table_grid.setEditTriggers(QTableWidget.NoEditTriggers)
        l_grid.addWidget(self.table_grid)
        layout.addWidget(g_grid)

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
            dash = self.research_svc.get_outcome_maturity_dashboard()
            surv = self.research_svc.get_survival_analysis("TARGET_3M")
            return dash, surv

        def on_done(res):
            dash, surv = res
            self._apply_data(dash, surv)
            animate_refresh_button(self.btn_refresh, False, "↻ Refresh")

        def on_err(err):
            animate_refresh_button(self.btn_refresh, False, "↻ Refresh")

        run_async_task(fetch, on_done, on_err, parent=self)

    def _apply_data(self, dash, surv):
        self.banner.setText(f"Target 3M Outcome Maturity | Overall Evidence Status: {dash.overall_evidence_status} | Survival Status: {surv.status_label}")

        # Populate Primary Maturity Table
        self.table_mat.setUpdatesEnabled(False)
        try:
            self.table_mat.setRowCount(len(dash.horizon_summary_rows))
            for row, r in enumerate(dash.horizon_summary_rows):
                items = [
                    QTableWidgetItem(r.horizon_name),
                    QTableWidgetItem(str(r.n_total)),
                    QTableWidgetItem(str(r.n_mature)),
                    QTableWidgetItem(str(r.n_pending)),
                    QTableWidgetItem(str(r.n_censored)),
                    QTableWidgetItem(str(r.n_success)),
                    QTableWidgetItem(str(r.n_failure)),
                    QTableWidgetItem(r.formatted_success_rate),
                    QTableWidgetItem(r.evidence_status),
                ]
                for col, itm in enumerate(items):
                    itm.setTextAlignment(Qt.AlignCenter if col != 0 else Qt.AlignLeft | Qt.AlignVCenter)
                    self.table_mat.setItem(row, col, itm)
        finally:
            self.table_mat.setUpdatesEnabled(True)

        # Populate Survival Table
        self.table_surv.setUpdatesEnabled(False)
        try:
            self.table_surv.setRowCount(len(surv.intervals))
            for row, inv in enumerate(surv.intervals):
                items = [
                    QTableWidgetItem(inv.interval_label),
                    QTableWidgetItem(str(inv.n_at_risk)),
                    QTableWidgetItem(str(inv.n_target_events)),
                    QTableWidgetItem(str(inv.n_competing_risk_events)),
                    QTableWidgetItem(str(inv.n_censored)),
                    QTableWidgetItem(f"{inv.kaplan_meier_survival:.4f}"),
                    QTableWidgetItem(inv.formatted_event_prob),
                    QTableWidgetItem(inv.formatted_risk_incidence),
                ]
                for col, itm in enumerate(items):
                    itm.setTextAlignment(Qt.AlignCenter if col != 0 else Qt.AlignLeft | Qt.AlignVCenter)
                    self.table_surv.setItem(row, col, itm)
        finally:
            self.table_surv.setUpdatesEnabled(True)

        # Populate 4x7 Matrix
        self.table_grid.setUpdatesEnabled(False)
        try:
            self.table_grid.setRowCount(len(dash.matrix_rows))
            for row, r in enumerate(dash.matrix_rows):
                items = [
                    QTableWidgetItem(r.target_name),
                    QTableWidgetItem(r.horizon_name),
                    QTableWidgetItem(str(r.n_mature)),
                    QTableWidgetItem(str(r.n_pending)),
                    QTableWidgetItem(str(r.n_censored)),
                    QTableWidgetItem(str(r.n_success)),
                    QTableWidgetItem(str(r.n_failure)),
                    QTableWidgetItem(r.formatted_success_rate),
                ]
                for col, itm in enumerate(items):
                    itm.setTextAlignment(Qt.AlignCenter if col not in (0, 7) else Qt.AlignLeft | Qt.AlignVCenter)
                    self.table_grid.setItem(row, col, itm)
        finally:
            self.table_grid.setUpdatesEnabled(True)


