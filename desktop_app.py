"""
Sub-$10K -> $3M+ Memecoin Scanner Desktop Application Launcher
Root convenience entry point for launching the PySide6 desktop trading terminal.
"""

import os
from pathlib import Path
import sys

# Ensure root directory in sys.path
root_dir = Path(__file__).resolve().parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from app.main import main

if __name__ == "__main__":
    main()
