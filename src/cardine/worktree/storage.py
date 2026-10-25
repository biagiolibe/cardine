"""Helpers extracted from the legacy CLI; see the module split plan."""

from __future__ import annotations

from cardine.shared.layout import names

from cardine.shared.errors import CardineError
from cardine.shared.git import _run_git
from cardine.shared.git import canonical_git_common_dir
from cardine.shared.git import canonical_project_root
from cardine.shared.git import git_output
from cardine.shared.jsonio import _read_json_object
from cardine.shared.models import ResolvedTaskIdentity
from cardine.shared.models import ResolvedWorktreeRoot
from cardine.tasks.identity import resolve_task_identity
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
import os


def _verified_lifecycle_project(supplied_project: Path | None = None) -> Path:
    current_project = canonical_project_root(Path.cwd())
    if supplied_project is not None:
        supplied = supplied_project.expanduser().resolve()
        supplied_primary = canonical_project_root(supplied)
        if supplied != supplied_primary or supplied_primary != current_project:
            raise CardineError(
                f"--project must name the canonical current project {current_project}, found {supplied}"
            )
    return current_project


def user_configuration_path(
    environment: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    values = os.environ if environment is None else environment
    user_home = (home or Path.home()).expanduser().resolve()
    configured = values.get("XDG_CONFIG_HOME")
    base = Path(configured).expanduser().resolve() if configured else user_home / ".config"
    return base / names().user_configuration_path


def _read_user_configuration(path: Path) -> dict[str, object] | None:
    if not path.exists():
        return None
    value = _read_json_object(path, "Cardine user configuration")
    if set(value) != {"version", "worktreeRoot"} or value.get("version") != 1:
        raise CardineError(
            f"Cardine user configuration must contain only version 1 and worktreeRoot: {path}"
        )
    root = value.get("worktreeRoot")
    if not isinstance(root, str) or not root.strip():
        raise CardineError(f"Cardine user configuration worktreeRoot must be a non-empty string: {path}")
    if not Path(root).expanduser().is_absolute():
        raise CardineError(f"Cardine user configuration worktreeRoot must be absolute: {path}")
    return value


def resolve_worktree_root(
    explicit: Path | None = None,
    *,
    environment: Mapping[str, str] | None = None,
    home: Path | None = None,
    config_path: Path | None = None,
) -> ResolvedWorktreeRoot:
    values = os.environ if environment is None else environment
    user_home = (home or Path.home()).expanduser().resolve()
    selected_config = config_path or user_configuration_path(values, user_home)
    explicit_path = explicit.expanduser().resolve() if explicit is not None else None
    environment_value = values.get("CARDINE_WORKTREE_ROOT")
    environment_path = (
        Path(environment_value).expanduser().resolve() if environment_value else None
    )
    if explicit_path is not None and environment_path is not None and explicit_path != environment_path:
        raise CardineError(
            "conflicting worktree roots: --worktree-root supplied "
            f"{explicit_path}; CARDINE_WORKTREE_ROOT supplied {environment_path}"
        )
    if explicit_path is not None:
        root, source = explicit_path, "--worktree-root"
    elif environment_path is not None:
        root, source = environment_path, "CARDINE_WORKTREE_ROOT"
    else:
        configuration = _read_user_configuration(selected_config)
        if configuration is not None:
            root = Path(str(configuration["worktreeRoot"])).expanduser().resolve()
            source = "user-config"
        else:
            root = user_home / names().worktree_root
            source = "default"
    if root in {Path(root.anchor), user_home}:
        raise CardineError(
            f"worktree root from {source} must be a dedicated directory, not the filesystem root or home: {root}"
        )
    return ResolvedWorktreeRoot(root, source, selected_config)


def _effective_worktree_root(worktree_root: Path | None = None) -> Path:
    return resolve_worktree_root(worktree_root).path


def _lifecycle_paths(project_root: Path, identity: ResolvedTaskIdentity) -> tuple[Path, Path, Path]:
    common = canonical_git_common_dir(project_root)
    state = common / names().worktree_state_directory / f"{identity.artifact_stem}.json"
    return state, common / names().integration_lease_name, common / names().integration_state_name


def _merge_head_path(project_root: Path) -> Path:
    path = Path(git_output(project_root, "rev-parse", "--git-path", "MERGE_HEAD"))
    return (project_root / path).resolve()


def _branch_commit(project_root: Path, branch: str) -> str | None:
    result = _run_git(project_root, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}")
    if result.returncode == 1:
        return None
    if result.returncode != 0:
        raise CardineError(result.stderr.strip() or f"cannot inspect branch {branch}")
    return result.stdout.strip()


def lifecycle_started_at(task_id: str, supplied_project: Path | None = None,
                         identity: ResolvedTaskIdentity | None = None) -> str | None:
    """Return a valid preparation timestamp, preserving legacy state as unavailable.

    `identity` is the caller's already resolved identity of `task_id` under the
    primary checkout; it only saves the resolution.
    """
    project_root = _verified_lifecycle_project(supplied_project)
    identity = identity or resolve_task_identity(project_root, task_id, "existing")
    state_path, _lease, _integration = _lifecycle_paths(project_root, identity)
    state = _read_json_object(state_path, "worktree lifecycle state")
    value = state.get("started_at")
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return value if parsed.tzinfo is not None else None


def _dirty_summary(worktree: Path) -> dict[str, int]:
    """Count changed and untracked paths without refreshing the index or naming files."""
    result = _run_git(worktree, "--no-optional-locks", "status", "--porcelain", "-z")
    if result.returncode != 0:
        raise CardineError(result.stderr.strip() or f"cannot inspect task worktree status: {worktree}")
    records = iter(item for item in result.stdout.split("\0") if item)
    changed = untracked = 0
    for record in records:
        if record.startswith("??"):
            untracked += 1
            continue
        changed += 1
        if record[0] in "RC" or record[1] in "RC":
            next(records, None)  # the source path of a rename or copy is its own record
    return {"changed_paths": changed, "untracked_paths": untracked}


def _proven_stale_base(project: Path, state: dict[str, object], head: str) -> bool:
    """Prove only branch creation followed by commit-less main fast-forwards."""
    base = state.get("base_commit")
    if not isinstance(base, str) or base == head or state.get("task_commit") != base:
        return False
    if _run_git(project, "merge-base", "--is-ancestor", head, "main").returncode != 0:
        return False
    reflog = _run_git(project, "reflog", "show", "--format=%H%x09%gs", str(state.get("branch", "")))
    entries = [line.split("\t", 1) for line in reversed(reflog.stdout.splitlines())]
    if reflog.returncode or not entries or any(len(entry) != 2 for entry in entries):
        return False
    if not entries[0][1].startswith("branch: Created from "):
        return False
    previous = entries[0][0]
    saw_base = previous == base
    for commit, action in entries[1:]:
        if (action != "merge main: Fast-forward" or commit == previous
                or _run_git(project, "merge-base", "--is-ancestor", previous, commit).returncode != 0):
            return False
        previous = commit
        saw_base = saw_base or commit == base
    return saw_base and previous == head
