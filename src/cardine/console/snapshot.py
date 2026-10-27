"""Project snapshot loading for the console.

Tasks are enumerated from validated state files through the shared status
service. The console adds Git, worktree, and closure observations for display
only; it never reads queue rows or record status lines. Installed legacy
layouts use the explicit `cardine.legacy.snapshot` path instead.
"""

from __future__ import annotations

from cardine.shared.git import scoped_command

from cardine.shared.git import _run_git

import contextlib
import json
import os
import re
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path

from cardine.console.models import Snapshot, Task
from cardine.lifecycle.execution import delivery_readiness
from cardine.shared.console_workflow import ConsoleError
from cardine.shared.errors import CardineError, CardineStop
from cardine.shared.git import (
    canonical_git_common_dir,
    parse_worktree_records,
    shared_worktree_records,
)
from cardine.shared.layout import ProjectNames, names
from cardine.shared.models import ResolvedTaskIdentity
from cardine.stops.render import stop_error
from cardine.tasks.identity import resolve_task_identity, task_identity_context
from cardine.tasks.state import read_task_state, review_is_required, state_path
from cardine.tasks.status import load_task_snapshot
from cardine.templates.mode import resolve_preset
from cardine.worktree.closure_status import closure_status
from cardine.worktree.storage import lifecycle_started_at

LIFECYCLE = {"queued": "todo", "in_progress": "in_progress", "in_review": "ready_for_review",
             "done": "done", "cancelled": "done"}
DEPENDENCY_LABELS = {"done": "Done", "cancelled": "Cancelled", "in_progress": "Working",
                     "in_review": "Review", "queued": "Open"}


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ConsoleError(f"Cannot read {path}: {error}") from error


def _section(text: str, *names: str) -> tuple[str, ...]:
    """Return the first named level-two section, tolerating decorative emoji."""
    inside = False
    lines: list[str] = []
    for line in text.splitlines():
        if line.startswith("## "):
            if inside:
                break
            heading = re.sub(r"^[^\w]+", "", line[3:]).strip().casefold()
            inside = heading in {name.casefold() for name in names}
        elif inside and line.strip():
            lines.append(line.strip())
    return tuple(lines)


def _git_result(project: Path, *args: str) -> subprocess.CompletedProcess[str]:
    try:
        return _run_git(str(project), *args, text=True, timeout=5, env={**os.environ, 'GIT_OPTIONAL_LOCKS': '0'})
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ConsoleError(f"Git {' '.join(args)} failed: {error}") from error


def _git(project: Path, *args: str) -> str:
    result = _git_result(project, *args)
    if result.returncode:
        raise ConsoleError(f"Git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def _git_optional(project: Path, *args: str) -> str | None:
    """Return Git output, or None when the object or ref does not exist."""
    result = _git_result(project, *args)
    return None if result.returncode else result.stdout


def _primary_checkout(project: Path) -> tuple[Path | None, str | None]:
    """Resolve Git's first registered worktree, which is the primary checkout."""
    result = _git_result(project, "worktree", "list", "--porcelain")
    if result.returncode:
        return None, "Cannot resolve the primary checkout"
    primary = next((line.removeprefix("worktree ") for line in result.stdout.splitlines()
                    if line.startswith("worktree ")), None)
    directory = Path(primary).resolve() if primary else None
    if directory is None or not directory.is_dir():
        return None, "Primary checkout is unavailable"
    return directory, None

def _worktrees(records: list[dict[str, str]]) -> tuple[dict[str, str], dict[str, str]]:
    """Return the registered branch-to-path map and each worktree's HEAD by path."""
    branches: dict[str, str] = {}
    heads: dict[str, str] = {}
    for record in records:
        path = record.get("worktree")
        if not path:
            continue
        heads[path] = record.get("HEAD", "")
        if record.get("branch", "").startswith("refs/heads/"):
            branches[record["branch"].removeprefix("refs/heads/")] = path
    return branches, heads


def _stat_identity(path: Path) -> tuple[int, int] | None:
    """Return a file's size and modification time, or None when it is unreadable."""
    try:
        status = path.stat()
    except OSError:
        return None
    return status.st_size, status.st_mtime_ns


class DeliveryCache:
    """Remember each task's delivery gate outcome until one of its inputs changes.

    `delivery_readiness` is a pure function of the task worktree contents and
    HEAD, the handoff and state files, the execution evidence, the lifecycle
    registration files, and whether `main` moved (a stale-base proof). The key
    holds all of them, so an unchanged review-ready task is not rechecked and
    any change discards its entry. Failures are cached too: the console shows
    their text. A dirty worktree is never cached; the gate rejects it cheaply.
    """

    def __init__(self) -> None:
        self._items: dict[str, tuple[tuple, str | None]] = {}

    def pending(self, project: Path, worktree: Path, head: str, task_id: str,
                identity: ResolvedTaskIdentity, main_commit: str | None,
                common_dir: Path | None) -> str | None:
        """Return the delivery failure text, or None when delivery is ready."""
        key = None
        status = _git_result(worktree, "status", "--porcelain")
        if not status.returncode and not status.stdout and head and common_dir is not None:
            lifecycle = common_dir / names().worktree_state_directory / f"{identity.artifact_stem}.json"
            try:
                handoff = worktree / _relative(project, identity.handoff_path)
            except ConsoleError:
                handoff = None
            if handoff is not None:
                key = (names(), head, main_commit,
                       *(_stat_identity(path) for path in (
                           handoff, state_path(worktree, task_id), worktree / names().execution_evidence_path(identity.canonical_id),
                           lifecycle, common_dir / names().integration_lease_name,
                           common_dir / names().integration_state_name)))
        if key is not None:
            cached = self._items.get(str(worktree))
            if cached is not None and cached[0] == key:
                return cached[1]
        try:
            delivery_readiness(worktree, task_id, verify_worktree=False)
            outcome = None
        except (CardineError, OSError, ValueError) as error:
            outcome = str(error)
        if key is None:
            self._items.pop(str(worktree), None)
        else:
            self._items[str(worktree)] = (key, outcome)
        return outcome


def _committed_update(project: Path, relative: str, ref: str = "HEAD") -> int | None:
    """Return the last committed change to a task record, when Git knows it."""
    try:
        value = _git(project, "log", "-1", "--format=%ct", ref, "--", relative).strip()
        return int(value) if value else None
    except (ConsoleError, ValueError):
        return None

def _relative(project: Path, path: Path) -> str:
    try:
        return path.relative_to(project).as_posix()
    except ValueError as error:
        raise ConsoleError(f"Task record is outside the project: {path}") from error


class IdentityCache:
    """Resolve each task identity once per console process.

    Entries are valid only for the bytes of the identity declaration they were
    resolved under; any change to that file discards them. Failures are never
    cached, so a corrected project recovers on the next refresh.
    """

    def __init__(self) -> None:
        self._layout: ProjectNames | None = None
        self._declaration: bytes | None = None
        self._loaded = False
        self._items: dict[str, ResolvedTaskIdentity] = {}
        self.context = None

    def resolve(self, project: Path, task_id: str) -> ResolvedTaskIdentity:
        try:
            declaration = (project / names().project_declaration_path).read_bytes()
        except OSError:
            declaration = None
        if not self._loaded or names() != self._layout or declaration != self._declaration:
            self._items.clear()
            self._layout = names()
            self._declaration, self._loaded = declaration, True
        identity = self._items.get(task_id)
        if identity is None:
            identity = self._items[task_id] = resolve_task_identity(project, task_id, "existing", context=self.context)
        return identity



@dataclass(frozen=True)
class BranchObservation:
    """Read-only observations of one task branch and its worktree."""

    branch: str
    exists: bool
    worktree: str | None
    worktree_available: bool
    dirty: bool
    state: dict | None
    state_error: str | None
    state_source: str


def _read_console_state(project: Path, task_id: str, text: str) -> tuple[dict | None, str | None]:
    """Validate state text from a branch or worktree; a bad state is a per-task error."""
    try:
        data = json.loads(text)
        return read_task_state(project, task_id, "single", spike="outcome" in data,
                               text=text, stop_factory=stop_error), None
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        return None, str(stop_error("TASK_STATE_INVALID", f"state metadata: {error}",
                                    task_id=task_id, project=project))
    except CardineStop as error:
        return None, str(error)


def _branch_observation(project: Path, task_id: str, worktrees: dict[str, str],
                        identities: IdentityCache) -> BranchObservation | None:
    """Observe the canonical task branch, or None when the task has no branch or worktree."""
    try:
        identity = identities.resolve(project, task_id)
    except CardineError as error:
        raise ConsoleError(f"Cannot resolve task identity for {task_id}: {error}") from error
    branch = identity.branch_name
    worktree = worktrees.get(branch)
    available = bool(worktree and Path(worktree).is_dir())
    ref = f"refs/heads/{branch}"
    if _git_optional(project, "rev-parse", "--verify", "--quiet", ref) is None:
        return BranchObservation(branch, False, worktree, available, False, None, None, "") if worktree else None
    state_source = f"task state on branch {branch}"
    state_text = None
    if available:
        state_source = f"task state in worktree {branch}"
        try:
            state_text = state_path(Path(worktree), task_id).read_text(encoding="utf-8")
        except FileNotFoundError:
            state_text = None
        except (OSError, UnicodeError) as error:
            return BranchObservation(branch, True, worktree, available, False, None,
                                     f"Cannot read task state in worktree: {error}", state_source)
    else:
        state_text = _git_optional(project, "show", f"{ref}:{_relative(project, state_path(project, task_id))}")
    state, error = (None, None) if state_text is None else _read_console_state(
        Path(worktree) if available else project, task_id, state_text)
    dirty = bool(available and (_git_optional(Path(worktree), "status", "--porcelain") or "").strip())
    return BranchObservation(branch, True, worktree, available, dirty, state, error, state_source)


def _lifecycle_progress(step: str, active: bool) -> tuple[str, tuple[str, ...]]:
    """Map closure-status's authoritative steps to display-only ordered gates."""
    gates = ("Run task validation", "Record validation evidence", "Stage integration",
             "Run candidate validation", "Push main", "Clean up worktree")
    if step == "C1":
        return "working", gates
    if step == "C3":
        return "review pending", ("Independent review", *gates[2:])
    if step == "C5":
        return "validation/evidence pending", gates
    if step in {"C6", "C7"}:
        return "candidate validation", gates[2:]
    if step == "C9":
        return "push pending", gates[4:]
    if step == "C10":
        return ("cleanup pending", (gates[-1],)) if active else ("done", ())
    return "unavailable", ()


# closure-status steps that mean closure work remains after `integrate stage`.
CLOSING_STEPS = frozenset({"C6", "C7", "C9", "C10"})


def _dependency_states(by_id: dict[str, dict], dependencies: tuple[str, ...]) -> tuple[tuple[str, str], ...]:
    return tuple((item, DEPENDENCY_LABELS[by_id[item]["status"]]) for item in dependencies if item in by_id)


def _record_text(project: Path, row: dict, worktree: str | None) -> tuple[Path | None, str | None]:
    """Read the stable record for display; the task worktree copy is preferred when present."""
    if not row["record"]:
        return None, None
    path = project / row["record"]
    shown = Path(worktree) / row["record"] if worktree else None
    try:
        return path, _read_text(shown if shown is not None and shown.is_file() else path)
    except ConsoleError:
        return path, None


def _closing_task(project: Path, row: dict, worktrees: dict[str, str], identities: IdentityCache,
                  by_id: dict[str, dict], preset: str) -> Task | None:
    """List a done task with closure work or a cleanup-only hint.

    The state keeps its real status; `CLOSING` is derived from the registered
    canonical worktree and the lifecycle command, and nothing is written. The
    check costs no subprocess for a done task without a registered worktree.
    """
    if row["status"] != "done":
        return None
    task_id = row["id"]
    needle = task_id.casefold()
    if not any(needle in branch.casefold() for branch in worktrees):
        return None
    try:
        identity = identities.resolve(project, task_id)
    except CardineError:
        return None
    worktree = worktrees.get(identity.branch_name)
    if worktree is None:
        return None
    closure: dict[str, object] | None = None
    try:
        report, _ready = closure_status(task_id, None, project, identity=identity)
        if (isinstance(report, dict) and report.get("step") in CLOSING_STEPS
                and "resume" in report and "stop_reason" in report
                and (report["resume"] is None or isinstance(report["resume"], str))
                and (report["stop_reason"] is None or isinstance(report["stop_reason"], str))):
            closure = report
    except (CardineError, OSError, ValueError):
        # A transient lifecycle read keeps the task listed with unavailable progress.
        pass
    if closure is not None and closure["step"] == "C10" and closure["resume"] is None:
        return None
    cleanup_pending = bool(closure and closure["step"] == "C10" and closure["resume"])
    started_at = None
    try:
        started_at = lifecycle_started_at(task_id, project, identity=identity)
    except (CardineError, OSError, ValueError):
        pass
    progress_phase, remaining_gates = (
        _lifecycle_progress(str(closure["step"]), True) if closure else ("unavailable", ()))
    path, text = _record_text(project, row, None)
    dependencies = tuple(row["dependencies"])
    return Task(
        task_id=task_id, title=row["title"], status="done", phase=(row["phase"],) if row["phase"] else (),
        dependencies=dependencies, path=path,
        objective=_section(text or "", "Objective", "Goal"),
        criteria=_section(text or "", "Acceptance Criteria"),
        worktree=worktree, readiness="DONE" if cleanup_pending else "CLOSING",
        lifecycle="done" if cleanup_pending else "closing", source="main",
        cleanup_pending=cleanup_pending, registered_worktree=True, workflow=preset, legacy=False,
        updated_at=_committed_update(project, row["record"]) if row["record"] else None,
        closure_stop_reason=closure["stop_reason"] if closure else None,
        closure_resume=closure["resume"] if closure else None,
        started_at=started_at, progress_phase=progress_phase, remaining_gates=remaining_gates,
        dependency_states=_dependency_states(by_id, dependencies),
        review_verdict=row["review"].get("verdict"),
    )


def _cached_identity(project: Path, task_id: str,
                     identities: IdentityCache | None) -> ResolvedTaskIdentity | None:
    """Return the console's resolved identity, or None to let the reader resolve (and report)."""
    try:
        return (identities or IdentityCache()).resolve(project, task_id)
    except CardineError:
        return None


def _delivery_pending(project: Path, worktree: str | None, task_id: str, heads: dict[str, str],
                      identities: IdentityCache | None, cache: DeliveryCache,
                      shared: dict[str, object]) -> str | None:
    """Return why a review-ready task is not deliverable, or None when it is."""
    if not worktree:
        return "canonical worktree unavailable"
    identity = _cached_identity(project, task_id, identities)
    if identity is None:
        # The gate resolves identity itself and reports the failure verbatim.
        try:
            delivery_readiness(Path(worktree), task_id, verify_worktree=False)
            return None
        except (CardineError, OSError, ValueError) as error:
            return str(error)
    if "main" not in shared:
        shared["main"] = (_git_optional(project, "rev-parse", "--verify", "--quiet",
                                        "refs/heads/main") or "").strip() or None
        try:
            shared["common"] = canonical_git_common_dir(project)
        except (CardineError, OSError):
            shared["common"] = None
    return cache.pending(project, Path(worktree), heads.get(worktree, ""), task_id, identity,
                         shared["main"], shared["common"])


@scoped_command
def load_snapshot(project: Path, identities: IdentityCache | None = None,
                  deliveries: DeliveryCache | None = None) -> Snapshot:
    return _load_snapshot(project, identities, deliveries=deliveries)


@scoped_command
def load_task(project: Path, task_id: str,
              identities: IdentityCache | None = None) -> Task | None:
    """Read only one task, or None when the state directory no longer holds it."""
    snapshot = _load_snapshot(project, identities, only=task_id)
    return snapshot.tasks[0] if snapshot.tasks else None


def _load_snapshot(project: Path, identities: IdentityCache | None = None,
                   only: str | None = None, deliveries: DeliveryCache | None = None) -> Snapshot:
    """Build the snapshot; `only` restricts the per-task Git reads to one task.

    Git lists the registered worktrees once; every lifecycle reader below
    shares that read.
    """
    project = project.expanduser().resolve()
    with contextlib.ExitStack() as stack:
        snapshot = _build_snapshot(project, identities, only, deliveries, stack)
        from cardine.lifecycle.context import resolve_run_locations
        from cardine.lifecycle.preview import preview_run
        tasks = []
        for task in snapshot.tasks:
            try:
                preview = preview_run(resolve_run_locations(task.task_id, project))
            except (CardineError, OSError, ValueError) as error:
                tasks.append(replace(task, state_error=str(error)))
                continue
            tasks.append(replace(task, run_preview=preview, progress_phase=preview['step'],
                state_error=None if preview['work'] and task.state_error_origin == 'worktree' else task.state_error,
                closure_stop_reason=preview['stop']['code'] if preview['stop'] else None,
                closure_resume=preview['next']['command'] if preview['next'] else None))
        return replace(snapshot, tasks=tuple(tasks))


def _build_snapshot(project: Path, identities: IdentityCache | None, only: str | None,
                    deliveries: DeliveryCache | None, stack: contextlib.ExitStack) -> Snapshot:
    records: list[dict[str, str]] = []
    listing_error: ConsoleError | None = None
    try:
        records = parse_worktree_records(_git(project, "worktree", "list", "--porcelain"))
        stack.enter_context(shared_worktree_records(records))
    except ConsoleError as error:
        listing_error = error
    try:
        resolve_preset(project)
    except CardineError as error:
        raise ConsoleError(str(error)) from error
    model, inputs, _config = load_task_snapshot(project, all_tasks=True)
    if model["preset"] is None:
        detail = "; ".join(f"{item['path']}: {item['error']}" for item in model["diagnostics"])
        raise ConsoleError(f"Cannot read project status: {detail}")
    preset = model["preset"]
    by_id = {row["id"]: row for row in model["tasks"]}
    states: dict[str, dict] = {}
    state_files = {path.stem: path for path in inputs if path.parent == project / names().tasks_path}
    for task_id, path in state_files.items():
        try:
            states[task_id] = json.loads(inputs[path].decode("utf-8"))
        except (ValueError, UnicodeError):
            pass
    diagnostics = {item["path"]: item["error"] for item in model["diagnostics"]}
    # Enumeration/totals are observations too. A forged terminal status must
    # not disappear from the list or increment Done before preview is called.
    for task_id, state in states.items():
        if task_id not in by_id:
            continue
        try:
            read_task_state(project, task_id, 'single', text=inputs[state_files[task_id]].decode('utf-8'),
                            spike='outcome' in state, stop_factory=stop_error, require_contract=True)
        except (CardineError, OSError, ValueError) as error:
            by_id.pop(task_id)
            model['tasks'] = [row for row in model['tasks'] if row['id'] != task_id]
            model['totals'][state['status']] -= 1
            model['totals']['total'] -= 1
            diagnostics[state_files[task_id].relative_to(project).as_posix()] = str(error)
    identities = identities or IdentityCache()
    try:
        identities.context = task_identity_context(project, states={
            task_id: state for task_id, state in states.items() if task_id in by_id and by_id[task_id]["record"]})
    except CardineError as error:
        raise ConsoleError(f"Cannot resolve task identities: {error}") from error
    status_lines = ["## "] if only is not None else _git(
        project, "status", "--porcelain=v1", "--branch").splitlines()
    if not status_lines:
        raise ConsoleError("Git status returned no branch line")
    branch_line = status_lines[0].removeprefix("## ")
    if listing_error:
        raise listing_error
    worktrees, heads = _worktrees(records)
    delivery_cache = deliveries or DeliveryCache()
    deliveries_shared: dict[str, object] = {}
    tasks: list[Task] = []
    closing_count = 0
    for task_id, path in sorted(state_files.items()):
        if (only is not None and task_id != only) or task_id in by_id:
            continue
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", task_id):
            continue
        error = diagnostics.get(path.relative_to(project).as_posix(), "task state is invalid")
        tasks.append(Task(
            task_id, task_id, "STATE_ERROR", (), (), None, (), (),
            lifecycle="in_progress", readiness="STATE ERROR", legacy=False,
            source="task state on main", state_error=error, state_error_origin='main', workflow=preset,
        ))
    for row in model["tasks"]:
        task_id = row["id"]
        if only is not None and task_id != only:
            continue
        if row["status"] in ("done", "cancelled"):
            closing = _closing_task(project, row, worktrees, identities, by_id, preset)
            if closing:
                tasks.append(closing)
                closing_count += int(not closing.cleanup_pending)
            continue
        identity_problem = None
        try:
            facts = _branch_observation(project, task_id, worktrees, identities)
        except ConsoleError as error:
            facts, identity_problem = None, str(error)
        state = facts.state if facts and facts.state is not None else states[task_id]
        state_error = facts.state_error if facts else None
        status = state["status"]
        from_branch = bool(facts and facts.state is not None and facts.state != states[task_id])
        source = facts.state_source if from_branch else "task state on main"
        mismatch = None
        order = ("queued", "in_progress", "in_review", "done", "cancelled")
        if facts and facts.state is not None and order.index(status) < order.index(row["status"]):
            mismatch = f"main {row['status']}, {facts.branch} {status}"
        lifecycle = LIFECYCLE[status]
        if status == "queued" and row["startable"] and facts and facts.exists and facts.worktree_available:
            # A prepared canonical worktree of a startable task means work began: resume is
            # offered, never start. Unmet dependencies keep the task blocked whatever the worktree.
            lifecycle, source = "in_progress", f"branch {facts.branch}"
        if state_error:
            status, lifecycle, source, mismatch = "STATE_ERROR", "in_progress", "task state", state_error
        review = "REQUIRED" if review_is_required(state) else "NOT REQUIRED"
        dependencies = tuple(row["dependencies"])
        path, text = _record_text(project, row, facts.worktree if facts and facts.worktree_available else None)
        problem = None if text is not None else (
            "task record not found" if not row["record"] else "task record is unreadable")
        problem = problem or identity_problem
        closure_reason = closure_resume = None
        started_at = next((item["at"] for item in state["transitions"] if item["to"] == "in_progress"), None)
        progress_phase = "unavailable"
        remaining_gates: tuple[str, ...] = ()
        if facts and facts.exists and facts.worktree and lifecycle == "ready_for_review":
            # A task waiting for approval stops at the review gate (C3), which
            # closure-status never reports; keep its timing and gate visible.
            progress_phase, remaining_gates = _lifecycle_progress("C3", True)
        missing = [item for item in dependencies if item not in by_id]
        if state_error:
            readiness = "STATE ERROR"
        elif mismatch:
            readiness = "MISMATCH"
        elif problem:
            readiness = "UNKNOWN: " + problem.split(":", 1)[0]
        elif missing:
            readiness = "UNKNOWN: missing " + ", ".join(missing)
        elif lifecycle == "todo":
            readiness = "READY" if row["startable"] else (
                "BLOCKED: " + ", ".join(row["blocked_by"]) if row["blocked_by"] else "UNKNOWN: not startable")
        else:
            readiness = {"in_progress": "IN PROGRESS", "ready_for_review": "READY FOR REVIEW"}[lifecycle]
        delivery_pending = None
        updated_ref = f"refs/heads/{facts.branch}" if from_branch else "HEAD"
        tasks.append(Task(
            task_id=task_id, title=row["title"], status=status,
            phase=(row["phase"],) if row["phase"] else (), dependencies=dependencies, path=path,
            objective=_section(text or "", "Objective", "Goal"),
            criteria=_section(text or "", "Acceptance Criteria"),
            worktree=facts.worktree if facts else None, readiness=readiness,
            updated_at=_committed_update(project, row["record"], updated_ref) if row["record"] else None,
            lifecycle=lifecycle, source=source, mismatch=mismatch,
            changes_requested=(not state_error and state.get("review", {}).get("verdict") == "CHANGES_REQUESTED"),
            active_writer=bool(facts and facts.dirty),
            registered_worktree=bool(facts and facts.exists and facts.worktree and not facts.dirty
                                     and (facts.state is None or facts.state["status"] == row["status"])),
            record_problem=problem, review=review, workflow=preset,
            closure_stop_reason=closure_reason, closure_resume=closure_resume,
            started_at=started_at, progress_phase=progress_phase, remaining_gates=remaining_gates,
            dependency_states=_dependency_states(by_id, dependencies), legacy=False,
            review_verdict=None if state_error else state.get("review", {}).get("verdict"),
            state_error=state_error,
            state_error_origin=('worktree' if facts and facts.worktree_available else 'branch') if state_error else None,
            delivery_pending=delivery_pending,
        ))
    totals = model["totals"]
    return Snapshot(
        project=project, queue=project / names().tasks_path, branch=branch_line,
        git_summary="clean" if len(status_lines) == 1 else f"{len(status_lines) - 1} changed paths",
        git_changes=len(status_lines) - 1, tasks=tuple(tasks),
        done_count=totals["done"] + totals["cancelled"] - closing_count,
        preset=preset, totals=tuple(totals.items()),
    )
