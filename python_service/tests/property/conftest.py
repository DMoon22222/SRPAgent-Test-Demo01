"""Allow isolated, test-only Hypothesis without modifying the runtime venv."""

import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[2] / ".interop/hardening-tools"
if TOOLS.is_dir():
    sys.path.insert(0, str(TOOLS))
