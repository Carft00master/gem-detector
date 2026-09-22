from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFrame
from app.ui.design_system import DS

class SkeletonLoader(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(DS.SPACE_SM)
        self.hide()
        
    def show_skeleton(self, rows: int, col_widths: list[int] = None):
        # Clear existing
        while self.layout.count():
            child = self.layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
                
        if not col_widths:
            col_widths = [100, 150, 80, 200, 120]
            
        for i in range(rows):
            row_frame = QFrame()
            row_frame.setFixedHeight(DS.H_TABLE_ROW)
            bg_color = DS.BG_ELEVATED if i % 2 == 0 else DS.BG_HOVER
            row_frame.setStyleSheet(f"background-color: {bg_color}; border-radius: 4px;")
            
            row_layout = QHBoxLayout(row_frame)
            row_layout.setContentsMargins(DS.SPACE_SM, DS.SPACE_XS, DS.SPACE_SM, DS.SPACE_XS)
            row_layout.setSpacing(DS.SPACE_MD)
            
            for width in col_widths:
                cell = QFrame()
                cell.setFixedWidth(width)
                cell.setStyleSheet(f"background-color: {DS.BG_BASE}; border-radius: 2px;")
                row_layout.addWidget(cell)
            row_layout.addStretch()
            
            self.layout.addWidget(row_frame)
        self.layout.addStretch()
        self.show()
        
    def hide_skeleton(self):
        self.hide()
