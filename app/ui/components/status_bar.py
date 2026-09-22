"""
TerminalStatusBar Component
Real-time system health and connectivity telemetry bar.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QWidget

from src.version import FROZEN_VERSION_MANIFEST


class BadgeLabel(QLabel):
    def __init__(self, text: str, color: str = "#10b981", parent=None):
        super().__init__(text, parent)
        self.color = color
        self.setFixedHeight(22)
        self.update_color(color)

    def update_color(self, color: str, text: str = None):
        self.color = color
        if text:
            self.setText(text)
        self.setStyleSheet(f"""
            background-color: {self.color}22;
            color: {self.color};
            border: 1px solid {self.color}55;
            border-radius: 4px;
            padding: 2px 8px;
            font-size: 11px;
            font-weight: bold;
        """)


class TerminalStatusBar(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(34)
        self.setStyleSheet("background-color: #080a0f; border-top: 1px solid #1f2937;")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(10)

        # Scanner Status
        self.lbl_status = BadgeLabel("SCANNER: RUNNING", "#10b981")
        self.lbl_mode = BadgeLabel("MODE: PAPER", "#3b82f6")

        # Feed Badges
        self.lbl_sol = BadgeLabel("SOLANA: ACTIVE", "#10b981")
        self.lbl_base = BadgeLabel("BASE: ACTIVE", "#10b981")
        self.lbl_rpc = BadgeLabel("RPC: 120ms", "#10b981")
        self.lbl_ws = BadgeLabel("WS: CONNECTED", "#10b981")
        self.lbl_version = BadgeLabel(f"VERSION: {FROZEN_VERSION_MANIFEST.scanner_version} (FROZEN)", "#8b5cf6")

        layout.addWidget(self.lbl_status)
        layout.addWidget(self.lbl_mode)
        layout.addWidget(self.lbl_sol)
        layout.addWidget(self.lbl_base)
        layout.addWidget(self.lbl_rpc)
        layout.addWidget(self.lbl_ws)
        layout.addStretch()
        layout.addWidget(self.lbl_version)

    def update_scanner_status(self, status: str, mode: str):
        if status == "RUNNING":
            self.lbl_status.update_color("#10b981", "SCANNER: RUNNING")
        elif status == "PAUSED":
            self.lbl_status.update_color("#f59e0b", "SCANNER: PAUSED")
        else:
            self.lbl_status.update_color("#ef4444", "SCANNER: STOPPED")

        mode_colors = {"SHADOW": "#6b7280", "PAPER": "#3b82f6", "LIVE": "#ec4899"}
        self.lbl_mode.update_color(mode_colors.get(mode, "#3b82f6"), f"MODE: {mode}")

    def update_telemetry(self, rpc_ms: float, ws_connected: bool):
        rpc_color = "#10b981" if rpc_ms < 250 else ("#f59e0b" if rpc_ms < 800 else "#ef4444")
        self.lbl_rpc.update_color(rpc_color, f"RPC: {rpc_ms:.0f}ms")

        ws_color = "#10b981" if ws_connected else "#ef4444"
        ws_text = "WS: CONNECTED" if ws_connected else "WS: OFFLINE"
        self.lbl_ws.update_color(ws_color, ws_text)
