"""Local terminal dashboard for a Cardine project."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import threading

from cardine.console.launch import _agent_defaults, _launch_selected
from cardine.console.models import FrameworkIdentity, Snapshot, Task
from cardine.console.render import _elapsed
from cardine.console.snapshot import DeliveryCache, IdentityCache, load_snapshot
from cardine.shared.console_workflow import ConsoleError


def _framework_identity(script_path: Path | None = None) -> FrameworkIdentity:
    """Read this running framework's identity once; identity lookup must not block the console."""
    root = (script_path.resolve().parent.parent if script_path is not None
            else Path(__file__).resolve().parents[3])
    try:
        version = (root / "VERSION").read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        version = "unknown"
    return FrameworkIdentity(version or "unknown", root)


class ConsoleState:
    """Snapshot, staleness and refresh state shown by the console.

    `refresh` loads synchronously. `start_refresh` loads on one background
    thread and hands the result over through `apply_pending`, so the display
    only ever changes on the caller's thread and never shows a mixed state.
    """

    def __init__(self, project: Path):
        self.project = project
        self.framework = _framework_identity()
        self.agent_defaults = _agent_defaults()
        self.snapshot: Snapshot | None = None
        self.last_success: datetime | None = None
        self.error: str | None = None
        self.identities = IdentityCache()
        self.deliveries = DeliveryCache()
        self._lock = threading.Lock()
        self._worker: threading.Thread | None = None
        self._pending: tuple[Snapshot | None, str | None] | None = None
        self._launcher: threading.Thread | None = None
        self.launch_target = ""
        self._launch_result: tuple[bool, str] | None = None

    def _load(self) -> tuple[Snapshot | None, str | None]:
        try:
            return load_snapshot(self.project, self.identities, self.deliveries), None
        except ConsoleError as error:
            return None, str(error)

    def _apply(self, candidate: Snapshot | None, error: str | None) -> None:
        if candidate is None:
            self.error = error
            return
        self.snapshot = candidate
        self.last_success = datetime.now().astimezone()
        self.error = None

    def refresh(self) -> None:
        self._apply(*self._load())

    @property
    def refreshing(self) -> bool:
        with self._lock:
            return self._worker is not None

    def start_refresh(self) -> bool:
        """Start a background refresh unless one is already running."""
        with self._lock:
            if self._worker is not None:
                return False
            self._worker = threading.Thread(target=self._run, daemon=True)
            worker = self._worker
        worker.start()
        return True

    def _run(self) -> None:
        try:
            result = self._load()
        except Exception as error:  # a worker must never die silently
            result = (None, f"Refresh failed: {error}")
        with self._lock:
            self._pending = result
            self._worker = None

    @property
    def launching(self) -> bool:
        with self._lock:
            return self._launcher is not None

    def start_launch(self, task: Task, agent: str, dirty_confirmed: bool = False) -> bool:
        """Revalidate and launch on one background thread; False while one is pending."""
        with self._lock:
            if self._launcher is not None:
                return False
            self.launch_target = f"{agent} for task {task.task_id}"
            self._launcher = threading.Thread(
                target=self._run_launch, args=(task, agent, dirty_confirmed), daemon=True)
            launcher = self._launcher
        launcher.start()
        return True

    def _run_launch(self, task: Task, agent: str, dirty_confirmed: bool) -> None:
        try:
            result = _launch_selected(self, task, agent, dirty_confirmed)
        except Exception as error:  # a worker must never die silently
            result = (False, f"Launch failed: {error}; [copy] remains available")
        with self._lock:
            self._launch_result = result
            self._launcher = None

    def take_launch_result(self) -> tuple[bool, str] | None:
        with self._lock:
            result, self._launch_result = self._launch_result, None
        return result

    def apply_pending(self) -> None:
        with self._lock:
            pending, self._pending = self._pending, None
        if pending is not None:
            self._apply(*pending)


def one_shot(state: ConsoleState) -> str:
    if state.error:
        return f"STALE: {state.error}"
    snapshot = state.snapshot
    if snapshot is None:
        return "No project snapshot available"
    stamp = state.last_success.strftime("%Y-%m-%d %H:%M:%S %Z") if state.last_success else "unknown"
    lines = [
        (f"CARDINE | {state.framework.label} | {snapshot.project} | {snapshot.branch}"
         f" | {snapshot.git_summary}"),
        f"Updated: {stamp} | Open: {snapshot.open_count} | Done: {snapshot.done_count}",
    ]
    if snapshot.totals:
        lines.append(f"Preset: {snapshot.preset} | Totals: "
                     + ", ".join(f"{key}={value}" for key, value in snapshot.totals))
    for task in snapshot.tasks:
        objective = " ".join(task.objective)
        lines.append(f"{task.task_id} [{task.readiness}] {task.title}")
        if objective:
            lines.append(f"  {objective}")
        lines.append(f"  Dependencies: {', '.join(task.dependencies) or 'none'}")
        lines.append(f"  Status: {task.status} | Verdict: {task.review_verdict or 'none'}"
                     + (" | legacy" if task.legacy else ""))
        if task.state_error:
            lines.append(f"  State error: {task.state_error}")
        if task.source != "main":
            lines.append(f"  State from: {task.source}")
        if task.mismatch:
            lines.append(f"  Mismatch: {task.mismatch}")
        if task.closure_stop_reason:
            lines.append(f"  Closure stop: {task.closure_stop_reason}")
        if task.cleanup_pending:
            lines.append("  Cleanup pending")
        if task.closure_resume:
            lines.append(f"  Resume: {task.closure_resume}")
        if task.shows_progress:
            lines.append(f"  Elapsed: {_elapsed(task.started_at)}")
            lines.append(f"  Progress: {task.progress_phase}")
            lines.append(f"  Remaining gates: {', '.join(task.remaining_gates) or 'none'}")
        if task.markers:
            lines.append(f"  Markers: {', '.join(task.markers)}")
        if task.record_problem:
            lines.append(f"  Record: {task.record_problem}")
        lines.append(f"  Next action: {task.next_action}")
        if task.worktree:
            lines.append(f"  Worktree: {task.worktree}")
    lines.append("Agent activity: unavailable (no verified local source)")
    return "\n".join(lines)
