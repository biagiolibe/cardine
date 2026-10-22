"""Compatibility adapter for shared.console_workflow."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cardine.shared.console_workflow import (  # noqa: E402, F401
    ID_PATTERN,
    ConsoleError,
)
