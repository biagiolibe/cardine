"""Resolve product workflow compatibility keys from project configuration."""

from __future__ import annotations

from pathlib import Path

from cardine.shared.project import resolve_project_configuration


def resolve_preset(project_root: Path) -> str:
    """Expose the configured preset without consulting queue or workflow text."""
    return resolve_project_configuration(project_root)["preset"]


def detect_mode(project_root: Path) -> str:
    """Keep legacy internal keys until workflow consumers are consolidated."""
    return {"lean": "lean-delivery", "governed": "governed-sdd"}[resolve_preset(project_root)]
