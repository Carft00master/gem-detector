"""
Application VPS Governor Service
Provides UI integration, memory monitoring, and automated lifecycle management for VPS environments.
"""

from typing import Any, Dict, List, Optional
from PySide6.QtCore import QObject, QTimer

from src.utils.vps_governor import vps_governor, VPSGovernorEngine


class VPSService(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.governor: VPSGovernorEngine = vps_governor
        
        # Periodic 30s background hygiene timer
        self.hygiene_timer = QTimer(self)
        self.hygiene_timer.setInterval(30000)
        self.hygiene_timer.timeout.connect(self._on_hygiene_tick)
        self.hygiene_timer.start()

    def _on_hygiene_tick(self):
        self.governor.perform_memory_hygiene()

    def is_vps_mode(self) -> bool:
        return self.governor.is_vps()

    def set_vps_mode(self, enabled: bool) -> None:
        self.governor.set_vps_mode(enabled)

    def cap_universe(self, items: List[Dict[str, Any]], max_size: Optional[int] = None) -> List[Dict[str, Any]]:
        return self.governor.cap_evaluation_universe(items, max_size)

    def should_emit_candidate(self) -> bool:
        return self.governor.should_emit_candidate()

    def register_view(self, view_index: int, view_widget: Any) -> None:
        self.governor.register_view(view_index, view_widget)

    def on_view_changed(self, new_index: int) -> None:
        self.governor.notify_active_view_changed(new_index)
