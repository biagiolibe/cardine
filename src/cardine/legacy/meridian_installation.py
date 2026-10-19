"""Explicit, read-only access to an installed Meridian layout.

These literals describe the installation, independently of product renames.
No product command dispatches to this module.
"""

from __future__ import annotations

import json
from pathlib import Path
import re

from cardine.console.models import Snapshot
from cardine.console.snapshot import load_snapshot
from cardine.shared.layout import ProjectNames, use


MERIDIAN_INSTALLATION_NAMES = ProjectNames(
    project_directory=".meridian",
    worktree_state_directory="meridian-worktrees",
    integration_lease_name="meridian-integration.lock",
    integration_state_name="meridian-integration.json",
    journal_name="meridian-journal.jsonl",
    journal_rotated_name="meridian-journal.1.jsonl",
    user_configuration_directory="meridian",
    shared_worktrees_context="meridian_shared_worktrees",
)

_CAPABILITY_MARKER = re.compile(r"<!-- MERIDIAN:BEGIN capability=([a-z0-9-]+) v(\d+) -->")
_MARKED_BLOCK = re.compile(
    r"<!-- MERIDIAN:BEGIN capability=([a-z0-9-]+) v(\d+) -->\n?.*?<!-- MERIDIAN:END -->",
    re.DOTALL,
)


def is_meridian_installation(project: Path) -> bool:
    return (project / MERIDIAN_INSTALLATION_NAMES.manifest_path).is_file()


def _read_object(path: Path) -> dict[str, object]:
    """Read installation data without applying product schema or defaults."""
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def read_manifest(project: Path) -> dict[str, object]:
    return _read_object(project / MERIDIAN_INSTALLATION_NAMES.manifest_path)


def read_task_state_file(project: Path, task_id: str) -> dict[str, object]:
    """Read one literal task ID, refusing path components or traversal."""
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", task_id) is None:
        raise ValueError(f"Invalid task ID: {task_id!r}")
    return _read_object(project / MERIDIAN_INSTALLATION_NAMES.tasks_path / f"{task_id}.json")


def meridian_marker_blocks(text: str) -> tuple[tuple[str, int, str], ...]:
    """Return (capability, version, complete block) tuples in source order."""
    return tuple(
        (match.group(1), int(match.group(2)), match.group(0))
        for match in _MARKED_BLOCK.finditer(text)
        if _CAPABILITY_MARKER.match(match.group(0))
    )


def load_meridian_snapshot(project: Path) -> Snapshot:
    """Build an installation snapshot under the frozen Meridian names."""
    with use(MERIDIAN_INSTALLATION_NAMES):
        return load_snapshot(project)
