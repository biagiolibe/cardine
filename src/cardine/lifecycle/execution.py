"""Execution location and delivery readiness."""

from __future__ import annotations

from cardine.shared.layout import names

from cardine.shared.errors import CardineError
from cardine.shared.git import _run_git
from cardine.shared.git import canonical_project_root
from cardine.shared.git import git_output
from cardine.stops.render import stop_error
from cardine.lifecycle.source import _execution_owned_paths, execution_source_digest
from cardine.tasks.contract import execution_entries
from cardine.tasks.evidence import frozen_validation_commands
from cardine.tasks.identity import find_task_file
from cardine.tasks.identity import resolve_task_identity
from cardine.tasks.preflight import readiness_check
from cardine.tasks.state import read_task_state, review_is_required
from cardine.tasks.state import state_path
from cardine.templates.mode import detect_mode
from cardine.worktree.checkout import inspect_task_worktree
from pathlib import Path
import json
import re
import shlex


def _execution_location(project_root: Path, task_id: str, *,
                        command: tuple[str, ...] = ("execution", "start")) -> dict[str, object]:
    """Verify the supplied checkout independently of the caller's directory."""
    supplied = project_root.resolve()
    # A stale path may still have a Git parent. Never infer a different task
    # checkout from cwd; cwd is only a fallback for locating the primary.
    primary = None
    for candidate in (supplied, *supplied.parents, Path.cwd()):
        try:
            primary = canonical_project_root(candidate)
            break
        except CardineError:
            continue
    if primary is None:
        raise CardineError(f"cannot identify the primary checkout from {supplied}")
    identity = resolve_task_identity(primary, task_id, "existing", allow_archived_queue_links=True)
    result, _valid = inspect_task_worktree(
        task_id, None, primary, require_effective_worktree=False,
        inspection_directory=primary, identity=identity)
    expected = Path(str(result["worktree"])).resolve()
    if supplied != expected or "unregistered-worktree" in result["errors"]:
        detail = (f"cwd={Path.cwd().resolve()}; --project={supplied}; expected worktree={expected}; "
                  + ("no registered task worktree" if "unregistered-worktree" in result["errors"]
                     else "--project does not name the canonical task worktree"))
        recovery = None
        if "unregistered-worktree" not in result["errors"]:
            recovery = shlex.join(("cardine", *command, identity.canonical_id, "--project", str(expected)))
        error = stop_error("WRONG_WORKTREE" if recovery is None else "WORKTREE_RELOCATE", detail, resume=recovery,
                           task_id=identity.canonical_id, project=shlex.quote(str(primary)))
        if recovery is not None:
            error.recovery_worktree = expected
            error.recovery_detail = detail
        raise error
    return result


def _execution_worktree(project_root: Path, task_id: str, *, resume: bool = False,
                        repeated_start: bool = False,
                        command: tuple[str, ...] = ("execution", "start"),
                        inspection: dict[str, object] | None = None) -> dict[str, object]:
    """Reuse canonical worktree verification; Resume is explicit, never inferred."""
    project_root = project_root.resolve()
    result = inspection if inspection is not None else _execution_location(project_root, task_id, command=command)
    errors = list(result["errors"])
    if errors == ["dirty-worktree"] and (resume or repeated_start):
        if repeated_start and not resume:
            identity = resolve_task_identity(project_root, task_id, "existing")
            changed = set(git_output(project_root, "diff", "HEAD", "--name-only").splitlines())
            untracked = set(git_output(project_root, "ls-files", "--others", "--exclude-standard").splitlines())
            state = _execution_state(project_root, task_id)
            previous = _run_git(project_root, "show", f"HEAD:{state_path(project_root, task_id).relative_to(project_root)}")
            if previous.returncode:
                raise stop_error("TASK_STATE_MISSING", "repeated start requires registered state at HEAD",
                                 task_id=task_id, project=project_root)
            original = read_task_state(project_root, task_id, detect_mode(project_root),
                                       text=previous.stdout, stop_factory=stop_error, require_contract=True)
            expected_state = dict(original)
            if original["status"] == "queued" and state["transitions"]:
                expected_state.update(status="in_progress", transitions=original["transitions"] + [state["transitions"][-1]])
            if original["status"] == "queued" and state["transitions"]:
                from cardine.lifecycle.receipts import digest, encoded
                operation = 'transition:' + digest(encoded(dict(target='in_progress')))
                chain = state.get('run', {}).get('receipts', [])
                old_chain = original.get('run', {}).get('receipts', [])
                if chain and chain[:-1] == old_chain and chain[-1]['kind'] == operation:
                    expected_state['run'] = state['run']
            # A repeated start tolerates only the exact command-owned state update.
            if (changed | untracked <= {state_path(project_root, identity.canonical_id).relative_to(project_root).as_posix()}
                    and state == expected_state):
                errors = []
        else:
            errors = []
    if errors or result["integration_active"]:
        raise stop_error("WRONG_WORKTREE", "execution worktree verification: "
                         + ", ".join(errors or ["integration-active"]), task_id=task_id, project=canonical_project_root(project_root))
    return result


def _execution_state(project_root: Path, task_id: str) -> dict[str, object]:
    return read_task_state(project_root, task_id, detect_mode(project_root),
                           stop_factory=stop_error, require_contract=True)


def _delivery_later_commits(project_root: Path, task_id: str, state: dict[str, object], head: str,
                            owned: set[str], report_path: str) -> list[str]:
    """Check every post-delivery commit, including changes later reverted.

    The transition anchors the original delivery's parent. Subsequent report-only
    commits have no readiness authority and need no delivery effect.
    """
    transition_head = state["transitions"][-1]["commit"]
    if _run_git(project_root, "merge-base", "--is-ancestor", transition_head, head).returncode:
        raise stop_error("EVIDENCE_INCOMPLETE", "delivery transition HEAD is not an ancestor",
                         task_id=task_id, project=canonical_project_root(project_root))
    commits = git_output(project_root, "rev-list", "--reverse", f"{transition_head}..{head}").splitlines()
    if not commits:
        raise stop_error("EVIDENCE_INCOMPLETE", "in_review needs a committed delivery",
                         task_id=task_id, project=canonical_project_root(project_root))
    delivery_paths = owned - {names().execution_evidence_path(resolve_task_identity(project_root, task_id, "existing").canonical_id).as_posix(), report_path}
    for index, commit in enumerate(commits):
        paths = set(git_output(project_root, "diff", "--name-only", f"{commit}^", commit).splitlines())
        allowed = delivery_paths if index == 0 else {report_path}
        if paths - allowed:
            raise stop_error("EVIDENCE_INCOMPLETE", "changes after delivery require renewed implementation and delivery",
                             task_id=task_id, project=canonical_project_root(project_root))
    return []


def delivery_readiness(project_root: Path, task_id: str, *, verify_worktree: bool = True) -> dict[str, object]:
    """Read-only delivery gate, also used by direct in_review transitions."""
    inspection = _execution_location(project_root, task_id, command=("execution", "deliver"))
    identity = resolve_task_identity(project_root, task_id, "existing")
    task_id = identity.canonical_id
    state = _execution_state(project_root, task_id)
    if (not review_is_required(state)
            or state["status"] not in ("in_progress", "in_review")):
        raise stop_error("TASK_STATUS_REJECTED", f"delivery requires a review-required task; found {state['status']}", task_id=task_id, project=canonical_project_root(project_root))
    if verify_worktree:
        worktree = _execution_worktree(project_root, task_id, inspection=inspection)
    else:
        if git_output(project_root, "status", "--porcelain"):
            raise stop_error("WRONG_WORKTREE", "delivery requires a clean worktree", task_id=task_id, project=canonical_project_root(project_root))
        primary = canonical_project_root(project_root)
        worktree, valid = inspect_task_worktree(task_id, None, primary, require_effective_worktree=False,
                                                  inspection_directory=primary)
        if not valid or worktree["integration_active"] or Path(worktree["worktree"]).resolve() != project_root.resolve():
            raise stop_error("WRONG_WORKTREE", "delivery requires the clean canonical worktree", task_id=task_id, project=canonical_project_root(project_root))
    enforce_execution_scope(project_root, task_id, state=state, base=str(worktree["base_commit"]))
    readiness_check(project_root, task_id)
    head = git_output(project_root, "rev-parse", "HEAD")
    base = str(worktree["base_commit"])
    owned = _execution_owned_paths(project_root, task_id)
    changed = set(git_output(project_root, "diff", "--name-only", base, head).splitlines())
    if not changed - owned:
        raise stop_error("EVIDENCE_INCOMPLETE", "delivery needs a committed implementation change after the prepared base", task_id=task_id, project=canonical_project_root(project_root))
    report_path = identity.handoff_path.relative_to(project_root).as_posix()
    digest = execution_source_digest(project_root, task_id)
    entries = execution_entries(project_root, task_id)
    commands = frozen_validation_commands(project_root, task_id)
    if state.get('run', {}).get('validation'):
        from cardine.tasks.validation import verified_validation
        progress = verified_validation(project_root, task_id, state)
        if progress is None or progress['phase'] != 'passed':
            raise stop_error('EVIDENCE_INCOMPLETE', 'Current measured task validation is missing or failing',
                             task_id=task_id, project=canonical_project_root(project_root))
        commands = progress['inputs']['commands']
        entries = progress['runs'][-1]
    if not commands and not state.get('run', {}).get('validation'):
        raise stop_error("EVIDENCE_INCOMPLETE", "delivery needs declared completed validation evidence", task_id=task_id, project=canonical_project_root(project_root))
    for command_id, command in commands.items():
        matching = [entry for entry in entries if entry.get("id") == command_id]
        entry = matching[-1] if matching else {}
        commit = entry.get("commit", "")
        if (entry.get("command") != command or entry.get("exitStatus") != 0
                or entry.get("sourceDigest") != digest or not re.fullmatch(r"[0-9a-f]{40}", str(commit))
                or _run_git(project_root, "merge-base", "--is-ancestor", str(commit), head).returncode):
            raise stop_error("EVIDENCE_INCOMPLETE", f"validation {command_id} is missing, failing, or stale; rerun execution validate and commit evidence", task_id=task_id, project=canonical_project_root(project_root))
    if state["status"] == "in_review":
        persisted = _run_git(project_root, "show", f"HEAD:{state_path(project_root, task_id).relative_to(project_root)}")
        if persisted.returncode or json.loads(persisted.stdout) != state:
            raise stop_error("EVIDENCE_INCOMPLETE", "in_review state must be committed", task_id=task_id, project=canonical_project_root(project_root))
        _delivery_later_commits(project_root, task_id, state, head, owned, report_path)
    return {"task_id": task_id, "commit": head, "clean": True, "status": state["status"]}


def enforce_execution_scope(root, task_id, *, base=None, state=None):
    """Interactive legacy snapshots may omit the surface; frozen surfaces always bind."""
    from cardine.lifecycle.scope import enforce_scope
    from cardine.worktree.checkout import inspect_task_worktree
    from cardine.shared.git import canonical_project_root
    state = state if state is not None else _execution_state(root, task_id)
    if not state['contract'].get('expectedCodeSurface'):
        return
    if base is None:
        inspection, _ = inspect_task_worktree(task_id, None, canonical_project_root(root),
                                              require_effective_worktree=False)
        base = str(inspection['base_commit'])
    return enforce_scope(root, state, base, owned=_execution_owned_paths(root, task_id))
