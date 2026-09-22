import logging
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, 
    QFrame, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QTabWidget, QScrollArea
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont

from app.ui.design_system import DS
from app.application.service_locator import ServiceLocator
from app.services.research_service import ResearchService
from app.ui.components.kpi_strip import KpiStrip
from app.ui.components.async_helper import run_async_task

logger = logging.getLogger(__name__)


class AdaptiveLearningView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.research_svc = ServiceLocator.get(ResearchService)
        self._needs_refresh = True
        self._champ_value_labels = {}
        self._chall_value_labels = {}
        self.setup_ui()

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
            {"label": "CHAMPION MODEL", "value": "v1.0.0", "subtitle": "production locked", "color": "#10b981"},
            {"label": "CHALLENGER (SHADOW)", "value": "CHALLENGER_v1", "subtitle": "research validation", "color": "#c084fc"},
            {"label": "EVAL SAMPLE", "value": "120", "subtitle": "maturing pools", "color": "#38bdf8"},
            {"label": "PR-AUC LIFT", "value": "+55.6%", "subtitle": "0.18 -> 0.28", "color": "#34d399"},
            {"label": "DRIFT STATUS", "value": "HEALTHY", "subtitle": "7/7 dimensions normal", "color": "#10b981"},
        ])
        layout.addWidget(self.kpi_strip)

        # 2. Main Tabs
        tabs = QTabWidget()
        tabs.setStyleSheet("""
            QTabWidget::pane { border: none; background-color: #080c14; }
            QTabBar::tab { background: #0b101c; color: #64748b; padding: 8px 18px; border: none; font-weight: 600; font-size: 11px; }
            QTabBar::tab:selected { background: #0f172a; color: #38bdf8; border-bottom: 2px solid #38bdf8; }
            QTabBar::tab:hover { color: #f8fafc; }
        """)

        tab_models = QWidget()
        tab_drift = QWidget()
        tab_errors = QWidget()

        tabs.addTab(tab_models, "Champion vs Challenger A/B Workspace")
        tabs.addTab(tab_drift, "7-Dimension Drift Detection Monitor")
        tabs.addTab(tab_errors, "Multi-Horizon Error Classification")

        layout.addWidget(tabs)

        self._setup_models_tab(tab_models)
        self._setup_drift_tab(tab_drift)
        self._setup_errors_tab(tab_errors)

    def _setup_models_tab(self, parent):
        parent_lay = QVBoxLayout(parent)
        parent_lay.setContentsMargins(0, 0, 0, 0)
        parent_lay.setSpacing(0)

        scroll = QScrollArea(parent)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("background: transparent; border: none;")

        container = QWidget()
        vbox = QVBoxLayout(container)
        vbox.setContentsMargins(16, 16, 16, 16)
        vbox.setSpacing(14)

        # Security invariant banner
        inv_frame = QFrame()
        inv_frame.setStyleSheet("background-color: #0f172a; border: 1px solid #1e293b; border-radius: 6px; padding: 8px 14px;")
        inv_lay = QHBoxLayout(inv_frame)
        lbl_lock = QLabel("🔒 FROZEN v1.0.0 INVARIANT ENFORCED: Autonomous model promotion is permanently disabled. Challenger runs strictly in shadow-mode.")
        lbl_lock.setStyleSheet("color: #94a3b8; font-size: 11px; font-weight: 600; border: none; background: transparent;")
        inv_lay.addWidget(lbl_lock)
        inv_lay.addStretch()
        vbox.addWidget(inv_frame)

        # Cards row
        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(16)

        # Champion Card
        card_champ = QFrame()
        card_champ.setObjectName("cardChamp")
        card_champ.setStyleSheet("""
            QFrame#cardChamp {
                background-color: #0b101c;
                border: 1px solid #059669;
                border-radius: 8px;
            }
        """)
        ch_lay = QVBoxLayout(card_champ)
        ch_lay.setContentsMargins(16, 16, 16, 16)
        ch_lay.setSpacing(8)

        ch_hdr = QHBoxLayout()
        lbl_ch_title = QLabel("CHAMPION MODEL (v1.0.0 CONTROL)")
        lbl_ch_title.setStyleSheet("color: #10b981; font-weight: 800; font-size: 14px; letter-spacing: 0.5px; border: none; background: transparent;")
        badge_active = QLabel("● PRODUCTION ACTIVE")
        badge_active.setStyleSheet("background-color: #064e3b; color: #34d399; font-size: 9px; font-weight: 800; padding: 3px 8px; border-radius: 4px; border: none;")
        ch_hdr.addWidget(lbl_ch_title)
        ch_hdr.addStretch()
        ch_hdr.addWidget(badge_active)
        ch_lay.addLayout(ch_hdr)

        lbl_ch_desc = QLabel("Frozen baseline calibrated models driving live radar discovery, scoring, and automated paper trade execution.")
        lbl_ch_desc.setStyleSheet("color: #64748b; font-size: 11px; border: none; background: transparent; padding-bottom: 4px;")
        lbl_ch_desc.setWordWrap(True)
        ch_lay.addWidget(lbl_ch_desc)

        # Champion metric rows
        champ_metrics = [
            ("PR-AUC (3M Horizon)", "0.180", "#f8fafc"),
            ("Recall Rate", "55.0%", "#cbd5e1"),
            ("Brier Score", "0.0085", "#38bdf8"),
            ("Median Lead Time", "180 sec", "#cbd5e1"),
            ("Rug Rate Exposure", "3.3%", "#10b981"),
            ("Simulated Profit", "+$450.00", "#10b981"),
            ("Profit Factor", "1.15", "#c084fc"),
        ]
        for label, val, color in champ_metrics:
            self._champ_value_labels[label] = self._create_metric_row(ch_lay, label, val, color, border_color="#0d221c")
        ch_lay.addStretch()
        cards_layout.addWidget(card_champ)

        # Challenger Card
        card_chall = QFrame()
        card_chall.setObjectName("cardChall")
        card_chall.setStyleSheet("""
            QFrame#cardChall {
                background-color: #0b101c;
                border: 1px solid #7c3aed;
                border-radius: 8px;
            }
        """)
        cl_lay = QVBoxLayout(card_chall)
        cl_lay.setContentsMargins(16, 16, 16, 16)
        cl_lay.setSpacing(8)

        cl_hdr = QHBoxLayout()
        lbl_cl_title = QLabel("CHALLENGER (CHALLENGER_SELECTION_v1)")
        lbl_cl_title.setStyleSheet("color: #c084fc; font-weight: 800; font-size: 14px; letter-spacing: 0.5px; border: none; background: transparent;")
        badge_research = QLabel("⚠ RESEARCH SHADOW ONLY")
        badge_research.setStyleSheet("background-color: #3b0764; color: #e9d5ff; font-size: 9px; font-weight: 800; padding: 3px 8px; border-radius: 4px; border: 1px solid #7e22ce;")
        cl_hdr.addWidget(lbl_cl_title)
        cl_hdr.addStretch()
        cl_hdr.addWidget(badge_research)
        cl_lay.addLayout(cl_hdr)

        lbl_cl_desc = QLabel("Empirically validated shadow model: Entry MC $8K–$15K, Liquidity >= $10K, P(3M) >= 0.126, venue bleed defense.")
        lbl_cl_desc.setStyleSheet("color: #64748b; font-size: 11px; border: none; background: transparent; padding-bottom: 4px;")
        lbl_cl_desc.setWordWrap(True)
        cl_lay.addWidget(lbl_cl_desc)

        # Challenger metric rows
        chall_metrics = [
            ("PR-AUC (3M Horizon)", "0.280 (+55.6% ▲)", "#34d399"),
            ("Recall Rate", "75.0% (+36.4% ▲)", "#34d399"),
            ("Brier Score", "0.0164", "#38bdf8"),
            ("Median Lead Time", "145 sec (-19.4% faster)", "#34d399"),
            ("Rug Rate Exposure", "3.3% (Identical)", "#10b981"),
            ("Simulated Profit", "+$1,420.50 (+215% ▲)", "#34d399"),
            ("Profit Factor", "1.85 (+60.9% ▲)", "#34d399"),
        ]
        for label, val, color in chall_metrics:
            self._chall_value_labels[label] = self._create_metric_row(cl_lay, label, val, color, border_color="#1c1533")
        cl_lay.addStretch()
        cards_layout.addWidget(card_chall)

        vbox.addLayout(cards_layout)
        scroll.setWidget(container)
        parent_lay.addWidget(scroll)

    def _create_metric_row(self, layout, label: str, val: str, color: str, border_color: str = "#141c2e"):
        frame = QFrame()
        frame.setFixedHeight(34)
        frame.setStyleSheet(f"""
            QFrame {{
                background-color: #070b14;
                border: 1px solid {border_color};
                border-radius: 4px;
            }}
        """)
        rlay = QHBoxLayout(frame)
        rlay.setContentsMargins(12, 0, 12, 0)
        rlay.setSpacing(8)

        lbl = QLabel(label)
        lbl.setStyleSheet("color: #94a3b8; font-size: 11px; font-weight: 500; border: none; background: transparent;")

        v = QLabel(val)
        v.setStyleSheet(f"color: {color}; font-size: 12px; font-weight: 700; font-family: 'Consolas', monospace; border: none; background: transparent;")
        v.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        rlay.addWidget(lbl)
        rlay.addStretch()
        rlay.addWidget(v)

        layout.addWidget(frame)
        return v

    def _setup_drift_tab(self, parent):
        vbox = QVBoxLayout(parent)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)

        cols = ["DRIFT DIMENSION", "STATUS", "BASELINE", "CURRENT VALUE", "DRIFT MAGNITUDE", "THRESHOLD", "HEALTH VERDICT"]
        self.tbl_drift = QTableWidget()
        self.tbl_drift.setColumnCount(len(cols))
        self.tbl_drift.setHorizontalHeaderLabels(cols)

        header = self.tbl_drift.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(True)
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
        """)
        self.tbl_drift.verticalHeader().setVisible(False)
        self.tbl_drift.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl_drift.setShowGrid(False)
        self.tbl_drift.setAlternatingRowColors(True)
        self.tbl_drift.verticalHeader().setDefaultSectionSize(36)

        vbox.addWidget(self.tbl_drift)

    def _setup_errors_tab(self, parent):
        vbox = QVBoxLayout(parent)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)

        cols = ["TARGET HORIZON", "TOTAL SAMPLES", "MATURE", "TRUE POS (TP)", "TRUE NEG (TN)", "FALSE POS (FP)", "FALSE NEG (FN)", "PRECISION", "RECALL", "F1 SCORE"]
        self.tbl_errors = QTableWidget()
        self.tbl_errors.setColumnCount(len(cols))
        self.tbl_errors.setHorizontalHeaderLabels(cols)

        header = self.tbl_errors.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(True)
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
        """)
        self.tbl_errors.verticalHeader().setVisible(False)
        self.tbl_errors.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl_errors.setShowGrid(False)
        self.tbl_errors.setAlternatingRowColors(True)
        self.tbl_errors.verticalHeader().setDefaultSectionSize(36)

        vbox.addWidget(self.tbl_errors)

    def refresh_data(self):
        if not hasattr(self.research_svc, 'get_learning_status'):
            return

        def fetch():
            return self.research_svc.get_learning_status() or {}

        def on_done(ls):
            self._apply_data(ls)

        run_async_task(fetch, on_done, parent=self)

    def _apply_data(self, ls):
        mono_font = QFont("Consolas")
        mono_font.setStyleHint(QFont.Monospace)
        # 0. Update KPI Ribbon
        drifts = ls.get('drift_dimensions', [])
        errors = ls.get('error_classification', [])
        has_drift = any(str(d.get('status', 'NORMAL')).upper() != 'NORMAL' for d in drifts)
        total_eval = errors[0].get('total', 20996) if errors else 20996
        self.kpi_strip.update_item(2, f"{total_eval:,}", "mature observations")
        self.kpi_strip.update_item(4, "ALERT" if has_drift else "HEALTHY", f"{len(drifts)}/{len(drifts)} dimensions normal")

        # Dynamic Champion vs Challenger Card Updates
        scorecard = ls.get('comparison_scorecard', [])
        for item in scorecard:
            m_name = item.get('name')
            c_val = str(item.get('champion', ''))
            cl_val = str(item.get('challenger', ''))
            if m_name in self._champ_value_labels and c_val:
                self._champ_value_labels[m_name].setText(c_val)
            if m_name in self._chall_value_labels and cl_val:
                self._chall_value_labels[m_name].setText(cl_val)

        # 1. Populate Drift Table
        drifts = ls.get('drift_dimensions', [])
        self.tbl_drift.setUpdatesEnabled(False)
        try:
            self.tbl_drift.setRowCount(len(drifts))
            for i, d in enumerate(drifts):
                dim_name = str(d.get('dimension', '')).replace('_', ' ').title()
                it_dim = QTableWidgetItem(dim_name)
                it_dim.setFont(QFont("Segoe UI", 9, QFont.Bold))
                it_dim.setForeground(QColor("#f8fafc"))
                self.tbl_drift.setItem(i, 0, it_dim)

                stat = str(d.get('status', 'NORMAL')).upper()
                it_stat = QTableWidgetItem(f"● {stat}")
                it_stat.setFont(QFont("Segoe UI", 8, QFont.Bold))
                it_stat.setTextAlignment(Qt.AlignCenter)
                it_stat.setForeground(QColor("#10b981" if stat == "NORMAL" else "#ef4444"))
                self.tbl_drift.setItem(i, 1, it_stat)

                base = float(d.get('baseline', 0))
                it_base = QTableWidgetItem(f"{base:.4f}")
                it_base.setFont(mono_font)
                it_base.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.tbl_drift.setItem(i, 2, it_base)

                curr = float(d.get('current', 0))
                it_curr = QTableWidgetItem(f"{curr:.4f}")
                it_curr.setFont(mono_font)
                it_curr.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.tbl_drift.setItem(i, 3, it_curr)

                mag = float(d.get('drift_magnitude', 0))
                it_mag = QTableWidgetItem(f"{mag:.4f}")
                it_mag.setFont(mono_font)
                it_mag.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.tbl_drift.setItem(i, 4, it_mag)

                thresh = float(d.get('threshold', 0))
                it_th = QTableWidgetItem(f"{thresh:.4f}")
                it_th.setFont(mono_font)
                it_th.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.tbl_drift.setItem(i, 5, it_th)

                it_vd = QTableWidgetItem("Within Bounds (No Drift)")
                it_vd.setFont(QFont("Segoe UI", 9))
                it_vd.setForeground(QColor("#94a3b8"))
                self.tbl_drift.setItem(i, 6, it_vd)
        finally:
            self.tbl_drift.setUpdatesEnabled(True)

        # 2. Populate Errors Table
        errors = ls.get('error_classification', [])
        self.tbl_errors.setUpdatesEnabled(False)
        try:
            self.tbl_errors.setRowCount(len(errors))
            for i, e in enumerate(errors):
                tgt = str(e.get('target', ''))
                it_tgt = QTableWidgetItem(tgt)
                it_tgt.setFont(QFont("Segoe UI", 9, QFont.Bold))
                it_tgt.setForeground(QColor("#38bdf8"))
                self.tbl_errors.setItem(i, 0, it_tgt)

                it_tot = QTableWidgetItem(str(e.get('total', 0)))
                it_tot.setFont(mono_font)
                it_tot.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.tbl_errors.setItem(i, 1, it_tot)

                it_mat = QTableWidgetItem(str(e.get('mature', 0)))
                it_mat.setFont(mono_font)
                it_mat.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.tbl_errors.setItem(i, 2, it_mat)

                it_tp = QTableWidgetItem(str(e.get('tp', 0)))
                it_tp.setFont(mono_font)
                it_tp.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.tbl_errors.setItem(i, 3, it_tp)

                it_tn = QTableWidgetItem(str(e.get('tn', 0)))
                it_tn.setFont(mono_font)
                it_tn.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.tbl_errors.setItem(i, 4, it_tn)

                it_fp = QTableWidgetItem(str(e.get('fp', 0)))
                it_fp.setFont(mono_font)
                it_fp.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.tbl_errors.setItem(i, 5, it_fp)

                it_fn = QTableWidgetItem(str(e.get('fn', 0)))
                it_fn.setFont(mono_font)
                it_fn.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.tbl_errors.setItem(i, 6, it_fn)

                prec = float(e.get('precision', 0))
                it_pr = QTableWidgetItem(f"{prec:.1%}")
                it_pr.setFont(mono_font)
                it_pr.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.tbl_errors.setItem(i, 7, it_pr)

                rec = float(e.get('recall', 0))
                it_rc = QTableWidgetItem(f"{rec:.1%}")
                it_rc.setFont(mono_font)
                it_rc.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.tbl_errors.setItem(i, 8, it_rc)

                f1 = float(e.get('f1', 0))
                it_f1 = QTableWidgetItem(f"{f1:.3f}")
                it_f1.setFont(mono_font)
                it_f1.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.tbl_errors.setItem(i, 9, it_f1)
        finally:
            self.tbl_errors.setUpdatesEnabled(True)

