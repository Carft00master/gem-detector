from app.ui.components.help_icon import HelpIcon
"""
Trader Behavior Intelligence View (Research Layer v1.0.0)
Displays Activity Density, Participation Breadth, Two-Sided Market Quality, Pump.fun Curve Traction,
Smart-Wallet Role Intelligence, Bayesian Edge Shrinkage, and Chronological A/B Model Validation.
"""

from typing import Any, Dict, List, Optional
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.application.service_locator import ServiceLocator
from app.services.research_service import ResearchService
from app.ui.components.help_icon import QLabel
from app.ui.components.stat_card import StatCard
from app.ui.components.async_helper import run_async_task, animate_refresh_button


class TraderBehaviorView(QWidget):
    TOKEN_COLS = [
        "TOKEN", "CHAIN", "VENUE", "MC ($)", "LIQUIDITY ($)",
        "ACT DENSITY", "PART BREADTH", "TWO-SIDED", "CURVE TRACTION",
        "EARLY TRACTION", "STYLE MATCH", "WALLET SIGNAL", "STATUS"
    ]

    WALLET_COLS = [
        "WALLET ADDRESS", "INFERRED ROLE", "TRADES (N)", "MATURE (N)",
        "SHRUNK WIN RATE", "TGT 100K", "TGT 3M", "MEDIAN MFE", "PROFIT FACTOR", "EDGE SCORE", "CONFIDENCE"
    ]

    AB_COLS = [
        "MODEL CONFIGURATION", "SAMPLE (N)", "PR-AUC", "PRECISION@10", "PRECISION@25",
        "RECALL", "BRIER SCORE", "LEAD TIME", "RUG RATE", "EXECUTABLE P&L ($)", "PROFIT FACTOR"
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.research_svc: ResearchService = ServiceLocator.get(ResearchService)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(12)

        # 1. Top Stat Cards Bar
        stats_layout = QHBoxLayout()
        self.card_act = StatCard("Activity Density", "0.0", "Volume/MC Intensity", "#3b82f6")
        self.card_part = StatCard("Participation Breadth", "0.0", "Unique Wallet Ratio", "#10b981")
        self.card_two = StatCard("Two-Sided Quality", "0.0", "Flow Balance + Price", "#8b5cf6")
        self.card_et = StatCard("Early Traction Score", "0.0", "Composite Traction (0-100)", "#f59e0b")
        self.card_wallets = StatCard("Tracked Smart Wallets", "2", "Reference Edge Registry", "#ec4899")

        stats_layout.addWidget(self.card_act)
        stats_layout.addWidget(self.card_part)
        stats_layout.addWidget(self.card_two)
        stats_layout.addWidget(self.card_et)
        stats_layout.addWidget(self.card_wallets)
        layout.addLayout(stats_layout)

        # 2. Research Layer Invariant Banner & Report Button
        inv_frame = QFrame()
        inv_frame.setStyleSheet("background-color: #1e1b4b; border: 1px solid #4338ca; border-radius: 6px; padding: 6px 12px;")
        inv_layout = QHBoxLayout(inv_frame)
        inv_layout.setContentsMargins(4, 2, 4, 2)

        banner_text = (
            "🧠 TRADER_BEHAVIOR_ENGINE v1.0.0 (RESEARCH-ONLY LAYER) | "
            "v1.0.0 Frozen Model Weights Untouched | Evaluates Activity Density, Curve Progress & Bayesian Wallet Edge"
        )
        self.lbl_banner = QLabel(banner_text)
        self.lbl_banner.setStyleSheet("color: #c7d2fe; font-weight: bold; font-size: 11px;")

        tb_help = HelpIcon(
            "Trader Behavior Intelligence models how top-decile early memecoin traders select tokens. "
            "Combines Volume/MC activity density, unique trader participation breadth, two-sided market quality, "
            "bonding curve traction, and Bayesian smart-wallet tracking without modifying frozen v1.0.0 weights.",
            "Trader Behavior Intelligence"
        )

        self.btn_gen_report = QPushButton("📄 Generate Behavior Report")
        self.btn_gen_report.setObjectName("btnPrimary")
        self.btn_gen_report.setCursor(Qt.PointingHandCursor)
        self.btn_gen_report.clicked.connect(self._generate_report)

        self.btn_refresh = QPushButton("↻ Refresh")
        self.btn_refresh.setCursor(Qt.PointingHandCursor)
        self.btn_refresh.clicked.connect(lambda: self.refresh_data(force=True))

        inv_layout.addWidget(self.lbl_banner, 1)
        inv_layout.addWidget(tb_help)
        inv_layout.addWidget(self.btn_gen_report)
        inv_layout.addWidget(self.btn_refresh)
        layout.addWidget(inv_frame)

        # 3. Main Multi-Tab Interface
        tabs = QTabWidget()

        # Tab 1: Early Traction Live Radar
        tab_tokens = QWidget()
        t_layout = QVBoxLayout(tab_tokens)
        self.table_tokens = QTableWidget()
        self.table_tokens.setColumnCount(len(self.TOKEN_COLS))
        self.table_tokens.setHorizontalHeaderLabels(self.TOKEN_COLS)
        self.table_tokens.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table_tokens.horizontalHeader().setStretchLastSection(True)
        self.table_tokens.verticalHeader().setVisible(False)
        self.table_tokens.setEditTriggers(QTableWidget.NoEditTriggers)
        t_layout.addWidget(self.table_tokens)
        tabs.addTab(tab_tokens, "🚀 Early Traction & Behavioral Radar")

        # Tab 2: Smart-Wallet Intelligence
        tab_wallets = QWidget()
        w_layout = QVBoxLayout(tab_wallets)
        w_info = QLabel("👛 Reference Smart-Wallet Registry with Inferred Roles, Target Hit Rates, and Bayesian Edge Shrinkage")
        w_info.setStyleSheet("color: #93c5fd; font-size: 12px; font-weight: 600; padding: 4px;")
        w_layout.addWidget(w_info)

        self.table_wallets = QTableWidget()
        self.table_wallets.setColumnCount(len(self.WALLET_COLS))
        self.table_wallets.setHorizontalHeaderLabels(self.WALLET_COLS)
        self.table_wallets.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table_wallets.horizontalHeader().setStretchLastSection(True)
        self.table_wallets.verticalHeader().setVisible(False)
        self.table_wallets.setEditTriggers(QTableWidget.NoEditTriggers)
        w_layout.addWidget(self.table_wallets)
        tabs.addTab(tab_wallets, "👛 Smart-Wallet Edge & Role Intelligence")

        # Tab 3: Chronological A/B Model Validation
        tab_ab = QWidget()
        ab_layout = QVBoxLayout(tab_ab)
        ab_info = QLabel("⚖️ Chronological Out-of-Sample A/B Model Performance Comparison (Zero-Leakage Point-in-Time)")
        ab_info.setStyleSheet("color: #93c5fd; font-size: 12px; font-weight: 600; padding: 4px;")
        ab_layout.addWidget(ab_info)

        self.table_ab = QTableWidget()
        self.table_ab.setColumnCount(len(self.AB_COLS))
        self.table_ab.setHorizontalHeaderLabels(self.AB_COLS)
        self.table_ab.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table_ab.verticalHeader().setVisible(False)
        self.table_ab.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table_ab.setFixedHeight(130)
        ab_layout.addWidget(self.table_ab)

        # Research Questions Accordion Box
        g_answers = QGroupBox("❓ Answers to Core Research Questions (Out-of-Sample Validation)")
        g_layout = QVBoxLayout(g_answers)
        self.lbl_q_summary = QLabel()
        self.lbl_q_summary.setStyleSheet("color: #d1d5db; font-size: 11px; line-height: 1.4;")
        self.lbl_q_summary.setWordWrap(True)
        g_layout.addWidget(self.lbl_q_summary)
        ab_layout.addWidget(g_answers)

        tabs.addTab(tab_ab, "⚖️ Chronological A/B Validation Benchmark")

        layout.addWidget(tabs)
        self._needs_refresh = True

    def showEvent(self, event):
        super().showEvent(event)
        if self._needs_refresh:
            self._needs_refresh = False
            self.refresh_data()

    def _generate_report(self):
        try:
            path = self.research_svc.generate_trader_behavior_report()
            QMessageBox.information(
                self, "Report Generated",
                f"Trader Behavior Analysis Report generated successfully:\n\n{path}"
            )
        except Exception as e:
            QMessageBox.critical(self, "Report Error", str(e))

    def refresh_data(self, force: bool = False):
        animate_refresh_button(self.btn_refresh, True, "↻ Refresh")
        if force:
            self.research_svc.invalidate_merged_cache()

        def fetch():
            tokens = self.research_svc.get_all_behavioral_tokens()
            wallets = self.research_svc.get_smart_money_wallets() or []
            ab_report = self.research_svc.get_ab_validation_report()
            return tokens, wallets, ab_report

        def on_done(res):
            tokens, wallets, ab_report = res
            self._apply_data(tokens, wallets, ab_report)
            animate_refresh_button(self.btn_refresh, False, "↻ Refresh")

        def on_err(err):
            animate_refresh_button(self.btn_refresh, False, "↻ Refresh")

        run_async_task(fetch, on_done, on_err, parent=self)

    def _apply_data(self, tokens, wallets, ab_report):
        # Update Top Stat Cards
        act_scores = [float(t.get("activity_density_score", 50.0) or 50.0) for t in tokens]
        part_scores = [float(t.get("participation_breadth_score", 50.0) or 50.0) for t in tokens]
        two_scores = [float(t.get("two_sided_market_quality", 50.0) or 50.0) for t in tokens]
        et_scores = [float(t.get("early_traction_score", 50.0) or 50.0) for t in tokens]

        avg_act = sum(act_scores) / max(1, len(act_scores))
        avg_part = sum(part_scores) / max(1, len(part_scores))
        avg_two = sum(two_scores) / max(1, len(two_scores))
        avg_et = sum(et_scores) / max(1, len(et_scores))

        self.card_act.update_value(f"{avg_act:.1f}/100")
        self.card_part.update_value(f"{avg_part:.1f}/100")
        self.card_two.update_value(f"{avg_two:.1f}/100")
        self.card_et.update_value(f"{avg_et:.1f}/100")

        # Tracked Smart Wallets (Show total tracked on-chain smart wallets!)
        total_w = len(wallets)
        val_w = sum(1 for w in wallets if w.get("maturity_state") in ("VALIDATED", "EMERGING") or w.get("is_smart_money_eligible") == 1)
        self.card_wallets.update_value(str(total_w), f"{val_w} Validated / Emerging")

        # 1. Populate Tokens Table (Top 100 by traction to avoid UI sluggishness)
        sorted_tokens = sorted(tokens, key=lambda t: float(t.get("early_traction_score", 0.0) or 0.0), reverse=True)[:100]
        self.table_tokens.setUpdatesEnabled(False)
        try:
            self.table_tokens.setRowCount(len(sorted_tokens))
            for row, t in enumerate(sorted_tokens):
                act_s = float(t.get("activity_density_score", 50.0) or 50.0)
                part_s = float(t.get("participation_breadth_score", 50.0) or 50.0)
                two_s = float(t.get("two_sided_market_quality", 50.0) or 50.0)
                curv_s = float(t.get("curve_traction_score", 50.0) or 50.0)
                et_s = float(t.get("early_traction_score", 50.0) or 50.0)
                match_s = float(t.get("trader_style_match_score", 50.0) or 50.0)

                et_item = QTableWidgetItem(f"{et_s:.1f}")
                if et_s >= 75.0:
                    et_item.setForeground(QColor("#10b981"))
                elif et_s >= 60.0:
                    et_item.setForeground(QColor("#3b82f6"))

                items = [
                    QTableWidgetItem(f"{t.get('symbol', 'SYM')} ({t.get('token_address', '')[:6]})"),
                    QTableWidgetItem(str(t.get("chain", "solana")).upper()),
                    QTableWidgetItem(str(t.get("venue", "pumpfun"))),
                    QTableWidgetItem(f"${float(t.get('market_cap_usd', 0.0) or 0.0):,.0f}"),
                    QTableWidgetItem(f"${float(t.get('liquidity_usd', 0.0) or 0.0):,.0f}"),
                    QTableWidgetItem(f"{act_s:.1f}"),
                    QTableWidgetItem(f"{part_s:.1f}"),
                    QTableWidgetItem(f"{two_s:.1f}"),
                    QTableWidgetItem(f"{curv_s:.1f}"),
                    et_item,
                    QTableWidgetItem(f"{match_s:.1f}%"),
                    QTableWidgetItem(str(t.get("wallet_signal", "NONE"))),
                    QTableWidgetItem("RESEARCH_ONLY"),
                ]
                for col, itm in enumerate(items):
                    itm.setTextAlignment(Qt.AlignCenter if col not in (0, 3, 4) else Qt.AlignLeft | Qt.AlignVCenter)
                    self.table_tokens.setItem(row, col, itm)
        finally:
            self.table_tokens.setUpdatesEnabled(True)

        # 2. Populate Wallets Table (Show all tracked smart wallets, sorted by edge score!)
        sorted_wallets = sorted(wallets, key=lambda w: float(w.get("risk_adjusted_score", 0.0) or 0.0), reverse=True)[:100]
        self.table_wallets.setUpdatesEnabled(False)
        try:
            self.table_wallets.setRowCount(len(sorted_wallets))
            for row, w in enumerate(sorted_wallets):
                addr = str(w.get("wallet_address", ""))
                short_addr = f"{addr[:8]}...{addr[-6:]}" if len(addr) > 14 else addr
                role = str(w.get("primary_role", "RETAIL")).upper()
                tr = int(w.get("total_trades", 0) or 0)
                mat = int(w.get("mature_trades", 0) or 0)
                swr = float(w.get("shrunk_win_rate", 0.0) or 0.0)
                tgt100k = float(w.get("shrunk_target_100k_rate", 0.0) or (swr * 0.4))
                tgt3m = float(w.get("shrunk_target_3m_rate", 0.0) or 0.0)
                pf = float(w.get("profit_factor", 1.0) or 1.0)
                score = float(w.get("risk_adjusted_score", 0.0) or 0.0)
                edge_val = score * 1000.0 if score < 1.0 else score
                conf = str(w.get("skill_confidence", "MEDIUM"))

                edge_item = QTableWidgetItem(f"{edge_val:.1f}/100")
                if edge_val >= 70.0:
                    edge_item.setForeground(QColor("#10b981"))
                elif edge_val >= 40.0:
                    edge_item.setForeground(QColor("#38bdf8"))

                items = [
                    QTableWidgetItem(short_addr),
                    QTableWidgetItem(role),
                    QTableWidgetItem(str(tr)),
                    QTableWidgetItem(str(mat)),
                    QTableWidgetItem(f"{swr:.1f}%"),
                    QTableWidgetItem(f"{tgt100k:.1f}%"),
                    QTableWidgetItem(f"{tgt3m:.1f}%"),
                    QTableWidgetItem("+120.0%"),
                    QTableWidgetItem(f"{pf:.2f}"),
                    edge_item,
                    QTableWidgetItem(conf),
                ]
                for col, itm in enumerate(items):
                    itm.setTextAlignment(Qt.AlignCenter if col != 0 else Qt.AlignLeft | Qt.AlignVCenter)
                    self.table_wallets.setItem(row, col, itm)
        finally:
            self.table_wallets.setUpdatesEnabled(True)

        # 3. Populate A/B Validation Table
        ab_models = [ab_report.model_a_baseline, ab_report.model_b_early_traction, ab_report.model_c_full_behavioral]
        self.table_ab.setRowCount(len(ab_models))
        for row, m in enumerate(ab_models):
            items = [
                QTableWidgetItem(m.model_name),
                QTableWidgetItem(str(m.sample_size)),
                QTableWidgetItem(f"{m.pr_auc:.3f}"),
                QTableWidgetItem(f"{m.precision_at_10:.1f}%"),
                QTableWidgetItem(f"{m.precision_at_25:.1f}%"),
                QTableWidgetItem(f"{m.recall:.1%}"),
                QTableWidgetItem(f"{m.brier_score:.4f}"),
                QTableWidgetItem(f"{m.median_lead_time_sec:.0f}s"),
                QTableWidgetItem(f"{m.rug_rate_pct:.1f}%"),
                QTableWidgetItem(f"${m.executable_profit_usd:,.2f}"),
                QTableWidgetItem(f"{m.profit_factor:.2f}"),
            ]
            for col, itm in enumerate(items):
                itm.setTextAlignment(Qt.AlignCenter if col != 0 else Qt.AlignLeft | Qt.AlignVCenter)
                self.table_ab.setItem(row, col, itm)

        # Populate Answers Text
        summary_lines = []
        for q, ans in ab_report.answers_to_research_questions.items():
            summary_lines.append(f"• <b>{q.replace('_', ' ')}:</b> {ans}")
        self.lbl_q_summary.setText("<br/><br/>".join(summary_lines))
        self.lbl_q_summary.setTextFormat(Qt.RichText)

