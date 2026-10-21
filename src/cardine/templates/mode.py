"""Resolve preset provenance independently of the single distribution."""

from __future__ import annotations

from pathlib import Path

from cardine.shared.project import resolve_project_configuration


def resolve_preset(project_root: Path) -> str:
    """Expose the configured preset without consulting queue or workflow text."""
    return resolve_project_configuration(project_root)["preset"]


def detect_mode(project_root: Path) -> str:
    """Validate project configuration and select the sole distribution."""
    resolve_preset(project_root)
    return "single"
