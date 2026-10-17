"""Workflow profiles and effective task state for the read-only project console."""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass
from typing import Callable


PHASES = ("todo", "in_progress", "ready_for_review", "done")
ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
LINK_PATTERN = re.compile(r"\[[^]]+\]\(([^)#]+)(?:#[^)]*)?\)")
HANDOFF_STATUS = re.compile(r"^[-*\s]*Status:\s*`?([A-Z_]+)`?\s*$", re.MULTILINE)
RECORD_STATUS = re.compile(r"^Status:\s*`?([A-Z_]+)`?\s*$", re.MULTILINE)
RECORD_REVIEW = re.compile(r"^Review:\s*(.*?)\s*$", re.MULTILINE)
REVIEW_ATTEMPT = re.compile(
    r"^## Attempt (\d+) — (CHANGES_REQUESTED|APPROVE|BLOCKED)\s*$", re.MULTILINE
)
TASK_HEADING = re.compile(r"^#\s+(?:Task\s+)?\S+\s+[—-]\s+(.+?)\s*$")
QUEUE_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
LEAN_QUEUE_WRAPPER = re.compile(r"\bActive Queue$", re.IGNORECASE)


class ConsoleError(Exception):
    """Project state could not be read without ambiguity."""


@dataclass(frozen=True)
class Profile:
    """Queue vocabulary of one workflow mode, normalized to console phases."""

    name: str
    tokens: dict[str, str]
    phases: dict[str, str]
    satisfying: frozenset[str]
    # The queue status `integrate stage` applies; a task with this status can
    # still be closing until cleanup removes its canonical worktree.
    closing_status: str = ""


PROFILES = {
    "lean-delivery": Profile(
        name="lean-delivery",
        tokens={"[ ]": "TODO", "[/]": "IN_PROGRESS", "[x]": "DONE"},
        phases={"TODO": "todo", "QUEUED": "todo", "IN_PROGRESS": "in_progress",
                "STATE_ERROR": "in_progress", "DONE": "done"},
        satisfying=frozenset({"DONE"}),
        closing_status="DONE",
    ),
    "governed-sdd": Profile(
        name="governed-sdd",
        tokens={name: name for name in (
            "QUEUED", "IN_PROGRESS", "READY_FOR_REVIEW", "ACCEPTED",
            "ANSWERED", "INCONCLUSIVE",
        )},
        phases={
            "QUEUED": "todo", "IN_PROGRESS": "in_progress",
            "CHANGES_REQUESTED": "in_progress", "STATE_ERROR": "in_progress",
            "READY_FOR_REVIEW": "ready_for_review", "ACCEPTED": "done",
            "ANSWERED": "done", "INCONCLUSIVE": "done",
        },
        satisfying=frozenset({"ACCEPTED", "ANSWERED"}),
        closing_status="ACCEPTED",
    ),
}


@dataclass(frozen=True)
class QueueRow:
    task_id: str
    status: str
    title: str
    section: tuple[str, ...]
    dependencies: str
    link: str
    review: str | None


def _cell(row: dict[str, str], *names: str) -> str:
    folded = {key.casefold(): value for key, value in row.items()}
    for name in names:
        if name.casefold() in folded:
            return folded[name.casefold()]
    return ""


def parse_queue(text: str, label: str, profile: Profile,
                status_reader: Callable[[str, dict[str, str]], str | None] | None = None
                ) -> list[QueueRow]:
    rows: list[QueueRow] = []
    headers: list[str] = []
    headings: list[tuple[int, str]] = []
    for line_number, line in enumerate(text.splitlines(), 1):
        heading = QUEUE_HEADING.match(line)
        if heading:
            level = len(heading.group(1))
            headings = [(depth, title) for depth, title in headings if depth < level]
            if level >= 2 and not (
                profile.name == "lean-delivery" and level == 2
                and LEAN_QUEUE_WRAPPER.search(heading.group(2))
            ):
                headings.append((level, heading.group(2)))
        if not line.startswith("|"):
            headers = []
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if "Status" in cells and "ID" in cells:
            headers = cells
            continue
        if not headers or len(cells) != len(headers) or set("".join(cells)) <= {"-", ":"}:
            continue
        row = dict(zip(headers, cells))
        folded_headers = {header.casefold() for header in headers}
        task_id = row["ID"].strip("`")
        if not ID_PATTERN.fullmatch(task_id):
            raise ConsoleError(f"Invalid task ID in {label}:{line_number}")
        status = status_reader(task_id, row) if status_reader else None
        if status is None:
            token = row.get("Status", "").strip("`")
            if token not in profile.tokens:
                raise ConsoleError(f"Unknown task status in {label}:{line_number}: {row.get('Status')}")
            status = profile.tokens[token]
        rows.append(QueueRow(
            task_id=task_id, status=status, title=_cell(row, "Title"),
            section=tuple(title for _, title in headings),
            dependencies=_cell(row, "Depends on", "Dependencies"),
            link=_cell(row, "File", "Task file"),
            # None: the queue has no Review column, so no policy is declared.
            review=_cell(row, "Review").strip("`") if "review" in folded_headers else None,
        ))
    return rows


def link_target(queue_relative: str, cell: str) -> str | None:
    """Resolve a queue link to a project-relative POSIX path, or None if it escapes."""
    match = LINK_PATTERN.fullmatch(cell)
    if not match:
        return None
    target = posixpath.normpath(posixpath.join(posixpath.dirname(queue_relative), match.group(1)))
    return None if target.startswith("..") or posixpath.isabs(target) else target


def has_link(cell: str) -> bool:
    """Whether a queue row declares a file link at all, valid or not."""
    return cell.strip() not in ("", "—", "–", "-")


IGNORED_RECORD_DIRECTORIES = frozenset({"reviews", "handoffs"})


def is_task_record_path(path: str, excluded_roots: tuple[str, ...]) -> bool:
    """Whether a project-relative POSIX path may be a task record.

    Review records and handoffs share the task ID, so anything under a declared
    review or handoff root, or a directory named `reviews` or `handoffs`, is not
    a task record.
    """
    if IGNORED_RECORD_DIRECTORIES.intersection(path.split("/")[:-1]):
        return False
    return not any(path == root or path.startswith(root.rstrip("/") + "/")
                   for root in excluded_roots)


def record_matches(task_id: str, paths: list[str], excluded_roots: tuple[str, ...]) -> list[str]:
    """Return the sorted task record candidates named `<ID>.md` among `paths`."""
    name = f"{task_id}.md"
    return sorted(path for path in paths
                  if posixpath.basename(path) == name and is_task_record_path(path, excluded_roots))


def heading_title(text: str) -> str:
    lines = text.splitlines()
    match = TASK_HEADING.match(lines[0]) if lines else None
    return match.group(1) if match else ""


def record_status(text: str | None) -> str | None:
    match = RECORD_STATUS.search(text or "")
    return match.group(1) if match else None


def record_review(text: str | None) -> str | None:
    """Return a declared task-record review policy, if it is recognized."""
    match = RECORD_REVIEW.search(text or "")
    value = match.group(1).strip() if match else None
    return value if value in ("REQUIRED", "NOT REQUIRED") else None


def handoff_status(text: str | None) -> str | None:
    match = HANDOFF_STATUS.search(text or "")
    return match.group(1) if match else None


def latest_review_verdict(text: str | None) -> str | None:
    attempts = [(int(number), verdict) for number, verdict in REVIEW_ATTEMPT.findall(text or "")]
    return max(attempts)[1] if attempts else None


@dataclass(frozen=True)
class BranchFacts:
    """Read-only observations of one task branch and its worktree."""

    branch: str
    row: QueueRow | None
    record: str | None
    handoff: str | None
    review_verdict: str | None
    ahead: bool
    worktree: str | None
    dirty: bool
    working_row: QueueRow | None = None
    record_path: str | None = None
    worktree_available: bool = False
    state: dict | None = None
    state_error: str | None = None
    state_source: str = ""


@dataclass(frozen=True)
class Effective:
    lifecycle: str
    status: str
    source: str
    mismatch: str | None = None
    changes_requested: bool = False
    active_writer: bool = False


def effective_state(profile: Profile, primary: QueueRow, primary_record: str | None,
                    facts: BranchFacts | None, review: str | None = None,
                    state: dict | None = None, state_error: str | None = None) -> Effective:
    """Combine the primary queue row with the task branch state, never writing either."""
    error = state_error or (facts.state_error if facts else None)
    if error:
        return Effective("in_progress", "STATE_ERROR", "task state", mismatch=error)
    snapshot = facts.state if facts and facts.state is not None else state
    if snapshot is not None:
        status = snapshot["status"]
        source = facts.state_source if facts and facts.state is not None else "task state on main"
        lifecycle = profile.phases[status]
        writer = bool(facts and facts.dirty)
        if (profile.name == "lean-delivery" and status == "QUEUED" and facts
                and facts.worktree_available and facts.record_path
                and not facts.record_path.startswith("tasks/done/")):
            lifecycle = "in_progress"
        return Effective(lifecycle, status, source, active_writer=writer,
                         changes_requested=snapshot.get("review", {}).get("verdict") == "CHANGES_REQUESTED")
    if facts is None:
        row, record, source, writer = primary, primary_record, "main", False
    else:
        source = f"branch {facts.branch}"
        writer = facts.dirty
        if facts.row is None:
            return Effective(
                "in_progress", "MISMATCH", source, active_writer=writer,
                mismatch=f"main {primary.status}, {facts.branch} has no queue row",
            )
        row, record = facts.row, facts.record
        if PHASES.index(profile.phases[row.status]) < PHASES.index(profile.phases[primary.status]):
            return Effective(
                "in_progress", "MISMATCH", source, active_writer=writer,
                mismatch=f"main {primary.status}, {facts.branch} {row.status}",
            )
        if facts.working_row is not None:
            working_phase = PHASES.index(profile.phases[facts.working_row.status])
            committed_phase = PHASES.index(profile.phases[row.status])
            if working_phase < committed_phase:
                return Effective(
                    "in_progress", "MISMATCH", source, active_writer=writer,
                    mismatch=(f"{facts.branch} {row.status}, working tree "
                              f"{facts.working_row.status}"),
                )
            if working_phase > committed_phase:
                row = facts.working_row
                source = f"uncommitted {facts.branch}"
        if (profile.name == "lean-delivery" and primary.status == "TODO"
                and row.status == "TODO" and facts.worktree_available
                and facts.record_path and not facts.record_path.startswith("tasks/done/")):
            # Lean Delivery keeps [/] derived: reserving the canonical branch and
            # worktree starts the task without a shared queue-file edit.
            return Effective("in_progress", "IN_PROGRESS", source, active_writer=writer)
        if row.status == primary.status:
            source = "main"

    def mismatch(reason: str) -> Effective:
        return Effective("in_progress", "MISMATCH", source, active_writer=writer, mismatch=reason)

    phase = profile.phases[row.status]
    if profile.name == "governed-sdd":
        review_value = row.review if review is None else review
        if (facts is not None and primary.status == "QUEUED" and row.status == "QUEUED"
                and facts.worktree_available and facts.record_path
                and not facts.record_path.startswith("tasks/done/")
                and record in (None, "QUEUED", "IN_PROGRESS", "READY_FOR_REVIEW")):
            # Task branches never edit the shared queue, so a Governed task's
            # in-branch state is derived from its record, like the Lean `[/]`.
            derived = f"branch {facts.branch}"
            if record == "READY_FOR_REVIEW":
                if review_value not in (None, "REQUIRED"):
                    return mismatch(f"queue QUEUED, Review {review_value or 'unset'}")
                return Effective("ready_for_review", "READY_FOR_REVIEW", derived,
                                 active_writer=writer)
            return Effective(
                "in_progress", "IN_PROGRESS", derived, active_writer=writer,
                changes_requested=facts.review_verdict == "CHANGES_REQUESTED",
            )
        if row.status == "READY_FOR_REVIEW" or record == "READY_FOR_REVIEW":
            if record != row.status:
                return mismatch(f"queue {row.status}, task record {record or 'no status'}")
            if review_value not in (None, "REQUIRED"):
                return mismatch(f"queue READY_FOR_REVIEW, Review {review_value or 'unset'}")
        return Effective(
            phase, row.status, source, active_writer=writer,
            changes_requested=bool(
                facts and row.status == "IN_PROGRESS"
                and facts.review_verdict == "CHANGES_REQUESTED"
            ),
        )
    if row.status == "DONE" and facts is not None:
        if facts.handoff != "DONE":
            return mismatch(f"{facts.branch} queue [x], handoff {facts.handoff or 'missing'}")
        if not facts.ahead:
            return mismatch(f"{facts.branch} queue [x], branch is not ahead of main")
        if facts.worktree and not facts.dirty:
            return Effective("ready_for_review", "READY_FOR_REVIEW", source)
        return Effective("in_progress", "IN_PROGRESS", source, active_writer=writer)
    return Effective(phase, row.status, source, active_writer=writer)
