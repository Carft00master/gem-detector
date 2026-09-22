from PySide6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QLabel, QWidget
from PySide6.QtCore import Qt
from app.ui.design_system import DS

class KpiStrip(QFrame):
    def __init__(self, items: list[dict], parent=None):
        super().__init__(parent)
        self.setObjectName("kpiStrip")
        self.setFixedHeight(54)
        self.setStyleSheet("""
            QFrame#kpiStrip {
                background-color: #080c14;
                border-bottom: 1px solid #141c2b;
            }
            QLabel {
                border: none;
                background: transparent;
            }
        """)
        
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(14, 4, 14, 4)
        self.layout.setSpacing(0)
        
        self.item_widgets = []
        self.update_all(items)
        
    def update_all(self, items: list[dict]):
        while self.layout.count():
            child = self.layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self.item_widgets.clear()
        
        for i, item in enumerate(items):
            container = QWidget()
            container.setObjectName("kpiItemContainer")
            container.setStyleSheet("""
                QWidget#kpiItemContainer {
                    background: transparent;
                    border: none;
                }
                QWidget#kpiItemContainer:hover {
                    background-color: #0f172a;
                    border-radius: 4px;
                }
            """)
            vbox = QVBoxLayout(container)
            vbox.setContentsMargins(12, 3, 12, 3)
            vbox.setSpacing(1)
            
            lbl_title = QLabel(item.get("label", "").upper())
            lbl_title.setStyleSheet("color: #64748b; font-size: 9px; font-weight: 700; letter-spacing: 0.8px; border: none;")
            
            val_color = item.get("color", "#f8fafc")
            lbl_value = QLabel(str(item.get("value", "")))
            lbl_value.setStyleSheet(f"color: {val_color}; font-size: 15px; font-weight: 800; font-family: 'Consolas', 'Roboto Mono', monospace; border: none;")
            
            vbox.addWidget(lbl_title)
            vbox.addWidget(lbl_value)
            
            subtitle = item.get("subtitle")
            lbl_sub = None
            if subtitle:
                lbl_sub = QLabel(subtitle)
                lbl_sub.setStyleSheet("color: #475569; font-size: 9px; font-weight: 500; border: none;")
                vbox.addWidget(lbl_sub)
            else:
                vbox.addStretch()
                
            self.layout.addWidget(container)
            self.item_widgets.append((lbl_value, lbl_sub, container))
            
            if i < len(items) - 1:
                divider = QFrame()
                divider.setFixedWidth(1)
                divider.setFixedHeight(26)
                divider.setStyleSheet("background-color: #141c2b; border: none;")
                self.layout.addWidget(divider)
                
        self.layout.addStretch()
        
    def update_item(self, index: int, value: str, subtitle: str = None):
        if 0 <= index < len(self.item_widgets):
            lbl_value, lbl_sub, container = self.item_widgets[index]
            lbl_value.setText(str(value))
            if subtitle is not None and lbl_sub is not None:
                lbl_sub.setText(subtitle)
