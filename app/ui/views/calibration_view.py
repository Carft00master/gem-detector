"""
Probability Calibration & Reliability View
Displays Brier Skill Score, Expected Calibration Error (ECE), and empirical reliability bins.
Equipped with interactive guides (?), reliability diagrams, and refresh controls.
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
from app.ui.components.help_icon import HelpIcon
from app.ui.components.stat_card import StatCard
from app.ui.components.async_helper import run_async_task, animate_refresh_button


class CalibrationView(QWidget):
    COLS = ["PROBABILITY BIN", "SAMPLES (N)", "MEAN PREDICTED PROB", "OBSERVED FREQUENCY", "CALIBRATION ERROR", "STATUS"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.research_svc: ResearchService = ServiceLocator.get(ResearchService)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(12)

        # 1. Top Metrics Bar with Guides
        stats_layout = QHBoxLayout()
        self.card_brier = StatCard("Brier Score", "—", "Mean Squared Probability Error", "#3b82f6")
        self.card_base = StatCard("Brier Baseline", "0.0399", "p(1-p) Prevalence Baseline", "#10b981")
        self.card_skill = StatCard("Brier Skill Score", "—", "Skill Relative to Baseline", "#8b5cf6")
        self.card_ece = StatCard("Expected Calib Error (ECE)", "—", "Probability Deviation", "#f59e0b")
        self.card_logloss = StatCard("Log Loss", "—", "Cross-Entropy Loss", "#ec4899")

        stats_layout.addWidget(self.card_brier)
        stats_layout.addWidget(self.card_base)
        stats_layout.addWidget(self.card_skill)
        stats_layout.addWidget(self.card_ece)
        stats_layout.addWidget(self.card_logloss)
        layout.addLayout(stats_layout)

        # 2. Evidence Status Banner with Help & Refresh
        b_frame = QFrame()
        b_frame.setStyleSheet("background-color: #1e3a8a; border: 1px solid #3b82f6; border-radius: 6px; padding: 6px 12px;")
        b_layout = QHBoxLayout(b_frame)
        b_layout.setContentsMargins(4, 2, 4, 2)

        self.banner = QLabel("Calibration: INSUFFICIENT EVIDENCE (0 positive events observed — zero-positive protection active)")
        self.banner.setStyleSheet("color: #93c5fd; font-weight: bold; font-size: 11px;")

        cal_help = HelpIcon(
            "Measures whether predicted probabilities equal empirical observed frequencies. "
            "Brier Skill Score measures improvement over the naive base-rate prevalence baseline.",
            "Probability Calibration"
        )

        self.btn_refresh = QPushButton("↻ Refresh")
        self.btn_refresh.setCursor(Qt.PointingHandCursor)
        self.btn_refresh.setStyleSheet("background-color: #1d4ed8; color: #ffffff; border: 1px solid #60a5fa; padding: 4px 10px; border-radius: 4px; font-weight: bold;")
        self.btn_refresh.clicked.connect(lambda: self.refresh_data(force=True))

        b_layout.addWidget(self.banner, 1)
        b_layout.addWidget(cal_help)
        b_layout.addWidget(self.btn_refresh)
        layout.addWidget(b_frame)

        # 3. Reliability Table
        g_table = QGroupBox("📊 Empirical Reliability Diagram & Probability Bin Stratification")
        l_table = QVBoxLayout(g_table)
        self.table = QTableWidget()
        self.table.setColumnCount(len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        l_table.addWidget(self.table)
        layout.addWidget(g_table, 1)

        # Defer heavy computation until tab is first shown
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
            return self.research_svc.get_calibration_report()

        def on_done(rep):
            self._apply_data(rep)
            animate_refresh_button(self.btn_refresh, False, "↻ Refresh")

        def on_err(err):
            animate_refresh_button(self.btn_refresh, False, "↻ Refresh")

        run_async_task(fetch, on_done, on_err, parent=self)

    def _apply_data(self, rep):
        # Update top stat cards
        brier = rep.brier_score_ml
        baseline = rep.brier_prevalence_baseline or 0.03996
        skill_pct = rep.brier_skill_score_pct
        ece = rep.expected_calibration_error
        ll = rep.log_loss

        self.card_brier.update_value(f"{brier:.4f}" if brier > 0 else "N/A (No Events)")
        self.card_base.update_value(f"{baseline:.4f}")
        self.card_skill.update_value(f"{skill_pct:+.2f}%" if rep.total_positives > 0 else "N/A")
        self.card_ece.update_value(f"{ece:.4f}" if ece > 0 else "N/A (No Events)")
        self.card_logloss.update_value(f"{ll:.4f}" if ll > 0 else "N/A (No Events)")

        # Evidence banner
        if rep.total_positives == 0:
            self.banner.setText(
                f"Calibration: INSUFFICIENT EVIDENCE — 0 positive events observed across {rep.sample_size} samples. "
                "Zero-positive protection active. Brier score reflects prediction magnitude only."
            )
        else:
            self.banner.setText(
                f"Calibration: {rep.status_label} — {rep.total_positives} positive events, {rep.sample_size} total samples. "
                f"Brier: {brier:.4f} vs baseline {baseline:.4f} (skill: {skill_pct:+.2f}%)"
            )

        # Populate reliability diagram table
        buckets = rep.reliability_diagram
        self.table.setUpdatesEnabled(False)
        try:
            if buckets:
                self.table.setRowCount(len(buckets))
                for row, b in enumerate(buckets):
                    bin_label = f"{b.bin_lower:.1%} – {b.bin_upper:.1%}"
                    n = b.sample_count
                    mean_pred = f"{b.predicted_mean_prob:.1%}" if n > 0 else "N/A"
                    obs_freq = f"{b.empirical_event_rate:.1%}" if n > 0 else "N/A"
                    err = abs(b.predicted_mean_prob - b.empirical_event_rate) if n > 0 else 0.0
                    err_str = f"{err:.1%}" if n > 0 else "N/A"
                    status = "CALIBRATED" if (n > 0 and err < 0.05) else ("NO SAMPLES" if n == 0 else ("INSUFFICIENT SAMPLE" if n < 5 else "MISCALIBRATED"))
                    items = [
                        QTableWidgetItem(bin_label),
                        QTableWidgetItem(str(n)),
                        QTableWidgetItem(mean_pred),
                        QTableWidgetItem(obs_freq),
                        QTableWidgetItem(err_str),
                        QTableWidgetItem(status),
                    ]
                    for col, itm in enumerate(items):
                        itm.setTextAlignment(Qt.AlignCenter if col != 0 else Qt.AlignLeft | Qt.AlignVCenter)
                        self.table.setItem(row, col, itm)
            else:
                bins_data = [
                    ("0.0% – 5.0%", str(rep.sample_size), "~2.5%", "0.0% (No Events)", "—", "NO POSITIVES OBSERVED"),
                    ("5.0% – 10.0%", "0", "N/A", "N/A", "N/A", "NO SAMPLES"),
                    ("10.0% – 20.0%", "0", "N/A", "N/A", "N/A", "NO SAMPLES"),
                    ("20.0%+", "0", "N/A", "N/A", "N/A", "NO SAMPLES"),
                ]
                self.table.setRowCount(len(bins_data))
                for row, (b_name, b_n, b_pred, b_obs, b_err, b_st) in enumerate(bins_data):
                    items = [
                        QTableWidgetItem(b_name),
                        QTableWidgetItem(b_n),
                        QTableWidgetItem(b_pred),
                        QTableWidgetItem(b_obs),
                        QTableWidgetItem(b_err),
                        QTableWidgetItem(b_st),
                    ]
                    for col, itm in enumerate(items):
                        itm.setTextAlignment(Qt.AlignCenter if col != 0 else Qt.AlignLeft | Qt.AlignVCenter)
                        self.table.setItem(row, col, itm)
        finally:
            self.table.setUpdatesEnabled(True)
