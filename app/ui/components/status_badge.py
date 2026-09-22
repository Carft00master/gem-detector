from PySide6.QtWidgets import QLabel
from PySide6.QtCore import Qt
from app.ui.design_system import DS, SIGNAL_STATE_META

class StatusBadge(QLabel):
    def __init__(self, state_key="WATCH", parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.update_state(state_key)
        
    def update_state(self, state_key: str):
        meta = SIGNAL_STATE_META.get(state_key, {"label": state_key, "icon": "❓", "color": DS.TEXT_PRIMARY, "bg": DS.BG_ELEVATED})
        self.setText(f"{meta['icon']} {meta['label']}")
        self.setStyleSheet(f"""
            background-color: {meta['bg']};
            color: {meta['color']};
            border-radius: 4px;
            padding: 2px 6px;
            font-size: {DS.FONT_XS};
            font-weight: bold;
        """)
        self.setToolTip(f"Current State: {meta['label']}")
