from PySide6.QtWidgets import QLabel
from PySide6.QtCore import Qt
from app.ui.design_system import DS

class RiskBadge(QLabel):
    def __init__(self, label="", color=DS.TEXT_PRIMARY, bg=DS.BG_ELEVATED, tooltip="", parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        if label:
            self.set_level(label, color, bg, tooltip)
        else:
            self.hide()
            
    def set_level(self, label: str, color: str, bg: str, tooltip: str = ""):
        self.setText(label.upper())
        self.setStyleSheet(f"""
            background-color: {bg};
            color: {color};
            border-radius: 3px;
            padding: 1px 5px;
            font-size: 10px;
            font-weight: bold;
        """)
        if tooltip:
            self.setToolTip(tooltip)
        self.show()
