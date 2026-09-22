"""
Unit tests for Frozen Manifest and Version Immutability (v1.0.0 Release)
"""

import json
from pathlib import Path
import pytest
from src.version import (
    CALIBRATION_VERSION,
    EXECUTION_MODEL_VERSION,
    FEATURE_SCHEMA_VERSION,
    FROZEN_VERSION_MANIFEST,
    MODEL_VERSION,
    REGIME_VERSION,
    RISK_RULES_VERSION,
    SCANNER_VERSION,
)


def test_frozen_version_manifest_integrity():
    assert SCANNER_VERSION == "v1.0.0"
    assert MODEL_VERSION == "v1.0.0"
    assert FEATURE_SCHEMA_VERSION == "v1.0.0"
    assert CALIBRATION_VERSION == "v1.0.0"
    assert REGIME_VERSION == "v1.0.0"
    assert RISK_RULES_VERSION == "v1.0.0"
    assert EXECUTION_MODEL_VERSION == "v1.0.0"

    manifest_path = Path(__file__).resolve().parent.parent / "src" / "manifest.json"
    assert manifest_path.exists()

    with open(manifest_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["manifest_version"] == "v1.0.0"
    assert len(data["feature_definitions"]) == 12
    assert "model_parameters" in data
    assert "risk_thresholds" in data
    assert "execution_assumptions" in data
