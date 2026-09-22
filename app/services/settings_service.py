"""
Settings & Credential Masking Service
Manages desktop user preferences, safe credential masking, and application configuration.
"""

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional
import yaml

from src.config import AppConfig, load_config
from src.version import FROZEN_VERSION_MANIFEST

logger = logging.getLogger(__name__)


class SettingsService:
    def __init__(self, config_dir: Optional[Path] = None):
        self.root_dir = Path(__file__).resolve().parent.parent.parent
        self.config_dir = config_dir or (self.root_dir / "config")
        self.user_settings_path = self.config_dir / "user_settings.json"
        self.user_settings = self._load_user_settings()
        self.app_config: AppConfig = load_config(
            settings_path=str(self.config_dir / "settings.yaml"),
            presets_path=str(self.config_dir / "presets.yaml"),
        )

    def _load_user_settings(self) -> Dict[str, Any]:
        default_settings = {
            "ui": {
                "theme": "dark_bloomberg",
                "refresh_interval_ms": 1500,
                "health_interval_ms": 3000,
                "enable_sound_alerts": True,
                "compact_tables": True,
                "vps_mode": True,
                "max_display_rows": 100,
            },
            "scanner": {
                "active_mode": "PAPER",  # "SHADOW" | "PAPER" | "LIVE"
                "active_chains": ["solana", "bsc"],
                "default_chain": "solana",
                "min_market_cap_usd": 8000.0,
                "max_market_cap_usd": 35000.0,
                "min_liquidity_usd": 5000.0,
                "poll_interval_sec": 10.0,
            },
            "paper_trading": {
                "default_position_size_usd": 250.0,
                "active_policy": "TRAILING_STOP",
            },
            "exports": {
                "export_directory": str(self.root_dir / "exports"),
            },
            "credentials": {
                "telegram_bot_token": "",
                "telegram_chat_id": "",
                "discord_webhook_url": "",
                "helius_rpc_url": "",
                "quicknode_rpc_url": "",
            },
        }

        if self.user_settings_path.exists():
            try:
                with open(self.user_settings_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    # Merge defaults
                    for section, values in default_settings.items():
                        if section in loaded and isinstance(loaded[section], dict):
                            values.update(loaded[section])
                    return default_settings
            except Exception as e:
                logger.error(f"Failed to load user settings: {e}")

        return default_settings

    def save_user_settings(self, new_settings: Dict[str, Any]) -> bool:
        try:
            self.user_settings.update(new_settings)
            self.user_settings_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.user_settings_path, "w", encoding="utf-8") as f:
                json.dump(self.user_settings, f, indent=2)
            logger.info("User settings saved successfully.")
            return True
        except Exception as e:
            logger.error(f"Failed to save user settings: {e}")
            return False

    @staticmethod
    def mask_secret(secret: Optional[str]) -> str:
        """Safely mask API keys or webhook URLs to prevent plain-text exposure."""
        if not secret or len(secret) < 8:
            return "********" if secret else ""
        return f"{secret[:4]}****{secret[-4:]}"

    def get_masked_credentials(self) -> Dict[str, str]:
        creds = self.user_settings.get("credentials", {})
        return {k: self.mask_secret(v) for k, v in creds.items()}

    def get_active_mode(self) -> str:
        return self.user_settings.get("scanner", {}).get("active_mode", "PAPER")

    def set_active_mode(self, mode: str) -> None:
        if mode in ("SHADOW", "PAPER", "LIVE"):
            self.user_settings.setdefault("scanner", {})["active_mode"] = mode
            self.save_user_settings(self.user_settings)

    @staticmethod
    def is_vps_environment() -> bool:
        """Detect if the application is running in a virtualized or remote VPS environment."""
        if any(os.environ.get(k) for k in ("SESSIONNAME", "SSH_CONNECTION", "SSH_CLIENT", "REMOTE_DESKTOP", "XRDP_SESSION", "VPS_MODE")):
            return True
        try:
            cpu_cnt = os.cpu_count() or 4
            if cpu_cnt <= 2:
                return True
        except Exception:
            pass
        return False

    def is_vps_mode_active(self) -> bool:
        ui_cfg = self.user_settings.get("ui", {})
        if "vps_mode" in ui_cfg:
            return bool(ui_cfg["vps_mode"])
        return self.is_vps_environment()

    def set_vps_mode(self, enabled: bool) -> None:
        if "ui" not in self.user_settings:
            self.user_settings["ui"] = {}
        self.user_settings["ui"]["vps_mode"] = bool(enabled)
        self.save_user_settings(self.user_settings)
