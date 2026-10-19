"""Locate the template source that every installation reads."""

from __future__ import annotations

from pathlib import Path

SINGLE_TEMPLATE_ROOT = Path("templates") / "single"
LEGACY_WORKFLOW_ROOT = Path("templates") / "workflows"


def single_template_root(framework_root: Path) -> Path:
    """The only template source an installation reads, for every preset."""
    return framework_root / SINGLE_TEMPLATE_ROOT
