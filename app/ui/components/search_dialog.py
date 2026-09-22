from PySide6.QtWidgets import QDialog, QVBoxLayout, QLineEdit, QListWidget, QListWidgetItem, QGraphicsDropShadowEffect
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from app.ui.design_system import DS

class GlobalSearchDialog(QDialog):
    result_selected = Signal(str, str) # type, id
    
    def __init__(self, data_provider, parent=None):
        super().__init__(parent)
        self.data_provider = data_provider
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(600, 400)
        
        self.setStyleSheet(f"""
            QDialog {{ background: transparent; }}
            QListWidget {{ 
                background-color: {DS.BG_SURFACE}; 
                border: none; 
                border-radius: {DS.RADIUS_MD}px; 
            }}
            QListWidget::item {{ 
                padding: {DS.SPACE_SM}px; 
                border-bottom: 1px solid {DS.BORDER}; 
                color: {DS.TEXT_PRIMARY};
            }}
            QListWidget::item:selected {{ 
                background-color: {DS.BG_SELECTED}; 
            }}
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("Search symbols, addresses, or trades... (Press Esc to close)")
        self.txt_search.setStyleSheet(f"""
            QLineEdit {{
                background-color: {DS.BG_ELEVATED};
                color: {DS.TEXT_PRIMARY};
                font-size: {DS.FONT_LG};
                padding: {DS.SPACE_MD}px;
                border: 1px solid {DS.ACCENT_BLUE};
                border-top-left-radius: {DS.RADIUS_LG}px;
                border-top-right-radius: {DS.RADIUS_LG}px;
                border-bottom: none;
            }}
        """)
        self.txt_search.textChanged.connect(self._on_search)
        self.txt_search.returnPressed.connect(self._on_enter)
        
        self.list_results = QListWidget()
        self.list_results.setStyleSheet(f"""
            QListWidget {{
                background-color: {DS.BG_ELEVATED};
                border: 1px solid {DS.BORDER};
                border-top: none;
                border-bottom-left-radius: {DS.RADIUS_LG}px;
                border-bottom-right-radius: {DS.RADIUS_LG}px;
            }}
        """)
        self.list_results.itemDoubleClicked.connect(self._on_double_click)
        
        layout.addWidget(self.txt_search)
        layout.addWidget(self.list_results)
        
        # Shadow effect
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setColor(QColor(0, 0, 0, 150))
        shadow.setOffset(0, 4)
        self.setGraphicsEffect(shadow)
        
    def _on_search(self, text):
        self.list_results.clear()
        if not text:
            return
            
        items = self.data_provider(text)
        for item in items[:8]:
            list_item = QListWidgetItem(f"{item['icon']}  {item['name']}   [{item['type']}]")
            list_item.setData(Qt.UserRole, item)
            self.list_results.addItem(list_item)
            
        if self.list_results.count() > 0:
            self.list_results.setCurrentRow(0)
            
    def _on_enter(self):
        item = self.list_results.currentItem()
        if item:
            data = item.data(Qt.UserRole)
            self.result_selected.emit(data['type'], data['id'])
            self.accept()
            
    def _on_double_click(self, item):
        data = item.data(Qt.UserRole)
        self.result_selected.emit(data['type'], data['id'])
        self.accept()
        
    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.reject()
        else:
            super().keyPressEvent(event)
