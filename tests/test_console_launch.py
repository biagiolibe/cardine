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

ITERM2_DICTIONARY_PROBE = (
    'tell application "iTerm2" to get unique id of current session of current tab of current window'
)

def _compile_applescript(script: str, output: Path) -> subprocess.CompletedProcess[str]:
    """Compile an AppleScript using the same isolated output handling for each check."""
    return subprocess.run(
        ("osacompile", "-o", str(output), "-e", script),
        capture_output=True, text=True, check=False, timeout=30,
    )


def _osacompile_can_resolve_iterm2_dictionary() -> tuple[bool, str]:
    """Probe whether osacompile can resolve the iTerm2 dictionary used by the payload."""
    with tempfile.TemporaryDirectory() as directory:
        try:
            result = _compile_applescript(ITERM2_DICTIONARY_PROBE, Path(directory) / "probe.scpt")
        except subprocess.TimeoutExpired:
            return False, "timed out"
    if result.returncode:
        return False, result.stderr
    return True, ""


from test_console_render import FakeScreen


class AgentLaunchTest(unittest.TestCase):
    SESSION_ID = "w0t1p2:12345678-1234-1234-1234-123456789abc"

    def task(self, **changes) -> owner_console_models.Task:
        values = dict(
            task_id="001", title="First", status="TODO", phase=(), dependencies=(), path=None,
            objective=(), criteria=(), readiness="READY", lifecycle="todo",
        )
        values.update(changes)
        return owner_console_models.Task(**values)

    def test_permitted_directive_matrix_refuses_writers_and_mismatches(self) -> None:
        self.assertEqual(self.task().launch_command, "Proceed with 001")
        self.assertFalse(self.task().is_resume)
        self.assertEqual(self.task().resume_confirmations, 0)
        for workflow in ("lean-delivery", "governed-sdd"):
            with self.subTest(workflow=workflow):
                resumed = self.task(workflow=workflow, readiness="IN PROGRESS",
                                    lifecycle="in_progress")
                self.assertTrue(resumed.is_resume)
                self.assertEqual(resumed.launch_command, "Proceed with 001")
                self.assertEqual(resumed.resume_confirmations, 1)
                self.assertEqual(
                    self.task(workflow=workflow, readiness="IN PROGRESS",
                              lifecycle="in_progress", active_writer=True).launch_command,
                    RESUME_001,
                )
                self.assertEqual(
                    self.task(workflow=workflow, readiness="IN PROGRESS",
                              lifecycle="in_progress", active_writer=True).resume_confirmations,
                    2,
                )
        self.assertEqual(self.task(workflow="lean-delivery", readiness="READY FOR REVIEW",
                                   lifecycle="ready_for_review").launch_command, "Review 001")
        self.assertEqual(self.task(workflow="governed-sdd", readiness="READY FOR REVIEW",
                                   lifecycle="ready_for_review", review="REQUIRED").launch_command,
                         "Review 001")
        self.assertFalse(self.task(workflow="governed-sdd", readiness="READY FOR REVIEW",
                                   lifecycle="ready_for_review", review="REQUIRED").is_resume)
        self.assertEqual(self.task(workflow="governed-sdd", readiness="IN PROGRESS",
                                   lifecycle="in_progress", changes_requested=True).launch_command,
                         "Address review 001")
        self.assertIsNone(self.task(workflow="governed-sdd", readiness="READY FOR REVIEW",
                                    lifecycle="ready_for_review", review="NOT_REQUIRED").launch_command)
        self.assertIsNone(self.task(readiness="MISMATCH", active_writer=True).launch_command)
        self.assertIsNone(self.task(active_writer=True).launch_command)
        self.assertIsNone(self.task(lifecycle="done", readiness="done ON BRANCH").launch_command)
        self.assertIsNone(self.task(lifecycle="closing", readiness="CLOSING").launch_command)
        self.assertIsNone(self.task(lifecycle="in_progress", readiness="IN PROGRESS",
                                    record_problem="duplicate record").launch_command)

    def test_next_action_explains_review_launches_and_refusals(self) -> None:
        required = self.task(workflow="governed-sdd", readiness="READY FOR REVIEW",
                             lifecycle="ready_for_review", review="REQUIRED")
        self.assertEqual(required.next_action, "If assigned: Review 001")
        self.assertEqual(
            self.task(workflow="governed-sdd", readiness="READY FOR REVIEW",
                      lifecycle="ready_for_review").next_action,
            "Review unavailable: review policy not declared",
        )
        self.assertEqual(
            self.task(workflow="governed-sdd", readiness="READY FOR REVIEW",
                      lifecycle="ready_for_review", review="NOT REQUIRED").next_action,
            "Review unavailable: Review: NOT REQUIRED",
        )
        self.assertEqual(
            self.task(workflow="governed-sdd", readiness="READY FOR REVIEW",
                      lifecycle="ready_for_review", review="REQUIRED", active_writer=True).next_action,
            "Review unavailable: active writer",
        )
        self.assertEqual(
            self.task(readiness="MISMATCH", mismatch="state conflict").next_action,
            "Resolve the state disagreement: state conflict",
        )
        self.assertEqual(
            self.task(readiness="READY FOR REVIEW", lifecycle="ready_for_review",
                      record_problem="task record not found").next_action,
            "Resolve the task record: task record not found",
        )
        lean = self.task(workflow="lean-delivery", readiness="READY FOR REVIEW",
                         lifecycle="ready_for_review")
        self.assertEqual(lean.next_action, "If assigned: Review 001")

    def test_request_revalidates_id_and_preserves_an_argument_vector(self) -> None:
        with mock.patch.dict(owner_console_launch.os.environ, {"ITERM_SESSION_ID": self.SESSION_ID}, clear=False):
            request, error = owner_console_launch._launch_request(self.task(), Path("."), "codex")
        self.assertIsNone(error)
        self.assertIsNotNone(request)
        self.assertEqual(request.directive, "Proceed with 001")
        self.assertEqual(request.session_uuid, "12345678-1234-1234-1234-123456789abc")
        self.assertIn("exec codex 'Proceed with 001'", request.shell_command)
        with mock.patch.dict(owner_console_launch.os.environ, {"ITERM_SESSION_ID": self.SESSION_ID}, clear=False):
            hostile, error = owner_console_launch._launch_request(self.task(task_id="001; rm -rf /"), Path("."), "codex")
        self.assertIsNone(hostile)
        self.assertIn("task ID", error or "")

    def test_defaults_read_only_known_and_unknown_fallbacks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / ".codex").mkdir()
            (home / ".claude").mkdir()
            (home / ".codex" / "config.toml").write_text(
                'model = "gpt-test"\nmodel_reasoning_effort = "high"\n', encoding="utf-8")
            (home / ".claude" / "settings.json").write_text(
                '{"model": "claude-test", "effort": "medium"}', encoding="utf-8")
            defaults = owner_console_launch._agent_defaults(home)
            self.assertEqual(defaults["codex"], owner_console_models.AgentDefaults("gpt-test", "high"))
            self.assertEqual(defaults["claude"], owner_console_models.AgentDefaults("claude-test", "medium"))
            (home / ".codex" / "config.toml").write_text("not = [valid", encoding="utf-8")
            (home / ".claude" / "settings.json").write_text("{", encoding="utf-8")
            defaults = owner_console_launch._agent_defaults(home)
            self.assertEqual(defaults["codex"], owner_console_models.AgentDefaults())
            self.assertEqual(defaults["claude"], owner_console_models.AgentDefaults())

    def test_launch_panel_is_bordered_and_identifies_the_choice(self) -> None:
        screen = FakeScreen(20, 100)
        palette = {name: 0 for name in (
            "base", "text", "title", "ready", "muted", "line", "action", "blocked",
        )}
        owner_console_render._draw_launch_prompt(
            screen, 100, 20, self.task(), 0, Path("/project"),
            {"claude": owner_console_models.AgentDefaults("claude-test", "medium"),
             "codex": owner_console_models.AgentDefaults("gpt-test", "high")}, palette,
        )
        rendered = "\n".join(screen.row(y) for y in range(20))
        self.assertIn("┌", rendered)
        self.assertIn("Task: 001", rendered)
        self.assertIn("Directive: Proceed with 001", rendered)
        self.assertIn("1 Claude Code", rendered)
        self.assertIn("2 Codex", rendered)
        self.assertIn("Esc cancels", rendered)

    def test_resume_prompts_for_liveness_and_a_second_dirty_confirmation(self) -> None:
        palette = {name: 0 for name in (
            "base", "text", "title", "ready", "muted", "line", "action", "blocked",
        )}
        defaults = {"claude": owner_console_models.AgentDefaults(), "codex": owner_console_models.AgentDefaults()}
        clean = self.task(readiness="IN PROGRESS", lifecycle="in_progress")
        screen = FakeScreen(20, 100)
        owner_console_render._draw_launch_prompt(screen, 100, 20, clean, 0, Path("/project"),
                                    defaults, palette)
        rendered = "\n".join(screen.row(y) for y in range(20))
        self.assertIn("cannot tell whether an agent is still active", rendered)
        self.assertIn("Press y to continue", rendered)

        dirty = self.task(readiness="IN PROGRESS", lifecycle="in_progress",
                          active_writer=True)
        screen = FakeScreen(20, 100)
        owner_console_render._draw_launch_prompt(screen, 100, 20, dirty, 1, Path("/project"),
                                    defaults, palette)
        rendered = "\n".join(screen.row(y) for y in range(20))
        self.assertIn("uncommitted changes", rendered)
        self.assertIn("Press y again", rendered)

    def test_resume_copy_and_launch_use_the_identical_directive(self) -> None:
        task = self.task(readiness="IN PROGRESS", lifecycle="in_progress")
        palette = {name: 0 for name in (
            "base", "text", "title", "ready", "working", "muted", "line", "action",
            "blocked",
        )}
        lines = [value for value, _style in owner_console_render._detail_lines(task, 80, palette)]
        self.assertIn(f"{task.launch_command}  [copy]  [l Resume]", lines)

    def test_agent_selection_revalidates_and_launches_without_enter(self) -> None:
        task = self.task()
        state = mock.Mock(project=Path("/project"))
        with mock.patch.object(owner_console_launch, "load_task", return_value=task) as reload, \
             mock.patch.object(owner_console_state, "load_snapshot") as full, \
             mock.patch.object(owner_console_launch, "_launch_request") as request, \
             mock.patch.object(owner_console_launch, "_start_launch", return_value=(True, "Started")) as start:
            request.return_value = (
                owner_console_models.LaunchRequest("codex", "Proceed with 001", Path("/project"), "001",
                                      "12345678-1234-1234-1234-123456789abc"), None)
            self.assertEqual(owner_console_launch._launch_selected(state, task, "codex"),
                             (True, "Started"))
        reload.assert_called_once()
        self.assertEqual(reload.call_args.args[:2], (Path("/project"), task.task_id))
        full.assert_not_called()
        state.refresh.assert_not_called()
        request.assert_called_once_with(task, Path("/project"), "codex")
        start.assert_called_once()

    def test_agent_selection_stops_on_revalidation_failure(self) -> None:
        task = self.task(readiness="IN PROGRESS", lifecycle="in_progress")
        closing = self.task(readiness="CLOSING", lifecycle="closing")
        for label, current in (("closing", closing), ("done", None)):
            with self.subTest(label=label):
                state = mock.Mock(project=Path("/project"))
                with mock.patch.object(owner_console_launch, "load_task", return_value=current), \
                     mock.patch.object(owner_console_launch, "_launch_request") as request, \
                     mock.patch.object(owner_console_launch, "_start_launch") as start:
                    success, message = owner_console_launch._launch_selected(state, task, "claude")
                self.assertFalse(success)
                self.assertIn("state changed", message)
                request.assert_not_called()
                start.assert_not_called()

    def test_agent_selection_requires_new_confirmation_if_worktree_became_dirty(self) -> None:
        selected = self.task(readiness="IN PROGRESS", lifecycle="in_progress")
        current = self.task(readiness="IN PROGRESS", lifecycle="in_progress",
                            active_writer=True)
        state = mock.Mock(project=Path("/project"))
        with mock.patch.object(owner_console_launch, "load_task", return_value=current), \
             mock.patch.object(owner_console_launch, "_launch_request") as request:
            success, message = owner_console_launch._launch_selected(state, selected, "codex")
        self.assertFalse(success)
        self.assertIn("state changed", message)  # the directive changed to the resume form
        request.assert_not_called()

    def test_unconfirmed_dirty_resume_is_refused_before_launch(self) -> None:
        task = self.task(readiness="IN PROGRESS", lifecycle="in_progress", active_writer=True)
        state = mock.Mock(project=Path("/project"))
        with mock.patch.object(owner_console_launch, "load_task", return_value=task), \
             mock.patch.object(owner_console_launch, "_launch_request") as request:
            success, message = owner_console_launch._launch_selected(state, task, "codex")
        self.assertFalse(success)
        self.assertIn("became dirty", message)
        request.assert_not_called()

    def test_resume_flag_is_only_in_the_dirty_resume_directive(self) -> None:
        for workflow in ("lean-delivery", "governed-sdd"):
            for fields in (
                dict(readiness="READY", lifecycle="todo"),
                dict(readiness="IN PROGRESS", lifecycle="in_progress"),
                dict(readiness="READY FOR REVIEW", lifecycle="ready_for_review", review="REQUIRED"),
                dict(readiness="IN PROGRESS", lifecycle="in_progress", changes_requested=True),
            ):
                with self.subTest(workflow=workflow, fields=fields):
                    directive = self.task(workflow=workflow, **fields).launch_command
                    self.assertTrue(directive is None or "--resume" not in directive)
        resume = self.task(readiness="IN PROGRESS", lifecycle="in_progress", active_writer=True)
        self.assertEqual(resume.launch_command, RESUME_001)
        self.assertIn("prepare 001 --resume --format json", RESUME_001)
        request, error = owner_console_launch._launch_request(resume, Path("/project"), "codex")
        self.assertIsNone(request)  # no iTerm session here; the directive itself is unchanged
        with mock.patch.dict(os.environ, {"ITERM_SESSION_ID": "w0t1p2:12345678-1234-1234-1234-123456789abc"}), \
             mock.patch.object(owner_console_launch, "_primary_checkout", return_value=(Path("/project"), None)):
            request, error = owner_console_launch._launch_request(resume, Path("/project"), "codex")
        self.assertIsNone(error)
        self.assertEqual(request.directive, RESUME_001)
        self.assertIn(RESUME_001, request.shell_command)

    def test_request_refuses_missing_or_malformed_console_session(self) -> None:
        for session_id in (None, "w0t1p2:not-a-uuid", "wrong:12345678-1234-1234-1234-123456789abc"):
            environment = {} if session_id is None else {"ITERM_SESSION_ID": session_id}
            with self.subTest(session_id=session_id), \
                 mock.patch.dict(owner_console_launch.os.environ, environment, clear=True):
                request, error = owner_console_launch._launch_request(self.task(), Path("."), "codex")
            self.assertIsNone(request)
            self.assertEqual(error, "iTerm2 console session is missing or invalid; [copy] remains available")

    def test_launch_failure_modes_leave_copy_as_fallback(self) -> None:
        request = owner_console_models.LaunchRequest(
            "codex", "Proceed with 001", Path("/project"), "001",
            "12345678-1234-1234-1234-123456789abc",
        )
        with mock.patch.object(owner_console_launch.sys, "platform", "linux"):
            self.assertIn("macOS", owner_console_launch._start_launch(request)[1])
        with mock.patch.object(owner_console_launch.sys, "platform", "darwin"), \
             mock.patch.object(owner_console_launch.shutil, "which", return_value=None):
            self.assertIn("codex is not available", owner_console_launch._start_launch(request)[1])
        with mock.patch.object(owner_console_launch.sys, "platform", "darwin"), \
             mock.patch.object(owner_console_launch.shutil, "which", return_value="/usr/bin/tool"), \
             mock.patch.object(owner_console_launch.subprocess, "run", side_effect=subprocess.TimeoutExpired("osascript", 10)):
            self.assertIn("timed out", owner_console_launch._start_launch(request)[1])

    def test_osascript_receives_quoted_command_and_reports_iterm_failure(self) -> None:
        request = owner_console_models.LaunchRequest(
            "claude", "Proceed with 001; echo nope", Path("/project name"), "001",
            "12345678-1234-1234-1234-123456789abc",
        )
        with mock.patch.object(owner_console_launch.sys, "platform", "darwin"), \
             mock.patch.object(owner_console_launch.shutil, "which", return_value="/usr/bin/tool"), \
             mock.patch.object(owner_console_launch.subprocess, "run") as run:
            run.return_value = mock.Mock(returncode=1, stderr="Application isn't running", stdout="")
            success, message = owner_console_launch._start_launch(request)
        self.assertFalse(success)
        self.assertIn("iTerm2 is unavailable", message)
        command = run.call_args.args[0]
        self.assertEqual(command[0], "osascript")
        self.assertIn("exec claude 'Proceed with 001; echo nope'", command[2])
        self.assertIn("split horizontally with default profile", command[2])
        self.assertIn('if unique id of aSession is "12345678-1234-1234-1234-123456789abc"', command[2])
        self.assertIn("repeat with aSession in sessions of aTab", command[2])
        self.assertIn("tell newSession to write text", command[2])
        self.assertNotIn("w0t1p2", command[2])
        self.assertNotIn("create tab", command[2])
        self.assertNotIn("create window", command[2])

    @unittest.skipUnless(
        sys.platform == "darwin" and shutil.which("osacompile")
        and Path("/Applications/iTerm.app").exists(),
        "requires macOS osacompile and iTerm2",
    )
    def test_split_payload_compiles_as_applescript(self) -> None:
        usable, reason = _osacompile_can_resolve_iterm2_dictionary()
        if not usable:
            self.skipTest(
                "osacompile cannot resolve the iTerm2 dictionary in this environment: "
                f"{reason}",
            )
        payload = owner_console_launch._apple_script(
            "exec claude 'a \"q\" \\ b'", "12345678-1234-1234-1234-123456789abc",
        )
        with tempfile.TemporaryDirectory() as directory:
            result = _compile_applescript(payload, Path(directory) / "payload.scpt")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_iterm2_dictionary_probe_skips_or_preserves_payload_failure(self) -> None:
        success = mock.Mock(returncode=0, stderr="")
        dictionary_failure = mock.Mock(
            returncode=1, stderr="Expected \u201cthen\u201d but found property. (-2741)\n(-2740)",
        )
        payload_failure = mock.Mock(returncode=1, stderr="payload does not compile")

        with self.subTest("probe failure skips"):
            with mock.patch.object(subprocess, "run", return_value=dictionary_failure):
                usable, reason = _osacompile_can_resolve_iterm2_dictionary()
            self.assertFalse(usable)
            with self.assertRaisesRegex(
                unittest.SkipTest,
                "^osacompile cannot resolve the iTerm2 dictionary in this environment: .*\\(-2741\\)",
            ):
                if not usable:
                    self.skipTest(
                        "osacompile cannot resolve the iTerm2 dictionary in this environment: "
                        f"{reason}",
                    )

        with self.subTest("probe timeout skips"):
            with mock.patch.object(
                subprocess, "run", side_effect=subprocess.TimeoutExpired("osacompile", 30),
            ):
                usable, reason = _osacompile_can_resolve_iterm2_dictionary()
            self.assertFalse(usable)
            with self.assertRaisesRegex(
                unittest.SkipTest,
                "^osacompile cannot resolve the iTerm2 dictionary in this environment: timed out",
            ):
                if not usable:
                    self.skipTest(
                        "osacompile cannot resolve the iTerm2 dictionary in this environment: "
                        f"{reason}",
                    )

        with self.subTest("successful probe preserves payload failure"):
            with mock.patch.object(subprocess, "run", side_effect=(success, payload_failure)):
                usable, reason = _osacompile_can_resolve_iterm2_dictionary()
                self.assertTrue(usable, reason)
                result = _compile_applescript("invalid payload", Path("payload.scpt"))
            with self.assertRaisesRegex(AssertionError, "payload does not compile"):
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_unmatched_console_session_leaves_copy_as_fallback(self) -> None:
        request = owner_console_models.LaunchRequest(
            "codex", "Proceed with 001", Path("/project"), "001",
            "12345678-1234-1234-1234-123456789abc",
        )
        with mock.patch.object(owner_console_launch.sys, "platform", "darwin"), \
             mock.patch.object(owner_console_launch.shutil, "which", return_value="/usr/bin/tool"), \
             mock.patch.object(owner_console_launch.subprocess, "run") as run:
            run.return_value = mock.Mock(returncode=1, stderr="CARDINE_SESSION_NOT_FOUND", stdout="")
            success, message = owner_console_launch._start_launch(request)
        self.assertFalse(success)
        self.assertEqual(message, "iTerm2 console session was not found; [copy] remains available")

    def test_old_session_error_token_is_not_recognized(self) -> None:
        request = owner_console_models.LaunchRequest(
            "codex", "Proceed with 001", Path("/project"), "001",
            "12345678-1234-1234-1234-123456789abc",
        )
        with mock.patch.object(owner_console_launch.sys, "platform", "darwin"), \
             mock.patch.object(owner_console_launch.shutil, "which", return_value="/usr/bin/tool"), \
             mock.patch.object(owner_console_launch.subprocess, "run") as run:
            run.return_value = mock.Mock(returncode=1, stderr="MERIDIAN_SESSION_NOT_FOUND", stdout="")  # MERIDIAN-OLD-NAME-TEST
            success, message = owner_console_launch._start_launch(request)
        self.assertFalse(success)
        self.assertTrue(message.startswith("iTerm2 is unavailable or rejected launch:"))
        self.assertNotIn("session was not found", message)

    def test_start_revalidates_task_and_session_ids(self) -> None:
        request = owner_console_models.LaunchRequest("codex", "Proceed with 001", Path("/project"), "001; rm -rf /", "bad")
        with mock.patch.object(owner_console_launch.sys, "platform", "darwin"), \
             mock.patch.object(owner_console_launch.shutil, "which", return_value="/usr/bin/tool"):
            success, message = owner_console_launch._start_launch(request)
        self.assertFalse(success)
        self.assertIn("task ID", message)



if __name__ == "__main__":
    unittest.main()
