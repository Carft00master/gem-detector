"""
HelpIcon Component
Compact interactive question mark (?) badge with rich HTML tooltips and hover guides.
Can be placed beside any tool, metric card, control, or table header.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QToolTip


class HelpIcon(QLabel):
    """
    Compact circular '?' badge that displays rich contextual guide tooltips on mouse hover.
    """

    def __init__(self, tooltip_text: str, title: str = "", parent=None):
        super().__init__("?", parent)
        self.setFixedSize(18, 18)
        self.setAlignment(Qt.AlignCenter)
        self.setCursor(Qt.PointingHandCursor)

        # Build formatted rich HTML tooltip
        formatted_html = self._format_tooltip(title, tooltip_text)
        self.setToolTip(formatted_html)

        self.setStyleSheet("""
            QLabel {
                background-color: #1e293b;
                color: #60a5fa;
                border: 1px solid #3b82f6;
                border-radius: 9px;
                font-family: 'Segoe UI', sans-serif;
                font-size: 11px;
                font-weight: 800;
                padding: 0px;
                margin: 0px;
            }
            QLabel:hover {
                background-color: #2563eb;
                color: #ffffff;
                border: 1px solid #60a5fa;
            }
        """)

    @staticmethod
    def _format_tooltip(title: str, text: str) -> str:
        header = f"<b style='color:#60a5fa; font-size:13px;'>ℹ {title}</b><br/><br/>" if title else ""
        return (
            f"<div style='background-color:#0f172a; color:#e2e8f0; font-size:12px; line-height:1.4; max-width:320px; padding:6px;'>"
            f"{header}"
            f"<span>{text}</span>"
            f"</div>"
        )
