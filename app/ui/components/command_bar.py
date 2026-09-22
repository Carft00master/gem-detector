from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QWidget
from PySide6.QtCore import Qt, Signal, QTimer
from app.ui.design_system import DS

class CommandBar(QFrame):
    start_clicked = Signal()
    pause_clicked = Signal()
    stop_clicked = Signal()
    settings_clicked = Signal()
    search_clicked = Signal()
    notifications_clicked = Signal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("commandBar")
        self.setFixedHeight(48)
        self.setStyleSheet("""
            QFrame#commandBar {
                background-color: #080a0f;
                border-bottom: 1px solid #141c2b;
            }
        """)
        
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(12, 0, 12, 0)
        self.layout.setSpacing(10)
        
        # Left zone: Clean compact logo & version badge
        left_zone = QHBoxLayout()
        left_zone.setSpacing(8)
        left_zone.setContentsMargins(0, 0, 0, 0)
        
        lbl_logo = QLabel("❖")
        lbl_logo.setStyleSheet("color: #38bdf8; font-size: 16px; font-weight: bold;")
        
        lbl_title = QLabel("QUANT TERMINAL")
        lbl_title.setStyleSheet("color: #f8fafc; font-weight: 800; font-size: 12px; letter-spacing: 1.2px;")
        
        self.lbl_version = QLabel("v1.0.0 FROZEN")
        self.lbl_version.setFixedHeight(20)
        self.lbl_version.setAlignment(Qt.AlignCenter)
        self.lbl_version.setStyleSheet("""
            color: #c084fc;
            font-size: 9px;
            font-weight: 700;
            background-color: #1e1533;
            border: 1px solid #581c87;
            padding: 1px 6px;
            border-radius: 3px;
        """)
        
        left_zone.addWidget(lbl_logo, 0, Qt.AlignVCenter)
        left_zone.addWidget(lbl_title, 0, Qt.AlignVCenter)
        left_zone.addWidget(self.lbl_version, 0, Qt.AlignVCenter)
        
        # Center zone: Telemetry (Status, Chains, Regime)
        center_zone = QHBoxLayout()
        center_zone.setSpacing(6)
        center_zone.setContentsMargins(0, 0, 0, 0)
        center_zone.setAlignment(Qt.AlignCenter)
        
        self.status_container = QFrame()
        self.status_container.setFixedHeight(24)
        self.status_container.setStyleSheet("background-color: #0b1120; border: 1px solid #1e293b; border-radius: 12px;")
        status_inner = QHBoxLayout(self.status_container)
        status_inner.setContentsMargins(8, 0, 8, 0)
        status_inner.setSpacing(5)
        
        self.lbl_status_dot = QLabel("○")
        self.lbl_status_dot.setStyleSheet("color: #64748b; font-size: 10px;")
        self.lbl_status_text = QLabel("SCANNER READY")
        self.lbl_status_text.setStyleSheet("color: #94a3b8; font-weight: 700; font-size: 10px; letter-spacing: 0.5px;")
        status_inner.addWidget(self.lbl_status_dot)
        status_inner.addWidget(self.lbl_status_text)
        
        self.badge_sol = QLabel("SOL")
        self.badge_sol.setFixedHeight(20)
        self.badge_sol.setAlignment(Qt.AlignCenter)
        self.badge_sol.setStyleSheet("color: #38bdf8; font-size: 9px; font-weight: 700; background-color: #082f49; border: 1px solid #0369a1; padding: 1px 6px; border-radius: 3px;")
        
        self.badge_bnb = QLabel("BNB")
        self.badge_bnb.setFixedHeight(20)
        self.badge_bnb.setAlignment(Qt.AlignCenter)
        self.badge_bnb.setStyleSheet("color: #fef08a; font-size: 9px; font-weight: 700; background-color: #451a03; border: 1px solid #d97706; padding: 1px 6px; border-radius: 3px;")
            
        self.lbl_regime = QLabel("REGIME: NORMAL")
        self.lbl_regime.setFixedHeight(20)
        self.lbl_regime.setAlignment(Qt.AlignCenter)
        self.lbl_regime.setStyleSheet("color: #38bdf8; font-size: 9px; font-weight: 700; background-color: #0f172a; border: 1px solid #1e293b; padding: 1px 7px; border-radius: 3px;")
        
        center_zone.addWidget(self.status_container, 0, Qt.AlignVCenter)
        center_zone.addWidget(self.badge_sol, 0, Qt.AlignVCenter)
        center_zone.addWidget(self.badge_bnb, 0, Qt.AlignVCenter)
        center_zone.addWidget(self.lbl_regime, 0, Qt.AlignVCenter)
        
        # Right zone: Action buttons & utility tools
        right_zone = QHBoxLayout()
        right_zone.setSpacing(6)
        right_zone.setContentsMargins(0, 0, 0, 0)
        right_zone.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        
        self.btn_start = QPushButton("▶ START")
        self.btn_start.setObjectName("btnSuccess")
        self.btn_start.setFixedHeight(28)
        self.btn_start.setCursor(Qt.PointingHandCursor)
        self.btn_start.clicked.connect(self.start_clicked)
        
        self.btn_pause = QPushButton("⏸")
        self.btn_pause.setObjectName("btnSecondary")
        self.btn_pause.setFixedSize(28, 28)
        self.btn_pause.setCursor(Qt.PointingHandCursor)
        self.btn_pause.setEnabled(False)
        self.btn_pause.clicked.connect(self.pause_clicked)
        
        self.btn_stop = QPushButton("⏹ STOP")
        self.btn_stop.setObjectName("btnDanger")
        self.btn_stop.setFixedHeight(28)
        self.btn_stop.setCursor(Qt.PointingHandCursor)
        self.btn_stop.setEnabled(False)
        self._stop_confirm = False
        self.btn_stop.clicked.connect(self._on_stop_clicked)
        
        sep = QFrame()
        sep.setFixedSize(1, 16)
        sep.setStyleSheet("background-color: #1e293b;")
        
        btn_search = QPushButton("⌕ Search [Ctrl+K]")
        btn_search.setObjectName("btnSecondary")
        btn_search.setFixedHeight(28)
        btn_search.setFixedWidth(125)
        btn_search.setCursor(Qt.PointingHandCursor)
        btn_search.clicked.connect(self.search_clicked)
        
        self.btn_notif = QPushButton("🔔")
        self.btn_notif.setObjectName("btnGhost")
        self.btn_notif.setFixedSize(28, 28)
        self.btn_notif.setCursor(Qt.PointingHandCursor)
        self.btn_notif.clicked.connect(self.notifications_clicked)
        
        self.lbl_notif_badge = QLabel("0", self.btn_notif)
        self.lbl_notif_badge.setFixedSize(14, 14)
        self.lbl_notif_badge.setAlignment(Qt.AlignCenter)
        self.lbl_notif_badge.setStyleSheet("background-color: #ef4444; color: white; border-radius: 7px; font-size: 8px; font-weight: bold;")
        self.lbl_notif_badge.move(14, 1)
        self.lbl_notif_badge.hide()
        
        self.btn_settings = QPushButton("⚙")
        self.btn_settings.setObjectName("btnGhost")
        self.btn_settings.setFixedSize(28, 28)
        self.btn_settings.setCursor(Qt.PointingHandCursor)
        self.btn_settings.clicked.connect(self.settings_clicked)
        
        right_zone.addWidget(self.btn_start)
        right_zone.addWidget(self.btn_pause)
        right_zone.addWidget(self.btn_stop)
        right_zone.addWidget(sep)
        right_zone.addWidget(btn_search)
        right_zone.addWidget(self.btn_notif)
        right_zone.addWidget(self.btn_settings)
        
        self.layout.addLayout(left_zone)
        self.layout.addStretch(1)
        self.layout.addLayout(center_zone)
        self.layout.addStretch(1)
        self.layout.addLayout(right_zone)
        
    def _on_stop_clicked(self):
        if not self._stop_confirm:
            self._stop_confirm = True
            self.btn_stop.setText("CONFIRM?")
            self.btn_stop.setStyleSheet(f"background-color: {DS.ACCENT_AMBER}; color: white; border: none;")
            def reset():
                self._stop_confirm = False
                self.btn_stop.setText("⏹ STOP")
                self.btn_stop.setStyleSheet("")
            QTimer.singleShot(2000, reset)
        else:
            self._stop_confirm = False
            self.btn_stop.setText("⏹ STOP")
            self.btn_stop.setStyleSheet("")
            self.stop_clicked.emit()
            
    def update_status(self, status: str, mode: str):
        if status == "running":
            self.lbl_status_dot.setStyleSheet(f"background-color: {DS.ACCENT_GREEN}; border-radius: 5px;")
            self.lbl_status_text.setText("RUNNING")
            self.lbl_status_text.setStyleSheet(f"color: {DS.ACCENT_GREEN}; font-weight: bold; font-size: {DS.FONT_SM};")
            self.btn_start.setEnabled(False)
            self.btn_pause.setEnabled(True)
            self.btn_stop.setEnabled(True)
        elif status == "stopping":
            self.lbl_status_dot.setStyleSheet(f"background-color: {DS.ACCENT_AMBER}; border-radius: 5px;")
            self.lbl_status_text.setText("STOPPING...")
            self.lbl_status_text.setStyleSheet(f"color: {DS.ACCENT_AMBER}; font-weight: bold; font-size: {DS.FONT_SM};")
            self.btn_start.setEnabled(False)
            self.btn_pause.setEnabled(False)
            self.btn_stop.setEnabled(False)
        elif status == "paused":
            self.lbl_status_dot.setStyleSheet(f"background-color: {DS.ACCENT_AMBER}; border-radius: 5px;")
            self.lbl_status_text.setText("PAUSED")
            self.lbl_status_text.setStyleSheet(f"color: {DS.ACCENT_AMBER}; font-weight: bold; font-size: {DS.FONT_SM};")
            self.btn_start.setEnabled(True)
            self.btn_pause.setEnabled(False)
            self.btn_stop.setEnabled(True)
        else:
            self.lbl_status_dot.setStyleSheet(f"background-color: {DS.TEXT_MUTED}; border-radius: 5px;")
            self.lbl_status_text.setText("STOPPED")
            self.lbl_status_text.setStyleSheet(f"color: {DS.TEXT_MUTED}; font-weight: bold; font-size: {DS.FONT_SM};")
            self.btn_start.setEnabled(True)
            self.btn_pause.setEnabled(False)
            self.btn_stop.setEnabled(False)
            
    def update_chains(self, chains: list[str]):
        if "solana" in chains:
            self.badge_sol.setStyleSheet("color: #e0e7ff; font-size: 9px; font-weight: bold; background-color: #4338ca; border: 1px solid #6366f1; padding: 1px 6px; border-radius: 3px;")
        else:
            self.badge_sol.setStyleSheet("color: #475569; font-size: 9px; font-weight: bold; background-color: #0f172a; border: 1px solid #1e293b; padding: 1px 6px; border-radius: 3px;")
            
        if "bsc" in chains or "bnb" in chains:
            self.badge_bnb.setStyleSheet("color: #fef08a; font-size: 9px; font-weight: bold; background-color: #451a03; border: 1px solid #d97706; padding: 1px 6px; border-radius: 3px;")
        else:
            self.badge_bnb.setStyleSheet("color: #475569; font-size: 9px; font-weight: bold; background-color: #0f172a; border: 1px solid #1e293b; padding: 1px 6px; border-radius: 3px;")
            
    def update_regime(self, regime: str):
        color = "#38bdf8"
        bg = "#082f49"
        border = "#0369a1"
        if regime == "HOT": 
            color, bg, border = "#34d399", "#064e3b", "#059669"
        elif regime == "PANIC": 
            color, bg, border = "#f87171", "#450a0a", "#dc2626"
        elif regime == "COLD": 
            color, bg, border = "#94a3b8", "#1e293b", "#334155"
        self.lbl_regime.setText(f"REGIME: {regime}")
        self.lbl_regime.setStyleSheet(f"color: {color}; font-size: 9px; font-weight: bold; background-color: {bg}; border: 1px solid {border}; padding: 1px 6px; border-radius: 3px;")
        
    def set_unread_count(self, count: int):
        if count > 0:
            self.lbl_notif_badge.setText(str(min(count, 99)))
            self.lbl_notif_badge.show()
        else:
            self.lbl_notif_badge.hide()
