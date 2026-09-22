# -*- mode: python ; coding: utf-8 -*-
import os
from pathlib import Path

block_cipher = None

root_path = Path.cwd()

datas = [
    (str(root_path / 'config'), 'config'),
    (str(root_path / 'data'), 'data'),
    (str(root_path / 'app'), 'app'),
    (str(root_path / 'src'), 'src'),
]

binaries = []

hidden_imports = [
    'PySide6',
    'PySide6.QtCore',
    'PySide6.QtGui',
    'PySide6.QtWidgets',
    'sqlite3',
    'yaml',
    'pandas',
    'numpy',
    'scipy',
    'sklearn',
    'aiohttp',
    'websockets',
    'rich',
    'app',
    'app.main',
    'app.application',
    'app.application.events',
    'app.application.service_locator',
    'app.services',
    'app.services.scanner_service',
    'app.services.paper_trading_service',
    'app.services.research_service',
    'app.services.export_service',
    'app.services.settings_service',
    'app.ui',
    'app.ui.design_system',
    'app.ui.styles',
    'app.ui.main_window',
    'app.ui.views.live_radar_view',
    'app.ui.views.token_detail_view',
    'app.ui.views.trader_behavior_view',
    'app.ui.views.adaptive_learning_view',
    'app.ui.views.smart_money_view',
    'app.ui.views.trade_timeline_view',
    'app.ui.views.performance_learning_view',
    'app.ui.views.paper_trading_view',
    'app.ui.views.opportunity_funnel_view',
    'app.ui.views.outcome_maturity_view',
    'app.ui.views.ranking_power_view',
    'app.ui.views.calibration_view',
    'app.ui.views.discovery_audit_view',
    'app.ui.views.execution_audit_view',
    'app.ui.views.shadow_universe_view',
    'app.ui.views.market_regime_view',
    'app.ui.views.system_health_view',
    'app.ui.views.logs_view',
    'app.ui.views.settings_view',
    'app.ui.views.faq_view',
    'app.ui.components.sidebar',
    'app.ui.components.command_bar',
    'app.ui.components.notification_panel',
    'app.ui.components.search_dialog',
    'app.ui.components.stat_card',
    'app.ui.components.status_badge',
    'app.ui.components.risk_badge',
    'app.ui.components.empty_state',
    'app.ui.components.skeleton_loader',
    'app.ui.components.kpi_strip',
    'app.ui.components.filter_bar',
    'app.ui.components.prob_display',
    'app.ui.components.timeline_event',
    'app.ui.components.actions_delegate',
    'app.ui.components.async_helper',
]

a = Analysis(
    [str(root_path / 'app' / 'main.py')],
    pathex=[str(root_path)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='MemecoinScanner',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # Windowed desktop application (no console)
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='MemecoinScanner',
)
