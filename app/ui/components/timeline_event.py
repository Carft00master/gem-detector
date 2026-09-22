from PySide6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QLabel
from PySide6.QtCore import Qt, Signal
from app.ui.design_system import DS

class TimelineEvent(QFrame):
    clicked = Signal()
    
    def __init__(self, event_type, timestamp, detail=None, color=None, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(f"TimelineEvent:hover {{ background-color: {DS.BG_HOVER}; border-radius: 4px; }}")
        
        if not color:
            color = DS.ACCENT_BLUE
            
        layout = QHBoxLayout(self)
        layout.setContentsMargins(DS.SPACE_SM, DS.SPACE_SM, DS.SPACE_SM, DS.SPACE_SM)
        layout.setSpacing(DS.SPACE_MD)
        
        # Left timeline indicator
        indicator_layout = QVBoxLayout()
        indicator_layout.setContentsMargins(0, 0, 0, 0)
        indicator_layout.setSpacing(0)
        
        dot = QFrame()
        dot.setFixedSize(8, 8)
        dot.setStyleSheet(f"background-color: {color}; border-radius: 4px;")
        
        line = QFrame()
        line.setFixedWidth(2)
        line.setStyleSheet(f"background-color: {DS.BORDER_STRONG};")
        
        indicator_layout.addWidget(dot, 0, Qt.AlignHCenter)
        indicator_layout.addWidget(line, 1, Qt.AlignHCenter)
        
        # Right content
        content_layout = QVBoxLayout()
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(2)
        
        lbl_header = QLabel(f"<span style='color:{color}; font-weight:bold;'>{event_type}</span> <span style='color:{DS.TEXT_MUTED}; font-size:{DS.FONT_SM};'>&nbsp;{timestamp}</span>")
        content_layout.addWidget(lbl_header)
        
        if detail:
            lbl_detail = QLabel(detail)
            lbl_detail.setStyleSheet(f"color: {DS.TEXT_SECONDARY}; font-size: {DS.FONT_SM};")
            lbl_detail.setWordWrap(True)
            content_layout.addWidget(lbl_detail)
            
        layout.addLayout(indicator_layout)
        layout.addLayout(content_layout)
        layout.setStretch(1, 1)
        
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)
