"""Shared paths helpers extracted from the legacy CLI."""

from __future__ import annotations

from pathlib import Path


SCRIPTS_ROOT = Path(__file__).resolve().parents[3] / "scripts"
