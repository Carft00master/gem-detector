from PySide6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QWidget
from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve
from app.ui.design_system import DS

class NotificationCard(QFrame):
    def __init__(self, event_type, title, subtitle, timestamp, token_address=None, parent=None):
        super().__init__(parent)
        self.token_address = token_address
        self.setStyleSheet(f"background-color: {DS.BG_ELEVATED}; border: 1px solid {DS.BORDER}; border-radius: {DS.RADIUS_MD}px;")
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(DS.SPACE_MD, DS.SPACE_SM, DS.SPACE_MD, DS.SPACE_SM)
        layout.setSpacing(DS.SPACE_XS)
        
        header_row = QHBoxLayout()
        lbl_title = QLabel(f"<b>{title}</b>")
        lbl_title.setStyleSheet(f"color: {DS.TEXT_PRIMARY};")
        lbl_time = QLabel(timestamp)
        lbl_time.setStyleSheet(f"color: {DS.TEXT_MUTED}; font-size: {DS.FONT_XS};")
        header_row.addWidget(lbl_title)
        header_row.addStretch()
        header_row.addWidget(lbl_time)
        
        lbl_sub = QLabel(subtitle)
        lbl_sub.setWordWrap(True)
        lbl_sub.setStyleSheet(f"color: {DS.TEXT_SECONDARY}; font-size: {DS.FONT_SM};")
        
        layout.addLayout(header_row)
        layout.addWidget(lbl_sub)
        
        if token_address:
            btn_open = QPushButton("Open")
            btn_open.setObjectName("btnGhost")
            btn_open.setCursor(Qt.PointingHandCursor)
            layout.addWidget(btn_open, 0, Qt.AlignRight)

class NotificationPanel(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(320)
        self.setStyleSheet(f"background-color: {DS.BG_SURFACE}; border-left: 1px solid {DS.BORDER};")
        self.hide()
        
        self._unread_count = 0
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Header
        header = QFrame()
        header.setFixedHeight(DS.H_COMMAND_BAR)
        header.setStyleSheet(f"border-bottom: 1px solid {DS.BORDER}; background-color: {DS.BG_BASE};")
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(DS.SPACE_MD, 0, DS.SPACE_MD, 0)
        
        lbl_title = QLabel("NOTIFICATIONS")
        lbl_title.setStyleSheet(f"color: {DS.TEXT_PRIMARY}; font-weight: bold;")
        
        btn_clear = QPushButton("Mark All Read")
        btn_clear.setObjectName("btnGhost")
        btn_clear.setCursor(Qt.PointingHandCursor)
        btn_clear.clicked.connect(self.clear_all)
        
        btn_close = QPushButton("✕")
        btn_close.setObjectName("btnGhost")
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.clicked.connect(self.toggle_visibility)
        
        h_layout.addWidget(lbl_title)
        h_layout.addStretch()
        h_layout.addWidget(btn_clear)
        h_layout.addWidget(btn_close)
        
        # Scroll area
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("border: none; background: transparent;")
        
        self.container = QWidget()
        self.container.setStyleSheet("background: transparent;")
        self.list_layout = QVBoxLayout(self.container)
        self.list_layout.setContentsMargins(DS.SPACE_SM, DS.SPACE_SM, DS.SPACE_SM, DS.SPACE_SM)
        self.list_layout.setSpacing(DS.SPACE_SM)
        self.list_layout.addStretch()
        
        self.scroll.setWidget(self.container)
        
        main_layout.addWidget(header)
        main_layout.addWidget(self.scroll)
        
        # Animation
        self.anim = QPropertyAnimation(self, b"maximumWidth")
        self.anim.setDuration(180)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)
        
    @property
    def unread_count(self):
        return self._unread_count
        
    def add_notification(self, event_type, title, subtitle, timestamp="Just now", token_address=None):
        card = NotificationCard(event_type, title, subtitle, timestamp, token_address)
        self.list_layout.insertWidget(0, card)
        self._unread_count += 1
        # Cap notifications to 40 cards max to prevent unbounded memory growth
        # Note: self.list_layout has 1 stretch item at the bottom, so count includes it
        while self.list_layout.count() > 41:
            item = self.list_layout.takeAt(self.list_layout.count() - 2)
            if item and item.widget():
                item.widget().deleteLater()
        
    def clear_all(self):
        while self.list_layout.count() > 1: # keep stretch
            item = self.list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._unread_count = 0
        
    def toggle_visibility(self):
        if self.isVisible():
            self.anim.setStartValue(320)
            self.anim.setEndValue(0)
            self.anim.finished.connect(self.hide)
            self.anim.start()
        else:
            try:
                self.anim.finished.disconnect()
            except:
                pass
            self.show()
            self.anim.setStartValue(0)
            self.anim.setEndValue(320)
            self.anim.start()
