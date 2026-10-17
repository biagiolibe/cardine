"""Helpers extracted from the legacy CLI; see the module split plan."""

from __future__ import annotations

from cardine.shared.errors import MeridianError
from cardine.shared.git import _run_git
from cardine.shared.git import canonical_git_common_dir
from cardine.shared.git import primary_project_root
from pathlib import Path
import json
import sys


BUDGET_PATH = Path(".meridian/budget.json")


BUDGET_STATE_NAME = "meridian-budget.json"


BUDGET_KINDS = ("diagnostic", "captures", "expansions", "investigations")


EVIDENCE_EVENT_KINDS = ("diagnostic", "captures", "expansions")


BUDGET_DEFAULT_CAPS = {"diagnostic": 3, "captures": 2, "expansions": 2, "investigations": 2}


BUDGET_FIELD_NAMES = {
    "diagnostic": "Diagnostic attempts",
    "captures": "Evidence captures",
    "expansions": "Context expansions",
    "investigations": "Investigation scope",
}


def budget_state_path(project_root: Path) -> Path:
    """Keep mutable budget state beside the shared Git metadata, never tracked files."""
    primary = primary_project_root(project_root)
    try:
        return canonical_git_common_dir(primary) / BUDGET_STATE_NAME
    except MeridianError:
        return primary / BUDGET_PATH


def tracked_budget_state(project_root: Path) -> bool:
    primary = primary_project_root(project_root)
    return _run_git(primary, "ls-files", "--error-unmatch", "--", str(BUDGET_PATH)).returncode == 0


def legacy_budget_migration_needed(project_root: Path) -> bool:
    """Whether an explicit write or upgrade must retire the tracked legacy file."""
    primary = primary_project_root(project_root)
    return (primary / BUDGET_PATH).is_file() and tracked_budget_state(primary)


def migrate_budget_state(project_root: Path) -> bool:
    """Move the legacy project file once and remove it from the Git index.

    This is deliberately called only by mutating operations. Read paths must
    continue to expose the legacy content without changing the checkout.
    """
    primary = primary_project_root(project_root)
    legacy = primary / BUDGET_PATH
    destination = budget_state_path(primary)
    if destination == legacy or not legacy.is_file():
        return False
    if not destination.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        legacy.replace(destination)
    else:
        legacy.unlink()
    if tracked_budget_state(primary):
        result = _run_git(primary, "rm", "--cached", "--ignore-unmatch", "--", str(BUDGET_PATH))
        if result.returncode != 0:
            raise MeridianError(result.stderr.strip() or "could not remove legacy budget state from Git")
    return True


def load_budget_state(project_root: Path) -> dict[str, object]:
    path = budget_state_path(project_root)
    legacy = primary_project_root(project_root) / BUDGET_PATH
    if not path.is_file() and legacy.is_file():
        path = legacy
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise MeridianError(f"invalid budget state: {path}") from error


def write_budget_state(project_root: Path, state: dict[str, object]) -> None:
    if migrate_budget_state(project_root):
        print("Migrated legacy .meridian/budget.json out of the index; commit its deletion.", file=sys.stderr)
    path = budget_state_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
