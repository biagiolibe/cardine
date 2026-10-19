"""Explicit, read-only access to an installed Meridian layout.

These literals describe the installation, independently of product renames.
No product command dispatches to this module.
"""

from __future__ import annotations

import json
from pathlib import Path
import re

from cardine.shared.errors import CardineError
from cardine.console.models import Snapshot
from cardine.console.snapshot import load_snapshot
from cardine.shared.layout import ProjectNames, use
from cardine.shared.snapshot_adapters import state_adapter, status_adapter


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


def detect_meridian_mode(project_root: Path) -> str:
    workflow = project_root / "PROJECT_WORKFLOW.md"
    if not workflow.is_file():
        raise CardineError(
            "cannot detect workflow mode: PROJECT_WORKFLOW.md is missing; pass --mode explicitly"
        )
    text = workflow.read_text(encoding="utf-8")
    is_governed = "GOVERNED_SDD" in text
    is_lean = "LEAN_DELIVERY" in text
    if is_governed and is_lean:
        raise CardineError(
            "cannot detect workflow mode: PROJECT_WORKFLOW.md mentions both mode locks; pass --mode explicitly"
        )
    if is_governed:
        return "governed-sdd"
    if is_lean:
        return "lean-delivery"
    raise CardineError(
        "cannot detect workflow mode: PROJECT_WORKFLOW.md has no recognized mode lock; pass --mode explicitly"
    )


MERIDIAN_STATUSES = {
    "QUEUED": "queued", "IN_PROGRESS": "in_progress", "READY_FOR_REVIEW": "in_review",
    "CHANGES_REQUESTED": "in_progress", "ACCEPTED": "in_progress",
    "ANSWERED": "in_progress", "INCONCLUSIVE": "in_progress", "DONE": "done",
}


def snapshot_task_state(state):
    """Map historical installation data in memory; never rewrite an installation."""
    value = json.loads(json.dumps(state))
    old = value["status"]
    value["status"] = MERIDIAN_STATUSES[old]
    if old in ("ANSWERED", "INCONCLUSIVE"):
        value["outcome"] = old
    for transition in value["transitions"]:
        transition["from"] = MERIDIAN_STATUSES[transition["from"]]
        transition["to"] = MERIDIAN_STATUSES[transition["to"]]
    return value


def load_meridian_snapshot(project: Path) -> Snapshot:
    """Build an installation snapshot under the frozen Meridian names."""
    state_token = state_adapter.set(snapshot_task_state)
    status_token = status_adapter.set(lambda value: MERIDIAN_STATUSES.get(value, value))
    try:
        with use(MERIDIAN_INSTALLATION_NAMES):
            return load_snapshot(project, workflow_resolver=detect_meridian_mode)
    finally:
        state_adapter.reset(state_token)
        status_adapter.reset(status_token)
