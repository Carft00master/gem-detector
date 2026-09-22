"""
GaugeWidget Component
Custom visual meter for risk levels, quality scores, and probability vectors.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar, QVBoxLayout


class GaugeWidget(QFrame):
    def __init__(
        self,
        label: str,
        value: float = 0.0,
        min_val: float = 0.0,
        max_val: float = 1.0,
        is_risk: bool = False,
        is_percentage: bool = True,
        parent=None,
    ):
        super().__init__(parent)
        self.min_val = min_val
        self.max_val = max_val
        self.is_risk = is_risk
        self.is_percentage = is_percentage

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(3)

        header_layout = QHBoxLayout()
        self.label_lbl = QLabel(label)
        self.label_lbl.setStyleSheet("color: #9ca3af; font-size: 11px; font-weight: 500;")

        self.value_lbl = QLabel("")
        self.value_lbl.setStyleSheet("color: #f3f4f6; font-size: 11px; font-weight: bold;")
        header_layout.addWidget(self.label_lbl)
        header_layout.addStretch()
        header_layout.addWidget(self.value_lbl)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setTextVisible(False)

        layout.addLayout(header_layout)
        layout.addWidget(self.progress_bar)

        self.set_value(value)

    def set_value(self, val: float):
        norm = (val - self.min_val) / max(0.001, (self.max_val - self.min_val))
        pct = int(min(100, max(0, norm * 100)))
        self.progress_bar.setValue(pct)

        if self.is_percentage:
            self.value_lbl.setText(f"{val:.1%}" if self.max_val <= 1.0 else f"{val:.1f}%")
        else:
            self.value_lbl.setText(f"{val:.2f}")

        # Dynamic Color assignment
        if self.is_risk:
            # Low risk is green, high risk is red
            if norm < 0.25:
                color = "#10b981"  # Emerald
            elif norm < 0.55:
                color = "#f59e0b"  # Amber
            else:
                color = "#ef4444"  # Red
        else:
            # High quality/probability is green, low is blue/gray
            if norm > 0.70:
                color = "#10b981"
            elif norm > 0.35:
                color = "#3b82f6"
            else:
                color = "#6b7280"

        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: #1f2937;
                border: none;
                border-radius: 4px;
            }}
            QProgressBar::chunk {{
                background-color: {color};
                border-radius: 4px;
            }}
        """)
