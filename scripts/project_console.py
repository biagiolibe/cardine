#!/usr/bin/env python3
"""Compatibility executable for the package console."""

import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cardine.console.entry import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
