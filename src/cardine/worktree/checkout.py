"""Task worktree preparation and inspection."""

from __future__ import annotations

from cardine.shared.layout import names

from cardine.shared.errors import CardineError
from cardine.shared.git import _git_worktrees
from cardine.shared.git import _run_git
from cardine.shared.git import canonical_git_common_dir
from cardine.shared.git import canonical_project_root
from cardine.shared.git import git_output
from cardine.shared.journal import JOURNAL_VERSION
from cardine.shared.journal import append_journal_line
from cardine.shared.jsonio import _read_json_object
from cardine.shared.jsonio import _write_json_atomic
from cardine.shared.models import ResolvedTaskIdentity
from cardine.stops.render import stop_error
from cardine.stops.render import stop_resume
from cardine.tasks.identity import resolve_task_identity
from cardine.tasks.identity import task_identity_context
from cardine.worktree.paths import _task_worktree_path_for_identity
from cardine.worktree.paths import handoff_worktree_value
from cardine.worktree.storage import _branch_commit
from cardine.worktree.storage import _dirty_summary
from cardine.worktree.storage import _effective_worktree_root
from cardine.worktree.storage import _lifecycle_paths
from cardine.worktree.storage import _proven_stale_base
from cardine.worktree.storage import _verified_lifecycle_project
from datetime import datetime
from datetime import timezone
from pathlib import Path
import json
import re
import shlex


def repair_task_worktree_base(
    task_id: str, worktree_root: Path | None, supplied_project: Path | None = None,
) -> dict[str, object]:
    project = _verified_lifecycle_project(supplied_project)
    identity = resolve_task_identity(project, task_id, "existing")
    report, _ready = inspect_task_worktree(task_id, worktree_root, project, require_effective_worktree=False)
    errors = [item for item in report["errors"] if item != "stale-base-record"]
    if Path.cwd().resolve() not in (project, Path(str(report["worktree"]))):
        errors.append("wrong-worktree")
    if report["integration_active"]:
        errors.append("active-integration")
    state_path, _lease, _integration = _lifecycle_paths(project, identity)
    state = _read_json_object(state_path, "worktree lifecycle state") if state_path.is_file() else {}
    head = str(report["task_commit"])
    unchanged = state.get("base_commit") == head and state.get("task_commit") == head
    if unchanged and _run_git(project, "merge-base", "--is-ancestor", head, "main").returncode != 0:
        errors.append("task-owned-commits")
    if errors or (not unchanged and "stale-base-record" not in report["errors"]):
        raise stop_error(
            "WRONG_WORKTREE", "base recovery rejected: " + ", ".join(errors or ["unproven-fast-forward"]),
            task_id=identity.canonical_id, project=project,
        )
    old_base = state["base_commit"]
    if not unchanged:
        from cardine.worktree.preparation import repair_preparation
        before = dict(state)
        state.update(base_commit=head, task_commit=head)
        repair_preparation(project, identity, before, state)
    return {
        "version": 1, "task_id": identity.canonical_id, "repaired": not unchanged,
        "previous_base_commit": old_base, "base_commit": head,
        "evidence_renewal_required": True,
        "next_action": "renew-validation-and-evidence",
    }


def prepare_task_worktree(task_id, worktree_root, supplied_project=None, base="main", resume=False):
    from cardine.worktree.preparation import preparation_lock, _path
    project = _verified_lifecycle_project(supplied_project)
    identity = resolve_task_identity(project, task_id, "existing")
    if resume and not _path(project, identity).exists():
        raise CardineError("nothing to resume: missing owned preparation receipt")
    from cardine.lifecycle.receipts import task_lock
    with task_lock(project, identity.canonical_id), preparation_lock(project, identity):
        try:
            return _prepare_task_worktree(task_id, worktree_root, supplied_project, base, resume)
        except CardineError as error:
            if getattr(error, 'code', None):
                raise
            raise stop_error('WRONG_WORKTREE', str(error), task_id=identity.canonical_id, project=project) from error


def _prepare_task_worktree(
    task_id: str,
    worktree_root: Path | None,
    supplied_project: Path | None = None,
    base: str = "main",
    resume: bool = False,
) -> dict[str, object]:
    if base != "main":
        raise CardineError("worktree prepare permits only the main base")
    project_root = _verified_lifecycle_project(supplied_project)
    root = _effective_worktree_root(worktree_root)
    identity = resolve_task_identity(project_root, task_id, "existing")
    path = _task_worktree_path_for_identity(project_root, root, identity)
    state_path, lease_path, integration_path = _lifecycle_paths(project_root, identity)
    from cardine.worktree.preparation import prepare_owned_pair, publish_preparation
    base_commit = git_output(project_root, "rev-parse", "--verify", f"{base}^{{commit}}")
    operation = prepare_owned_pair(project_root, root, identity, path, base_commit, resume=resume)
    records = _git_worktrees(project_root)
    registered = next((item for item in records if Path(item["worktree"]).resolve() == path), None)
    branch_commit = _branch_commit(project_root, identity.branch_name)
    created = operation.get("result") != "verified"
    prior: dict[str, object] = {}
    dirty_summary: dict[str, int] | None = None
    state_missing = False
    if resume:
        if registered is None:
            raise CardineError(
                f"nothing to resume for {identity.canonical_id}: no task branch or canonical worktree exists"
            )
        for retained in (lease_path, integration_path):
            if retained.exists():
                try:
                    holder = _read_json_object(retained, "integration state").get("task_id")
                except CardineError:
                    holder = None
                if holder in (None, identity.canonical_id):
                    raise CardineError(
                        f"cannot resume {identity.canonical_id} while an integration lease or staged merge is active: {retained}"
                    )
    if registered is None:
        if path.exists():
            raise CardineError(f"worktree path collision at {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        added = _run_git(project_root, "worktree", "add", "-b", identity.branch_name, str(path), base_commit)
        if added.returncode != 0:
            raise CardineError(added.stderr.strip() or "git worktree add failed")
        branch_commit = base_commit
        created = True
    else:
        expected_ref = f"refs/heads/{identity.branch_name}"
        if registered.get("branch") != expected_ref or registered.get("HEAD") != branch_commit:
            raise CardineError(
                f"canonical worktree mismatch retained at {path}: expected {expected_ref} at {branch_commit}"
            )
        if resume:
            dirty_summary = _dirty_summary(path)
        elif git_output(path, "status", "--porcelain"):
            raise CardineError(f"existing task worktree is dirty and was retained: {path}")
        if state_path.is_file():
            prior = _read_json_object(state_path, "worktree lifecycle state")
            if prior.get("worktree") != str(path) or prior.get("branch") != identity.branch_name:
                raise stop_error(
                    "WRONG_WORKTREE",
                    f"lifecycle state mismatch retained at {state_path}: expected worktree {path} and branch "
                    f"{identity.branch_name}; found worktree {prior.get('worktree')} and branch {prior.get('branch')}",
                    resume=f"the developer corrects or removes the lifecycle state file {state_path}, then rerun "
                    f"cardine worktree prepare {identity.canonical_id} --project {project_root} --format json",
                )
            base_commit = str(prior.get("base_commit", base_commit))
            if not resume and _proven_stale_base(project_root, prior, str(branch_commit)):
                raise stop_error("STALE_WORKTREE_BASE", "prepared branch fast-forwarded without task commits",
                                 resume=stop_resume("STALE_WORKTREE_BASE", task_id=identity.canonical_id,
                                                    project=shlex.quote(str(project_root)))
                                 + f" --worktree-root {shlex.quote(str(root))}")
        elif resume:
            # Missing state is never repaired by a resume; Git supplies the facts instead.
            merge_base = _run_git(project_root, "merge-base", base, identity.branch_name)
            if merge_base.returncode != 0:
                raise CardineError(merge_base.stderr.strip() or f"cannot derive the base commit of {identity.branch_name}")
            base_commit = merge_base.stdout.strip()
            state_missing = True
    state = {
        "version": 1,
        "task_id": identity.canonical_id,
        "branch": identity.branch_name,
        "worktree": str(path),
        "worktree_root": str(root),
        "project": str(project_root),
        "git_common_dir": str(canonical_git_common_dir(project_root)),
        "base_commit": base_commit,
        "task_commit": branch_commit,
        "handoff": str(identity.handoff_path),
    }
    if created:
        saved = operation.get("lifecycle")
        state["started_at"] = (saved["started_at"] if saved else
                               datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
    elif "started_at" in prior:
        # Keep a pre-existing value byte-for-byte; malformed values are handled
        # as unavailable by the read-only console rather than rewritten.
        state["started_at"] = prior["started_at"]
    if not resume or operation.get("result") != "verified":
        publish_preparation(project_root, identity, operation, state)
    result: dict[str, object] = {
        **state,
        "handoff_worktree": handoff_worktree_value(root, path),
        "created": created,
        "next_action": "check",
    }
    if state_missing:
        result.update({
            "base_commit_source": "derived",
            "state": "missing",
            "state_repair": f"cardine worktree prepare {identity.canonical_id} --project {project_root} --format json",
        })
    if dirty_summary is not None:
        dirty = bool(dirty_summary["changed_paths"] or dirty_summary["untracked_paths"])
        result.update({"resumed": True, "dirty": dirty, **dirty_summary})
        if dirty:
            result["next_action"] = "inspect-dirty"
            result["next_command"] = shlex.join((
                "cardine", "worktree", "check", identity.canonical_id, "--resume",
                "--project", str(project_root), "--format", "json",
            ))
    return result


def inspect_task_worktree(
    task_id: str,
    worktree_root: Path | None,
    supplied_project: Path | None = None,
    *,
    resume: bool = False,
    require_effective_worktree: bool = True,
    inspection_directory: Path | None = None,
    identity: ResolvedTaskIdentity | None = None,
) -> tuple[dict[str, object], bool]:
    project_root = (_verified_lifecycle_project(supplied_project) if inspection_directory is None
                    else canonical_project_root(inspection_directory))
    root = _effective_worktree_root(worktree_root)
    identity = identity or resolve_task_identity(project_root, task_id, "existing")
    expected = _task_worktree_path_for_identity(project_root, root, identity)
    state_path, lease_path, integration_path = _lifecycle_paths(project_root, identity)
    errors: list[str] = []
    dirty_summary: dict[str, int] = {}
    state: dict[str, object] = {}
    if state_path.is_file():
        state = _read_json_object(state_path, "worktree lifecycle state")
    else:
        errors.append("missing-state")
    records = _git_worktrees(project_root)
    registered = next((item for item in records if Path(item["worktree"]).resolve() == expected), None)
    current = Path.cwd().resolve()
    if require_effective_worktree and current != expected:
        errors.append("wrong-worktree")
    if registered is None:
        errors.append("unregistered-worktree")
        head = ""
        branch = ""
        clean = False
    else:
        head = registered.get("HEAD", "")
        branch = registered.get("branch", "").removeprefix("refs/heads/")
        if branch != identity.branch_name:
            errors.append("branch-mismatch")
        if not expected.exists():
            clean = False
            errors.append("missing-worktree")
        else:
            dirty_summary = _dirty_summary(expected)
            clean = not any(dirty_summary.values())
            if not clean:
                errors.append("dirty-worktree")
    if state:
        from cardine.worktree.preparation import verify_preparation
        try:
            verify_preparation(project_root, root, identity, expected, state)
        except (CardineError, KeyError, TypeError) as error:
            errors.append("preparation-receipt-mismatch")
        if state.get("task_id") != identity.canonical_id:
            errors.append("state-task-mismatch")
        if state.get("project") != str(project_root) or state.get("worktree") != str(expected):
            errors.append("state-path-mismatch")
        if state.get("branch") != identity.branch_name:
            errors.append("state-branch-mismatch")
        if state.get("worktree_root") != str(root):
            errors.append("state-root-mismatch")
        if state.get("git_common_dir") != str(canonical_git_common_dir(project_root)):
            errors.append("state-common-dir-mismatch")
        base_commit = state.get("base_commit")
        if not isinstance(base_commit, str) or _run_git(
            project_root, "cat-file", "-e", f"{base_commit}^{{commit}}"
        ).returncode != 0:
            errors.append("base-commit-mismatch")
    result = {
        "version": 1,
        "status": "ready" if not errors else "blocked",
        "task_id": identity.canonical_id,
        "branch": branch or identity.branch_name,
        "worktree": str(expected),
        "git_common_dir": str(canonical_git_common_dir(project_root)),
        "canonical_prepared_path": str(expected),
        "handoff_worktree": handoff_worktree_value(root, expected),
        "effective_worker_path": str(current),
        "base_commit": state.get("base_commit", ""),
        "task_commit": head,
        "clean": clean,
        "integration_active": lease_path.exists() or integration_path.exists(),
        "errors": errors,
        "next_action": "implement" if not errors else "repair-or-abort",
    }
    if not errors and not result["integration_active"] and _proven_stale_base(project_root, state, head):
        errors.append("stale-base-record")
        result.update(status="blocked", next_action="repair-base", stop_reason="STALE_WORKTREE_BASE",
                      resume=stop_resume("STALE_WORKTREE_BASE", task_id=identity.canonical_id,
                                         project=shlex.quote(str(project_root)))
                      + f" --worktree-root {shlex.quote(str(root))}")
    if errors == ["dirty-worktree"]:
        result["resume"] = shlex.join((
            "cardine", "worktree", "prepare", identity.canonical_id, "--resume",
            "--project", str(project_root), "--format", "json",
        ))
        if resume:
            result.pop("resume")
            result.update(status="ready-dirty", next_action="inspect-dirty", **dirty_summary)
            return result, True
    return result, not errors


def active_worktree_task(directory: Path) -> dict[str, object] | None:
    """Resolve the task owned by an exact, registered task worktree.

    This deliberately uses the lifecycle registration and branch-to-identity
    mapping, rather than a queue status.  It is a small read-only companion to
    ``worktree check`` for hooks which do not know a task ID in advance.
    """
    current = directory.expanduser().resolve()
    primary = canonical_project_root(current)
    if current == primary:
        return None
    records = _git_worktrees(primary)
    registered = next((item for item in records if Path(item["worktree"]).resolve() == current), None)
    if registered is None:
        return None
    branch = registered.get("branch", "").removeprefix("refs/heads/")
    state_directory = canonical_git_common_dir(primary) / names().worktree_state_directory
    context: TaskIdentityContext | None = None
    for state_path in sorted(state_directory.glob("*.json")) if state_directory.is_dir() else ():
        try:
            state = _read_json_object(state_path, "worktree lifecycle state")
            if state.get("branch") != branch or state.get("worktree") != str(current):
                continue
            task_id = state.get("task_id")
            if not isinstance(task_id, str):
                continue
            context = context or task_identity_context(primary)
            identity = resolve_task_identity(primary, task_id, "existing", context=context)
        except CardineError:
            continue
        if state_path.name != f"{identity.artifact_stem}.json" or identity.branch_name != branch or state.get("task_id") != identity.canonical_id:
            continue
        from cardine.worktree.preparation import verify_preparation
        try:
            verify_preparation(primary, Path(str(state.get('worktree_root', ''))), identity, current, state)
        except (CardineError, KeyError, TypeError):
            continue
        archived = identity.task_path.parent / "done" / identity.task_path.name
        exempt = [identity.task_path, archived, identity.handoff_path, identity.review_path,
                  primary / names().tasks_path / f"{identity.canonical_id}.json"]
        return {
            "task_id": identity.canonical_id,
            "branch": branch,
            "worktree": str(current),
            "exempt_paths": [str(path) for path in exempt],
        }
    return None


def registered_worktree_task_states(project_root: Path) -> list[dict[str, str]]:
    """Return in-flight task states from lifecycle registrations and records."""
    primary = canonical_project_root(project_root)
    worktrees = {
        Path(item["worktree"]).resolve(): item.get("branch", "").removeprefix("refs/heads/")
        for item in _git_worktrees(primary) if "worktree" in item
    }
    states: list[dict[str, str]] = []
    state_directory = canonical_git_common_dir(primary) / names().worktree_state_directory
    context: TaskIdentityContext | None = None
    for state_path in sorted(state_directory.glob("*.json")) if state_directory.is_dir() else ():
        try:
            lifecycle = _read_json_object(state_path, "worktree lifecycle state")
            task_id = lifecycle.get("task_id")
            if not isinstance(task_id, str):
                continue
            context = context or task_identity_context(primary)
            identity = resolve_task_identity(primary, task_id, "existing", context=context)
            worktree = Path(str(lifecycle["worktree"])).resolve()
        except (KeyError, TypeError, CardineError):
            continue
        if (state_path.name != f"{identity.artifact_stem}.json"
                or lifecycle.get("task_id") != identity.canonical_id
                or lifecycle.get("branch") != identity.branch_name
                or worktrees.get(worktree) != identity.branch_name):
            continue
        from cardine.tasks.state import read_task_state
        from cardine.templates.mode import detect_mode
        from cardine.worktree.preparation import verify_preparation
        try:
            verify_preparation(primary, Path(str(lifecycle.get('worktree_root', ''))), identity, worktree, lifecycle)
            status = read_task_state(worktree, identity.canonical_id, detect_mode(worktree), stop_factory=stop_error)["status"]
        except CardineError:
            continue
        states.append({"task_id": identity.canonical_id, "status": status})
    return states

