# coding: utf-8
"""Design System - Centralized Design Tokens for Quant Memecoin Scanner."""


class DS:
    BG_BASE = "#080a0f"
    BG_SURFACE = "#0d1117"
    BG_ELEVATED = "#111827"
    BG_HOVER = "#161d2e"
    BG_SELECTED = "#1a2849"
    ACCENT_BLUE = "#3b82f6"
    ACCENT_BLUE_D = "#1d4ed8"
    ACCENT_GREEN = "#10b981"
    ACCENT_GREEN_D = "#059669"
    ACCENT_AMBER = "#f59e0b"
    ACCENT_RED = "#ef4444"
    ACCENT_RED_D = "#dc2626"
    ACCENT_PURPLE = "#8b5cf6"
    ACCENT_CYAN = "#06b6d4"
    BORDER = "#1f2937"
    BORDER_STRONG = "#374151"
    BORDER_ACCENT = "#2d4a7a"
    TEXT_PRIMARY = "#f3f4f6"
    TEXT_SECONDARY = "#9ca3af"
    TEXT_MUTED = "#6b7280"
    TEXT_DISABLED = "#4b5563"
    COLOR_WIN = "#10b981"
    COLOR_LOSS = "#ef4444"
    COLOR_NEUTRAL = "#9ca3af"
    COLOR_WARN = "#f59e0b"
    COLOR_INFO = "#3b82f6"
    COLOR_OPEN_TRADE = "#06b6d4"
    FONT_FAMILY = "Segoe UI, SF Pro Display, -apple-system, sans-serif"
    FONT_MONO = "Consolas, SF Mono, Fira Code, monospace"
    FONT_XS = "10px"
    FONT_SM = "11px"
    FONT_BASE = "13px"
    FONT_LG = "15px"
    FONT_XL = "18px"
    FONT_2XL = "22px"
    FONT_3XL = "28px"
    SPACE_XS = 4
    SPACE_SM = 8
    SPACE_MD = 12
    SPACE_LG = 16
    SPACE_XL = 24
    RADIUS_XS = 3
    RADIUS_SM = 4
    RADIUS_MD = 6
    RADIUS_LG = 8
    RADIUS_XL = 12
    H_COMMAND_BAR = 52
    H_STATUS_BAR = 26
    H_TABLE_ROW = 38
    H_TABLE_HEADER = 32
    H_INPUT = 32
    H_BUTTON = 32
    H_BUTTON_SM = 26
    H_KPI_STRIP = 68
    H_FILTER_BAR = 42
    SIDEBAR_EXPANDED = 220
    SIDEBAR_COLLAPSED = 60
    SIDEBAR_ANIM_MS = 150
    ANIM_FAST = 120
    ANIM_NORMAL = 180
    ANIM_SLOW = 280


SIGNAL_STATE_META = {
    "WATCH":           {"label": "WATCH",      "icon": "eye",  "color": DS.TEXT_MUTED,     "bg": DS.BG_ELEVATED},
    "EARLY_BREAKOUT":  {"label": "BREAKOUT",   "icon": "bolt", "color": DS.ACCENT_BLUE,    "bg": "#0d1f3c"},
    "STRENGTHENING":   {"label": "STRENGTH",   "icon": "up",   "color": DS.ACCENT_GREEN,   "bg": "#0a1f17"},
    "TARGET_PROGRESS": {"label": "TARGET",     "icon": "aim",  "color": DS.ACCENT_AMBER,   "bg": "#1f1505"},
    "WEAKENING":       {"label": "WEAKENING",  "icon": "down", "color": "#fb923c",         "bg": "#1f0f05"},
    "INVALIDATED":     {"label": "INVALID",    "icon": "x",    "color": DS.ACCENT_RED,     "bg": "#1f0505"},
    "EXIT":            {"label": "EXIT",       "icon": "stop", "color": DS.ACCENT_PURPLE,  "bg": "#160b2e"},
    "HIGH_CONVICTION": {"label": "CONVICTION", "icon": "star", "color": DS.ACCENT_GREEN,   "bg": "#0a1f17"},
}


def rug_risk_level(p_rug: float) -> dict:
    if p_rug < 0.20:
        return {"label": "LOW",  "color": DS.ACCENT_GREEN, "bg": "#0a1f17"}
    elif p_rug < 0.45:
        return {"label": "MED",  "color": DS.ACCENT_AMBER, "bg": "#1f1505"}
    else:
        return {"label": "HIGH", "color": DS.ACCENT_RED,   "bg": "#1f0505"}


def cabal_risk_level(score: float) -> dict:
    if score < 0.25:
        return {"label": "LOW",  "color": DS.ACCENT_GREEN, "bg": "#0a1f17"}
    elif score < 0.55:
        return {"label": "MED",  "color": DS.ACCENT_AMBER, "bg": "#1f1505"}
    else:
        return {"label": "HIGH", "color": DS.ACCENT_RED,   "bg": "#1f0505"}
