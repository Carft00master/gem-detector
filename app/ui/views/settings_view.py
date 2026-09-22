import logging
import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, 
    QLineEdit, QComboBox, QCheckBox, QPushButton, QTabWidget, QFrame, 
    QMessageBox, QSpinBox, QDoubleSpinBox
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from app.ui.design_system import DS
from app.application.service_locator import ServiceLocator
from app.services.settings_service import SettingsService
from src.version import FROZEN_VERSION_MANIFEST

logger = logging.getLogger(__name__)


class SettingsView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings_svc = ServiceLocator.get(SettingsService)
        self.setup_ui()
        self.refresh_data()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        # Header Title
        hdr_frame = QFrame()
        hdr_frame.setStyleSheet("background-color: #0b101c; border: 1px solid #141c2b; border-radius: 8px; padding: 12px 18px;")
        hdr_layout = QHBoxLayout(hdr_frame)
        
        lbl_title = QLabel("⚙  TERMINAL CONFIGURATION & SYSTEM SETTINGS")
        lbl_title.setStyleSheet("color: #f8fafc; font-size: 14px; font-weight: 800; letter-spacing: 0.8px;")
        
        lbl_manifest = QLabel(f"MANIFEST: {FROZEN_VERSION_MANIFEST.scanner_version} [LOCKED]")
        lbl_manifest.setStyleSheet("background-color: #1e1533; color: #c084fc; border: 1px solid #581c87; font-size: 10px; font-weight: 700; padding: 3px 8px; border-radius: 4px;")
        
        hdr_layout.addWidget(lbl_title)
        hdr_layout.addStretch()
        hdr_layout.addWidget(lbl_manifest)
        layout.addWidget(hdr_frame)

        # Main Tabs
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane { border: none; background-color: #080c14; }
            QTabBar::tab { background: #0b101c; color: #64748b; padding: 10px 20px; border: none; font-weight: 600; font-size: 11px; }
            QTabBar::tab:selected { background: #0f172a; color: #38bdf8; border-bottom: 2px solid #38bdf8; }
            QTabBar::tab:hover { color: #f8fafc; }
        """)

        tab_scanner = QWidget()
        tab_trading = QWidget()
        tab_alerts = QWidget()
        tab_performance = QWidget()
        tab_integrity = QWidget()

        self.tabs.addTab(tab_scanner, "Scanner Engine")
        self.tabs.addTab(tab_trading, "Paper Trading")
        self.tabs.addTab(tab_alerts, "Alerts & Webhooks")
        self.tabs.addTab(tab_performance, "VPS & Performance")
        self.tabs.addTab(tab_integrity, "System Invariants & Security")

        layout.addWidget(self.tabs)

        self._setup_scanner_tab(tab_scanner)
        self._setup_trading_tab(tab_trading)
        self._setup_alerts_tab(tab_alerts)
        self._setup_performance_tab(tab_performance)
        self._setup_integrity_tab(tab_integrity)

        # Bottom Action Bar
        bottom_bar = QHBoxLayout()
        bottom_bar.setSpacing(12)
        
        self.lbl_save_status = QLabel("")
        self.lbl_save_status.setStyleSheet("color: #10b981; font-weight: 600; font-size: 11px;")
        
        self.btn_save = QPushButton("💾  Save Configuration")
        self.btn_save.setObjectName("btnSuccess")
        self.btn_save.setFixedHeight(32)
        self.btn_save.setCursor(Qt.PointingHandCursor)
        self.btn_save.clicked.connect(self._save_settings)

        self.btn_reset = QPushButton("↺  Reset")
        self.btn_reset.setObjectName("btnSecondary")
        self.btn_reset.setFixedHeight(32)
        self.btn_reset.setCursor(Qt.PointingHandCursor)
        self.btn_reset.clicked.connect(self.refresh_data)

        bottom_bar.addWidget(self.lbl_save_status)
        bottom_bar.addStretch()
        bottom_bar.addWidget(self.btn_reset)
        bottom_bar.addWidget(self.btn_save)
        layout.addLayout(bottom_bar)

    def _setup_scanner_tab(self, parent):
        vbox = QVBoxLayout(parent)
        vbox.setContentsMargins(20, 20, 20, 20)
        vbox.setSpacing(16)

        grid = QGridLayout()
        grid.setVerticalSpacing(14)
        grid.setHorizontalSpacing(20)

        grid.addWidget(self._create_label("Active Target Chains:"), 0, 0)
        self.cmb_chain = QComboBox()
        self.cmb_chain.addItems([
            "All Active Chains (Solana + BNB)",
            "Solana Only (Raydium + Pump.fun)",
            "BNB Chain Only (PancakeSwap)",
        ])
        self.cmb_chain.setFixedHeight(28)
        grid.addWidget(self.cmb_chain, 0, 1)

        grid.addWidget(self._create_label("Scanner Polling Interval (sec):"), 1, 0)
        self.spn_poll = QDoubleSpinBox()
        self.spn_poll.setRange(2.0, 60.0)
        self.spn_poll.setValue(10.0)
        self.spn_poll.setSingleStep(1.0)
        self.spn_poll.setFixedHeight(28)
        grid.addWidget(self.spn_poll, 1, 1)

        grid.addWidget(self._create_label("Min Discovery Market Cap ($):"), 2, 0)
        self.spn_min_mc = QDoubleSpinBox()
        self.spn_min_mc.setRange(1000.0, 100000.0)
        self.spn_min_mc.setValue(8000.0)
        self.spn_min_mc.setSingleStep(1000.0)
        self.spn_min_mc.setFixedHeight(28)
        grid.addWidget(self.spn_min_mc, 2, 1)

        grid.addWidget(self._create_label("Max Discovery Market Cap ($):"), 3, 0)
        self.spn_max_mc = QDoubleSpinBox()
        self.spn_max_mc.setRange(10000.0, 500000.0)
        self.spn_max_mc.setValue(35000.0)
        self.spn_max_mc.setSingleStep(5000.0)
        self.spn_max_mc.setFixedHeight(28)
        grid.addWidget(self.spn_max_mc, 3, 1)

        grid.addWidget(self._create_label("Min Liquidity Floor ($):"), 4, 0)
        self.spn_min_liq = QDoubleSpinBox()
        self.spn_min_liq.setRange(1000.0, 100000.0)
        self.spn_min_liq.setValue(5000.0)
        self.spn_min_liq.setSingleStep(500.0)
        self.spn_min_liq.setFixedHeight(28)
        grid.addWidget(self.spn_min_liq, 4, 1)

        vbox.addLayout(grid)
        vbox.addStretch()

    def _setup_trading_tab(self, parent):
        vbox = QVBoxLayout(parent)
        vbox.setContentsMargins(20, 20, 20, 20)
        vbox.setSpacing(16)

        grid = QGridLayout()
        grid.setVerticalSpacing(14)
        grid.setHorizontalSpacing(20)

        grid.addWidget(self._create_label("Default Position Size ($ USD):"), 0, 0)
        self.spn_pos_size = QDoubleSpinBox()
        self.spn_pos_size.setRange(10.0, 10000.0)
        self.spn_pos_size.setValue(250.0)
        self.spn_pos_size.setSingleStep(50.0)
        self.spn_pos_size.setFixedHeight(28)
        grid.addWidget(self.spn_pos_size, 0, 1)

        grid.addWidget(self._create_label("Automated Exit Policy:"), 1, 0)
        self.cmb_policy = QComboBox()
        self.cmb_policy.addItems(["TRAILING_STOP", "STAGE_EXIT (Multi-Target)", "STOP_LOSS_ONLY"])
        self.cmb_policy.setFixedHeight(28)
        grid.addWidget(self.cmb_policy, 1, 1)

        grid.addWidget(self._create_label("Simulated Max AMM Slippage (bps):"), 2, 0)
        self.spn_slip = QSpinBox()
        self.spn_slip.setRange(10, 500)
        self.spn_slip.setValue(50)
        self.spn_slip.setFixedHeight(28)
        grid.addWidget(self.spn_slip, 2, 1)

        vbox.addLayout(grid)
        vbox.addStretch()

    def _setup_alerts_tab(self, parent):
        vbox = QVBoxLayout(parent)
        vbox.setContentsMargins(20, 20, 20, 20)
        vbox.setSpacing(16)

        grid = QGridLayout()
        grid.setVerticalSpacing(14)
        grid.setHorizontalSpacing(20)

        grid.addWidget(self._create_label("Telegram Bot Token:"), 0, 0)
        self.txt_tg_token = QLineEdit()
        self.txt_tg_token.setPlaceholderText("Enter bot token or leave blank...")
        self.txt_tg_token.setFixedHeight(28)
        grid.addWidget(self.txt_tg_token, 0, 1)

        grid.addWidget(self._create_label("Telegram Chat ID:"), 1, 0)
        self.txt_tg_chat = QLineEdit()
        self.txt_tg_chat.setPlaceholderText("Enter channel/chat ID...")
        self.txt_tg_chat.setFixedHeight(28)
        grid.addWidget(self.txt_tg_chat, 1, 1)

        grid.addWidget(self._create_label("Discord Webhook URL:"), 2, 0)
        self.txt_discord = QLineEdit()
        self.txt_discord.setPlaceholderText("https://discord.com/api/webhooks/...")
        self.txt_discord.setFixedHeight(28)
        grid.addWidget(self.txt_discord, 2, 1)

        grid.addWidget(self._create_label("Sound Notifications:"), 3, 0)
        self.chk_sound = QCheckBox("Enable Audio Alert on High Conviction Signals")
        self.chk_sound.setChecked(True)
        grid.addWidget(self.chk_sound, 3, 1)

    def _setup_performance_tab(self, parent):
        vbox = QVBoxLayout(parent)
        vbox.setContentsMargins(20, 20, 20, 20)
        vbox.setSpacing(16)

        lbl_desc = QLabel(
            "Configure performance profiles and GUI rendering optimizations for virtual private servers (VPS), "
            "remote desktop protocols (RDP, VNC, AnyDesk), and constrained hardware environments."
        )
        lbl_desc.setWordWrap(True)
        lbl_desc.setStyleSheet("color: #94a3b8; font-size: 11px; line-height: 1.4;")
        vbox.addWidget(lbl_desc)

        grid = QGridLayout()
        grid.setVerticalSpacing(14)
        grid.setHorizontalSpacing(20)

        # VPS Mode Toggle
        grid.addWidget(self._create_label("VPS / Remote Desktop Mode:"), 0, 0)
        self.chk_vps_mode = QCheckBox("Enable VPS & Remote Desktop Performance Profile")
        self.chk_vps_mode.setStyleSheet("color: #f8fafc; font-weight: 600; font-size: 11px;")
        grid.addWidget(self.chk_vps_mode, 0, 1)

        # Max display rows
        grid.addWidget(self._create_label("Max Table Display Rows:"), 1, 0)
        self.spn_max_rows = QSpinBox()
        self.spn_max_rows.setRange(25, 2000)
        self.spn_max_rows.setValue(100)
        self.spn_max_rows.setSingleStep(25)
        self.spn_max_rows.setFixedHeight(28)
        grid.addWidget(self.spn_max_rows, 1, 1)

        # Environment status
        grid.addWidget(self._create_label("Host Environment Detection:"), 2, 0)
        is_vps = self.settings_svc.is_vps_environment() if hasattr(self.settings_svc, 'is_vps_environment') else False
        env_detected = "Virtual Machine / Remote Session Detected" if is_vps else "Local Physical Host Detected"
        color = "#10b981" if is_vps else "#38bdf8"
        lbl_env = QLabel(f"{env_detected} (CPUs: {os.cpu_count() or 'N/A'})")
        lbl_env.setStyleSheet(f"color: {color}; font-weight: 700; font-size: 11px;")
        grid.addWidget(lbl_env, 2, 1)

        # Features enabled card
        card = QFrame()
        card.setStyleSheet("background-color: #0b101c; border: 1px solid #1e293b; border-radius: 6px; padding: 14px;")
        c_lay = QVBoxLayout(card)
        c_lay.setSpacing(6)
        c_lay.addWidget(self._create_code_row("Event Compression:", "AA_CompressHighFrequencyEvents (Active)"))
        c_lay.addWidget(self._create_code_row("Tab Navigation:", "Zero-Lag Asynchronous Background Loading"))
        c_lay.addWidget(self._create_code_row("Table Item Allocation:", "In-place Cell Recycling (Zero Widget Thrashing)"))
        c_lay.addWidget(self._create_code_row("Research Data Caching:", "30s In-Memory Merged Cache with Dirty-Check"))
        c_lay.addWidget(self._create_code_row("Paper Ledger Caching:", "15s Aggregated Analytics Cache"))

        vbox.addLayout(grid)
        vbox.addWidget(card)
        vbox.addStretch()

    def _setup_integrity_tab(self, parent):
        vbox = QVBoxLayout(parent)
        vbox.setContentsMargins(20, 20, 20, 20)
        vbox.setSpacing(12)

        lbl_desc = QLabel("Frozen model baseline checksums guaranteeing 100% deterministic calibration and model immutability.")
        lbl_desc.setStyleSheet("color: #64748b; font-size: 11px;")
        vbox.addWidget(lbl_desc)

        card = QFrame()
        card.setStyleSheet("background-color: #0b101c; border: 1px solid #1e293b; border-radius: 6px; padding: 14px;")
        c_lay = QVBoxLayout(card)
        c_lay.setSpacing(8)

        m = FROZEN_VERSION_MANIFEST
        c_lay.addWidget(self._create_code_row("Scanner Version:", m.scanner_version))
        c_lay.addWidget(self._create_code_row("Model Version:", m.model_version))
        c_lay.addWidget(self._create_code_row("Calibration Version:", m.calibration_version))
        c_lay.addWidget(self._create_code_row("Risk Rules Version:", m.risk_rules_version))
        c_lay.addWidget(self._create_code_row("Execution Engine Version:", m.execution_model_version))
        c_lay.addWidget(self._create_code_row("Smart Money Engine Version:", m.smart_money_engine_version))
        c_lay.addWidget(self._create_code_row("Smart Money Mode:", m.smart_money_mode))
        c_lay.addWidget(self._create_code_row("Scoring Logic Status:", "PERMANENTLY FROZEN (ZERO DRIFT)"))
        c_lay.addWidget(self._create_code_row("Database Engine:", "SQLite3 WAL Mode (Isolated Research Registry)"))

        vbox.addWidget(card)
        vbox.addStretch()

    def _create_label(self, text):
        lbl = QLabel(text)
        lbl.setStyleSheet("color: #cbd5e1; font-weight: 600; font-size: 11px;")
        return lbl

    def _create_code_row(self, label, val):
        w = QWidget()
        l = QHBoxLayout(w)
        l.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel(label)
        lbl.setStyleSheet("color: #94a3b8; font-weight: 600; font-size: 11px;")
        v = QLabel(str(val))
        v.setStyleSheet("color: #38bdf8; font-family: 'Consolas', monospace; font-size: 11px; font-weight: 700;")
        l.addWidget(lbl)
        l.addStretch()
        l.addWidget(v)
        return w

    def refresh_data(self):
        cfg = getattr(self.settings_svc, 'user_settings', {}) or {}
        sc = cfg.get('scanner', {})
        chains = sc.get('active_chains', ['solana', 'bsc'])
        if isinstance(chains, list):
            chains_set = set(c.lower() for c in chains)
            if chains_set == {"solana"}:
                self.cmb_chain.setCurrentIndex(1)
            elif chains_set in ({"bsc"}, {"bnb"}):
                self.cmb_chain.setCurrentIndex(2)
            else:
                self.cmb_chain.setCurrentIndex(0)

        self.spn_poll.setValue(float(sc.get('poll_interval_sec', 10.0)))
        self.spn_min_mc.setValue(float(sc.get('min_market_cap_usd', 8000.0)))
        self.spn_max_mc.setValue(float(sc.get('max_market_cap_usd', 35000.0)))
        self.spn_min_liq.setValue(float(sc.get('min_liquidity_usd', 5000.0)))

        pt = cfg.get('paper_trading', {})
        self.spn_pos_size.setValue(float(pt.get('default_position_size_usd', 250.0)))

        cr = cfg.get('credentials', {})
        self.txt_tg_token.setText(str(cr.get('telegram_bot_token', '')))
        self.txt_tg_chat.setText(str(cr.get('telegram_chat_id', '')))
        self.txt_discord.setText(str(cr.get('discord_webhook_url', '')))

        ui = cfg.get('ui', {})
        self.chk_sound.setChecked(bool(ui.get('enable_sound_alerts', True)))
        vps_active = ui.get('vps_mode', self.settings_svc.is_vps_environment() if hasattr(self.settings_svc, 'is_vps_environment') else False)
        self.chk_vps_mode.setChecked(bool(vps_active))
        self.spn_max_rows.setValue(int(ui.get('max_display_rows', 100)))
        self.lbl_save_status.setText("")

    def _save_settings(self):
        try:
            cfg = getattr(self.settings_svc, 'user_settings', {}) or {}
            cfg.setdefault('scanner', {})['poll_interval_sec'] = self.spn_poll.value()
            cfg['scanner']['min_market_cap_usd'] = self.spn_min_mc.value()
            cfg['scanner']['max_market_cap_usd'] = self.spn_max_mc.value()
            cfg['scanner']['min_liquidity_usd'] = self.spn_min_liq.value()

            idx = self.cmb_chain.currentIndex()
            if idx == 1:
                cfg['scanner']['active_chains'] = ["solana"]
            elif idx == 2:
                cfg['scanner']['active_chains'] = ["bsc"]
            else:
                cfg['scanner']['active_chains'] = ["solana", "bsc"]

            cfg.setdefault('paper_trading', {})['default_position_size_usd'] = self.spn_pos_size.value()
            cfg['paper_trading']['active_policy'] = self.cmb_policy.currentText().split()[0]

            cfg.setdefault('credentials', {})['telegram_bot_token'] = self.txt_tg_token.text().strip()
            cfg['credentials']['telegram_chat_id'] = self.txt_tg_chat.text().strip()
            cfg['credentials']['discord_webhook_url'] = self.txt_discord.text().strip()

            cfg.setdefault('ui', {})['enable_sound_alerts'] = self.chk_sound.isChecked()
            cfg['ui']['vps_mode'] = self.chk_vps_mode.isChecked()
            cfg['ui']['max_display_rows'] = self.spn_max_rows.value()

            if hasattr(self.settings_svc, 'save_user_settings'):
                self.settings_svc.save_user_settings(cfg)

            self.lbl_save_status.setText("✓ Configuration saved to user_settings.json")
            QMessageBox.information(self, "Settings Saved", "User configuration parameters updated successfully.")
        except Exception as e:
            QMessageBox.warning(self, "Save Error", f"Failed to save settings: {e}")
