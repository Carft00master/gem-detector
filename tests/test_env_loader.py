"""
Unit tests for src/utils/env_loader.py:
- Loading variables from .env file into os.environ
- Preserving pre-existing environment variables
- Correct handling of quotes, whitespace, and comments
- Graceful handling when .env does not exist
"""

import os
from pathlib import Path
import pytest
from src.utils.env_loader import load_env_file


def test_env_loader_loads_variables(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        """
        # This is a comment
        TEST_VAR_1=helius_secret_123
        TEST_VAR_2="quoted_secret_456"
        TEST_VAR_3='single_quoted_789'
        
        EMPTY_LINE_ABOVE=valid
        """,
        encoding="utf-8",
    )

    monkeypatch.delenv("TEST_VAR_1", raising=False)
    monkeypatch.delenv("TEST_VAR_2", raising=False)
    monkeypatch.delenv("TEST_VAR_3", raising=False)
    monkeypatch.delenv("EMPTY_LINE_ABOVE", raising=False)

    load_env_file(env_file)

    assert os.environ.get("TEST_VAR_1") == "helius_secret_123"
    assert os.environ.get("TEST_VAR_2") == "quoted_secret_456"
    assert os.environ.get("TEST_VAR_3") == "single_quoted_789"
    assert os.environ.get("EMPTY_LINE_ABOVE") == "valid"


def test_env_loader_preserves_existing_env(tmp_path, monkeypatch):
    monkeypatch.setenv("EXISTING_VAR", "original_value")

    env_file = tmp_path / ".env"
    env_file.write_text("EXISTING_VAR=overwritten_attempt\nNEW_VAR=hello", encoding="utf-8")

    load_env_file(env_file)

    assert os.environ.get("EXISTING_VAR") == "original_value"
    assert os.environ.get("NEW_VAR") == "hello"


def test_env_loader_nonexistent_file(tmp_path):
    # Should not raise exception
    missing_file = tmp_path / ".env.does_not_exist"
    load_env_file(missing_file)
