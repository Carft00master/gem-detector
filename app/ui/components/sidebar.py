from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QScrollArea
from PySide6.QtCore import Qt, Signal, QPropertyAnimation, QEasingCurve, QSettings
from app.ui.design_system import DS

class NavItem(QFrame):
    clicked = Signal(int)
    
    def __init__(self, view_index, icon, label, parent=None):
        super().__init__(parent)
        self.view_index = view_index
        self.icon = icon
        self.label_text = label
        self.is_expanded = True
        self.is_selected = False
        
        self.setFixedHeight(34)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(label)
        
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(12, 0, 10, 0)
        self.layout.setSpacing(10)
        
        self.lbl_icon = QLabel(icon)
        self.lbl_icon.setFixedWidth(18)
        self.lbl_icon.setAlignment(Qt.AlignCenter)
        self.lbl_icon.setStyleSheet("font-size: 13px; font-weight: bold; color: #64748b; font-family: 'Segoe UI Symbol', 'Lucida Sans Unicode', sans-serif;")
        self.lbl_icon.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        
        self.lbl_text = QLabel(label)
        self.lbl_text.setStyleSheet("color: #94a3b8; font-size: 11px; font-weight: 500;")
        self.lbl_text.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        self.lbl_badge = QLabel("")
        self.lbl_badge.setStyleSheet("background-color: #0e2038; color: #38bdf8; font-size: 9px; font-weight: 700; padding: 1px 5px; border-radius: 3px;")
        self.lbl_badge.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.lbl_badge.hide()
        
        self.layout.addWidget(self.lbl_icon)
        self.layout.addWidget(self.lbl_text)
        self.layout.addStretch()
        self.layout.addWidget(self.lbl_badge)
        
        self.update_style()

    def set_badge(self, text: str):
        if text and self.is_expanded:
            self.lbl_badge.setText(str(text))
            self.lbl_badge.show()
        else:
            self.lbl_badge.hide()
        
    def set_expanded(self, expanded: bool):
        self.is_expanded = expanded
        self.lbl_text.setVisible(expanded)
        self.lbl_badge.setVisible(expanded and bool(self.lbl_badge.text()))
        if not expanded:
            self.layout.setContentsMargins(6, 0, 0, 0)
        else:
            self.layout.setContentsMargins(12, 0, 10, 0)
            
    def set_selected(self, selected: bool):
        self.is_selected = selected
        self.update_style()
        
    def update_style(self):
        if self.is_selected:
            self.setStyleSheet("""
                QFrame {
                    background-color: #172554;
                    border-left: 3px solid #38bdf8;
                    border-top-right-radius: 4px;
                    border-bottom-right-radius: 4px;
                }
            """)
            self.lbl_icon.setStyleSheet("font-size: 13px; font-weight: bold; color: #38bdf8; font-family: 'Segoe UI Symbol', 'Lucida Sans Unicode', sans-serif;")
            self.lbl_text.setStyleSheet("color: #ffffff; font-size: 11px; font-weight: 700;")
        else:
            self.setStyleSheet("""
                QFrame {
                    background-color: transparent;
                    border-left: 3px solid transparent;
                }
            """)
            self.lbl_icon.setStyleSheet("font-size: 13px; font-weight: bold; color: #64748b; font-family: 'Segoe UI Symbol', 'Lucida Sans Unicode', sans-serif;")
            self.lbl_text.setStyleSheet("color: #94a3b8; font-size: 11px; font-weight: 500;")
            
    def enterEvent(self, event):
        if not self.is_selected:
            self.setStyleSheet("""
                QFrame {
                    background-color: #0f172a;
                    border-left: 3px solid #334155;
                    border-top-right-radius: 4px;
                    border-bottom-right-radius: 4px;
                }
            """)
            self.lbl_text.setStyleSheet("color: #f8fafc; font-size: 11px; font-weight: 500;")
        super().enterEvent(event)
        
    def leaveEvent(self, event):
        self.update_style()
        super().leaveEvent(event)
        
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._pressed = True
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and getattr(self, '_pressed', False):
            self._pressed = False
            if self.rect().contains(event.pos()):
                self.clicked.emit(self.view_index)
        super().mouseReleaseEvent(event)


class Sidebar(QFrame):
    selected_changed = Signal(int)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setStyleSheet("""
            QFrame#sidebar {
                background-color: #080c14;
                border-right: 1px solid #141c2b;
            }
        """)
        
        self.settings = QSettings("GemDetector", "Terminal")
        self.is_expanded = self.settings.value("sidebar_expanded", True, type=bool)
        self.setFixedWidth(200 if self.is_expanded else 54)
        
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        
        # Logo area
        self.logo_area = QFrame()
        self.logo_area.setFixedHeight(48)
        self.logo_area.setStyleSheet("border-bottom: 1px solid #141c2b;")
        self.logo_layout = QHBoxLayout(self.logo_area)
        self.logo_layout.setContentsMargins(14, 0, 12, 0)
        self.logo_layout.setSpacing(8)
        
        self.lbl_logo_icon = QLabel("❖")
        self.lbl_logo_icon.setStyleSheet("color: #38bdf8; font-size: 16px; font-weight: bold;")
        self.lbl_logo_text = QLabel("QUANT")
        self.lbl_logo_text.setStyleSheet("color: #f8fafc; font-size: 13px; font-weight: 800; letter-spacing: 2px;")
        
        self.logo_layout.addWidget(self.lbl_logo_icon)
        self.logo_layout.addWidget(self.lbl_logo_text)
        self.logo_layout.addStretch()
        
        # Scroll area for nav items
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("border: none; background: transparent;")
        
        self.nav_container = QWidget()
        self.nav_container.setStyleSheet("background: transparent;")
        self.nav_layout = QVBoxLayout(self.nav_container)
        self.nav_layout.setContentsMargins(0, 6, 0, 6)
        self.nav_layout.setSpacing(1)
        
        self.items = []
        self.sections = []
        
        self._add_section("OVERVIEW")
        self._add_item(0, "◎", "Live Radar")
        self._add_item(15, "▦", "Market Overview")
        
        self._add_section("DISCOVERY")
        self._add_item(1, "⌕", "Token Detail")
        self._add_item(2, "♟", "Trader Behavior")
        self._add_item(4, "◆", "Smart Money")
        self._add_item(14, "◌", "Shadow Universe")
        
        self._add_section("TRADING")
        self._add_item(7, "▶", "Paper Trading")
        self._add_item(5, "◷", "Trade Timeline")
        self._add_item(6, "▲", "Performance")
        
        self._add_section("RESEARCH")
        self._add_item(3, "⬡", "Adaptive Learning")
        self._add_item(8, "▽", "Opportunity Funnel")
        self._add_item(9, "◪", "Outcome Maturity")
        self._add_item(10, "★", "Ranking Power")
        self._add_item(11, "⊙", "Prob Calibration")
        
        self._add_section("SYSTEM")
        self._add_item(12, "✓", "Discovery Audit")
        self._add_item(13, "⎔", "Execution Audit")
        self._add_item(16, "✚", "System Health")
        self._add_item(17, "≡", "Logs")
        self._add_item(18, "⛯", "Settings")
        self._add_item(19, "?", "Knowledge Base")
        
        self.nav_layout.addStretch()
        self.scroll.setWidget(self.nav_container)
        
        # Collapse toggle
        self.toggle_area = QFrame()
        self.toggle_area.setStyleSheet("border-top: 1px solid #141c2b;")
        self.toggle_layout = QHBoxLayout(self.toggle_area)
        self.toggle_layout.setContentsMargins(8, 4, 8, 4)
        self.btn_toggle = QPushButton("⇤")
        self.btn_toggle.setObjectName("btnGhost")
        self.btn_toggle.setFixedHeight(28)
        self.btn_toggle.setCursor(Qt.PointingHandCursor)
        self.btn_toggle.setToolTip("Toggle Sidebar (Compact / Expanded)")
        self.btn_toggle.clicked.connect(self.toggle_collapse)
        self.toggle_layout.addWidget(self.btn_toggle)
        
        self.layout.addWidget(self.logo_area)
        self.layout.addWidget(self.scroll)
        self.layout.addWidget(self.toggle_area)
        
        self.anim = QPropertyAnimation(self, b"minimumWidth")
        self.anim_max = QPropertyAnimation(self, b"maximumWidth")
        self.anim.setDuration(150)
        self.anim_max.setDuration(150)
        
        self._apply_expanded_state(self.is_expanded)
        if self.items:
            self.set_selected(0)

    def set_item_badge(self, view_index: int, text: str):
        for item in self.items:
            if item.view_index == view_index:
                item.set_badge(text)
                break
            
    def _add_section(self, name):
        lbl = QLabel(name)
        lbl.setStyleSheet("color: #475569; font-size: 9px; font-weight: 800; letter-spacing: 0.8px; padding-left: 14px; padding-top: 10px; padding-bottom: 2px;")
        self.nav_layout.addWidget(lbl)
        self.sections.append(lbl)
        
    def _add_item(self, index, icon, label):
        item = NavItem(index, icon, label)
        item.clicked.connect(self._on_item_clicked)
        self.nav_layout.addWidget(item)
        self.items.append(item)
        
    def _on_item_clicked(self, index):
        self.set_selected(index)
        self.selected_changed.emit(index)
        
    def set_selected(self, index, notify: bool = False):
        for item in self.items:
            item.set_selected(item.view_index == index)
        if notify:
            self.selected_changed.emit(index)
            
    def toggle_collapse(self):
        self.is_expanded = not self.is_expanded
        self.settings.setValue("sidebar_expanded", self.is_expanded)
        
        start_w = 54 if self.is_expanded else 200
        end_w = 200 if self.is_expanded else 54
        
        self.anim.setStartValue(start_w)
        self.anim.setEndValue(end_w)
        self.anim_max.setStartValue(start_w)
        self.anim_max.setEndValue(end_w)
        
        self.anim.start()
        self.anim_max.start()
        
        self._apply_expanded_state(self.is_expanded)
        
    def _apply_expanded_state(self, expanded):
        self.lbl_logo_text.setVisible(expanded)
        self.btn_toggle.setText("≪" if expanded else "≫")
        for sec in self.sections:
            sec.setVisible(expanded)
        for item in self.items:
            item.set_expanded(expanded)
