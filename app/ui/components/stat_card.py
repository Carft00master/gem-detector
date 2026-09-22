from PySide6.QtWidgets import QFrame, QVBoxLayout, QLabel, QHBoxLayout, QWidget
from PySide6.QtCore import Qt
from app.ui.design_system import DS

class StatCard(QFrame):
    def __init__(self, title, initial_value="0", subtitle="", accent_color=None, parent=None):
        if isinstance(accent_color, QWidget):
            parent = accent_color
            accent_color = None
        super().__init__(parent)
        self.setObjectName("kpiCard")
        self.setFixedHeight(72)
        accent = accent_color or DS.ACCENT_BLUE
        
        # Base layout
        layout = QHBoxLayout(self)
        layout.setContentsMargins(DS.SPACE_MD, DS.SPACE_SM, DS.SPACE_MD, DS.SPACE_SM)
        layout.setSpacing(DS.SPACE_MD)
        
        # Left accent border
        self.accent_border = QFrame()
        self.accent_border.setFixedWidth(3)
        self.accent_border.setStyleSheet(f"background-color: {accent}; border-radius: 1px;")
        
        # Content
        content = QVBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(0)
        
        # Title
        self.lbl_title = QLabel(str(title).upper())
        self.lbl_title.setStyleSheet(f"color: {DS.TEXT_MUTED}; font-size: {DS.FONT_SM}; font-weight: bold; letter-spacing: 1px;")
        self.title_lbl = self.lbl_title
        
        # Value + Trend row
        val_row = QHBoxLayout()
        val_row.setContentsMargins(0, 0, 0, 0)
        val_row.setSpacing(DS.SPACE_SM)
        
        self.lbl_value = QLabel(str(initial_value))
        self.lbl_value.setStyleSheet(f"color: {accent if accent_color else DS.TEXT_PRIMARY}; font-size: {DS.FONT_2XL}; font-weight: bold;")
        self.value_lbl = self.lbl_value
        
        self.lbl_trend = QLabel()
        self.lbl_trend.setStyleSheet(f"font-size: {DS.FONT_XS}; font-weight: bold;")
        self.lbl_trend.hide()
        
        val_row.addWidget(self.lbl_value)
        val_row.addWidget(self.lbl_trend)
        val_row.addStretch()
        
        # Subtitle
        self.lbl_subtitle = QLabel(str(subtitle) if subtitle else "")
        self.lbl_subtitle.setStyleSheet(f"color: {DS.TEXT_SECONDARY}; font-size: {DS.FONT_XS};")
        self.subtitle_lbl = self.lbl_subtitle
        if not subtitle:
            self.lbl_subtitle.hide()
            
        content.addWidget(self.lbl_title)
        content.addLayout(val_row)
        content.addWidget(self.lbl_subtitle)
        
        layout.addWidget(self.accent_border)
        layout.addLayout(content)
        layout.addStretch()

        
    def update_value(self, value, subtitle=None, trend=None):
        self.lbl_value.setText(str(value))
        if subtitle is not None:
            self.lbl_subtitle.setText(subtitle)
            self.lbl_subtitle.setVisible(bool(subtitle))
        if trend is not None:
            if trend > 0:
                self.lbl_trend.setText(f"↗ +{trend}%")
                self.lbl_trend.setStyleSheet(f"color: {DS.ACCENT_GREEN}; font-size: {DS.FONT_XS}; font-weight: bold;")
            elif trend < 0:
                self.lbl_trend.setText(f"↘ {trend}%")
                self.lbl_trend.setStyleSheet(f"color: {DS.ACCENT_RED}; font-size: {DS.FONT_XS}; font-weight: bold;")
            else:
                self.lbl_trend.setText("→ 0%")
                self.lbl_trend.setStyleSheet(f"color: {DS.TEXT_MUTED}; font-size: {DS.FONT_XS}; font-weight: bold;")
            self.lbl_trend.show()
        else:
            self.lbl_trend.hide()
