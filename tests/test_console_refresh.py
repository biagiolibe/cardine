"""Read-only project console snapshot and output tests."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
from cardine.console import state as owner_console_state
from cardine.console import render as owner_console_render
from cardine.console import entry as owner_console_entry
from cardine.console import launch as owner_console_launch
from cardine.console import models as owner_console_models
from cardine.console import snapshot as owner_console_snapshot
from cardine.shared import console_workflow as owner_console_workflow
from cardine.shared import errors as owner_shared_errors
from cardine.tasks import identity as owner_tasks_identity
from cardine.worktree import storage as owner_worktree_storage


from console_support import HEADER, RESUME_001
import console_support as support

class BackgroundRefreshTest(unittest.TestCase):
    def wait_idle(self, state: owner_console_state.ConsoleState) -> None:
        deadline = time.monotonic() + 5
        while state.refreshing and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertFalse(state.refreshing)

    def snapshot(self, marker: str) -> owner_console_models.Snapshot:
        return owner_console_models.Snapshot(
            project=Path("/p"), queue=Path("/p/q"), branch=marker, git_summary="clean",
            git_changes=0, tasks=(), done_count=0,
        )

    def test_refresh_is_non_blocking_single_flight_and_published_atomically(self) -> None:
        state = owner_console_state.ConsoleState(Path("/p"))
        state.snapshot = self.snapshot("old")
        release = threading.Event()
        started = threading.Event()
        returned = threading.Event()

        def slow(_project, _identities, _deliveries=None):
            started.set()
            self.assertTrue(returned.wait(5), "start_refresh must return before loading completes")
            release.wait(5)
            return self.snapshot("new")

        with mock.patch.object(owner_console_state, "load_snapshot", side_effect=slow) as loader:
            self.assertTrue(state.start_refresh())
            returned.set()
            self.assertTrue(started.wait(5))
            self.assertFalse(state.start_refresh(), "refreshes must not overlap")
            state.apply_pending()
            self.assertEqual(state.snapshot.branch, "old")
            release.set()
            self.wait_idle(state)
            self.assertEqual(state.snapshot.branch, "old", "published only when applied")
            state.apply_pending()
            self.assertEqual(state.snapshot.branch, "new")
            self.assertIsNone(state.error)
            self.assertEqual(loader.call_count, 1)

    def test_failed_background_refresh_keeps_last_snapshot_and_marks_it_stale(self) -> None:
        state = owner_console_state.ConsoleState(Path("/p"))
        state.snapshot = self.snapshot("old")
        with mock.patch.object(owner_console_state, "load_snapshot",
                               side_effect=owner_console_workflow.ConsoleError("boom")):
            self.assertTrue(state.start_refresh())
            self.wait_idle(state)
        state.apply_pending()
        self.assertEqual(state.snapshot.branch, "old")
        self.assertEqual(state.error, "boom")
        with mock.patch.object(owner_console_state, "load_snapshot", side_effect=RuntimeError("bug")):
            self.assertTrue(state.start_refresh())
            self.wait_idle(state)
        state.apply_pending()
        self.assertEqual(state.snapshot.branch, "old")
        self.assertIn("bug", state.error)
        with mock.patch.object(owner_console_state, "load_snapshot", return_value=self.snapshot("fresh")):
            self.assertTrue(state.start_refresh())
            self.wait_idle(state)
        state.apply_pending()
        self.assertEqual((state.snapshot.branch, state.error), ("fresh", None))


    def test_launch_runs_off_the_caller_thread_and_is_single_flight(self) -> None:
        state = owner_console_state.ConsoleState(Path("/p"))
        task = mock.Mock(task_id="001")
        release = threading.Event()
        started = threading.Event()

        def slow(_state, _task, _agent, _dirty):
            started.set()
            release.wait(5)
            return True, "Started"

        with mock.patch.object(owner_console_state, "_launch_selected", side_effect=slow), \
             mock.patch.object(owner_console_state, "load_snapshot",
                               side_effect=AssertionError("full snapshot")) as full:
            begun = time.monotonic()
            self.assertTrue(state.start_launch(task, "codex"))
            self.assertLess(time.monotonic() - begun, 1)
            self.assertTrue(started.wait(5))
            self.assertTrue(state.launching)
            self.assertFalse(state.start_launch(task, "claude"), "one launch in flight")
            self.assertIsNone(state.take_launch_result())
            release.set()
            deadline = time.monotonic() + 5
            while state.launching and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertEqual(state.take_launch_result(), (True, "Started"))
            self.assertIsNone(state.take_launch_result())
            full.assert_not_called()

    def test_launch_failure_or_crash_is_reported_not_raised(self) -> None:
        state = owner_console_state.ConsoleState(Path("/p"))
        task = mock.Mock(task_id="001")
        for effect in (RuntimeError("boom"), owner_console_workflow.ConsoleError("git timed out")):
            with self.subTest(effect=str(effect)), \
                 mock.patch.object(owner_console_launch, "load_task", side_effect=effect):
                self.assertTrue(state.start_launch(task, "codex"))
                deadline = time.monotonic() + 5
                while state.launching and time.monotonic() < deadline:
                    time.sleep(0.01)
                success, message = state.take_launch_result()
                self.assertFalse(success)
                self.assertTrue(message)

    def test_key_handler_returns_while_snapshot_and_osascript_are_slow(self) -> None:
        state = owner_console_state.ConsoleState(Path("/p"))
        task = mock.Mock(task_id="001")
        gate = threading.Event()

        def blocked(*_args, **_kwargs):
            gate.wait(5)
            raise AssertionError("must not run on the caller thread")

        with mock.patch.object(owner_console_launch, "load_task", side_effect=blocked), \
             mock.patch.object(owner_console_launch.subprocess, "run", side_effect=blocked):
            begun = time.monotonic()
            self.assertTrue(state.start_launch(task, "codex"))
            self.assertLess(time.monotonic() - begun, 1)
            self.assertTrue(state.launching)
            gate.set()
            deadline = time.monotonic() + 5
            while state.launching and time.monotonic() < deadline:
                time.sleep(0.01)
        self.assertFalse(state.take_launch_result()[0])



if __name__ == "__main__":
    unittest.main()
