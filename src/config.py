"""
Gem Detector - Configuration Module
Loads, validates, and manages scanner settings, filters, scoring weights, and presets.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml


@dataclass
class ScannerConfig:
    active_chains: List[str] = field(default_factory=lambda: ["solana", "bsc"])
    poll_interval_sec: float = 10.0
    max_token_age_minutes: float = 180.0
    enable_websocket_feed: bool = True
    dashboard_display_limit: int = 15


@dataclass
class FilterConfig:
    min_market_cap_usd: float = 5000.0
    max_market_cap_usd: float = 75000.0
    min_token_age_minutes: float = 0.5
    min_liquidity_usd: float = 5000.0
    min_liquidity_mc_ratio: float = 0.15
    min_p_reach_3m: float = 0.09
    min_volume_5m_usd: float = 2000.0
    min_volume_mc_ratio: float = 0.6
    max_volume_mc_ratio: float = 5.0
    min_buy_sell_ratio: float = 1.5
    min_unique_buyers: int = 40
    min_buyer_seller_ratio: float = 1.4
    max_top10_holder_percent: float = 18.0
    max_dev_holding_percent: float = 3.0
    require_mint_renounced: bool = True
    require_freeze_renounced: bool = True
    max_allowed_tax_percent: float = 1.0



@dataclass
class ScoringWeights:
    holder_distribution: float = 25.0
    volume_momentum: float = 25.0
    order_flow: float = 20.0
    liquidity_health: float = 20.0
    social_virality: float = 10.0


@dataclass
class ScoringConfig:
    alert_score_threshold: float = 75.0
    weights: ScoringWeights = field(default_factory=ScoringWeights)


@dataclass
class TelegramAlertConfig:
    enabled: bool = False
    bot_token: str = ""
    chat_id: str = ""
    min_score_for_alert: float = 75.0


@dataclass
class DiscordAlertConfig:
    enabled: bool = False
    webhook_url: str = ""
    min_score_for_alert: float = 75.0


@dataclass
class TerminalAlertConfig:
    sound_alert: bool = True
    log_to_file: bool = True
    log_file_path: str = "logs/detected_gems.jsonl"


@dataclass
class AlertConfig:
    telegram: TelegramAlertConfig = field(default_factory=TelegramAlertConfig)
    discord: DiscordAlertConfig = field(default_factory=DiscordAlertConfig)
    terminal: TerminalAlertConfig = field(default_factory=TerminalAlertConfig)


@dataclass
class AppConfig:
    scanner: ScannerConfig = field(default_factory=ScannerConfig)
    filters: FilterConfig = field(default_factory=FilterConfig)
    scoring: ScoringConfig = field(default_factory=ScoringConfig)
    alerts: AlertConfig = field(default_factory=AlertConfig)


def _deep_update(source: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively update a dictionary."""
    for key, val in overrides.items():
        if isinstance(val, dict) and key in source and isinstance(source[key], dict):
            source[key] = _deep_update(source[key], val)
        else:
            source[key] = val
    return source


def load_config(
    settings_path: str = "config/settings.yaml",
    presets_path: str = "config/presets.yaml",
    preset: Optional[str] = None,
    overrides: Optional[Dict[str, Any]] = None,
) -> AppConfig:
    """
    Load configuration from YAML files with optional preset and CLI overrides.
    """
    base_data: Dict[str, Any] = {}

    settings_file = Path(settings_path)
    if settings_file.exists():
        with open(settings_file, "r", encoding="utf-8") as f:
            base_data = yaml.safe_load(f) or {}

    # Apply preset if requested
    if preset:
        preset_file = Path(presets_path)
        if preset_file.exists():
            with open(preset_file, "r", encoding="utf-8") as f:
                presets_data = yaml.safe_load(f) or {}
                if "presets" in presets_data and preset in presets_data["presets"]:
                    preset_override = presets_data["presets"][preset]
                    # Exclude description
                    preset_override = {k: v for k, v in preset_override.items() if k != "description"}
                    base_data = _deep_update(base_data, preset_override)
                else:
                    raise ValueError(f"Preset '{preset}' not found in {presets_path}")

    # Apply manual runtime overrides
    if overrides:
        base_data = _deep_update(base_data, overrides)

    # Instantiate dataclasses
    scanner_data = base_data.get("scanner", {})
    filters_data = base_data.get("filters", {})
    scoring_data = base_data.get("scoring", {})
    alerts_data = base_data.get("alerts", {})

    scoring_weights = ScoringWeights(**scoring_data.get("weights", {}))
    scoring_cfg = ScoringConfig(
        alert_score_threshold=scoring_data.get("alert_score_threshold", 75.0),
        weights=scoring_weights,
    )

    alert_cfg = AlertConfig(
        telegram=TelegramAlertConfig(**alerts_data.get("telegram", {})),
        discord=DiscordAlertConfig(**alerts_data.get("discord", {})),
        terminal=TerminalAlertConfig(**alerts_data.get("terminal", {})),
    )

    return AppConfig(
        scanner=ScannerConfig(**scanner_data),
        filters=FilterConfig(**filters_data),
        scoring=scoring_cfg,
        alerts=alert_cfg,
    )
