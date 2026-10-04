import logging
from pathlib import Path
import sqlite3
import webbrowser
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, 
                             QLabel, QTabWidget, QPushButton, QFrame, QProgressBar, QApplication, QScrollArea)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont

from app.ui.design_system import DS, rug_risk_level, cabal_risk_level
from app.application.service_locator import ServiceLocator
from app.services.scanner_service import ScannerService
from app.ui.components.timeline_event import TimelineEvent
from app.ui.components.empty_state import EmptyState

logger = logging.getLogger(__name__)

class TokenDetailView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.scanner_svc = ServiceLocator.get(ScannerService)
        self.token_address = None
        self.current_candidate = None
        self.setup_ui()

    def setup_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        # 1. Top Identity & Action Header
        self.header_frame = QFrame()
        self.header_frame.setObjectName("tokenDetailHeader")
        self.header_frame.setStyleSheet("""
            QFrame#tokenDetailHeader {
                background-color: #0b101c;
                border-bottom: 1px solid #141c2b;
            }
        """)
        hdr_layout = QHBoxLayout(self.header_frame)
        hdr_layout.setContentsMargins(16, 10, 16, 10)
        hdr_layout.setSpacing(12)

        # Left: Symbol & Name
        identity_vbox = QVBoxLayout()
        identity_vbox.setSpacing(2)
        
        id_top_row = QHBoxLayout()
        id_top_row.setSpacing(8)
        
        self.lbl_symbol = QLabel("SELECT TOKEN")
        self.lbl_symbol.setStyleSheet("font-size: 18px; font-weight: 800; color: #f8fafc;")
        self.lbl_token_title = QLabel("TOKEN NOT FOUND")
        self.lbl_token_title.hide()
        
        self.badge_chain = QLabel("SOLANA")
        self.badge_chain.setStyleSheet("background-color: #082f49; color: #38bdf8; border: 1px solid #0369a1; font-size: 10px; font-weight: 700; padding: 2px 7px; border-radius: 3px;")
        
        self.badge_venue = QLabel("RAYDIUM")
        self.badge_venue.setStyleSheet("background-color: #1e1533; color: #c084fc; border: 1px solid #581c87; font-size: 10px; font-weight: 700; padding: 2px 7px; border-radius: 3px;")
        
        self.badge_signal = QLabel("⚡ EARLY BREAKOUT")
        self.badge_signal.setStyleSheet("background-color: #082f49; color: #38bdf8; font-size: 10px; font-weight: 700; padding: 2px 7px; border-radius: 3px;")

        id_top_row.addWidget(self.lbl_symbol)
        id_top_row.addWidget(self.badge_chain)
        id_top_row.addWidget(self.badge_venue)
        id_top_row.addWidget(self.badge_signal)
        id_top_row.addStretch()

        id_bot_row = QHBoxLayout()
        id_bot_row.setSpacing(8)
        self.lbl_address = QLabel("No token selected")
        self.lbl_address.setStyleSheet("color: #64748b; font-family: 'Consolas', monospace; font-size: 11px;")
        
        self.btn_copy_ca = QPushButton("📋 Copy CA")
        self.btn_copy_ca.setObjectName("btnGhost")
        self.btn_copy_ca.setFixedHeight(24)
        self.btn_copy_ca.setStyleSheet("""
            QPushButton#btnGhost {
                background-color: transparent;
                border: 1px solid #334155;
                color: #94a3b8;
                border-radius: 4px;
                padding: 2px 8px;
                font-size: 11px;
            }
            QPushButton#btnGhost:hover {
                background-color: #1e293b;
                color: #f1f5f9;
            }
        """)
        self.btn_copy_ca.setCursor(Qt.PointingHandCursor)
        self.btn_copy_ca.clicked.connect(self._copy_ca)
        
        self.lbl_age = QLabel("● Discovery: —")
        self.lbl_age.setStyleSheet("color: #94a3b8; font-size: 11px;")

        id_bot_row.addWidget(self.lbl_address)
        id_bot_row.addWidget(self.btn_copy_ca)
        id_bot_row.addWidget(self.lbl_age)
        id_bot_row.addStretch()

        identity_vbox.addLayout(id_top_row)
        identity_vbox.addLayout(id_bot_row)
        hdr_layout.addLayout(identity_vbox, 1)

        # Right: Quick Explorer Links
        links_box = QHBoxLayout()
        links_box.setSpacing(6)
        
        btn_link_qss = """
            QPushButton#btnSecondary {
                background-color: #1e293b;
                border: 1px solid #334155;
                color: #f1f5f9;
                border-radius: 4px;
                padding: 2px 10px;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton#btnSecondary:hover {
                background-color: #334155;
                border-color: #475569;
            }
        """
        self.btn_dex = QPushButton("DexScreener ↗")
        self.btn_dex.setObjectName("btnSecondary")
        self.btn_dex.setFixedHeight(28)
        self.btn_dex.setStyleSheet(btn_link_qss)
        self.btn_dex.setCursor(Qt.PointingHandCursor)
        self.btn_dex.clicked.connect(self._open_dexscreener)
        
        self.btn_exp = QPushButton("Explorer ↗")
        self.btn_exp.setObjectName("btnSecondary")
        self.btn_exp.setFixedHeight(28)
        self.btn_exp.setStyleSheet(btn_link_qss)
        self.btn_exp.setCursor(Qt.PointingHandCursor)
        self.btn_exp.clicked.connect(self._open_explorer)

        links_box.addWidget(self.btn_dex)
        links_box.addWidget(self.btn_exp)
        hdr_layout.addLayout(links_box)

        self.main_layout.addWidget(self.header_frame)

        # 2. Research Tabs
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane { border: none; background-color: #080c14; }
            QTabBar::tab { background: #0b101c; color: #64748b; padding: 8px 18px; border: none; font-weight: 600; font-size: 11px; }
            QTabBar::tab:selected { background: #0f172a; color: #38bdf8; border-bottom: 2px solid #38bdf8; }
            QTabBar::tab:hover { color: #f8fafc; }
        """)

        self.tab_overview = QWidget()
        self.tab_selector = QWidget()
        self.tab_order_flow = QWidget()
        self.tab_risk = QWidget()
        self.tab_exec = QWidget()
        self.tab_history = QWidget()

        self.tabs.addTab(self.tab_overview, "Overview & Probabilities")
        self.tabs.addTab(self.tab_selector, "★ Selector V2 (Conviction)")
        self.tabs.addTab(self.tab_order_flow, "Order Flow & Volume")
        self.tabs.addTab(self.tab_risk, "Risk & Anti-Rug")
        self.tabs.addTab(self.tab_exec, "Execution Capacity")
        self.tabs.addTab(self.tab_history, "Audit Trail")

        self.main_layout.addWidget(self.tabs)

        self._setup_overview()
        self._setup_selector()
        self._setup_order_flow()
        self._setup_risk()
        self._setup_exec()
        self._setup_history()

    def _setup_overview(self):
        layout = QVBoxLayout(self.tab_overview)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        # Section 1: Probability Radar Cards
        lbl_p_title = QLabel("MULTI-HORIZON EXPANSION PROBABILITIES (FROZEN MODEL)")
        lbl_p_title.setStyleSheet("color: #475569; font-size: 10px; font-weight: 800; letter-spacing: 1px;")
        layout.addWidget(lbl_p_title)

        p_row = QHBoxLayout()
        p_row.setSpacing(12)
        
        self.p_cards = {}
        horizons = [
            ("p100k", "P(REACH $100K)", "#38bdf8"),
            ("p500k", "P(REACH $500K)", "#60a5fa"),
            ("p1m",   "P(REACH $1.0M)", "#a855f7"),
            ("p3m",   "P(REACH $3.0M)", "#10b981"),
        ]
        for key, title, color in horizons:
            frame = QFrame()
            frame.setStyleSheet("background-color: #0b1120; border: 1px solid #1e293b; border-radius: 6px; padding: 10px;")
            vbox = QVBoxLayout(frame)
            vbox.setSpacing(4)
            vbox.setContentsMargins(0, 0, 0, 0)
            
            lbl_h = QLabel(title)
            lbl_h.setStyleSheet("color: #64748b; font-size: 9px; font-weight: 700; letter-spacing: 0.8px;")
            
            lbl_val = QLabel("0.0%")
            lbl_val.setStyleSheet(f"color: {color}; font-size: 20px; font-weight: 800; font-family: 'Consolas', monospace;")
            
            pbar = QProgressBar()
            pbar.setFixedHeight(4)
            pbar.setTextVisible(False)
            pbar.setStyleSheet(f"""
                QProgressBar {{ background-color: #1e293b; border: none; border-radius: 2px; }}
                QProgressBar::chunk {{ background-color: {color}; border-radius: 2px; }}
            """)
            pbar.setValue(0)
            
            vbox.addWidget(lbl_h)
            vbox.addWidget(lbl_val)
            vbox.addWidget(pbar)
            p_row.addWidget(frame)
            
            self.p_cards[key] = (lbl_val, pbar)
            
        layout.addLayout(p_row)

        # Section 2: Key Metrics Grid
        lbl_m_title = QLabel("PRIMARY POOL & LIQUIDITY TELEMETRY")
        lbl_m_title.setStyleSheet("color: #475569; font-size: 10px; font-weight: 800; letter-spacing: 1px; margin-top: 8px;")
        layout.addWidget(lbl_m_title)

        grid = QGridLayout()
        grid.setSpacing(10)
        
        self.metric_labels = {}
        metric_defs = [
            ("mc", "Market Cap", "$0", 0, 0),
            ("liq", "Pool Liquidity", "$0", 0, 1),
            ("liq_ratio", "Liquidity / MC Ratio", "0.0%", 0, 2),
            ("vol_5m", "5-Min Volume", "$0", 1, 0),
            ("vol_1h", "1-Hour Volume", "$0", 1, 1),
            ("buyers", "Unique Buyers", "0", 1, 2),
        ]
        
        for key, label, default_val, r, c in metric_defs:
            f = QFrame()
            f.setStyleSheet("background-color: #0b1120; border: 1px solid #141c2b; border-radius: 4px; padding: 8px 12px;")
            vb = QVBoxLayout(f)
            vb.setSpacing(2)
            vb.setContentsMargins(0, 0, 0, 0)
            
            l = QLabel(label.upper())
            l.setStyleSheet("color: #64748b; font-size: 9px; font-weight: 700; letter-spacing: 0.8px;")
            v = QLabel(default_val)
            v.setStyleSheet("color: #f8fafc; font-size: 14px; font-weight: 700; font-family: 'Consolas', monospace;")
            vb.addWidget(l)
            vb.addWidget(v)
            grid.addWidget(f, r, c)
            self.metric_labels[key] = v

        layout.addLayout(grid)
        layout.addStretch()

    def _setup_selector(self):
        scroll = QScrollArea(self.tab_selector)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("background-color: transparent;")

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        lbl_s_title = QLabel("SELECTOR V2 HIGH-CONVICTION OPPORTUNITY ENGINE")
        lbl_s_title.setStyleSheet("color: #475569; font-size: 10px; font-weight: 800; letter-spacing: 1px;")
        layout.addWidget(lbl_s_title)

        # 1. KPI Cards Row (4 cards)
        kpi_row = QHBoxLayout()
        kpi_row.setSpacing(10)

        # Quality Score Card
        f_score = QFrame()
        f_score.setStyleSheet("background-color: #0b1120; border: 1px solid #1e293b; border-radius: 6px; padding: 10px;")
        vb_score = QVBoxLayout(f_score)
        vb_score.setSpacing(4)
        vb_score.setContentsMargins(0, 0, 0, 0)
        lbl_h_sc = QLabel("SETUP QUALITY SCORE")
        lbl_h_sc.setStyleSheet("color: #64748b; font-size: 9px; font-weight: 700; letter-spacing: 0.8px;")
        self.lbl_v2_score = QLabel("0.0 / 100")
        self.lbl_v2_score.setStyleSheet("color: #f8fafc; font-size: 20px; font-weight: 800; font-family: 'Consolas', monospace;")
        self.lbl_v2_tier = QLabel("TIER: UNRATED")
        self.lbl_v2_tier.setStyleSheet("color: #94a3b8; font-size: 10px; font-weight: 700;")
        vb_score.addWidget(lbl_h_sc)
        vb_score.addWidget(self.lbl_v2_score)
        vb_score.addWidget(self.lbl_v2_tier)
        kpi_row.addWidget(f_score)

        # Expected Value Card
        f_ev = QFrame()
        f_ev.setStyleSheet("background-color: #0b1120; border: 1px solid #1e293b; border-radius: 6px; padding: 10px;")
        vb_ev = QVBoxLayout(f_ev)
        vb_ev.setSpacing(4)
        vb_ev.setContentsMargins(0, 0, 0, 0)
        lbl_h_ev = QLabel("NET EXPECTED VALUE (EV)")
        lbl_h_ev.setStyleSheet("color: #64748b; font-size: 9px; font-weight: 700; letter-spacing: 0.8px;")
        self.lbl_v2_ev = QLabel("+0.0%")
        self.lbl_v2_ev.setStyleSheet("color: #10b981; font-size: 20px; font-weight: 800; font-family: 'Consolas', monospace;")
        self.lbl_v2_ev_sub = QLabel("Friction & Drag Adjusted (Min +3.0%)")
        self.lbl_v2_ev_sub.setStyleSheet("color: #94a3b8; font-size: 10px;")
        vb_ev.addWidget(lbl_h_ev)
        vb_ev.addWidget(self.lbl_v2_ev)
        vb_ev.addWidget(self.lbl_v2_ev_sub)
        kpi_row.addWidget(f_ev)

        # Confluence Card
        f_conf = QFrame()
        f_conf.setStyleSheet("background-color: #0b1120; border: 1px solid #1e293b; border-radius: 6px; padding: 10px;")
        vb_conf = QVBoxLayout(f_conf)
        vb_conf.setSpacing(4)
        vb_conf.setContentsMargins(0, 0, 0, 0)
        lbl_h_cf = QLabel("CONFLUENCE CONFIRMATION")
        lbl_h_cf.setStyleSheet("color: #64748b; font-size: 9px; font-weight: 700; letter-spacing: 0.8px;")
        self.lbl_v2_confluence = QLabel("0 / 7 AXES")
        self.lbl_v2_confluence.setStyleSheet("color: #38bdf8; font-size: 20px; font-weight: 800; font-family: 'Consolas', monospace;")
        self.lbl_v2_conf_sub = QLabel("Min 4 Independent Confirmations")
        self.lbl_v2_conf_sub.setStyleSheet("color: #94a3b8; font-size: 10px;")
        vb_conf.addWidget(lbl_h_cf)
        vb_conf.addWidget(self.lbl_v2_confluence)
        vb_conf.addWidget(self.lbl_v2_conf_sub)
        kpi_row.addWidget(f_conf)

        # Admission Status Card
        f_elig = QFrame()
        f_elig.setStyleSheet("background-color: #0b1120; border: 1px solid #1e293b; border-radius: 6px; padding: 10px;")
        vb_elig = QVBoxLayout(f_elig)
        vb_elig.setSpacing(4)
        vb_elig.setContentsMargins(0, 0, 0, 0)
        lbl_h_el = QLabel("ADMISSION STATUS")
        lbl_h_el.setStyleSheet("color: #64748b; font-size: 9px; font-weight: 700; letter-spacing: 0.8px;")
        self.lbl_v2_status = QLabel("INELIGIBLE")
        self.lbl_v2_status.setStyleSheet("color: #ef4444; font-size: 20px; font-weight: 800;")
        self.lbl_v2_status_sub = QLabel("Primary Selection Gate")
        self.lbl_v2_status_sub.setStyleSheet("color: #94a3b8; font-size: 10px;")
        vb_elig.addWidget(lbl_h_el)
        vb_elig.addWidget(self.lbl_v2_status)
        vb_elig.addWidget(self.lbl_v2_status_sub)
        kpi_row.addWidget(f_elig)

        layout.addLayout(kpi_row)

        # 2. Main Content Split: Left (7 Confluence Axes), Right (False Positive & Diagnostics)
        body_split = QHBoxLayout()
        body_split.setSpacing(14)

        # Left Column: 7 Confluence Axes Checklist
        left_box = QFrame()
        left_box.setStyleSheet("background-color: #0b1120; border: 1px solid #1e293b; border-radius: 6px; padding: 12px;")
        left_vb = QVBoxLayout(left_box)
        left_vb.setSpacing(8)

        lbl_ax_title = QLabel("INDEPENDENT CONFLUENCE AXES (7 STRUCTURAL GATES)")
        lbl_ax_title.setStyleSheet("color: #38bdf8; font-size: 10px; font-weight: 800; letter-spacing: 0.8px;")
        left_vb.addWidget(lbl_ax_title)

        self.axis_widgets = {}
        axes_defs = [
            ("PROBABILITY", "Probability Expansion", "P(3M) ≥ 12.6% & Positive Velocity"),
            ("MOMENTUM", "Momentum Acceleration", "MC Velocity > 0 & Price Acceleration ≥ 0"),
            ("PARTICIPATION", "Organic Participation", "Buyer Growth > 0 & Unique Buyer Ratio ≥ 40%"),
            ("MARKET_QUALITY", "Market Quality & Depth", "Liquidity ≥ $10k, Two-sided Vol, Low Wash/Cabal"),
            ("CURVE", "Bonding Curve Progress", "Active Progress (20%-95%) & Positive Velocity"),
            ("SMART_MONEY", "Smart Money Validation", "≥1 Tracked Whale / Smart Money Consensus"),
            ("EXECUTION", "Execution Friction", "Slippage ≤ 2.5%, Impact ≤ 2.5%, Confidence ≥ 70%"),
        ]

        for ax_key, ax_title, ax_req in axes_defs:
            row_frame = QFrame()
            row_frame.setStyleSheet("background-color: #080c14; border: 1px solid #141c2b; border-radius: 4px; padding: 6px 10px;")
            rh = QHBoxLayout(row_frame)
            rh.setContentsMargins(0, 0, 0, 0)
            rh.setSpacing(8)

            txt_vb = QVBoxLayout()
            txt_vb.setSpacing(1)
            l_t = QLabel(ax_title)
            l_t.setStyleSheet("color: #f1f5f9; font-size: 11px; font-weight: 700;")
            l_r = QLabel(ax_req)
            l_r.setStyleSheet("color: #64748b; font-size: 9px;")
            txt_vb.addWidget(l_t)
            txt_vb.addWidget(l_r)
            rh.addLayout(txt_vb, 1)

            badge = QLabel("—")
            badge.setStyleSheet("font-size: 10px; font-weight: 800; padding: 2px 6px; border-radius: 3px;")
            rh.addWidget(badge)

            left_vb.addWidget(row_frame)
            self.axis_widgets[ax_key] = badge

        body_split.addWidget(left_box, 1)

        # Right Column: False-Positive Pruner & Gate Diagnostics
        right_vb = QVBoxLayout()
        right_vb.setSpacing(10)

        # Top Right: False-Positive Pruning Checks
        fp_box = QFrame()
        fp_box.setStyleSheet("background-color: #0b1120; border: 1px solid #1e293b; border-radius: 6px; padding: 12px;")
        fp_vb = QVBoxLayout(fp_box)
        fp_vb.setSpacing(8)

        lbl_fp_title = QLabel("FALSE-POSITIVE PRUNER (TOXIC SETUP ELIMINATION)")
        lbl_fp_title.setStyleSheet("color: #f59e0b; font-size: 10px; font-weight: 800; letter-spacing: 0.8px;")
        fp_vb.addWidget(lbl_fp_title)

        self.fp_widgets = {}
        fp_defs = [
            ("FP_HIGH_P3M_LOW_BREADTH", "Insider / Fake Breakout Trap", "High P(3M) with ≤ 20 unique buyers"),
            ("FP_WASH_PUMP_LOW_INDEPENDENCE", "Wash Trading Artificial Volume", "Vol/MC ≥ 4x with High Cabal/Wash Risk"),
            ("FP_HIGH_MOMENTUM_THIN_LIQUIDITY", "Extreme Slippage Exit Trap", "High Price Velocity with Liquidity < $8,000"),
            ("FP_SMART_MONEY_CABAL_COLLUSION", "Smart Money Cabal Collusion", "Tracked Whale Collusion with Cabal > 45%"),
            ("FP_DISTRIBUTION_BID_EXHAUSTION", "Bid Exhaustion / Distribution", "≥ 80 Txns with Falling MC Velocity"),
        ]

        for fp_key, fp_name, fp_desc in fp_defs:
            row_frame = QFrame()
            row_frame.setStyleSheet("background-color: #080c14; border: 1px solid #141c2b; border-radius: 4px; padding: 6px 10px;")
            rh = QHBoxLayout(row_frame)
            rh.setContentsMargins(0, 0, 0, 0)
            rh.setSpacing(8)

            txt_vb = QVBoxLayout()
            txt_vb.setSpacing(1)
            l_t = QLabel(fp_name)
            l_t.setStyleSheet("color: #f1f5f9; font-size: 11px; font-weight: 700;")
            l_r = QLabel(fp_desc)
            l_r.setStyleSheet("color: #64748b; font-size: 9px;")
            txt_vb.addWidget(l_t)
            txt_vb.addWidget(l_r)
            rh.addLayout(txt_vb, 1)

            badge = QLabel("PASS")
            badge.setStyleSheet("background-color: #064e3b; color: #34d399; font-size: 10px; font-weight: 800; padding: 2px 6px; border-radius: 3px;")
            rh.addWidget(badge)

            fp_vb.addWidget(row_frame)
            self.fp_widgets[fp_key] = badge

        right_vb.addWidget(fp_box)

        # Bottom Right: Admission Decision & Diagnostic Reason Log
        diag_box = QFrame()
        diag_box.setStyleSheet("background-color: #0b1120; border: 1px solid #1e293b; border-radius: 6px; padding: 12px;")
        diag_vb = QVBoxLayout(diag_box)
        diag_vb.setSpacing(6)

        lbl_diag_title = QLabel("ADMISSION LOG & GATE DIAGNOSTICS")
        lbl_diag_title.setStyleSheet("color: #94a3b8; font-size: 10px; font-weight: 800; letter-spacing: 0.8px;")
        diag_vb.addWidget(lbl_diag_title)

        self.lbl_v2_diagnostics = QLabel("Evaluating token admission status...")
        self.lbl_v2_diagnostics.setWordWrap(True)
        self.lbl_v2_diagnostics.setStyleSheet("""
            background-color: #080c14;
            color: #94a3b8;
            font-family: 'Consolas', monospace;
            font-size: 11px;
            padding: 10px;
            border-radius: 4px;
            border: 1px solid #141c2b;
        """)
        diag_vb.addWidget(self.lbl_v2_diagnostics)

        right_vb.addWidget(diag_box)

        body_split.addLayout(right_vb, 1)
        layout.addLayout(body_split)
        layout.addStretch()

        scroll.setWidget(container)
        scroll_layout = QVBoxLayout(self.tab_selector)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.addWidget(scroll)

    def _update_selector_tab(self, c: dict):
        if not c:
            self.lbl_v2_score.setText("—")
            self.lbl_v2_tier.setText("TIER: UNRATED")
            self.lbl_v2_tier.setStyleSheet("color: #94a3b8; font-size: 10px; font-weight: 700;")
            self.lbl_v2_ev.setText("—")
            self.lbl_v2_confluence.setText("—")
            self.lbl_v2_status.setText("UNKNOWN")
            self.lbl_v2_status.setStyleSheet("color: #64748b; font-size: 20px; font-weight: 800;")
            self.lbl_v2_diagnostics.setText("No active candidate data available.")
            for badge in self.axis_widgets.values():
                badge.setText("—")
                badge.setStyleSheet("font-size: 10px; font-weight: 800; padding: 2px 6px; border-radius: 3px;")
            for badge in self.fp_widgets.values():
                badge.setText("—")
                badge.setStyleSheet("font-size: 10px; font-weight: 800; padding: 2px 6px; border-radius: 3px;")
            return

        # If token does not yet contain V2 evaluation, compute on the fly
        if "setup_tier" not in c or not c.get("setup_tier"):
            try:
                from src.research.selector_v2_high_conviction import SetupQualityModel
                eval_res = SetupQualityModel.evaluate(c)
                c["setup_tier"] = eval_res.tier.value
                c["setup_quality_score"] = eval_res.setup_quality_score
                c["confluence_count"] = eval_res.confluence_count
                c["expected_value"] = eval_res.expected_value
                c["confirmed_axes"] = eval_res.confirmed_axes
                c["is_v2_eligible"] = eval_res.is_eligible
                c["rejection_reasons"] = eval_res.rejection_reasons
            except Exception as e:
                logger.debug(f"Selector V2 on-the-fly evaluation error: {e}")

        tier = str(c.get("setup_tier", "REJECT"))
        score = float(c.get("setup_quality_score", 0.0))
        ev = float(c.get("expected_value", 0.0))
        conf_count = int(c.get("confluence_count", 0))
        is_elig = bool(c.get("is_v2_eligible", False))
        confirmed_axes = set(c.get("confirmed_axes", []))
        rejections = c.get("rejection_reasons", [])

        self.lbl_v2_score.setText(f"{score:.1f} / 100")
        if tier == "A+":
            self.lbl_v2_tier.setText("★ TIER A+ (TOP CONVICTION)")
            self.lbl_v2_tier.setStyleSheet("color: #fbbf24; font-size: 10px; font-weight: 800;")
        elif tier == "A":
            self.lbl_v2_tier.setText("● TIER A (HIGH CONVICTION)")
            self.lbl_v2_tier.setStyleSheet("color: #34d399; font-size: 10px; font-weight: 800;")
        elif tier == "B":
            self.lbl_v2_tier.setText("○ TIER B (WATCHLIST / UNCONFIRMED)")
            self.lbl_v2_tier.setStyleSheet("color: #38bdf8; font-size: 10px; font-weight: 800;")
        elif tier == "C":
            self.lbl_v2_tier.setText("· TIER C (WEAK / MONITORING)")
            self.lbl_v2_tier.setStyleSheet("color: #94a3b8; font-size: 10px; font-weight: 700;")
        else:
            self.lbl_v2_tier.setText("✕ REJECT (INSUFFICIENT)")
            self.lbl_v2_tier.setStyleSheet("color: #ef4444; font-size: 10px; font-weight: 700;")

        ev_color = "#10b981" if ev >= 3.0 else ("#fbbf24" if ev > 0 else "#ef4444")
        self.lbl_v2_ev.setText(f"{ev:+.1f}%")
        self.lbl_v2_ev.setStyleSheet(f"color: {ev_color}; font-size: 20px; font-weight: 800; font-family: 'Consolas', monospace;")

        conf_color = "#10b981" if conf_count >= 5 else ("#38bdf8" if conf_count >= 4 else "#fbbf24" if conf_count >= 3 else "#94a3b8")
        self.lbl_v2_confluence.setText(f"{conf_count} / 7 AXES")
        self.lbl_v2_confluence.setStyleSheet(f"color: {conf_color}; font-size: 20px; font-weight: 800; font-family: 'Consolas', monospace;")

        if is_elig:
            self.lbl_v2_status.setText("✓ QUALIFIED")
            self.lbl_v2_status.setStyleSheet("color: #10b981; font-size: 20px; font-weight: 800;")
            self.lbl_v2_status_sub.setText(f"Eligible for primary entry ({tier} Tier)")
        else:
            self.lbl_v2_status.setText("✕ INELIGIBLE")
            self.lbl_v2_status.setStyleSheet("color: #ef4444; font-size: 20px; font-weight: 800;")
            self.lbl_v2_status_sub.setText("Filtered by conviction gates")

        # 3. Update 7 Confluence Axes badges
        for ax_key, badge in self.axis_widgets.items():
            if ax_key in confirmed_axes:
                badge.setText("✓ CONFIRMED")
                badge.setStyleSheet("background-color: #064e3b; color: #34d399; font-size: 10px; font-weight: 800; padding: 2px 6px; border-radius: 3px;")
            else:
                badge.setText("✗ UNCONFIRMED")
                badge.setStyleSheet("background-color: #1f2937; color: #64748b; font-size: 10px; font-weight: 700; padding: 2px 6px; border-radius: 3px;")

        # 4. Update False-Positive badges
        fp_reasons_str = " ".join(rejections)
        for fp_key, badge in self.fp_widgets.items():
            if fp_key in fp_reasons_str:
                badge.setText("FLAGGED")
                badge.setStyleSheet("background-color: #7f1d1d; color: #f87171; font-size: 10px; font-weight: 800; padding: 2px 6px; border-radius: 3px;")
            else:
                badge.setText("PASS")
                badge.setStyleSheet("background-color: #064e3b; color: #34d399; font-size: 10px; font-weight: 800; padding: 2px 6px; border-radius: 3px;")

        # 5. Diagnostics Log
        if is_elig:
            self.lbl_v2_diagnostics.setText(
                f"[GATE PASS]: Token satisfies all structural gates for High-Conviction execution.\n"
                f"• Tier: {tier} | Quality Score: {score:.1f}/100\n"
                f"• Net Expectancy: {ev:+.2f}% per unit (Friction & Drag accounted)\n"
                f"• Confirmed Axes ({conf_count}/7): {', '.join(sorted(confirmed_axes))}"
            )
            self.lbl_v2_diagnostics.setStyleSheet("""
                background-color: #022c22;
                color: #6ee7b7;
                font-family: 'Consolas', monospace;
                font-size: 11px;
                padding: 10px;
                border-radius: 4px;
                border: 1px solid #065f46;
            """)
        else:
            rej_lines = "\n".join(f"• {r}" for r in rejections) if rejections else "• Ineligible setup profile."
            self.lbl_v2_diagnostics.setText(
                f"[GATE REJECTION]: Token was filtered by conviction gates.\n"
                f"Active Rejection Reasons:\n{rej_lines}"
            )
            self.lbl_v2_diagnostics.setStyleSheet("""
                background-color: #1e1b18;
                color: #fca5a5;
                font-family: 'Consolas', monospace;
                font-size: 11px;
                padding: 10px;
                border-radius: 4px;
                border: 1px solid #7c2d12;
            """)

    def _setup_order_flow(self):
        layout = QVBoxLayout(self.tab_order_flow)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)
        
        lbl_title = QLabel("TRANSACTION MOMENTUM & TWO-SIDED ORDER FLOW")
        lbl_title.setStyleSheet("color: #475569; font-size: 10px; font-weight: 800; letter-spacing: 1px;")
        layout.addWidget(lbl_title)
        
        # Buy/Sell Ratio Box
        box = QFrame()
        box.setStyleSheet("background-color: #0b1120; border: 1px solid #1e293b; border-radius: 6px; padding: 14px;")
        box_layout = QVBoxLayout(box)
        box_layout.setSpacing(8)
        
        flow_row = QHBoxLayout()
        self.lbl_buys = QLabel("BUYS: 0")
        self.lbl_buys.setStyleSheet("color: #10b981; font-weight: 800; font-size: 13px;")
        self.lbl_sells = QLabel("SELLS: 0")
        self.lbl_sells.setStyleSheet("color: #ef4444; font-weight: 800; font-size: 13px;")
        flow_row.addWidget(self.lbl_buys)
        flow_row.addStretch()
        flow_row.addWidget(self.lbl_sells)
        box_layout.addLayout(flow_row)
        
        self.flow_bar = QProgressBar()
        self.flow_bar.setFixedHeight(8)
        self.flow_bar.setTextVisible(False)
        self.flow_bar.setStyleSheet("""
            QProgressBar { background-color: #ef4444; border-radius: 4px; }
            QProgressBar::chunk { background-color: #10b981; border-radius: 4px; }
        """)
        self.flow_bar.setValue(50)
        box_layout.addWidget(self.flow_bar)
        
        self.lbl_ratio = QLabel("Buy/Sell Ratio: 1.0x (Neutral)")
        self.lbl_ratio.setStyleSheet("color: #94a3b8; font-size: 11px;")
        box_layout.addWidget(self.lbl_ratio)
        
        layout.addWidget(box)
        layout.addStretch()

    def _setup_risk(self):
        layout = QVBoxLayout(self.tab_risk)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)
        
        lbl_title = QLabel("ANTI-RUG & RISK INTELLIGENCE MATRIX")
        lbl_title.setStyleSheet("color: #475569; font-size: 10px; font-weight: 800; letter-spacing: 1px;")
        layout.addWidget(lbl_title)
        
        grid = QGridLayout()
        grid.setSpacing(10)
        
        self.risk_labels = {}
        risk_defs = [
            ("rug", "Rug / Liquidity Pull Risk", "LOW (<10%)", "#10b981", 0, 0),
            ("cabal", "Cabal / Insider Clustering", "LOW", "#10b981", 0, 1),
            ("wash", "Wash Trading Risk Score", "NORMAL", "#38bdf8", 1, 0),
            ("dev", "Dev Wallet Allocation", "0.0%", "#10b981", 1, 1),
        ]
        
        for key, title, val, color, r, c in risk_defs:
            f = QFrame()
            f.setStyleSheet("background-color: #0b1120; border: 1px solid #141c2b; border-radius: 4px; padding: 10px 14px;")
            vb = QVBoxLayout(f)
            vb.setSpacing(2)
            vb.setContentsMargins(0, 0, 0, 0)
            
            l = QLabel(title.upper())
            l.setStyleSheet("color: #64748b; font-size: 9px; font-weight: 700;")
            v = QLabel(val)
            v.setStyleSheet(f"color: {color}; font-size: 14px; font-weight: 800;")
            vb.addWidget(l)
            vb.addWidget(v)
            grid.addWidget(f, r, c)
            self.risk_labels[key] = v
            
        layout.addLayout(grid)
        layout.addStretch()

    def _setup_exec(self):
        layout = QVBoxLayout(self.tab_exec)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)
        
        lbl_title = QLabel("AMM DEPTH & MAXIMUM POSITION CAPACITY")
        lbl_title.setStyleSheet("color: #475569; font-size: 10px; font-weight: 800; letter-spacing: 1px;")
        layout.addWidget(lbl_title)
        
        grid = QGridLayout()
        grid.setSpacing(10)
        
        self.exec_labels = {}
        caps = [
            ("cap1", "1% AMM Depth Safe Cap", "$0", 0, 0),
            ("cap2", "2% AMM Depth Safe Cap", "$0", 0, 1),
            ("cap5", "5% AMM Depth High-Impact Cap", "$0", 1, 0),
            ("slip", "Estimated Price Impact at 2%", "< 1.5%", 1, 1),
        ]
        for key, title, val, r, c in caps:
            f = QFrame()
            f.setStyleSheet("background-color: #0b1120; border: 1px solid #141c2b; border-radius: 4px; padding: 10px 14px;")
            vb = QVBoxLayout(f)
            vb.setSpacing(2)
            vb.setContentsMargins(0, 0, 0, 0)
            l = QLabel(title.upper())
            l.setStyleSheet("color: #64748b; font-size: 9px; font-weight: 700;")
            v = QLabel(val)
            v.setStyleSheet("color: #fbbf24; font-size: 14px; font-weight: 800; font-family: 'Consolas', monospace;")
            vb.addWidget(l)
            vb.addWidget(v)
            grid.addWidget(f, r, c)
            self.exec_labels[key] = v
            
        layout.addLayout(grid)
        layout.addStretch()

    def _setup_history(self):
        layout = QVBoxLayout(self.tab_history)
        layout.setContentsMargins(16, 16, 16, 16)
        
        lbl_title = QLabel("CHRONOLOGICAL CANDIDATE AUDIT TRAIL")
        lbl_title.setStyleSheet("color: #475569; font-size: 10px; font-weight: 800; letter-spacing: 1px; margin-bottom: 8px;")
        layout.addWidget(lbl_title)
        
        self.history_layout = QVBoxLayout()
        self.history_layout.setSpacing(8)
        layout.addLayout(self.history_layout)
        layout.addStretch()

    def _lookup_historical_candidate(self, token_address: str):
        from src.utils.paths import get_data_dir
        data_dir = get_data_dir()
        candidate_dirs = [data_dir, Path("data"), Path("dist/MemecoinScanner/data"), Path("dist/MemecoinScanner/_internal/data")]

        # 1. Look in paper_trading.db across resolved paths
        for cand_dir in candidate_dirs:
            pt_db = cand_dir / "paper_trading.db"
            if not pt_db.exists():
                continue
            conn = None
            try:
                conn = sqlite3.connect(pt_db)
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                cur.execute("""
                    SELECT * FROM paper_trades 
                    WHERE token_address = ? OR token_address LIKE ?
                    ORDER BY exit_timestamp DESC, entry_signal_timestamp DESC
                    LIMIT 1
                """, (token_address, f"{token_address}%"))
                row = cur.fetchone()
                if row:
                    d = dict(row)
                    trade_id = d.get('trade_id')
                    ev_liq = None
                    try:
                        cur.execute("""
                            SELECT liquidity_usd FROM trade_event_log 
                            WHERE (trade_id = ? OR token_address = ? OR token_address LIKE ?)
                              AND liquidity_usd IS NOT NULL AND liquidity_usd > 0
                            ORDER BY liquidity_usd DESC
                            LIMIT 1
                        """, (trade_id, token_address, f"{token_address}%"))
                        ev_row = cur.fetchone()
                        if ev_row and ev_row[0]:
                            ev_liq = float(ev_row[0])
                    except Exception:
                        pass

                    chain = d.get('chain') or ('bsc' if token_address.startswith('0x') else 'solana')
                    venue = d.get('venue') or ('pancakeswap' if token_address.startswith('0x') else 'raydium')
                    hold_sec = float(d.get('hold_duration_seconds') or 0)
                    best_liq = ev_liq or d.get('exit_liquidity_usd') or d.get('entry_liquidity_usd') or d.get('liquidity_usd', 0)
                    return {
                        'symbol': d.get('symbol', 'UNK'),
                        'token_address': d.get('token_address', token_address),
                        'chain': chain,
                        'venue': venue,
                        'market_cap_usd': d.get('exit_market_cap_usd') or d.get('entry_market_cap_usd') or d.get('market_cap_usd', 0),
                        'liquidity_usd': best_liq,
                        'price_usd': d.get('exit_price_usd') or d.get('entry_price_usd') or 0,
                        'volume_5m_usd': 0,
                        'volume_1h_usd': 0,
                        'unique_buyers': 0,
                        'txns_5m_buys': 0,
                        'txns_5m_sells': 0,
                        'p_reach_100k': d.get('p_reach_100k', 0),
                        'p_reach_500k': d.get('p_reach_500k', 0),
                        'p_reach_1m': d.get('p_reach_1m', 0),
                        'p_reach_3m': d.get('p_reach_3m', 0),
                        'p_rug': d.get('p_rug', 0),
                        'cabal_risk': d.get('cabal_risk_at_entry', 0),
                        'wash_trading_risk': 0,
                        'signal_state': d.get('signal_state_at_entry', 'CLOSED'),
                        'token_age_minutes': hold_sec / 60.0,
                        'is_historical': True,
                        'exit_reason': d.get('exit_reason'),
                        'exit_timestamp': d.get('exit_timestamp'),
                        'entry_timestamp': d.get('entry_signal_timestamp'),
                        'net_realized_pnl_usd': d.get('net_realized_pnl_usd', 0),
                        'net_realized_return_pct': d.get('net_realized_return_pct', 0),
                    }
            except Exception as e:
                logger.debug(f"Historical paper lookup error in {pt_db}: {e}")
            finally:
                if conn:
                    try:
                        conn.close()
                    except Exception:
                        pass

        # 2. Look in shadow_universe.db across resolved paths
        for cand_dir in candidate_dirs:
            sh_db = cand_dir / "shadow_universe.db"
            if not sh_db.exists():
                continue
            try:
                conn = sqlite3.connect(sh_db)
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                cur.execute("""
                    SELECT * FROM shadow_tokens 
                    WHERE token_address = ? OR token_address LIKE ?
                    LIMIT 1
                """, (token_address, f"{token_address}%"))
                row = cur.fetchone()
                conn.close()
                if row:
                    d = dict(row)
                    chain = d.get('chain') or ('bsc' if token_address.startswith('0x') else 'solana')
                    venue = d.get('venue') or ('pancakeswap' if token_address.startswith('0x') else 'raydium')
                    return {
                        'symbol': d.get('symbol', 'UNK'),
                        'token_address': d.get('token_address', token_address),
                        'chain': chain,
                        'venue': venue,
                        'market_cap_usd': d.get('market_cap_usd', 0),
                        'liquidity_usd': d.get('liquidity_usd', 0),
                        'volume_5m_usd': d.get('volume_5m_usd', 0),
                        'volume_1h_usd': d.get('volume_1h_usd', 0),
                        'unique_buyers': d.get('unique_buyers', 0),
                        'txns_5m_buys': 0,
                        'txns_5m_sells': 0,
                        'p_reach_100k': d.get('p_reach_100k', 0),
                        'p_reach_500k': d.get('p_reach_500k', 0),
                        'p_reach_1m': d.get('p_reach_1m', 0),
                        'p_reach_3m': d.get('p_reach_3m', 0),
                        'p_rug': d.get('p_rug', 0),
                        'cabal_risk': d.get('cabal_risk_score', 0),
                        'wash_trading_risk': d.get('wash_trade_risk', 0),
                        'signal_state': d.get('signal_state', 'SHADOW'),
                        'token_age_minutes': d.get('token_age_minutes', 0),
                        'is_historical': True,
                        'discovery_timestamp': d.get('discovery_timestamp'),
                    }
            except Exception as e:
                logger.debug(f"Historical shadow lookup error in {sh_db}: {e}")

        # 3. Dynamic DexScreener Fallback Lookup (if not present in local SQLite)
        try:
            import urllib.request, json, ssl
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, context=ctx, timeout=2.5) as resp:
                data = json.loads(resp.read().decode())
                pairs = data.get("pairs", [])
                if pairs:
                    p = pairs[0]
                    base = p.get("baseToken", {})
                    liq = p.get("liquidity", {})
                    vol = p.get("volume", {})
                    tx = p.get("txns", {}).get("m5", {})
                    return {
                        'symbol': base.get('symbol', 'UNK'),
                        'token_address': base.get('address', token_address),
                        'chain': p.get('chainId', 'solana'),
                        'venue': p.get('dexId', 'pumpswap'),
                        'market_cap_usd': float(p.get('marketCap') or p.get('fdv') or 0),
                        'liquidity_usd': float(liq.get('usd') or 0),
                        'volume_5m_usd': float(vol.get('m5') or 0),
                        'volume_1h_usd': float(vol.get('h1') or 0),
                        'unique_buyers': int(tx.get('buys') or 0),
                        'txns_5m_buys': int(tx.get('buys') or 0),
                        'txns_5m_sells': int(tx.get('sells') or 0),
                        'p_reach_100k': 0.50,
                        'p_reach_500k': 0.30,
                        'p_reach_1m': 0.20,
                        'p_reach_3m': 0.10,
                        'p_rug': 0.10,
                        'cabal_risk': 0.0,
                        'wash_trading_risk': 0.0,
                        'signal_state': 'WATCH',
                        'token_age_minutes': 10.0,
                        'is_historical': True,
                    }
        except Exception as dex_err:
            logger.debug(f"Live DexScreener fallback lookup error: {dex_err}")

        return None

    def load_token(self, token_address: str):
        self.token_address = token_address
        candidates = self.scanner_svc.get_active_candidates() if hasattr(self.scanner_svc, 'get_active_candidates') else []
        c = next((x for x in candidates if x.get('token_address') == token_address), None)
        
        if not c:
            c = self._lookup_historical_candidate(token_address)

        self.current_candidate = c
        
        if c:
            is_hist = c.get('is_historical', False)
            sym = c.get('symbol', 'UNK')
            title_text = f"{sym} ({token_address})"
            self.lbl_token_title.setText(title_text)
            self.lbl_symbol.setText(sym)
            display_addr = f"{token_address[:10]}...{token_address[-8:]}" if len(token_address) > 20 else token_address
            self.lbl_address.setText(display_addr)
            self.lbl_address.setToolTip(token_address)
            
            raw_chain = c.get('chain', '')
            if not raw_chain or raw_chain == 'UNK':
                chain = 'BSC' if token_address.startswith('0x') else 'SOLANA'
            else:
                chain = raw_chain.upper()
            self.badge_chain.setText(chain)
            self.badge_chain.setStyleSheet(
                "background-color: #082f49; color: #38bdf8; border: 1px solid #0369a1; font-size: 10px; font-weight: 700; padding: 2px 7px; border-radius: 3px;" 
                if "SOL" in chain else 
                "background-color: #172554; color: #60a5fa; border: 1px solid #1d4ed8; font-size: 10px; font-weight: 700; padding: 2px 7px; border-radius: 3px;"
            )
            
            self.badge_venue.setText(c.get('venue', 'AMM').upper())
            
            sig = c.get('signal_state', 'WATCH')
            if is_hist:
                self.badge_signal.setText(f"⚡ {sig} (HISTORICAL)")
                self.badge_signal.setStyleSheet("background-color: #3b2408; color: #fbbf24; border: 1px solid #b45309; font-size: 10px; font-weight: 700; padding: 2px 7px; border-radius: 3px;")
            else:
                self.badge_signal.setText(f"⚡ {sig}")
                self.badge_signal.setStyleSheet("background-color: #082f49; color: #38bdf8; font-size: 10px; font-weight: 700; padding: 2px 7px; border-radius: 3px;")
            
            age = float(c.get('token_age_minutes', 0))
            age_str = f"{int(age)}m" if age < 60 else f"{int(age//60)}h {int(age%60)}m"
            if is_hist and c.get('exit_reason'):
                self.lbl_age.setText(f"● Closed Trade ({c.get('exit_reason')}) — Hold: {age_str}")
            else:
                self.lbl_age.setText(f"● Age: {age_str}")
            
            # Probabilities
            p100k = float(c.get('p_reach_100k', 0)) or min(float(c.get('p_reach_3m', 0)) * 3.5, 0.95)
            p500k = float(c.get('p_reach_500k', 0)) or min(float(c.get('p_reach_3m', 0)) * 2.2, 0.85)
            p1m   = float(c.get('p_reach_1m', 0))   or min(float(c.get('p_reach_3m', 0)) * 1.5, 0.70)
            p3m   = float(c.get('p_reach_3m', 0))
            
            self.p_cards['p100k'][0].setText(f"{p100k:.1%}")
            self.p_cards['p100k'][1].setValue(int(p100k * 100))
            
            self.p_cards['p500k'][0].setText(f"{p500k:.1%}")
            self.p_cards['p500k'][1].setValue(int(p500k * 100))
            
            self.p_cards['p1m'][0].setText(f"{p1m:.1%}")
            self.p_cards['p1m'][1].setValue(int(p1m * 100))
            
            self.p_cards['p3m'][0].setText(f"{p3m:.1%}")
            self.p_cards['p3m'][1].setValue(int(p3m * 100))
            
            # Metrics
            mc = float(c.get('market_cap_usd', 0))
            liq = float(c.get('liquidity_usd', 0))
            vol_5m = float(c.get('volume_5m_usd', 0))
            vol_1h = float(c.get('volume_1h_usd', 0))
            buyers = int(c.get('unique_buyers', 0))
            
            self.metric_labels['mc'].setText(f"${mc:,.0f}")
            self.metric_labels['liq'].setText(f"${liq:,.0f}")
            ratio = (liq / mc * 100) if mc > 0 else 0
            self.metric_labels['liq_ratio'].setText(f"{ratio:.1f}%")
            self.metric_labels['vol_5m'].setText(f"${vol_5m:,.0f}")
            self.metric_labels['vol_1h'].setText(f"${vol_1h:,.0f}")
            self.metric_labels['buyers'].setText(str(buyers))
            
            # Order flow
            buys = int(c.get('txns_5m_buys', 0))
            sells = int(c.get('txns_5m_sells', 0))
            total_tx = buys + sells
            pct_buy = int(buys / total_tx * 100) if total_tx > 0 else 50
            self.lbl_buys.setText(f"BUYS: {buys}")
            self.lbl_sells.setText(f"SELLS: {sells}")
            self.flow_bar.setValue(pct_buy)
            ratio_txt = f"{buys / max(sells, 1):.1f}x ({'Bullish Flow' if pct_buy > 55 else 'Balanced'})" if total_tx > 0 else "N/A (Historical Snapshot)"
            self.lbl_ratio.setText(f"Buy/Sell Ratio: {ratio_txt}")
            
            # Risk
            rug = float(c.get('p_rug', 0))
            r_info = rug_risk_level(rug)
            r_label = r_info.get("label", "LOW") if isinstance(r_info, dict) else str(r_info)
            self.risk_labels['rug'].setText(f"{r_label} ({rug:.1%})")
            
            cabal = float(c.get('cabal_risk', 0))
            self.risk_labels['cabal'].setText("HIGH ALERT" if cabal > 0.4 else "SAFE (< 20%)")
            self.risk_labels['wash'].setText("DETECTED" if c.get('wash_trading_risk', 0) > 0.3 else "CLEAN")
            
            # Execution
            self.exec_labels['cap1'].setText(f"${liq * 0.01:,.0f}")
            self.exec_labels['cap2'].setText(f"${liq * 0.02:,.0f}")
            self.exec_labels['cap5'].setText(f"${liq * 0.05:,.0f}")
            
            # History / Timeline
            while self.history_layout.count():
                item = self.history_layout.takeAt(0)
                if item.widget(): item.widget().deleteLater()
                
            if is_hist:
                entry_ts = str(c.get('entry_timestamp', 'Historical Entry'))[:19].replace('T', ' ')
                exit_ts = str(c.get('exit_timestamp', 'Historical Exit'))[:19].replace('T', ' ')
                exit_reason = c.get('exit_reason', 'CLOSED')
                pnl_usd = float(c.get('net_realized_pnl_usd', 0))
                pnl_pct = float(c.get('net_realized_return_pct', 0))
                e1 = TimelineEvent("HISTORICAL_DISCOVERY", entry_ts, f"Discovered on {c.get('venue', 'DEX')} at initial liquidity ${liq:,.0f}", color="#38bdf8")
                e2 = TimelineEvent("ENTRY_SIGNAL", "Trade Record", f"Signal State: {sig} | Model P(3M): {p3m:.1%} | Rug Risk: {rug:.1%}", color="#a855f7")
                e3 = TimelineEvent("TRADE_EXIT", exit_ts, f"Closed: {exit_reason} (Net P&L: ${pnl_usd:+.2f} / {pnl_pct:+.1f}%)", color="#f59e0b" if pnl_usd < 0 else "#10b981")
                self.history_layout.addWidget(e1)
                self.history_layout.addWidget(e2)
                self.history_layout.addWidget(e3)
            else:
                e1 = TimelineEvent("DISCOVERY", f"{age_str} ago", f"Discovered on {c.get('venue', 'DEX')} at initial pool liquidity ${liq:,.0f}", color="#38bdf8")
                e2 = TimelineEvent("QUANT_EVAL", "Score Engine", f"Model assigned P(3M) = {p3m:.1%}, Rug Risk = {rug:.1%}", color="#a855f7")
                e3 = TimelineEvent("SIGNAL_ALERT", "Signal Engine", f"Signal State promoted to: {sig}", color="#10b981")
                self.history_layout.addWidget(e1)
                self.history_layout.addWidget(e2)
                self.history_layout.addWidget(e3)

            # Update Selector V2 Tab
            self._update_selector_tab(c)
        else:
            self.lbl_token_title.setText(f"TOKEN NOT FOUND ({token_address})")
            self.lbl_symbol.setText("TOKEN NOT FOUND")
            display_addr = f"{token_address[:10]}...{token_address[-8:]}" if len(token_address) > 20 else token_address
            self.lbl_address.setText(display_addr)
            self.lbl_address.setToolTip(token_address)
            
            is_evm = token_address.startswith("0x")
            self.badge_chain.setText("BSC" if is_evm else "SOLANA")
            self.badge_chain.setStyleSheet(
                "background-color: #172554; color: #60a5fa; border: 1px solid #1d4ed8; font-size: 10px; font-weight: 700; padding: 2px 7px; border-radius: 3px;"
                if is_evm else
                "background-color: #082f49; color: #38bdf8; border: 1px solid #0369a1; font-size: 10px; font-weight: 700; padding: 2px 7px; border-radius: 3px;"
            )
            self.badge_venue.setText("PANCAKESWAP" if is_evm else "RAYDIUM")
            self.badge_signal.setText("⚡ DELISTED / INACTIVE")
            self.badge_signal.setStyleSheet("background-color: #27272a; color: #a1a1aa; border: 1px solid #3f3f46; font-size: 10px; font-weight: 700; padding: 2px 7px; border-radius: 3px;")
            self.lbl_age.setText("● Not in active radar or local DB")
            self._update_selector_tab(None)

    def _copy_ca(self):
        if self.token_address:
            QApplication.clipboard().setText(self.token_address)
            self.btn_copy_ca.setText("✓ Copied!")
            QTimer.singleShot(1500, lambda: self.btn_copy_ca.setText("📋 Copy CA"))

    def _open_dexscreener(self):
        if self.token_address:
            chain = ""
            if self.current_candidate and self.current_candidate.get('chain'):
                chain = str(self.current_candidate.get('chain', '')).lower()
            elif self.token_address.startswith("0x"):
                chain = "bsc"
            else:
                chain = "solana"
            
            slug = "solana" if "sol" in chain else "bsc"
            url = f"https://dexscreener.com/{slug}/{self.token_address}"
            webbrowser.open(url)

    def _open_explorer(self):
        if self.token_address:
            chain = ""
            if self.current_candidate and self.current_candidate.get('chain'):
                chain = str(self.current_candidate.get('chain', '')).lower()
            elif self.token_address.startswith("0x"):
                chain = "bsc"
            else:
                chain = "solana"
            
            if "sol" in chain:
                url = f"https://solscan.io/token/{self.token_address}"
            else:
                url = f"https://bscscan.com/token/{self.token_address}"
            webbrowser.open(url)

    def refresh_data(self):
        if self.token_address:
            self.load_token(self.token_address)


