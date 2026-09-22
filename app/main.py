"""
Sub-$10K -> $3M+ Memecoin Research Scanner Desktop Application Entry Point
Initializes PySide6 Qt Application, High-DPI scaling, services, and MainWindow.
"""

import logging
import os
from pathlib import Path
import sys

# Ensure repository root is on sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from app.application.service_locator import ServiceLocator
from app.services.export_service import ExportService
from app.services.paper_trading_service import PaperTradingService
from app.services.research_service import ResearchService
from app.services.scanner_service import ScannerService
from app.services.settings_service import SettingsService
from app.ui.main_window import MainWindow
from src.version import FROZEN_VERSION_MANIFEST

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s]: %(message)s",
)
logger = logging.getLogger("MemecoinScannerApp")


def setup_services(settings_svc: SettingsService | None = None) -> None:
    """Initialize and register singletons into the ServiceLocator."""
    if settings_svc is None:
        settings_svc = SettingsService()
    paper_svc = PaperTradingService()
    research_svc = ResearchService()
    export_svc = ExportService()
    scanner_svc = ScannerService()

    ServiceLocator.register(SettingsService, settings_svc)
    ServiceLocator.register(PaperTradingService, paper_svc)
    ServiceLocator.register(ResearchService, research_svc)
    ServiceLocator.register(ExportService, export_svc)
    ServiceLocator.register(ScannerService, scanner_svc)
    logger.info("Application services successfully initialized and registered.")


def main():
    logger.info(f"Launching Sub-$10K -> $3M+ Memecoin Scanner Terminal ({FROZEN_VERSION_MANIFEST.scanner_version})")

    # Initialize settings early to configure display and performance parameters
    settings_svc = SettingsService()
    if settings_svc.is_vps_mode_active():
        os.environ.setdefault("QT_QUICK_BACKEND", "software")
        os.environ.setdefault("QSG_RENDER_LOOP", "basic")
        logger.info("VPS / Remote desktop mode active: software rendering & event throttling enabled.")

    # Set High-DPI environment variables
    os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"

    # Compress high-frequency mouse move/scroll events to ensure fluid remote RDP/VNC sessions
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_CompressHighFrequencyEvents, True)

    app = QApplication(sys.argv)
    app.setApplicationName("MemecoinScannerTerminal")
    app.setApplicationDisplayName(f"Memecoin Scanner Terminal ({FROZEN_VERSION_MANIFEST.scanner_version})")

    # Initialize Services
    setup_services(settings_svc)

    # Create and Show Main Window
    window = MainWindow()
    window.show()

    # Clean shutdown hook
    def on_app_exit():
        scanner_svc = ServiceLocator.try_get(ScannerService)
        if scanner_svc and scanner_svc.get_status() == "RUNNING":
            logger.info("Stopping background scanner worker on application exit...")
            scanner_svc.stop()

    app.aboutToQuit.connect(on_app_exit)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
