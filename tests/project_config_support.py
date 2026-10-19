"""Explicit product configuration for temporary test projects."""

import json
from pathlib import Path


def write_project_config(project: Path, preset: str = "lean", **overrides) -> None:
    path = project / ".cardine/project.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 1, "preset": preset, **overrides}), encoding="utf-8")
