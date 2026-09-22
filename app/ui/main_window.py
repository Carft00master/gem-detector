import logging
import time
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QStackedWidget, QMessageBox,
)
from PySide6.QtCore import Qt, QSettings
from PySide6.QtGui import QShortcut, QKeySequence

from app.application.events import event_bus
from app.application.service_locator import ServiceLocator
from app.services.scanner_service import ScannerService
from app.ui.design_system import DS
from app.ui.styles import DARK_THEME_QSS
from app.ui.components.sidebar import Sidebar
from app.ui.components.command_bar import CommandBar
from app.ui.components.notification_panel import NotificationPanel
from app.ui.components.search_dialog import GlobalSearchDialog
from app.ui.components.async_helper import run_async_task
from src.version import FROZEN_VERSION_MANIFEST

# Explicit view imports so PyInstaller statically traces and bundles all views
from app.ui.views.live_radar_view import LiveRadarView
from app.ui.views.token_detail_view import TokenDetailView
from app.ui.views.trader_behavior_view import TraderBehaviorView
from app.ui.views.adaptive_learning_view import AdaptiveLearningView
from app.ui.views.smart_money_view import SmartMoneyView
from app.ui.views.trade_timeline_view import TradeTimelineView
from app.ui.views.performance_learning_view import PerformanceLearningView
from app.ui.views.paper_trading_view import PaperTradingView
from app.ui.views.opportunity_funnel_view import OpportunityFunnelView
from app.ui.views.outcome_maturity_view import OutcomeMaturityView
from app.ui.views.ranking_power_view import RankingPowerView
from app.ui.views.calibration_view import CalibrationView
from app.ui.views.discovery_audit_view import DiscoveryAuditView
from app.ui.views.execution_audit_view import ExecutionAuditView
from app.ui.views.shadow_universe_view import ShadowUniverseView
from app.ui.views.market_regime_view import MarketRegimeView
from app.ui.views.system_health_view import SystemHealthView
from app.ui.views.logs_view import LogsView
from app.ui.views.settings_view import SettingsView
from app.ui.views.faq_view import FAQView

logger = logging.getLogger(__name__)


class _NavListBridge:
    def __init__(self, main_window):
        self._win = main_window

    def setCurrentRow(self, row: int):
        self._win.navigate_to(row)

    def currentRow(self) -> int:
        return self._win.stacked.currentIndex()

    def count(self) -> int:
        return len(MainWindow.NAV_ITEMS)


class MainWindow(QMainWindow):
    NAV_ITEMS = [
        "📡  Live Radar",
        "🔍  Token Detail",
        "👥  Trader Behavior",
        "🧠  Adaptive Learning",
        "💼  Smart Money",
        "⏳  Trade Timeline",
        "📈  Performance",
        "📝  Paper Trading",
        "🌪️  Opportunity Funnel",
        "🎯  Outcome Maturity",
        "⚡  Ranking Power",
        "📐  Calibration",
        "🔎  Discovery Audit",
        "⚖️  Execution Audit",
        "🌌  Shadow Universe",
        "🌡️  Market Regime",
        "🩺  System Health",
        "📜  Logs",
        "⚙️  Settings",
        "❓  FAQ",
    ]

    def __init__(self):
        super().__init__()
        self.scanner_svc: ScannerService = ServiceLocator.get(ScannerService)
        self.setWindowTitle(f"Sub-$10K → $3M+ Memecoin Research Terminal ({FROZEN_VERSION_MANIFEST.scanner_version})")
        self.setMinimumSize(1280, 768)
        self.setStyleSheet(DARK_THEME_QSS)
        self.nav_list = _NavListBridge(self)

        
        # Main layout
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QHBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        
        # 1. Sidebar
        self.sidebar = Sidebar()
        self.sidebar.selected_changed.connect(self._on_nav_changed)
        
        # 2. Right side container (Command Bar + Content)
        self.right_container = QWidget()
        self.right_layout = QVBoxLayout(self.right_container)
        self.right_layout.setContentsMargins(0, 0, 0, 0)
        self.right_layout.setSpacing(0)
        
        # Command Bar
        self.cmd_bar = CommandBar()
        self.cmd_bar.start_clicked.connect(self._on_start_clicked)
        self.cmd_bar.stop_clicked.connect(self._on_stop_clicked)
        self.cmd_bar.pause_clicked.connect(lambda: self.scanner_svc.pause() if hasattr(self.scanner_svc, "pause") else None)
        self.cmd_bar.search_clicked.connect(self._show_search)
        self.cmd_bar.notifications_clicked.connect(self._toggle_notifications)
        self.cmd_bar.settings_clicked.connect(lambda: self.navigate_to(18))
        
        # Content Area (Stacked Widget + Notification Panel)
        self.content_area = QWidget()
        self.content_layout = QHBoxLayout(self.content_area)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(0)
        
        # Stacked Views Container
        self.stacked = QStackedWidget()
        
        self.notification_panel = NotificationPanel()
        
        self.content_layout.addWidget(self.stacked)
        self.content_layout.addWidget(self.notification_panel)
        
        self.right_layout.addWidget(self.cmd_bar)
        self.right_layout.addWidget(self.content_area)
        
        self.main_layout.addWidget(self.sidebar)
        self.main_layout.addWidget(self.right_container)
        
        # Lazy View Factories: views are instantiated only when first navigated to
        self.view_factories = [
            lambda: LiveRadarView(),
            lambda: TokenDetailView(),
            lambda: TraderBehaviorView(),
            lambda: AdaptiveLearningView(),
            lambda: SmartMoneyView(),
            lambda: TradeTimelineView(),
            lambda: PerformanceLearningView(),
            lambda: PaperTradingView(),
            lambda: OpportunityFunnelView(),
            lambda: OutcomeMaturityView(),
            lambda: RankingPowerView(),
            lambda: CalibrationView(),
            lambda: DiscoveryAuditView(),
            lambda: ExecutionAuditView(),
            lambda: ShadowUniverseView(),
            lambda: MarketRegimeView(),
            lambda: SystemHealthView(),
            lambda: LogsView(),
            lambda: SettingsView(),
            lambda: FAQView(),
        ]
        self._views = [None] * len(self.view_factories)
        
        # Pre-populate placeholders
        for i in range(len(self.view_factories)):
            if i == 0:
                v0 = self.view_factories[0]()
                self._views[0] = v0
                self.stacked.addWidget(v0)
            else:
                placeholder = QWidget()
                self.stacked.addWidget(placeholder)
                
        # Connect Event Bus
        event_bus.scanner_status_changed.connect(self._on_scanner_status_changed)
        event_bus.scanner_error.connect(self._on_scanner_error)
        event_bus.navigate_to_token_detail.connect(self._on_navigate_to_detail)
        event_bus.navigate_to_tab.connect(self._on_navigate_to_tab)
        event_bus.candidate_updated.connect(self._on_candidate_updated)
        event_bus.paper_trade_opened.connect(self._on_trade_event)
        event_bus.paper_trade_closed.connect(self._on_trade_event)
        
        # Keyboard Shortcuts
        QShortcut(QKeySequence("Ctrl+1"), self).activated.connect(lambda: self.navigate_to(0))
        QShortcut(QKeySequence("Ctrl+2"), self).activated.connect(lambda: self.navigate_to(7))
        QShortcut(QKeySequence("Ctrl+3"), self).activated.connect(lambda: self.navigate_to(4))
        QShortcut(QKeySequence("Ctrl+K"), self).activated.connect(self._show_search)
        QShortcut(QKeySequence("Esc"), self).activated.connect(self._on_esc)
        QShortcut(QKeySequence("R"), self).activated.connect(self._on_refresh_view)
        
        # Initial State
        self.cmd_bar.update_chains(["solana", "bsc"])
        self.cmd_bar.update_regime("NORMAL")
        self._last_radar_badge_count = -1
        self._last_trade_badge_count = -1
        self._view_refresh_timestamps = {0: time.time()}

    def navigate_to(self, row: int):
        """Navigate to a view by index, updating sidebar selection and displaying the view."""
        if 0 <= row < len(self.view_factories):
            self.sidebar.set_selected(row)
            self._on_nav_changed(row)

    def get_view(self, index: int) -> QWidget:
        if 0 <= index < len(self._views):
            if self._views[index] is None:
                try:
                    view = self.view_factories[index]()
                except Exception as e:
                    logger.error(f"Error instantiating view {index}: {e}", exc_info=True)
                    view = QWidget()
                self._views[index] = view
                placeholder = self.stacked.widget(index)
                if placeholder is not None:
                    self.stacked.removeWidget(placeholder)
                    placeholder.deleteLater()
                self.stacked.insertWidget(index, view)
            return self._views[index]
        return None

    @property
    def view_radar(self): return self.get_view(0)
    @property
    def view_detail(self): return self.get_view(1)

    def _on_nav_changed(self, row: int):
        if 0 <= row < len(self.view_factories):
            self.sidebar.set_selected(row)
            is_new = (self._views[row] is None)
            current_widget = self.get_view(row)
            if current_widget is not None:
                # 1. Instant tab switch (0ms blocking)
                self.stacked.setCurrentWidget(current_widget)
                self.stacked.setCurrentIndex(row)
                current_widget.show()
                current_widget.raise_()

                # 2. Smart refresh: if newly created, __init__ already initialized it.
                # If existing, only refresh if stale (> 30s) so tab switching is lightning fast.
                now = time.time()
                last_t = self._view_refresh_timestamps.get(row, 0.0)
                if is_new:
                    self._view_refresh_timestamps[row] = now
                elif (now - last_t) > 30.0:
                    self._view_refresh_timestamps[row] = now
                    if hasattr(current_widget, "refresh_data"):
                        try:
                            current_widget.refresh_data()
                        except Exception as e:
                            logger.warning(f"Error refreshing view {row}: {e}")
                
    def _on_start_clicked(self):
        started = self.scanner_svc.start(mode="PAPER")
        if not started:
            self.cmd_bar.update_status("stopped", "")
            
    def _on_stop_clicked(self):
        self.cmd_bar.update_status("stopping", "")
        run_async_task(self.scanner_svc.stop, lambda res: None, parent=self)
        
    def _on_scanner_status_changed(self, status: str, mode: str):
        self.cmd_bar.update_status(status.lower(), mode)
        
    def _on_scanner_error(self, error_msg: str):
        self.cmd_bar.update_status("stopped", "")
        self.notification_panel.add_notification("SYSTEM_ERROR", "Scanner Failed", error_msg)
        self.cmd_bar.set_unread_count(self.notification_panel.unread_count)
        QMessageBox.warning(self, "Scanner Error", f"The scanner encountered an issue:\n\n{error_msg}\n\nPlease check the Logs tab.")
        
    def _on_navigate_to_detail(self, token_address: str):
        self.navigate_to(1)
        if self.view_detail and hasattr(self.view_detail, 'load_token'):
            self.view_detail.load_token(token_address)
        
    def _on_navigate_to_tab(self, tab_idx: int):
        self.navigate_to(tab_idx)
        
    def _toggle_notifications(self):
        self.notification_panel.toggle_visibility()
        if self.notification_panel.isVisible():
            self.cmd_bar.set_unread_count(0)
            
    def _show_search(self):
        dialog = GlobalSearchDialog(self._search_provider, self)
        dialog.result_selected.connect(self._on_search_result)
        dialog.exec()
        
    def _search_provider(self, query):
        q = str(query).strip().lower()
        results = []
        if self.view_radar and hasattr(self.view_radar, 'candidates'):
            for c in self.view_radar.candidates.values():
                sym = str(c.get('symbol', '')).lower()
                addr = str(c.get('token_address', '')).lower()
                name = str(c.get('name', '')).lower()
                if q in sym or q in addr or q in name:
                    chain = str(c.get('chain', 'UNK')).upper()
                    mc = float(c.get('market_cap_usd', 0) or 0)
                    results.append({
                        "icon": "💎",
                        "name": f"{c.get('symbol', 'UNK')} · {chain} (${mc:,.0f})",
                        "type": "token",
                        "id": c.get('token_address', '')
                    })
                    if len(results) >= 8:
                        break
        return results
        
    def _on_search_result(self, type_, id_):
        if type_ == "token":
            self._on_navigate_to_detail(id_)
            
    def _on_esc(self):
        if self.notification_panel.isVisible():
            self.notification_panel.toggle_visibility()
            
    def _on_refresh_view(self):
        current_widget = self.stacked.currentWidget()
        if hasattr(current_widget, "refresh_data"):
            current_widget.refresh_data()
            
    def _on_candidate_updated(self, data):
        import time
        now = time.monotonic()
        if hasattr(self, "_last_radar_badge_time") and (now - self._last_radar_badge_time) < 1.0:
            return
        self._last_radar_badge_time = now
        if self.view_radar and hasattr(self.view_radar, 'candidates'):
            cnt = len(self.view_radar.candidates)
            if cnt != self._last_radar_badge_count:
                self._last_radar_badge_count = cnt
                self.sidebar.set_item_badge(0, str(cnt) if cnt > 0 else "")
        
    def _on_trade_event(self, data):
        self.notification_panel.add_notification(
            "TRADE", "Paper Trade Executed",
            f"{data.get('symbol', 'Token')} trade event.",
            token_address=data.get('address')
        )
        self.cmd_bar.set_unread_count(self.notification_panel.unread_count)
        # Avoid forcing lazy instantiation of PaperTradingView (index 7) if it's not created yet
        if 0 <= 7 < len(self._views) and self._views[7] is not None:
            p_view = self._views[7]
            if hasattr(p_view, 'trades'):
                open_count = len([t for t in p_view.trades if t.get('status') == 'OPEN'])
                if open_count != self._last_trade_badge_count:
                    self._last_trade_badge_count = open_count
                    self.sidebar.set_item_badge(7, str(open_count) if open_count > 0 else "")
