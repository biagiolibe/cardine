"""Console data models."""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import Path



@dataclass(frozen=True)
class FrameworkIdentity:
    version: str
    root: Path

    @property
    def label(self) -> str:
        version = "version unknown" if self.version == "unknown" else f"v{self.version}"
        return f"{version} | {self.root_label}"

    @property
    def root_label(self) -> str:
        try:
            relative = self.root.relative_to(Path.home().resolve())
            return "~" if relative == Path(".") else "~/" + str(relative)
        except ValueError:
            return str(self.root)


@dataclass(frozen=True)
class AgentDefaults:
    model: str = "unknown"
    effort: str = "unknown"

    @property
    def label(self) -> str:
        return f"configured default: model {self.model}; effort {self.effort}"


@dataclass(frozen=True)
class Task:
    task_id: str
    title: str
    status: str
    phase: tuple[str, ...]
    dependencies: tuple[str, ...]
    path: Path | None
    objective: tuple[str, ...]
    criteria: tuple[str, ...]
    worktree: str | None = None
    readiness: str = ""
    updated_at: int | None = None
    lifecycle: str = "todo"
    source: str = "main"
    mismatch: str | None = None
    changes_requested: bool = False
    active_writer: bool = False
    registered_worktree: bool = False
    record_problem: str | None = None
    review: str | None = None
    dependency_states: tuple[tuple[str, str], ...] = ()
    workflow: str = "single"
    checkbox: bool = False
    closure_stop_reason: str | None = None
    closure_resume: str | None = None
    cleanup_pending: bool = False
    started_at: str | None = None
    progress_phase: str = "unavailable"
    remaining_gates: tuple[str, ...] = ()
    legacy: bool = True
    review_verdict: str | None = None
    state_error: str | None = None
    delivery_pending: str | None = None

    @property
    def is_resume(self) -> bool:
        """Whether Proceed with would resume ordinary implementation work."""
        return (self.lifecycle == "in_progress"
                and not self.changes_requested)

    @property
    def resume_confirmations(self) -> int:
        """Explicit warnings required before Resume reaches agent selection."""
        return (1 + int(self.active_writer)) if self.is_resume else 0

    @property
    def launch_command(self) -> str | None:
        if self.state_error or self.record_problem or self.delivery_pending or self.readiness == "MISMATCH":
            return None
        if self.is_resume:
            if self.active_writer:
                return (f"Proceed with {self.task_id} (Resume: run "
                        f"cardine worktree prepare {self.task_id} --resume --format json)")
            return f"Proceed with {self.task_id}"
        if self.active_writer:
            return None
        if self.lifecycle == "todo" and self.readiness == "READY":
            return f"Proceed with {self.task_id}"
        if self.lifecycle == "ready_for_review":
            if self.review == "REQUIRED" or (self.legacy and self.checkbox and self.review is None):
                return f"Review {self.task_id}"
        if self.lifecycle == "in_progress" and self.changes_requested:
            return f"Address review {self.task_id}"
        return None

    @property
    def shows_progress(self) -> bool:
        """Whether elapsed time and lifecycle progress apply to this task."""
        return self.lifecycle in ("in_progress", "closing") or (
            self.lifecycle == "ready_for_review"
            and self.worktree is not None
        )

    @property
    def markers(self) -> tuple[str, ...]:
        return (
            *(("changes requested",) if self.changes_requested else ()),
            *(("active writer",) if self.active_writer else ()),
            *(("registered worktree",) if self.registered_worktree else ()),
        )

    @property
    def next_action(self) -> str:
        if self.state_error:
            return self.state_error
        if self.is_resume and self.launch_command:
            return f"If assigned: {self.launch_command}"
        if self.closure_stop_reason:
            return f"{self.closure_stop_reason}: {self.closure_resume or 'no resume command'}"
        if self.closure_resume:
            return self.closure_resume
        if self.readiness == "CLOSING":
            return "Closure state unavailable: rerun cardine worktree closure-status"
        if self.record_problem and self.readiness != "MISMATCH":
            return f"Resolve the task record: {self.record_problem}"
        if self.readiness == "READY":
            return f"If assigned: {self.launch_command}"
        if self.readiness == "MISMATCH":
            return f"Resolve the state disagreement: {self.mismatch}"
        if self.readiness == "READY FOR REVIEW":
            if self.launch_command:
                return f"If assigned: {self.launch_command}"
            if self.active_writer:
                return "Review unavailable: active writer"
            if self.review == "NOT REQUIRED":
                return "Review unavailable: Review: NOT REQUIRED"
            if self.review is None:
                return "Review unavailable: review policy not declared"
            return "Awaiting review of the task branch"
        if self.readiness == "DONE ON BRANCH":
            return "Awaiting integration of the task branch"
        if self.readiness == "IN PROGRESS":
            return "Continue the assigned task in its worktree"
        if self.readiness.startswith("BLOCKED"):
            return "Wait for the listed dependencies to complete"
        return "Resolve the missing dependency record"


@dataclass(frozen=True)
class LaunchRequest:
    """A confirmed, safe-to-quote invocation for an iTerm2 split pane."""

    agent: str
    directive: str
    directory: Path
    task_id: str
    session_uuid: str

    @property
    def shell_command(self) -> str:
        return "cd " + shlex.quote(str(self.directory)) + " && exec " + shlex.join(
            (self.agent, self.directive)
        )


@dataclass(frozen=True)
class Snapshot:
    project: Path
    queue: Path
    branch: str
    git_summary: str
    git_changes: int
    tasks: tuple[Task, ...]
    done_count: int
    preset: str = ""
    totals: tuple[tuple[str, int], ...] = ()

    @property
    def open_count(self) -> int:
        """Open tasks: from the status totals when present, else the listed tasks."""
        if not self.totals:
            return sum(not task.cleanup_pending for task in self.tasks)
        totals = dict(self.totals)
        return (totals["queued"] + totals["in_progress"] + totals["in_review"]
                + sum(task.lifecycle == "closing" for task in self.tasks))
