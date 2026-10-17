"""Regression coverage for lifecycle-state-backed hook lookups (task 151)."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import meridian  # noqa: E402


class TaskStateLookupTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = (Path(self.temporary.name) / "project").resolve()
        self.root.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=self.root, check=True)
        (self.root / "tasks").mkdir()
        self.worker = self.root.parent / "worker"
        self.worker.mkdir()
        for number in range(1, 301):
            task_id = f"{number:03d}"
            (self.root / "tasks" / f"{task_id}.md").write_text(
                f"> **ID**: `{task_id}`\n\nStatus: IN_PROGRESS\n", encoding="utf-8"
            )
        state_dir = self.root / ".git" / meridian.WORKTREE_STATE_DIRECTORY
        state_dir.mkdir()
        (state_dir / "001.json").write_text(json.dumps({
            "task_id": "001", "branch": "task-001", "worktree": str(self.worker),
        }), encoding="utf-8")
        (self.worker / "tasks").mkdir()
        (self.worker / "tasks" / "001.md").write_text(
            "> **ID**: `001`\n\nStatus: IN_PROGRESS\n", encoding="utf-8"
        )
        self.records = [
            {"worktree": str(self.root), "branch": "refs/heads/main"},
            {"worktree": str(self.worker), "branch": "refs/heads/task-001"},
        ]

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_states_and_active_build_authorities_once_for_300_tasks(self) -> None:
        original = meridian._task_authorities
        calls = 0

        def counted(*args, **kwargs):
            nonlocal calls
            calls += 1
            return original(*args, **kwargs)

        with mock.patch.object(meridian, "_git_worktrees", return_value=self.records), \
             mock.patch.object(meridian, "canonical_project_root", return_value=self.root), \
             mock.patch.object(meridian, "_task_authorities", side_effect=counted):
            states = meridian.registered_worktree_task_states(self.root)
            self.assertEqual(states, [{"task_id": "001", "status": "IN_PROGRESS"}])
            self.assertEqual(calls, 1)

            calls = 0
            active = meridian.active_worktree_task(self.worker)
            self.assertEqual(active["task_id"], "001")
            self.assertEqual(calls, 1)


if __name__ == "__main__":
    unittest.main()
