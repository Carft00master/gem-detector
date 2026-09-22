from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton, QSizePolicy
from PySide6.QtCore import Qt
from app.ui.design_system import DS

class EmptyState(QWidget):
    def __init__(self, icon=None, title="", subtitle="", action_label=None, on_action=None, parent=None):
        if isinstance(icon, QWidget):
            parent = icon
            icon = None
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.layout = QVBoxLayout(self)
        self.layout.setAlignment(Qt.AlignCenter)
        self.layout.setContentsMargins(24, 32, 24, 32)
        self.layout.setSpacing(DS.SPACE_SM)
        
        self.lbl_icon = QLabel()
        self.lbl_icon.setAlignment(Qt.AlignCenter)
        self.lbl_icon.setStyleSheet("font-size: 40px; margin-bottom: 4px;")
        
        self.lbl_title = QLabel()
        self.lbl_title.setAlignment(Qt.AlignCenter)
        self.lbl_title.setStyleSheet("color: #f8fafc; font-size: 15px; font-weight: 700;")
        
        self.lbl_subtitle = QLabel()
        self.lbl_subtitle.setAlignment(Qt.AlignCenter)
        self.lbl_subtitle.setWordWrap(True)
        self.lbl_subtitle.setStyleSheet("color: #94a3b8; font-size: 12px; max-width: 520px;")
        
        self.btn_action = QPushButton()
        self.btn_action.setObjectName("btnSecondary")
        self.btn_action.setStyleSheet("""
            QPushButton#btnSecondary {
                background-color: #1e293b;
                border: 1px solid #38bdf8;
                color: #38bdf8;
                border-radius: 4px;
                padding: 6px 16px;
                font-size: 12px;
                font-weight: 600;
                margin-top: 8px;
            }
            QPushButton#btnSecondary:hover {
                background-color: #0f172a;
                border-color: #7dd3fc;
                color: #f8fafc;
            }
        """)
        self.btn_action.setCursor(Qt.PointingHandCursor)
        self.btn_action.hide()
        
        self.layout.addStretch(1)
        self.layout.addWidget(self.lbl_icon)
        self.layout.addWidget(self.lbl_title)
        self.layout.addWidget(self.lbl_subtitle)
        self.layout.addWidget(self.btn_action, 0, Qt.AlignHCenter)
        self.layout.addStretch(1)
        
        if icon or title or subtitle:
            self.set_state(icon or "", title, subtitle, action_label, on_action)

        
    def set_state(self, icon, title, subtitle, action_label=None, on_action=None):
        self.lbl_icon.setText(icon)
        self.lbl_title.setText(title)
        self.lbl_subtitle.setText(subtitle)
        
        if action_label and on_action:
            self.btn_action.setText(action_label)
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                try:
                    self.btn_action.clicked.disconnect()
                except Exception:
                    pass
            self.btn_action.clicked.connect(on_action)
            self.btn_action.show()
        else:
            self.btn_action.hide()

    @staticmethod
    def no_data(parent=None):
        es = EmptyState(parent)
        es.set_state("📭", "No Data Available", "There is currently no data to display in this view.")
        return es
        
    @staticmethod
    def loading(parent=None):
        es = EmptyState(parent)
        es.set_state("⏳", "Loading Data", "Please wait while data is being fetched...")
        return es
        
    @staticmethod
    def error(msg, retry_fn=None, parent=None):
        es = EmptyState(parent)
        es.set_state("⚠️", "Error Occurred", msg, "Retry" if retry_fn else None, retry_fn)
        return es
