from PySide6.QtWidgets import (QFrame, QVBoxLayout, QHBoxLayout, QLineEdit, 
                             QComboBox, QPushButton, QMenu, QLabel)
from PySide6.QtCore import Signal, Qt
from app.ui.design_system import DS

class FilterBar(QFrame):
    filter_changed = Signal(dict)
    
    def __init__(self, chains=None, states=None, sort_options=None, preset_filters=None, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background-color: #0b101c; border-bottom: 1px solid #141c2b;")
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(14, 8, 14, 8)
        main_layout.setSpacing(6)
        
        # Row 1: Smart Filter Preset Pills
        row1 = QHBoxLayout()
        row1.setSpacing(6)
        
        lbl_presets = QLabel("QUICK FILTERS:")
        lbl_presets.setStyleSheet("color: #475569; font-size: 9px; font-weight: 800; letter-spacing: 0.8px;")
        row1.addWidget(lbl_presets)
        
        self.preset_buttons = {}
        presets = [
            ("ALL", "⚡ ALL"),
            ("HIGH_CONVICTION", "★ HIGH CONVICTION"),
            ("EARLY_BREAKOUT", "⚡ EARLY BREAKOUT"),
            ("STRENGTHENING", "▲ STRENGTHENING"),
            ("LOW_RUG", "🛡️ LOW RUG (<20%)"),
            ("NEW_TOKENS", "✨ NEW (<30m)"),
        ]
        
        self.active_preset = "ALL"
        for key, label in presets:
            btn = QPushButton(label)
            btn.setObjectName("filterPill")
            btn.setCheckable(True)
            btn.setChecked(key == "ALL")
            btn.setProperty("checked", key == "ALL")
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda checked, k=key: self._on_preset_clicked(k))
            row1.addWidget(btn)
            self.preset_buttons[key] = btn
            
        row1.addStretch()
        main_layout.addLayout(row1)
        
        # Row 2: Search + Granular Filters + Sort + Tools
        row2 = QHBoxLayout()
        row2.setSpacing(8)
        
        # Search
        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("🔍  Search token symbol or 0x address...")
        self.txt_search.setFixedWidth(240)
        self.txt_search.setFixedHeight(28)
        self.txt_search.textChanged.connect(self._emit_changed)
        row2.addWidget(self.txt_search)
        
        # Chain filter
        self.cmb_chain = QComboBox()
        self.cmb_chain.setFixedHeight(28)
        self.cmb_chain.addItem("All Chains")
        if chains:
            for ch in chains:
                if ch != "All Chains":
                    self.cmb_chain.addItem(ch)
        self.cmb_chain.currentTextChanged.connect(self._emit_changed)
        row2.addWidget(self.cmb_chain)
        
        # State filter
        self.cmb_state = QComboBox()
        self.cmb_state.setFixedHeight(28)
        self.cmb_state.addItem("All States")
        if states:
            for st in states:
                if st != "All States":
                    self.cmb_state.addItem(st)
        self.cmb_state.currentTextChanged.connect(self._emit_changed)
        row2.addWidget(self.cmb_state)
        
        # Sort
        self.cmb_sort = QComboBox()
        self.cmb_sort.setFixedHeight(28)
        if sort_options:
            self.cmb_sort.addItems(sort_options)
        self.cmb_sort.currentTextChanged.connect(self._emit_changed)
        row2.addWidget(self.cmb_sort)
        
        row2.addStretch()
        
        # Columns config
        self.btn_cols = QPushButton("⚙ Columns")
        self.btn_cols.setObjectName("btnSecondary")
        self.btn_cols.setFixedHeight(28)
        self.btn_cols.setCursor(Qt.PointingHandCursor)
        self.menu_cols = QMenu(self)
        for col in ["Token", "Chain", "MC", "Liq", "Age", "P(3M)", "Rug", "Signal", "@2% Cap"]:
            action = self.menu_cols.addAction(col)
            action.setCheckable(True)
            action.setChecked(True)
            action.toggled.connect(self._emit_changed)
        self.btn_cols.setMenu(self.menu_cols)
        row2.addWidget(self.btn_cols)
        
        # Refresh
        self.btn_refresh = QPushButton("↻ Refresh")
        self.btn_refresh.setObjectName("btnSecondary")
        self.btn_refresh.setFixedHeight(28)
        self.btn_refresh.setCursor(Qt.PointingHandCursor)
        self.btn_refresh.clicked.connect(lambda: self._emit_changed())
        row2.addWidget(self.btn_refresh)
        
        main_layout.addLayout(row2)
        
    def _on_preset_clicked(self, key):
        self.active_preset = key
        for k, btn in self.preset_buttons.items():
            btn.setChecked(k == key)
            btn.setProperty("checked", k == key)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        self._emit_changed()
        
    def _emit_changed(self):
        visible_cols = [action.text() for action in self.menu_cols.actions() if action.isChecked()]
        self.filter_changed.emit({
            "search": self.txt_search.text(),
            "chain": self.cmb_chain.currentText(),
            "state": self.cmb_state.currentText(),
            "sort": self.cmb_sort.currentText(),
            "preset": self.active_preset,
            "visible_columns": visible_cols
        })
        
    def get_filter(self) -> dict:
        visible_cols = [action.text() for action in self.menu_cols.actions() if action.isChecked()]
        return {
            "search": self.txt_search.text(),
            "chain": self.cmb_chain.currentText(),
            "state": self.cmb_state.currentText(),
            "sort": self.cmb_sort.currentText(),
            "preset": self.active_preset,
            "visible_columns": visible_cols
        }

