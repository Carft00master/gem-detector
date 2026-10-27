"""
Automatic .env File Loader (src/utils/env_loader.py)
Loads key-value pairs from .env in the repository root into os.environ without overriding
existing environment variables. Zero external dependencies.
"""

import os
from pathlib import Path


def load_env_file(env_path: Path | None = None) -> None:
    """
    Search for .env in project root and load key-value pairs into os.environ.
    Preserves existing environment variables. Ignores comments and blank lines.
    """
    if env_path is None:
        curr = Path(__file__).resolve().parent
        while curr != curr.parent:
            if (curr / "pyproject.toml").exists() or (curr / ".git").exists():
                env_path = curr / ".env"
                break
            curr = curr.parent
        if env_path is None:
            env_path = Path.cwd() / ".env"

    if not env_path.exists():
        return

    try:
        content = env_path.read_text(encoding="utf-8")
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip().strip("'").strip('"')
                if key and key not in os.environ:
                    os.environ[key] = val
    except Exception:
        pass
