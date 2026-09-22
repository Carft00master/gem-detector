from app.ui.components.help_icon import HelpIcon
"""
Knowledge Base & Frequently Asked Questions (FAQ) View
Comprehensive guide and interactive documentation for all scanner tools, models, and features.
"""

from typing import List, Tuple
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.ui.components.help_icon import QLabel
from src.version import FROZEN_VERSION_MANIFEST


class FAQAccordionCard(QFrame):
    """Collapsible QFrame displaying a question, category badge, and expandable answer."""

    def __init__(self, category: str, question: str, answer_html: str, parent=None):
        super().__init__(parent)
        self.answer_html = answer_html
        self.is_expanded = False

        self.setStyleSheet("""
            QFrame {
                background-color: #0f141c;
                border: 1px solid #1f2937;
                border-radius: 8px;
                padding: 4px;
            }
            QFrame:hover {
                border: 1px solid #374151;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        # Header Row (Category Badge + Question + Expand Button)
        hdr_layout = QHBoxLayout()
        hdr_layout.setSpacing(10)

        cat_badge = QLabel(category.upper())
        cat_badge.setStyleSheet("""
            background-color: #1e3a8a;
            color: #93c5fd;
            border-radius: 4px;
            padding: 2px 8px;
            font-size: 10px;
            font-weight: bold;
        """)

        self.lbl_question = QLabel(question)
        self.lbl_question.setStyleSheet("color: #f3f4f6; font-size: 13px; font-weight: 700;")
        self.lbl_question.setWordWrap(True)

        self.btn_toggle = QPushButton("▼ Expand")
        self.btn_toggle.setFixedWidth(80)
        self.btn_toggle.setStyleSheet("""
            QPushButton {
                background-color: #1f2937;
                color: #60a5fa;
                border: 1px solid #374151;
                border-radius: 4px;
                font-size: 11px;
                font-weight: 600;
                padding: 3px 6px;
            }
            QPushButton:hover {
                background-color: #2563eb;
                color: #ffffff;
            }
        """)
        self.btn_toggle.clicked.connect(self.toggle_expanded)

        hdr_layout.addWidget(cat_badge)
        hdr_layout.addWidget(self.lbl_question, 1)
        hdr_layout.addWidget(self.btn_toggle)
        layout.addLayout(hdr_layout)

        # Answer Body (Hidden by default)
        self.lbl_answer = QLabel(answer_html)
        self.lbl_answer.setStyleSheet("""
            color: #d1d5db;
            font-size: 12px;
            line-height: 1.5;
            padding: 8px 12px;
            background-color: #111827;
            border-radius: 6px;
            border-left: 3px solid #3b82f6;
        """)
        self.lbl_answer.setWordWrap(True)
        self.lbl_answer.setTextFormat(Qt.RichText)
        self.lbl_answer.setVisible(False)
        layout.addWidget(self.lbl_answer)

    def toggle_expanded(self):
        self.is_expanded = not self.is_expanded
        self.lbl_answer.setVisible(self.is_expanded)
        self.btn_toggle.setText("▲ Collapse" if self.is_expanded else "▼ Expand")


class FAQView(QWidget):
    """Main FAQ & Interactive Knowledge Base Screen."""

    FAQS = [
        (
            "Architecture",
            "What is the Sub-$10K → $3M+ Memecoin Research Scanner?",
            "<b>The Sub-$10K → $3M+ Memecoin Scanner</b> is a research-grade quantitative discovery and execution validation engine designed to identify micro-cap tokens (between $8K and $35K Market Cap) that exhibit structural breakout characteristics before transitioning toward multi-million dollar liquidity valuations.<br/><br/>It combines multi-venue feeds (Pump.fun, Raydium, Uniswap, Aerodrome), on-chain wallet clustering, order-flow entropy analysis, non-anticipative paper trading simulation, and calibrated survival modeling."
        ),
        (
            "Frozen Model",
            "Why is the system 'Frozen' at v1.0.0? What does that mean?",
            "To prevent <b>overfitting, hindsight bias, and data snooping</b>, the quantitative predictor, feature schema, calibration weights, and risk thresholds are strictly frozen under manifest <code>v1.0.0</code>.<br/><br/>During the live validation phase, no model weights or predictive indicators are altered. The objective is strictly out-of-sample statistical measurement and execution verification on live market data."
        ),
        (
            "Controls",
            "How do the Start and Stop Scanner tools work?",
            "<b>● START SCANNER:</b> Spawns a background asynchronous worker thread (non-blocking) that continuously polls Raydium, Pump.fun, DexScreener, and GeckoTerminal, calculates all ML features and risk scores, runs real-time paper trades, and streams candidate updates into the Live Radar table.<br/><br/><b>■ STOP SCANNER:</b> Gracefully signals the worker loop to finish its current pass and close network sessions safely without UI freezing."
        ),
        (
            "Methodology",
            "How is P(3M) calculated and calibrated?",
            "<b>P(3M)</b> represents the calibrated probability that a token discovered at $8K–$35K will achieve and sustain a $3,000,000+ market cap valuation without an intervening catastrophic rug pull or dev abandonment.<br/><br/>It is trained on strictly chronological, entity-disjoint historical splits and calibrated via isotonic regression so that when P(3M) = 15%, exactly 15 out of 100 historical tokens in that bin achieved the milestone."
        ),
        (
            "Methodology",
            "Why are active tokens classified as PENDING instead of FAILURE?",
            "Under rigorous survival analysis, an active, un-rugged token that has not yet reached $3M <b>cannot be classified as a failure</b> simply because the time horizon has not elapsed.<br/><br/>Converting active tokens to failures would introduce severe right-censoring bias. A token is only classified as a Terminal Failure if it suffers a contract rug pull, liquidity drainage (<$500), or developer total dump."
        ),
        (
            "Risk & Cabal",
            "How does the Cabal Detection and Wallet Graph Engine work?",
            "The <b>Wallet Graph Engine</b> constructs an on-chain transactional graph linking early buyers to common funding wallets and exchange withdrawal hubs (e.g. Binance, OKX hot wallets).<br/><br/>It calculates effective Top 10 concentration and flags <i>sybil clusters</i> where a single coordinated operator controls multiple wallets to fake organic retail demand."
        ),
        (
            "Order Flow",
            "What is Trade Size Entropy and how does it detect Wash Trading?",
            "Organic retail buying produces high entropy (varying transaction sizes like $12, $45, $250, $80). Coordinated volume-generating bots produce low entropy (uniform identical sizes like $100.00 repeated every 2 seconds).<br/><br/>The scanner penalizes low trade-size entropy with high wash-trading risk scores."
        ),
        (
            "Execution",
            "What is the 2% Liquidity Capacity Rule and AMM Execution Simulator?",
            "In micro-cap AMM pools (Constant Product <code>x*y=k</code>), large trades incur heavy price impact and slippage. The scanner calculates exact multi-tier maximum position sizes for 1%, 2%, 5%, and 10% price impact.<br/><br/>Standard strategy sizing enforces <b>max trade ≤ 2% pool liquidity</b> to ensure survivable net returns after slippage, priority fees, and DEX swap fees."
        ),
        (
            "Paper Trading",
            "What are the 5 Non-Anticipative Exit Policies?",
            "The paper trading engine simulates 5 decoupled, realistic exit strategies without looking ahead:<br/>"
            "1. <b>Trailing Stop (35%):</b> Locks in profits as market cap rises.<br/>"
            "2. <b>Fixed Horizon (24h):</b> Closes exactly at 24 hours elapsed.<br/>"
            "3. <b>Multi-Stage Scaling:</b> Sells 33% at 3x, 33% at 5x, runners to $3M.<br/>"
            "4. <b>Risk Invalidation:</b> Immediate exit upon dev dumping or liquidity pull.<br/>"
            "5. <b>Target Milestone ($3M):</b> Holds until $3M target touch or timeout."
        ),
        (
            "Data & Export",
            "How do I export data and generate full audit reports?",
            "Navigate to the <b>⚙️ Settings</b> tab in the sidebar.<br/>"
            "• Click <b>'Export Shadow CSV'</b> to download all captured candidate data.<br/>"
            "• Click <b>'Export Paper Trades'</b> to download the complete simulated trade ledger.<br/>"
            "• Click <b>'Generate Research Audit Report'</b> to compile an automated Markdown audit containing all funnel counts, Wilson confidence intervals, Brier skill scores, and execution benchmarks."
        ),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(12)

        # 1. Top Header Banner
        hdr_frame = QFrame()
        hdr_frame.setStyleSheet("background-color: #0f141c; border: 1px solid #1f2937; border-radius: 8px; padding: 10px;")
        hdr_layout = QHBoxLayout(hdr_frame)

        title_vbox = QVBoxLayout()
        title_lbl = QLabel("📚 QUANT RESEARCH KNOWLEDGE BASE & FREQUENTLY ASKED QUESTIONS")
        title_lbl.setStyleSheet("font-size: 14px; font-weight: 800; color: #60a5fa; letter-spacing: 0.5px;")
        sub_lbl = QLabel(f"Comprehensive methodology guide for Scanner {FROZEN_VERSION_MANIFEST.scanner_version} (Frozen Model: {FROZEN_VERSION_MANIFEST.model_version})")
        sub_lbl.setStyleSheet("color: #9ca3af; font-size: 11px;")
        title_vbox.addWidget(title_lbl)
        title_vbox.addWidget(sub_lbl)
        hdr_layout.addLayout(title_vbox, 1)

        help_icon = HelpIcon("Search and review complete statistical, risk, and execution methodology documentation.", "Knowledge Base Guide")
        hdr_layout.addWidget(help_icon)
        layout.addWidget(hdr_frame)


        # 2. Search & Filter Bar
        f_frame = QFrame()
        f_frame.setStyleSheet("background-color: #0f141c; border: 1px solid #1f2937; border-radius: 6px; padding: 6px;")
        f_layout = QHBoxLayout(f_frame)

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("🔍 Search FAQs & Guides by keyword (e.g. 'P(3M)', 'Cabal', 'Start', 'Export')...")
        self.search_box.textChanged.connect(self._filter_faqs)

        self.btn_expand_all = QPushButton("Expand All")
        self.btn_expand_all.clicked.connect(self._expand_all)

        self.btn_collapse_all = QPushButton("Collapse All")
        self.btn_collapse_all.clicked.connect(self._collapse_all)

        f_layout.addWidget(self.search_box, 2)
        f_layout.addWidget(self.btn_expand_all)
        f_layout.addWidget(self.btn_collapse_all)
        layout.addWidget(f_frame)

        # 3. Scrollable List of FAQ Cards
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border: none; background: transparent;")

        self.cards_container = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_container)
        self.cards_layout.setSpacing(10)
        scroll.setWidget(self.cards_container)
        layout.addWidget(scroll, 1)

        self.cards: List[FAQAccordionCard] = []
        for cat, q, ans in self.FAQS:
            card = FAQAccordionCard(cat, q, ans)
            self.cards.append(card)
            self.cards_layout.addWidget(card)

        self.cards_layout.addStretch()

    def _filter_faqs(self, text: str):
        query = text.strip().lower()
        for card in self.cards:
            match = (query in card.lbl_question.text().lower() or query in card.answer_html.lower())
            card.setVisible(match or not query)

    def _expand_all(self):
        for card in self.cards:
            if not card.is_expanded:
                card.toggle_expanded()

    def _collapse_all(self):
        for card in self.cards:
            if card.is_expanded:
                card.toggle_expanded()

    def refresh_data(self):
        """Called on navigation."""
        pass

