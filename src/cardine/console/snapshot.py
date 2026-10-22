"""Project snapshot loading for the console."""

from __future__ import annotations

from cardine.tasks.contract_snapshot import read_human_contract
from cardine.tasks.contract_fields import snapshot_record_path
from cardine.shared.layout import ProjectNames, names
from cardine.shared.snapshot_adapters import state_adapter

import contextlib
import json
import os
import re
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Callable

from cardine.console.models import Snapshot, Task
from cardine.lifecycle.execution import delivery_readiness
from cardine.shared.console_workflow import (
    BranchFacts,
    ConsoleError,
    ID_PATTERN,
    PROFILES,
    Profile,
    QueueRow,
    effective_state,
    handoff_status,
    has_link,
    heading_title,
    is_task_record_path,
    latest_review_verdict,
    link_target,
    parse_queue,
    record_matches,
    record_review,
    record_status,
)
from cardine.shared.errors import CardineError, CardineStop
from cardine.shared.git import (
    canonical_git_common_dir,
    parse_worktree_records,
    shared_worktree_records,
)
from cardine.shared.models import (
    ResolvedTaskIdentity,
)
from cardine.shared.text import read_task_field
from cardine.stops.render import stop_error
from cardine.tasks.identity import resolve_project_locations, resolve_task_identity, task_identity_context
from cardine.tasks.state import read_task_state, state_path, review_is_required
from cardine.templates.mode import detect_mode
from cardine.worktree.closure_status import closure_status
from cardine.worktree.storage import lifecycle_started_at


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ConsoleError(f"Cannot read {path}: {error}") from error


class RecordResolver:
    """Find task records for queue rows with absent or missing file targets.

    The task roots are walked at most once per snapshot, and only when a row
    needs the search, so resolution adds no per-task subprocess work.
    """

    def __init__(self, project: Path, locations) -> None:
        self.project = project
        self.roots = tuple(root.as_posix() for root in locations.task_roots)
        self.excluded = (locations.handoff_root.as_posix(), locations.review_root.as_posix())
        self._paths: list[str] | None = None
        self.states: dict[str, dict | None] = {}

    def _scan(self) -> list[str]:
        if self._paths is None:
            found: set[str] = set()
            for root in self.roots:
                for directory, names, files in os.walk(self.project / root):
                    relative = Path(directory).relative_to(self.project).as_posix()
                    names[:] = [
                        name for name in names
                        if is_task_record_path(f"{relative}/{name}/x", self.excluded)
                    ]
                    found.update(
                        f"{relative}/{name}" for name in files
                        if name.endswith(".md") and not os.path.islink(os.path.join(directory, name))
                    )
            self._paths = sorted(found)
        return self._paths

    def find(self, task_id: str) -> tuple[Path | None, str | None]:
        """Return the record path, or the per-task problem that prevents one."""
        matches = record_matches(task_id, self._scan(), self.excluded)
        if not matches:
            return None, "task record not found"
        if len(matches) > 1:
            return None, "ambiguous task record: " + ", ".join(matches)
        path = (self.project / matches[0]).resolve()
        if not path.is_relative_to(self.project) or not path.is_file():
            return None, f"task record is unavailable within the project: {matches[0]}"
        return path, None

    def find_by_name(self, basename: str) -> tuple[Path | None, str | None]:
        """Resolve an exact linked filename using the cached task-root scan."""
        matches = [relative for relative in self._scan()
                   if Path(relative).name == basename
                   and is_task_record_path(relative, self.excluded)]
        if not matches:
            return None, "task record not found"
        if len(matches) > 1:
            return None, "ambiguous task record: " + ", ".join(matches)
        path = (self.project / matches[0]).resolve()
        if not path.is_relative_to(self.project) or not path.is_file():
            return None, f"task record is unavailable within the project: {matches[0]}"
        return path, None

    def find_on_ref(self, ref: str, task_id: str) -> str | None:
        """Apply the same rules to a task branch tree; None unless exactly one match."""
        listing = _git_optional(self.project, "ls-tree", "-r", "--name-only", ref, "--", *self.roots)
        matches = record_matches(task_id, (listing or "").splitlines(), self.excluded)
        return matches[0] if len(matches) == 1 else None


def _task_path(project: Path, queue: Path, row: QueueRow,
               resolver: RecordResolver) -> tuple[Path | None, str | None]:
    """Resolve the frozen record path, including its exact archive location."""
    try:
        if resolver is not None and row.task_id in resolver.states:
            human = (resolver.states[row.task_id] or {}).get("contract", {})
            if "recordPath" not in human:
                raise CardineError("no frozen record path")
        else:
            human = read_human_contract(project, row.task_id)
        path = snapshot_record_path(project, human)
    except CardineError:
        # Unregistered and sparse historical records have only stable file
        # identity. This compatibility lookup never reads their headings.
        if not has_link(row.link):
            return resolver.find(row.task_id)
        target = link_target(queue.relative_to(project).as_posix(), row.link)
        if target is None:
            raise ConsoleError(f"Task {row.task_id} has no unambiguous file link")
        path = (project / target).resolve()
        if path.is_relative_to(project) and not path.exists():
            relative = path.relative_to(project).as_posix()
            if any(relative.startswith(root.rstrip("/") + "/") for root in resolver.roots):
                archived, problem = resolver.find_by_name(Path(target).name)
                if archived is not None and problem is None:
                    return archived, None
        if not path.is_relative_to(project) or not path.is_file():
            raise ConsoleError(f"Task {row.task_id} file is unavailable within the project: {path}")
    if not path.is_file():
        return None, "task record not found"
    return path, None


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
        return subprocess.run(
            ("git", "-C", str(project), *args),
            capture_output=True, text=True, check=False, timeout=5,
            env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
        )
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
                           handoff, state_path(worktree, task_id), worktree / names().execution_evidence_path,
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


def _select_profile(project: Path, workflow_resolver: Callable[[Path], str]) -> Profile:
    try:
        mode = workflow_resolver(project)
    except CardineError as error:
        raise ConsoleError(str(error).partition("; pass --mode")[0]) from error
    return PROFILES[mode]


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
            declaration = (project / names().task_identity_path).read_bytes()
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


def _read_console_state(project: Path, profile: Profile, task_id: str,
                        record_loader: Callable[[], str | None], *, text: str | None = None
                        ) -> tuple[dict | None, str | None]:
    """Read only the addressed task; missing state alone enables legacy prose."""
    # Class is metadata for outcome validation, never a status projection.
    try:
        journal = project / names().project_directory / "task-creation.lock"
        if text is None and journal.exists():
            raise stop_error("TASK_STATE_INVALID", "task creation is in progress; retry", task_id=task_id, project=project)
        raw = text if text is not None else state_path(project, task_id).read_text(encoding="utf-8")
        if text is None and journal.exists():
            raise stop_error("TASK_STATE_INVALID", "task creation changed during read; retry", task_id=task_id, project=project)
        adapter = state_adapter.get()
        if adapter is not None:
            return adapter(json.loads(raw)), None
        data = json.loads(raw)
        record = record_loader() if "contract" not in data else ""
        state = read_task_state(
            project, task_id, profile.name, review_required=None,
            spike=(read_task_field(record or "", "Class") or "").lower() == "spike",
            text=raw, stop_factory=stop_error,
        )
        return state, None
    except FileNotFoundError:
        return None, None
    except (ValueError, KeyError, TypeError) as error:
        return None, str(stop_error("TASK_STATE_INVALID", f"state metadata: {error}", task_id=task_id, project=project))
    except CardineStop as error:
        if error.code == "TASK_STATE_MISSING":
            return None, None
        return None, str(error)
    except ConsoleError as error:
        return None, str(stop_error("TASK_STATE_INVALID", f"state metadata: {error}",
                                    task_id=task_id, project=project))


def _branch_facts(project: Path, profile: Profile, task_id: str, queue: str,
                  worktrees: dict[str, str], identities: IdentityCache | None = None,
                  resolver: RecordResolver | None = None, main_record: str | None = None,
                  archived_link: bool = False, main_state: dict | None = None
                  ) -> tuple[BranchFacts | None, str | None, str | None, str | None]:
    """Read one task branch and its worktree state without modifying either.

    Returns the branch facts, the branch task record text and path, and the
    registered worktree path (known even when the branch ref is unreadable).
    """
    try:
        identity = (identities or IdentityCache()).resolve(project, task_id)
    except CardineError as error:
        raise ConsoleError(f"Cannot resolve task identity for {task_id}: {error}") from error
    branch = identity.branch_name
    worktree = worktrees.get(branch)
    if _git_optional(project, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}") is None:
        return None, None, None, worktree
    ref = f"refs/heads/{branch}"

    def show(relative: str) -> str | None:
        return _git_optional(project, "show", f"{ref}:{relative}")

    record_relative = _relative(project, identity.task_path)
    archived_relative = str(Path(record_relative).parent / "done" / Path(record_relative).name)

    def record_loader():
        for relative in (record_relative, archived_relative):
            if worktree and (Path(worktree) / relative).is_file():
                return _read_text(Path(worktree) / relative)
            text = show(relative)
            if text is not None:
                return text
        return None

    branch_state = branch_error = None
    state_source = f"task state on branch {branch}"
    if worktree and Path(worktree).is_dir():
        state_source = f"task state in worktree {branch}"
        branch_state, branch_error = _read_console_state(Path(worktree), profile, task_id, record_loader)
    else:
        state_text = show(_relative(project, state_path(project, task_id)))
        if state_text is not None:
            branch_state, branch_error = _read_console_state(
                project, profile, task_id, record_loader, text=state_text)

    def status_reader(row_id: str, _cells: dict[str, str]) -> str | None:
        if row_id != task_id:
            return None
        state = branch_state if branch_state is not None else main_state
        return "STATE_ERROR" if branch_error else state["status"] if state else None

    queue_text = show(queue)
    row = next((item for item in parse_queue(queue_text, f"{branch}:{queue}", profile, status_reader)
                if item.task_id == task_id), None) if queue_text is not None else None
    if row is None:
        record_path = None
    elif has_link(row.link):
        record_path = link_target(queue, row.link)
    else:
        record_path = main_record
    record = show(record_path) if record_path else None
    if record is None and resolver and row and not has_link(row.link):
        # The branch moved the record: resolve it in the branch tree by the same rules.
        record_path = resolver.find_on_ref(ref, task_id)
        record = show(record_path) if record_path else None
    legacy = branch_state is None and main_state is None and branch_error is None
    review = (show(_relative(project, identity.review_path))
              if legacy else None)
    base = "refs/heads/main" if _git_optional(
        project, "rev-parse", "--verify", "--quiet", "refs/heads/main") is not None else "HEAD"
    ahead = (_git_optional(project, "rev-list", "--count", f"{base}..{ref}") or "0").strip() != "0"
    dirty = bool(worktree and (_git_optional(worktree, "status", "--porcelain") or "").strip())
    working_row = None
    if dirty and worktree and legacy:
        try:
            working_text = _read_text(Path(worktree) / queue)
            working_row = next(
                (item for item in parse_queue(working_text, f"{worktree}:{queue}", profile)
                 if item.task_id == task_id),
                None,
            )
        except ConsoleError:
            # An unreadable or invalid uncommitted queue cannot supersede the
            # committed branch state.
            pass
    facts = BranchFacts(
        branch=branch, row=row, record=record_status(record) if legacy else None,
        handoff=handoff_status(show(_relative(project, identity.handoff_path))),
        review_verdict=latest_review_verdict(review) if legacy else None, ahead=ahead,
        worktree=worktree, dirty=dirty, working_row=working_row,
        record_path=record_path,
        worktree_available=bool(worktree and Path(worktree).is_dir()),
        state=branch_state, state_error=branch_error, state_source=state_source,
    )
    return facts, record, record_path, worktree


def _dependency_ids(row: QueueRow) -> tuple[str, ...]:
    dependencies = tuple(
        item.strip().strip("`") for item in row.dependencies.split(",")
        if item.strip() not in ("", "—", "-")
    )
    if any(not ID_PATTERN.fullmatch(item) for item in dependencies):
        raise ConsoleError(f"Task {row.task_id} has an invalid dependency")
    return dependencies


def _dependency_states(profile: Profile, by_id: dict[str, str],
                       dependencies: tuple[str, ...]) -> tuple[tuple[str, str], ...]:
    return tuple(
        (item, {
            "done": "Done", "in_progress": "Working",
            "ready_for_review": "Review", "todo": "Open",
        }[profile.phases[by_id[item]]])
        for item in dependencies if item in by_id
    )


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


def _closing_task(project: Path, profile: Profile, row: QueueRow, queue: Path,
                  worktrees: dict[str, str], identities: IdentityCache | None,
                  resolver: RecordResolver, by_id: dict[str, str]) -> Task | None:
    """List a terminal task with closure work or a cleanup-only hint.

    The queue keeps its real status; `CLOSING` is derived from the registered
    canonical worktree and the lifecycle command, and nothing is written. The
    check costs no subprocess for a done row without a registered worktree.
    """
    if row.status != profile.closing_status:
        return None
    needle = row.task_id.casefold()
    if not any(needle in branch.casefold() for branch in worktrees):
        return None
    try:
        identity = (identities or IdentityCache()).resolve(project, row.task_id)
    except CardineError:
        return None
    worktree = worktrees.get(identity.branch_name)
    if worktree is None:
        return None
    closure: dict[str, object] | None = None
    try:
        report, _ready = closure_status(row.task_id, None, project, identity=identity)
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
        started_at = lifecycle_started_at(row.task_id, project, identity=identity)
    except (CardineError, OSError, ValueError):
        pass
    progress_phase, remaining_gates = (
        _lifecycle_progress(str(closure["step"]), True) if closure else ("unavailable", ()))
    try:
        path, _problem = _task_path(project, queue, row, resolver)
        text = _read_text(path) if path else None
    except ConsoleError:
        path, text = None, None
    dependencies = _dependency_ids(row)
    return Task(
        task_id=row.task_id, title=heading_title(_read_console_state(project, profile, row.task_id, lambda: None)[0]) or row.title or row.task_id,
        status=row.status, phase=row.section, dependencies=dependencies, path=path,
        objective=_section(text or "", "Objective", "Goal"),
        criteria=_section(text or "", "Acceptance Criteria"),
        worktree=worktree, readiness="DONE" if cleanup_pending else "CLOSING",
        lifecycle="done" if cleanup_pending else "closing", source="main",
        cleanup_pending=cleanup_pending,
        registered_worktree=True, workflow=profile.name, checkbox=row.checkbox,
        updated_at=_committed_update(project, _relative(project, path)) if path else None,
        closure_stop_reason=closure["stop_reason"] if closure else None,
        closure_resume=closure["resume"] if closure else None,
        started_at=started_at, progress_phase=progress_phase, remaining_gates=remaining_gates,
        dependency_states=_dependency_states(profile, by_id, dependencies),
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


def load_snapshot(project: Path, identities: IdentityCache | None = None,
                  deliveries: DeliveryCache | None = None,
                  *, workflow_resolver: Callable[[Path], str] = detect_mode) -> Snapshot:
    return _load_snapshot(project, identities, deliveries=deliveries, workflow_resolver=workflow_resolver)


def load_task(project: Path, task_id: str,
              identities: IdentityCache | None = None) -> Task | None:
    """Read only one queued or closing task, or None when the queues no longer hold it."""
    snapshot = _load_snapshot(project, identities, only=task_id)
    return snapshot.tasks[0] if snapshot.tasks else None


def _load_snapshot(project: Path, identities: IdentityCache | None = None,
                   only: str | None = None, deliveries: DeliveryCache | None = None,
                   *, workflow_resolver: Callable[[Path], str] = detect_mode) -> Snapshot:
    """Build the snapshot; `only` restricts the per-task Git reads to one task.

    Git lists the registered worktrees once; every lifecycle reader below
    shares that read.
    """
    project = project.expanduser().resolve()
    with contextlib.ExitStack() as stack:
        return _build_snapshot(project, identities, only, deliveries, stack, workflow_resolver)


def _build_snapshot(project: Path, identities: IdentityCache | None, only: str | None,
                    deliveries: DeliveryCache | None, stack: contextlib.ExitStack, workflow_resolver: Callable[[Path], str]) -> Snapshot:
    # Read the registered worktrees first so that profile and location detection
    # share the one read; a failure surfaces where the read used to happen.
    records: list[dict[str, str]] = []
    listing_error: ConsoleError | None = None
    try:
        records = parse_worktree_records(_git(project, "worktree", "list", "--porcelain"))
        stack.enter_context(shared_worktree_records(records))
    except ConsoleError as error:
        listing_error = error
    profile = _select_profile(project, workflow_resolver)
    try:
        locations = resolve_project_locations(project)
    except Exception as error:
        raise ConsoleError(f"Cannot resolve canonical queue: {error}") from error
    queue = project / locations.queue
    archive = queue.with_name("QUEUE_ARCHIVE.md")
    resolver = RecordResolver(project, locations)
    states: dict[str, dict | None] = {}
    state_errors: dict[str, str | None] = {}
    resolver.states = states

    def status_reader(task_id: str, cells: dict[str, str]) -> str | None:
        provisional = QueueRow(
            task_id, "", "", (), "", cells.get("File", cells.get("Task file", "")), None)

        def record_loader():
            path, _problem = _task_path(project, queue, provisional, resolver)
            return _read_text(path) if path else None
        states[task_id] = None
        states[task_id], state_errors[task_id] = _read_console_state(
            project, profile, task_id, record_loader)
        if state_errors[task_id]:
            return "STATE_ERROR"
        return states[task_id]["status"] if states[task_id] else None

    active_rows = parse_queue(_read_text(queue), str(queue), profile, status_reader)
    archived_rows = parse_queue(_read_text(archive), str(archive), profile) if archive.is_file() else []
    # Read archived machine state only for dependencies that the active queue
    # addresses; unrelated historical files retain the bounded-read contract.
    addressed = {dependency for row in active_rows for dependency in _dependency_ids(row)}
    for row in archived_rows:
        if row.task_id in addressed:
            status_reader(row.task_id, {"File": row.link})
    by_id: dict[str, str] = {}
    for row in (*active_rows, *archived_rows):
        if row.task_id in by_id:
            raise ConsoleError(f"Duplicate task ID across queues: {row.task_id}")
        by_id[row.task_id] = row.status
    from cardine.tasks.state import dependency_satisfied
    identities = identities or IdentityCache()
    identities.context = task_identity_context(project, states=states)
    satisfied_ids = {row.task_id for row in (*active_rows, *archived_rows)
                     if (dependency_satisfied(states[row.task_id]) if states.get(row.task_id)
                         else row.status in profile.satisfying and not state_errors.get(row.task_id))}
    # A single-task read needs neither the branch line nor the change count.
    status_lines = ["## "] if only is not None else _git(
        project, "status", "--porcelain=v1", "--branch").splitlines()
    if not status_lines:
        raise ConsoleError("Git status returned no branch line")
    branch_line = status_lines[0].removeprefix("## ")
    branch = branch_line.split("...", 1)[0].split(" [", 1)[0]
    if listing_error:
        raise listing_error
    worktrees, heads = _worktrees(records)
    delivery_cache = deliveries or DeliveryCache()
    deliveries_shared: dict[str, object] = {}
    queue_relative = _relative(project, queue)
    tasks: list[Task] = []
    closing_count = 0
    # A phase archived by `integrate stage` leaves the active queue while its
    # task still has closure work, so archived rows are checked too.
    for row in archived_rows:
        if only is not None and row.task_id != only:
            continue
        closing = _closing_task(project, profile, row, queue, worktrees, identities,
                                resolver, by_id)
        if closing:
            tasks.append(closing)
            closing_count += int(not closing.cleanup_pending)
    for row in active_rows:
        if only is not None and row.task_id != only:
            continue
        if state_errors[row.task_id]:
            tasks.append(Task(
                row.task_id, row.title or row.task_id, "STATE_ERROR", row.section, (), None, (), (),
                lifecycle="in_progress", readiness="STATE ERROR", legacy=False,
                source="task state on main", state_error=state_errors[row.task_id], workflow=profile.name, checkbox=row.checkbox,
            ))
            continue
        if profile.phases[row.status] == "done":
            closing = _closing_task(project, profile, row, queue, worktrees, identities,
                                    resolver, by_id)
            if closing:
                state = states[row.task_id]
                closing = replace(closing, legacy=state is None,
                                  review_verdict=state.get("review", {}).get("verdict") if state else None)
                tasks.append(closing)
                closing_count += int(not closing.cleanup_pending)
            continue
        dependencies = _dependency_ids(row)
        path, main_problem = _task_path(project, queue, row, resolver)
        primary_text = _read_text(path) if path else None
        if main_problem:
            # Task identity needs exactly one record, so a task without one has no branch state.
            facts, branch_text, branch_path, worktree = None, None, None, None
        else:
            facts, branch_text, branch_path, worktree = _branch_facts(
                project, profile, row.task_id, queue_relative, worktrees, identities, resolver,
                _relative(project, path) if path and not has_link(row.link) else None,
                main_state=states[row.task_id],
                archived_link=bool(path and has_link(row.link) and
                                   path != (project / link_target(queue_relative, row.link)).resolve()))
        branch_policy_text = (branch_text if facts and facts.row
                              and facts.row.status != row.status else primary_text)
        state = facts.state if facts and facts.state is not None else states[row.task_id]
        state_error = facts.state_error if facts else None
        review = ("REQUIRED" if review_is_required(state)
                  else "NOT REQUIRED") if state else (
                      row.review if row.review is not None else record_review(branch_policy_text))
        effective = effective_state(profile, row, None if state or state_error else record_status(primary_text),
                                    facts, review, states[row.task_id], state_error)
        closure_reason = closure_resume = None
        started_at = None
        progress_phase = "unavailable"
        remaining_gates: tuple[str, ...] = ()
        # The lifecycle command is authoritative for closure guidance.  Restrict
        # the extra read to registered active worktrees; queued tasks retain the
        # constant-cost refresh path established by task 078.
        if (facts and facts.worktree and not row.checkbox
                and effective.lifecycle == "ready_for_review"):
            # A task waiting for approval stops at the review gate (C3), which
            # closure-status never reports; keep its timing and gate visible.
            progress_phase, remaining_gates = _lifecycle_progress("C3", True)
            try:
                started_at = lifecycle_started_at(
                    row.task_id, project, identity=_cached_identity(project, row.task_id, identities))
            except (CardineError, OSError, ValueError):
                pass
        if facts and facts.worktree and effective.lifecycle == "in_progress":
            known = _cached_identity(project, row.task_id, identities)
            try:
                closure, _ready = closure_status(row.task_id, None, project, identity=known)
                closure_reason = closure["stop_reason"]
                closure_resume = closure["resume"]
                progress_phase, remaining_gates = _lifecycle_progress(
                    str(closure.get("step", "")), bool(facts and facts.worktree),
                )
            except (CardineError, OSError, ValueError):
                # A transient lifecycle read must not make the entire dashboard stale.
                pass
            try:
                started_at = lifecycle_started_at(row.task_id, project, identity=known)
            except (CardineError, OSError, ValueError):
                # Legacy or unreadable timing data is intentionally non-fatal.
                pass
        if state:
            started_at = next((item["at"] for item in state["transitions"]
                               if item["to"] == "in_progress"), None)
        from_branch = facts is not None and branch_text is not None and effective.source != "main"
        task_text = branch_text if from_branch else primary_text
        problem = None if task_text is not None else (main_problem or "task record not found")
        # Dependencies are satisfied by integrated state only: a task accepted on its
        # branch does not unblock dependents until it reaches the primary queue.
        missing = [item for item in dependencies if item not in by_id]
        waiting = [item for item in dependencies
                   if item in by_id and item not in satisfied_ids]
        if state_error:
            readiness = "STATE ERROR"
        elif effective.mismatch:
            readiness = "MISMATCH"
        elif problem:
            readiness = "UNKNOWN: " + problem.split(":", 1)[0]
        elif missing:
            readiness = "UNKNOWN: missing " + ", ".join(missing)
        elif waiting:
            readiness = "BLOCKED: " + ", ".join(waiting)
        else:
            readiness = {
                "todo": "READY", "in_progress": "IN PROGRESS",
                "ready_for_review": "READY FOR REVIEW", "done": "DONE ON BRANCH",
            }[effective.lifecycle]
        delivery_pending = None
        if state and state["status"] == "in_review":
            delivery_pending = _delivery_pending(
                project, worktree, row.task_id, heads, identities, delivery_cache, deliveries_shared)
            if delivery_pending is not None:
                readiness = "PENDING DELIVERY/CHANGES"
        updated_path = branch_path if from_branch else (_relative(project, path) if path else None)
        updated_ref = ("refs/heads/" + facts.branch) if from_branch else "HEAD"
        title = heading_title(state) or row.title or row.task_id
        tasks.append(Task(
            task_id=row.task_id, title=title, status=effective.status,
            phase=row.section, dependencies=dependencies, path=path,
            objective=_section(task_text or "", "Objective", "Goal"),
            criteria=_section(task_text or "", "Acceptance Criteria"),
            worktree=worktree, readiness=readiness,
            updated_at=_committed_update(project, updated_path, updated_ref) if updated_path else None,
            lifecycle=effective.lifecycle, source=effective.source,
            mismatch=effective.mismatch, changes_requested=effective.changes_requested,
            active_writer=effective.active_writer,
            registered_worktree=bool(
                facts and facts.worktree and not facts.dirty and facts.row
                and facts.row.status == row.status
            ),
            record_problem=problem, review=review,
            workflow=profile.name, checkbox=row.checkbox,
            closure_stop_reason=closure_reason,
            closure_resume=closure_resume,
            started_at=started_at,
            progress_phase=progress_phase,
            remaining_gates=remaining_gates,
            dependency_states=_dependency_states(profile, by_id, dependencies),
            legacy=state is None and state_error is None,
            review_verdict=state.get("review", {}).get("verdict") if state else (facts.review_verdict if facts else None),
            state_error=state_error, delivery_pending=delivery_pending,
        ))
    return Snapshot(
        project=project, queue=queue, branch=branch_line,
        git_summary="clean" if len(status_lines) == 1 else f"{len(status_lines) - 1} changed paths",
        git_changes=len(status_lines) - 1, tasks=tuple(tasks),
        done_count=sum(profile.phases[status] == "done" for status in by_id.values()) - closing_count,
    )
