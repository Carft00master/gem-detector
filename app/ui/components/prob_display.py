from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame
from PySide6.QtCore import Qt
from app.ui.design_system import DS

class ProbCell(QWidget):
    def __init__(self, prob: float, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, DS.SPACE_XS, 0, DS.SPACE_XS)
        self.layout.setSpacing(2)
        
        color = DS.ACCENT_GREEN if prob > 0.15 else (DS.ACCENT_BLUE if prob > 0.08 else DS.TEXT_MUTED)
        
        self.lbl_val = QLabel(f"{prob*100:.1f}%")
        self.lbl_val.setStyleSheet(f"color: {color}; font-size: {DS.FONT_SM}; font-weight: bold;")
        self.lbl_val.setAlignment(Qt.AlignCenter)
        
        self.bar_bg = QFrame()
        self.bar_bg.setFixedHeight(4)
        self.bar_bg.setStyleSheet(f"background-color: {DS.BG_ELEVATED}; border-radius: 2px;")
        
        self.bar_fg = QFrame(self.bar_bg)
        self.bar_fg.setFixedHeight(4)
        self.bar_fg.setStyleSheet(f"background-color: {color}; border-radius: 2px;")
        
        # Calculate width relative to 100% - realistically max probability is small
        # Assuming max prob to display full bar is ~30% for memes
        fill_ratio = min(1.0, prob / 0.3)
        self.bar_fg.resize(int(60 * fill_ratio), 4) # Assuming cell width ~60
        
        self.layout.addWidget(self.lbl_val)
        self.layout.addWidget(self.bar_bg)
        
    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Update bar_fg width based on actual width
        prob = float(self.lbl_val.text().strip('%')) / 100.0
        fill_ratio = min(1.0, prob / 0.3)
        self.bar_fg.resize(int(self.bar_bg.width() * fill_ratio), 4)

class ProbPanel(QWidget):
    def __init__(self, probs: dict, parent=None):
        super().__init__(parent)
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(DS.SPACE_MD)
        
        for key, val in probs.items():
            col = QVBoxLayout()
            col.setSpacing(2)
            lbl = QLabel(key)
            lbl.setStyleSheet(f"color: {DS.TEXT_MUTED}; font-size: {DS.FONT_XS};")
            lbl.setAlignment(Qt.AlignCenter)
            cell = ProbCell(val)
            col.addWidget(lbl)
            col.addWidget(cell)
            self.layout.addLayout(col)
