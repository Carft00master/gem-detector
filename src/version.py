"""
Formal Immutable Version Metadata Registry (v1.0.0 Frozen Validation Release)
Every recorded signal, execution quote, and paper trade permanently records these versions.
"""

from dataclasses import dataclass
from typing import Dict, Any


SCANNER_VERSION = "v1.0.0"
MODEL_VERSION = "v1.0.0"
FEATURE_SCHEMA_VERSION = "v1.0.0"
CALIBRATION_VERSION = "v1.0.0"
REGIME_VERSION = "v1.0.0"
RISK_RULES_VERSION = "v1.0.0"
EXECUTION_MODEL_VERSION = "v1.0.0"
LEARNING_DATA_VERSION = "v1.0.0"
TRADE_LEDGER_SCHEMA_VERSION = "v1.1.0"
SMART_MONEY_ENGINE_VERSION = "v1.0.0"
SMART_MONEY_MODE = "RESEARCH_ONLY"


@dataclass(frozen=True)
class SystemVersionManifest:
    scanner_version: str = SCANNER_VERSION
    model_version: str = MODEL_VERSION
    feature_schema_version: str = FEATURE_SCHEMA_VERSION
    calibration_version: str = CALIBRATION_VERSION
    regime_version: str = REGIME_VERSION
    risk_rules_version: str = RISK_RULES_VERSION
    execution_model_version: str = EXECUTION_MODEL_VERSION
    learning_data_version: str = LEARNING_DATA_VERSION
    trade_ledger_schema_version: str = TRADE_LEDGER_SCHEMA_VERSION
    smart_money_engine_version: str = SMART_MONEY_ENGINE_VERSION
    smart_money_mode: str = SMART_MONEY_MODE

    def to_dict(self) -> Dict[str, str]:
        return {
            "scanner_version": self.scanner_version,
            "model_version": self.model_version,
            "feature_schema_version": self.feature_schema_version,
            "calibration_version": self.calibration_version,
            "regime_version": self.regime_version,
            "risk_rules_version": self.risk_rules_version,
            "execution_model_version": self.execution_model_version,
            "learning_data_version": self.learning_data_version,
            "trade_ledger_schema_version": self.trade_ledger_schema_version,
            "smart_money_engine_version": self.smart_money_engine_version,
            "smart_money_mode": self.smart_money_mode,
        }


FROZEN_VERSION_MANIFEST = SystemVersionManifest()

