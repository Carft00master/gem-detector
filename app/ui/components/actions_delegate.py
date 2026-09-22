"""
ActionButtonsDelegate: High-performance QStyledItemDelegate
Renders clickable action buttons directly via QPainter in table cells.
Replaces heavy QWidget/QPushButton cellWidget allocations, preventing
Windows GDI exhaustion and C-stack overflow crashes (0xc00000fd / 0xc000041d).
"""

from PySide6.QtWidgets import QStyledItemDelegate, QStyle, QApplication, QToolTip
from PySide6.QtCore import Qt, QRect, QPoint, QEvent
from PySide6.QtGui import QPainter, QColor, QFont, QBrush, QCursor


class ActionButtonsDelegate(QStyledItemDelegate):
    """
    Renders up to two compact clickable action buttons in a table cell.
    """

    def __init__(self, parent=None, actions=None, on_action=None):
        super().__init__(parent)
        self.actions = actions or []
        self.on_action = on_action

    def paint(self, painter: QPainter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = option.rect

        # Respect selection highlight
        if option.state & QStyle.State_Selected:
            painter.fillRect(rect, QColor("#1e293b"))

        btn_w, btn_h = 28, 22
        spacing = 5
        n_btns = len(self.actions)
        total_w = n_btns * btn_w + (n_btns - 1) * spacing
        start_x = rect.x() + (rect.width() - total_w) // 2
        start_y = rect.y() + (rect.height() - btn_h) // 2

        font = QFont("Segoe UI", 9, QFont.Bold)
        painter.setFont(font)

        for i, act in enumerate(self.actions):
            bx = start_x + i * (btn_w + spacing)
            brect = QRect(bx, start_y, btn_w, btn_h)

            painter.setPen(QColor(act.get("border", "#1e293b")))
            painter.setBrush(QBrush(QColor(act.get("bg", "#0f172a"))))
            painter.drawRoundedRect(brect, 3, 3)

            painter.setPen(QColor(act.get("fg", "#94a3b8")))
            painter.drawText(brect, Qt.AlignCenter, act.get("label", ""))

        painter.restore()

    def editorEvent(self, event, model, option, index):
        if event.type() == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            rect = option.rect
            btn_w, btn_h = 28, 22
            spacing = 5
            n_btns = len(self.actions)
            total_w = n_btns * btn_w + (n_btns - 1) * spacing
            start_x = rect.x() + (rect.width() - total_w) // 2
            start_y = rect.y() + (rect.height() - btn_h) // 2

            pos = event.position().toPoint()
            row_data = index.data(Qt.UserRole)


            for i, act in enumerate(self.actions):
                bx = start_x + i * (btn_w + spacing)
                brect = QRect(bx, start_y, btn_w, btn_h)
                if brect.contains(pos):
                    act_id = act.get("id")
                    if self.on_action:
                        self.on_action(act_id, row_data, index.row())
                    return True
        return super().editorEvent(event, model, option, index)
