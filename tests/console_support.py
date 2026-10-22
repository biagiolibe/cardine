"""Non-discovered console repository fixtures."""
from __future__ import annotations
import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from project_config_support import write_project_config
from task_state_support import set_state, write_task
from cardine.shared.layout import names
from cardine.console import models as owner_console_models
from cardine.console import snapshot as owner_console_snapshot

HEADER = (
    "| Status | ID | Title | Priority | Depends on | File |\n"
    "|--------|----|-------|----------|------------|------|\n"
)

RESUME_001 = "Proceed with 001 (Resume: run cardine worktree prepare 001 --resume --format json)"


class RepoCase(unittest.TestCase):
    """Throwaway Git repository with a primary checkout and task worktrees."""

    lock = "LEAN_DELIVERY"

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.project = self.root / "project"
        self.project.mkdir()
        self.git(self.project, "init", "-q", "-b", "main")
        write_project_config(self.project, "lean" if self.lock == "LEAN_DELIVERY" else "governed")

    def git(self, cwd: Path, *args: str) -> str:
        return subprocess.run(
            ["git", "-c", "commit.gpgsign=false", "-c", "user.name=Test",
             "-c", "user.email=test@example.com", "-C", str(cwd), *args],
            capture_output=True, text=True, check=True,
        ).stdout

    def write(self, root: Path, relative: str, text: str) -> None:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def commit(self, cwd: Path, message: str = "change") -> None:
        self.git(cwd, "add", "-A")
        self.git(cwd, "commit", "-q", "-m", message)

    def worktree(self, branch: str) -> Path:
        path = self.root / f"wt-{branch}"
        self.git(self.project, "worktree", "add", "-q", "-b", branch, str(path))
        return path

    def load(self) -> dict[str, owner_console_models.Task]:
        return {task.task_id: task for task in owner_console_snapshot.load_snapshot(self.project).tasks}

    def refs_and_status(self) -> tuple[str, str]:
        return (self.git(self.project, "for-each-ref"),
                self.git(self.project, "status", "--porcelain"))



class LeanEffectiveStateFixture(RepoCase):
    def queue(self, statuses: dict[str, str], deps: dict[str, str] | None = None) -> str:
        rows = "".join(
            f"| `[{token}]` | {task_id} | Task {task_id} | P2 | {(deps or {}).get(task_id, '—')} "
            f"| [{task_id}]({task_id}-task.md) |\n"
            for task_id, token in statuses.items()
        )
        return ("# Queue\n\n### Phase 1\n\n" + HEADER + rows)

    def setup_project(self, statuses: dict[str, str], deps: dict[str, str] | None = None) -> None:
        self.write(self.project, "tasks/QUEUE.md", self.queue(statuses, deps))
        for task_id in statuses:
            self.write(
                self.project, f"tasks/{task_id}-task.md",
                f"# Task {task_id} — Title {task_id}\n\n> **ID**: `{task_id}`\n\n"
                "## Objective\n\nDo it.\n\n## Acceptance Criteria\n\n- [ ] Check.\n",
            )
        self.commit(self.project, "initial")

    def set_branch_status(self, wt: Path, task_id: str, token: str, handoff: str | None = None) -> None:
        queue = (wt / "tasks/QUEUE.md").read_text(encoding="utf-8")
        queue = re.sub(rf"\| `\[.\]` \| {task_id} \|", f"| `[{token}]` | {task_id} |", queue)
        self.write(wt, "tasks/QUEUE.md", queue)
        if handoff:
            self.write(wt, f"tasks/handoffs/{task_id}.md",
                       f"# Completion Report — {task_id}\n\n- Status: `{handoff}`\n")
        self.commit(wt, f"{task_id} {token}")



class GovernedEffectiveStateFixture(RepoCase):
    lock = "GOVERNED_SDD"

    header = (
        "| Order | ID | Priority | Status | Review | Dependencies | Task file |\n"
        "|---:|---|---|---|---|---|---|\n"
    )

    def setup_project(self, rows: list[tuple[str, str, str, str]]) -> None:
        """Rows are (id, status, review, dependencies)."""
        body = "# Task Execution Queue\n\n" + self.header + "".join(
            f"| {index} | {task_id} | P1 | {status} | {review} | {deps} | "
            f"[{task_id}]({task_id}.md) |\n"
            for index, (task_id, status, review, deps) in enumerate(rows, 1)
        )
        self.write(self.project, "tasks/QUEUE.md", body)
        for task_id, status, review, _deps in rows:
            self.write_record(self.project, task_id, status)
        self.commit(self.project, "initial")

    def write_record(self, root: Path, task_id: str, status: str) -> None:
        self.write(root, f"tasks/{task_id}.md",
                   f"# Task {task_id} — Governed {task_id}\n\nPriority: P1\nStatus: {status}\n"
                   "Review: REQUIRED\n\n## Objective\n\nGoverned work.\n")

    def set_branch(self, wt: Path, task_id: str, status: str, record: str | None = None,
                   review: str | None = None) -> None:
        queue = (wt / "tasks/QUEUE.md").read_text(encoding="utf-8")
        queue = re.sub(rf"(\| {task_id} \| P1 \| )\w+", rf"\g<1>{status}", queue)
        self.write(wt, "tasks/QUEUE.md", queue)
        self.write_record(wt, task_id, record or status)
        if review:
            self.write(wt, f"tasks/reviews/{task_id}.md", review)
        self.commit(wt, f"{task_id} {status}")



class MachineStateConsoleFixture(RepoCase):
    lock = "GOVERNED_SDD"

    header = GovernedEffectiveStateFixture.header

    setup_project = GovernedEffectiveStateFixture.setup_project

    write_record = GovernedEffectiveStateFixture.write_record

    def state(self, root: Path, task_id: str, status: str, *, workflow="single",
              verdict=None, required=True) -> None:
        # MERIDIAN-INSTALLATION-CHECK
        if names().project_directory == ".meridian":
            # Deliberately historical installation data, read only by the legacy adapter.
            route = ["QUEUED"] if status == "QUEUED" else ["QUEUED", status]
        else:
            route = ["queued"]
            if status != "queued":
                route.append("in_progress")
            if status == "in_review" or (verdict and status == "in_progress"):
                route.append("in_review")
            if route[-1] != status:
                route.append(status)
        snapshot = {
            "version": 1, "task_id": task_id, "workflow": workflow, "status": status,
            "transitions": [{"from": before, "to": after, "commit": "a" * 40,
                             "at": "2026-10-11T12:00:00Z"}
                            for before, after in zip(route, route[1:])],
        }
        snapshot["review"] = {"required": required, "verdict": verdict, "attempt": 1,
                              "reviewed_commit": "a" * 40 if verdict else None,
                              "approved_by": "reviewer" if verdict else None}
        self.write(root, str(names().tasks_path / f"{task_id}.json"), json.dumps(snapshot))

    queue = LeanEffectiveStateFixture.queue


class StateConsoleFixture(RepoCase):
    """Product console fixture: a task exists only as validated state plus its record."""

    def add(self, task_id: str, status: str = "queued", dependencies: str = "none", **options) -> Path:
        return write_task(self.project, task_id, status, dependencies, **options)

    def setup_project(self, tasks: dict[str, str], deps: dict[str, str] | None = None) -> None:
        for task_id, status in tasks.items():
            self.add(task_id, status, (deps or {}).get(task_id, "none"))
        self.commit(self.project, "initial")

    def branch_state(self, worktree: Path, task_id: str, status: str, *, verdict: str | None = None,
                     commit: bool = True) -> None:
        set_state(worktree, task_id, status, verdict=verdict)
        if commit:
            self.commit(worktree, f"{task_id} {status}")
