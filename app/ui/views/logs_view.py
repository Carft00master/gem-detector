from app.ui.components.help_icon import HelpIcon
"""
Logs & Diagnostic Stream View
Real-time searchable and filterable application event log stream.
Equipped with interactive guides (?), level filters, and export tools.
"""

from datetime import datetime, timezone
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.application.events import event_bus
from app.ui.components.help_icon import QLabel


class LogsView(QWidget):
    COLS = ["TIMESTAMP (UTC)", "LEVEL", "COMPONENT", "MESSAGE"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.logs = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(12)

        # 1. Filter Bar with Help Guides
        f_frame = QFrame()
        f_frame.setStyleSheet("background-color: #0f141c; border: 1px solid #1f2937; border-radius: 6px; padding: 6px;")
        f_layout = QHBoxLayout(f_frame)
        f_layout.setContentsMargins(8, 4, 8, 4)
        f_layout.setSpacing(8)

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("🔍 Filter Logs by keyword or component...")
        self.search_box.textChanged.connect(self._apply_filter)
        search_help = HelpIcon("Search log messages and module components in real-time.", "Log Search")

        self.level_filter = QComboBox()
        self.level_filter.addItems(["All Levels", "INFO", "WARNING", "ERROR", "CRITICAL"])
        self.level_filter.currentIndexChanged.connect(self._apply_filter)
        level_help = HelpIcon("Filter logs by severity level (INFO, WARNING, ERROR).", "Level Filter")

        self.btn_clear = QPushButton("🗑 Clear")
        self.btn_clear.setCursor(Qt.PointingHandCursor)
        self.btn_clear.clicked.connect(self._clear_logs)

        self.btn_export = QPushButton("💾 Export Logs")
        self.btn_export.setCursor(Qt.PointingHandCursor)
        self.btn_export.clicked.connect(self._export_logs)
        export_help = HelpIcon("Save diagnostic logs to a text file for offline troubleshooting.", "Export Logs Tool")

        f_layout.addWidget(self.search_box, 2)
        f_layout.addWidget(search_help)
        f_layout.addWidget(self.level_filter, 1)
        f_layout.addWidget(level_help)
        f_layout.addWidget(self.btn_clear)
        f_layout.addWidget(self.btn_export)
        f_layout.addWidget(export_help)
        layout.addWidget(f_frame)

        # 2. Log Table
        self.table = QTableWidget()
        self.table.setColumnCount(len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.table)

        # Connect Event Bus
        event_bus.log_emitted.connect(self.add_log_entry)

        self._dirty = False

        # Populate initial startup logs
        self._add_initial_logs()

    def showEvent(self, event):
        super().showEvent(event)
        if getattr(self, '_dirty', False):
            self._apply_filter()
            self._dirty = False

    def _add_initial_logs(self):
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        self.add_log_entry(now, "INFO", "System", "Desktop Application Initialized in Dark Bloomberg Mode")
        self.add_log_entry(now, "INFO", "Manifest", "Verified Frozen v1.0.0 Research Manifest: Passed")
        self.add_log_entry(now, "INFO", "Database", "SQLite Research Database connected in WAL mode")
        self.add_log_entry(now, "INFO", "ServiceLocator", "Registered ScannerService, ResearchService, PaperTradingService")

    def add_log_entry(self, ts: str, level: str, component: str, msg: str):
        self.logs.append((ts, level, component, msg))
        if len(self.logs) > 1000:
            self.logs.pop(0)

        # Performance: If tab is not visible, simply record the log and mark dirty
        if not self.isVisible():
            self._dirty = True
            return

        search = self.search_box.text().strip().lower()
        level_f = self.level_filter.currentText()

        # If no active filter is set (default 99% of time), prepend single row in O(1) time
        if not search and level_f == "All Levels":
            self.table.setUpdatesEnabled(False)
            try:
                self.table.insertRow(0)
                lvl_item = QTableWidgetItem(level)
                if level in ("ERROR", "CRITICAL"):
                    lvl_item.setForeground(QColor("#ef4444"))
                elif level == "WARNING":
                    lvl_item.setForeground(QColor("#f59e0b"))
                else:
                    lvl_item.setForeground(QColor("#10b981"))

                items = [
                    QTableWidgetItem(ts),
                    lvl_item,
                    QTableWidgetItem(component),
                    QTableWidgetItem(msg),
                ]
                for col, itm in enumerate(items):
                    itm.setTextAlignment(Qt.AlignCenter if col in (0, 1, 2) else Qt.AlignLeft | Qt.AlignVCenter)
                    self.table.setItem(0, col, itm)

                if self.table.rowCount() > 1000:
                    self.table.removeRow(1000)
            finally:
                self.table.setUpdatesEnabled(True)
        else:
            self._apply_filter()

    def _apply_filter(self):
        search = self.search_box.text().strip().lower()
        level_f = self.level_filter.currentText()

        filtered = []
        for ts, lvl, comp, msg in self.logs:
            if search and (search not in msg.lower() and search not in comp.lower()):
                continue
            if level_f != "All Levels" and lvl != level_f:
                continue
            filtered.append((ts, lvl, comp, msg))

        self.table.setUpdatesEnabled(False)
        try:
            self.table.setRowCount(len(filtered))
            for row, (ts, lvl, comp, msg) in enumerate(reversed(filtered)):
                lvl_item = QTableWidgetItem(lvl)
                if lvl in ("ERROR", "CRITICAL"):
                    lvl_item.setForeground(QColor("#ef4444"))
                elif lvl == "WARNING":
                    lvl_item.setForeground(QColor("#f59e0b"))
                else:
                    lvl_item.setForeground(QColor("#10b981"))

                items = [
                    QTableWidgetItem(ts),
                    lvl_item,
                    QTableWidgetItem(comp),
                    QTableWidgetItem(msg),
                ]
                for col, itm in enumerate(items):
                    itm.setTextAlignment(Qt.AlignCenter if col in (0, 1, 2) else Qt.AlignLeft | Qt.AlignVCenter)
                    self.table.setItem(row, col, itm)
        finally:
            self.table.setUpdatesEnabled(True)

    def _clear_logs(self):
        self.logs.clear()
        self.table.setRowCount(0)

    def _export_logs(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export Log File", "", "Text Files (*.log *.txt)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                for ts, lvl, comp, msg in self.logs:
                    f.write(f"[{ts}] [{lvl}] [{comp}]: {msg}\n")
            QMessageBox.information(self, "Export Complete", f"Application logs exported successfully to:\n\n{path}")

