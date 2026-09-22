"""
Thread-safe Global Application Event Bus
Decouples UI views, background workers, and quantitative services using Qt Signals.
"""

from typing import Any, Dict, Optional
from PySide6.QtCore import QObject, Signal


class AppEventBus(QObject):
    # Scanner Lifecycle Signals
    scanner_status_changed = Signal(str, str)     # status ("RUNNING" | "STOPPED" | "PAUSED"), mode ("SHADOW" | "PAPER" | "LIVE")
    scanner_error = Signal(str)                   # error message

    # Data Stream Signals
    candidate_discovered = Signal(dict)           # TokenCandidate dict
    candidate_updated = Signal(dict)              # TokenCandidate dict with predictions & state
    alert_triggered = Signal(dict)                # GemScoreOutput dict
    token_selected = Signal(str)                  # token_address

    # Paper Trading Signals
    paper_trade_opened = Signal(dict)             # PaperTradeRecord dict
    paper_trade_closed = Signal(dict)             # PaperTradeRecord dict
    paper_ledger_updated = Signal()

    # Research & Invariant Signals
    population_registry_updated = Signal()
    outcome_maturity_updated = Signal()
    survival_analysis_updated = Signal()

    # System Health & Telemetry Signals
    system_health_updated = Signal(dict)          # health metrics dict
    log_emitted = Signal(str, str, str, str)      # timestamp, level, component, message

    # UI Navigation Signals
    navigate_to_token_detail = Signal(str)        # token_address
    navigate_to_tab = Signal(int)                 # tab_index


# Global Singleton Event Bus Instance
event_bus = AppEventBus()
