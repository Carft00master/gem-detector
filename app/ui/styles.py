from app.ui.design_system import DS

DARK_THEME_QSS = f"""
/* Global Reset & Base Styling */
QMainWindow, QWidget {{
    background-color: {DS.BG_BASE};
    color: {DS.TEXT_PRIMARY};
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
    font-size: 12px;
}}

/* Crisp Monospace for Numbers and Tables */
.mono-text {{
    font-family: 'Consolas', 'Roboto Mono', 'SF Mono', monospace;
}}

/* Thin Sleek ScrollBars */
QScrollBar:vertical {{
    background: {DS.BG_BASE};
    width: 6px;
    margin: 0px;
}}
QScrollBar:horizontal {{
    background: {DS.BG_BASE};
    height: 6px;
    margin: 0px;
}}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
    background: #1e293b;
    border-radius: 3px;
    min-height: 24px;
    min-width: 24px;
}}
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {{
    background: #334155;
}}
QScrollBar::add-line, QScrollBar::sub-line,
QScrollBar::add-page, QScrollBar::sub-page {{
    background: none;
    border: none;
}}

/* Buttons */
QPushButton {{
    background-color: #131b2e;
    color: #e2e8f0;
    border: 1px solid #1e293b;
    border-radius: 4px;
    padding: 5px 12px;
    font-weight: 600;
    font-size: 11px;
}}
QPushButton:hover {{
    background-color: #1e293b;
    border-color: #38bdf8;
    color: #ffffff;
}}
QPushButton:pressed {{
    background-color: #0f172a;
}}
QPushButton:disabled {{
    background-color: #0b0f19;
    color: #475569;
    border: 1px solid #141c2b;
}}

/* Primary Emerald Start Button */
QPushButton#btnSuccess {{
    background-color: #065f46;
    color: #ecfdf5;
    border: 1px solid #10b981;
    font-weight: 700;
    letter-spacing: 0.5px;
}}
QPushButton#btnSuccess:hover {{
    background-color: #047857;
    border-color: #34d399;
    color: #ffffff;
}}
QPushButton#btnSuccess:disabled {{
    background-color: #06231a;
    border-color: #0c3b2d;
    color: #276749;
}}

/* Danger Crimson Stop Button */
QPushButton#btnDanger {{
    background-color: #7f1d1d;
    color: #fef2f2;
    border: 1px solid #ef4444;
    font-weight: 700;
    letter-spacing: 0.5px;
}}
QPushButton#btnDanger:hover {{
    background-color: #991b1b;
    border-color: #f87171;
    color: #ffffff;
}}
QPushButton#btnDanger:disabled {{
    background-color: #260c0c;
    border-color: #451212;
    color: #6b2121;
}}

/* Secondary Outlined Buttons */
QPushButton#btnSecondary {{
    background-color: #0e1626;
    color: #94a3b8;
    border: 1px solid #1e293b;
}}
QPushButton#btnSecondary:hover {{
    background-color: #172554;
    border-color: #38bdf8;
    color: #38bdf8;
}}

/* Ghost Clean Buttons */
QPushButton#btnGhost {{
    background-color: transparent;
    color: #94a3b8;
    border: 1px solid transparent;
}}
QPushButton#btnGhost:hover {{
    background-color: #1e293b;
    color: #f8fafc;
    border-color: #334155;
}}

/* Pill Toggle Buttons (Smart Filters) */
QPushButton#filterPill {{
    background-color: #0e1626;
    color: #94a3b8;
    border: 1px solid #1e293b;
    border-radius: 12px;
    padding: 3px 10px;
    font-size: 11px;
    font-weight: 600;
}}
QPushButton#filterPill:hover {{
    background-color: #172554;
    border-color: #38bdf8;
    color: #f8fafc;
}}
QPushButton#filterPill[checked="true"], QPushButton#filterPill:checked {{
    background-color: #0369a1;
    color: #ffffff;
    border: 1px solid #38bdf8;
    font-weight: 700;
}}

/* Table Views */
QTableWidget, QTableView {{
    background-color: #090d16;
    alternate-background-color: #0d121f;
    border: 1px solid #141c2e;
    border-radius: 4px;
    gridline-color: #101726;
    selection-background-color: #172554;
    selection-color: #ffffff;
    font-size: 12px;
}}
QHeaderView::section {{
    background-color: #0b101c;
    color: #64748b;
    padding: 6px 10px;
    border: none;
    border-bottom: 1px solid #1e293b;
    border-right: 1px solid #101726;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.8px;
    text-transform: uppercase;
}}
QTableWidget::item, QTableView::item {{
    padding: 0px 8px;
    border-bottom: 1px solid #0f1523;
}}
QTableWidget::item:selected, QTableView::item:selected {{
    background-color: #172554;
    color: #ffffff;
}}
QTableWidget::item:hover, QTableView::item:hover {{
    background-color: #151e33;
}}

/* Inputs and Combos */
QLineEdit {{
    background-color: #0b101c;
    color: #f8fafc;
    border: 1px solid #1e293b;
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 12px;
}}
QLineEdit:hover {{
    border-color: #334155;
}}
QLineEdit:focus {{
    border-color: #38bdf8;
    background-color: #0f172a;
}}

QComboBox {{
    background-color: #0b101c;
    color: #cbd5e1;
    border: 1px solid #1e293b;
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 11px;
    font-weight: 600;
}}
QComboBox:hover {{
    border-color: #38bdf8;
    color: #ffffff;
}}
QComboBox::drop-down {{
    border: none;
    width: 18px;
}}
QComboBox QAbstractItemView {{
    background-color: #0f172a;
    color: #cbd5e1;
    border: 1px solid #1e293b;
    selection-background-color: #1e293b;
    selection-color: #38bdf8;
    padding: 4px;
}}

/* Tab Widgets */
QTabWidget::pane {{
    border: 1px solid #1e293b;
    border-radius: 4px;
    background-color: #0b0f19;
}}
QTabBar::tab {{
    background-color: #080c14;
    color: #64748b;
    padding: 8px 16px;
    font-weight: 600;
    font-size: 11px;
    border-bottom: 2px solid transparent;
}}
QTabBar::tab:hover {{
    color: #cbd5e1;
}}
QTabBar::tab:selected {{
    color: #38bdf8;
    border-bottom: 2px solid #38bdf8;
    background-color: #0f172a;
}}

/* Context Menus */
QMenu {{
    background-color: #0f172a;
    color: #f1f5f9;
    border: 1px solid #1e293b;
    border-radius: 6px;
    padding: 4px;
}}
QMenu::item {{
    padding: 6px 14px;
    border-radius: 3px;
}}
QMenu::item:selected {{
    background-color: #1e293b;
    color: #38bdf8;
}}

/* Tooltips */
QToolTip {{
    background-color: #090d16;
    color: #f8fafc;
    border: 1px solid #0284c7;
    border-radius: 4px;
    padding: 6px 10px;
    font-size: 11px;
}}
"""

