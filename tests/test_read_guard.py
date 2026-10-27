"""Regression tests for hooks/read-guard.sh (task 035): mechanical
enforcement of the file-read discipline docs/CONTEXT_BUDGET_POLICY.md
already states in prose -- a `Read` of a large file with no `offset`/`limit`
is denied unless the file is exempt or the project isn't a Cardine one.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from project_config_support import write_project_config
from task_contract_support import freeze_record
from installation_fixture import copy_hook, hook_environment

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "hooks" / "read-guard.sh"  # MERIDIAN-INSTALLATION-CHECK

GOVERNED_HEADER = (
    "| Order | ID | Priority | Status | Dependencies |\n|---:|---|---|---|---|\n"
)


def run_hook(payload: dict | str) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory() as directory:
        # MERIDIAN-INSTALLATION-CHECK
        hook = copy_hook(Path(directory), "read-guard.sh")
        return subprocess.run(
            ["bash", str(hook)], input=payload if isinstance(payload, str) else json.dumps(payload),
            capture_output=True, text=True, check=False, env=hook_environment(),
        )


class ReadGuardTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.project = Path(self.temporary.name)
        home = self.project / "home"
        home.mkdir()
        environment = patch.dict(os.environ, HOME=str(home), XDG_CONFIG_HOME=str(home / ".config"))
        environment.start()
        self.addCleanup(environment.stop)
        (self.project / "tasks").mkdir()
        # MERIDIAN-INSTALLATION-CHECK
        (self.project / "PROJECT_WORKFLOW.md").write_text(
            "<!-- CARDINE:BEGIN capability=execution-assets v1 -->\n<!-- CARDINE:END -->\n"
            "Task files live under `tasks/`; queue is `tasks/QUEUE.md`.\n\n## Roles\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_file(self, path: str, lines: int) -> Path:
        target = self.project / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("\n".join(f"line {n}" for n in range(1, lines + 1)) + "\n", encoding="utf-8")
        return target

    def payload(self, file_path: Path, **tool_input: object) -> dict:
        return {
            "tool_name": "Read",
            "tool_input": {"file_path": str(file_path), **tool_input},
            "cwd": str(self.project),
        }

    def test_allows_a_file_under_the_threshold(self) -> None:
        target = self.write_file("small.txt", 50)
        result = run_hook(self.payload(target))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_denies_an_unranged_read_over_the_threshold(self) -> None:
        target = self.write_file("big.txt", 500)
        result = run_hook(self.payload(target))
        self.assertEqual(result.returncode, 2)
        self.assertIn("500", result.stderr)
        self.assertIn("400", result.stderr)
        self.assertIn("grep -n", result.stderr)
        # MERIDIAN-INSTALLATION-CHECK
        self.assertIn("meridian context authority", result.stderr)
        # MERIDIAN-INSTALLATION-CHECK
        self.assertIn("meridian adr show", result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_allows_a_ranged_read_over_the_threshold(self) -> None:
        target = self.write_file("big.txt", 500)
        result = run_hook(self.payload(target, offset=1, limit=50))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_allows_an_exempted_file_over_the_threshold_via_authority(self) -> None:
        target = self.write_file("big.txt", 500)
        (self.project / "tasks/QUEUE.md").write_text(
            GOVERNED_HEADER + "| 1 | TASK-001 | P0 | IN_PROGRESS | — |\n", encoding="utf-8"
        )
        (self.project / "tasks/TASK-001.md").write_text(
            "Status: IN_PROGRESS\n\n## Authority\n\n- `big.txt` — the fixture under test.\n\n"
            "## Expected code surface\n",
            encoding="utf-8",
        )
        freeze_record(self.project, "TASK-001")
        result = run_hook(self.payload(target))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_allows_the_active_tasks_own_file_over_the_threshold(self) -> None:
        write_project_config(self.project)
        (self.project / "tasks/QUEUE.md").write_text(
            GOVERNED_HEADER + "| 1 | TASK-002 | P0 | IN_PROGRESS | — |\n", encoding="utf-8"
        )
        target = self.write_file("tasks/TASK-002.md", 500)
        result = run_hook(self.payload(target))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_allows_language_policy_over_the_threshold(self) -> None:
        # MERIDIAN-INSTALLATION-CHECK
        target = self.write_file("LANGUAGE_POLICY.md", 500)
        result = run_hook(self.payload(target))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_allows_a_file_an_entry_router_declares_always_loaded(self) -> None:
        # MERIDIAN-INSTALLATION-CHECK
        target = self.write_file("AGENTS.md", 500)
        router = self.project / "docs/workflows/ENTRY_ROUTER.md"
        router.parent.mkdir(parents=True)
        # MERIDIAN-INSTALLATION-CHECK
        router.write_text("`AGENTS.md` and `CLAUDE.md` are always loaded at session start.\n", encoding="utf-8")
        result = run_hook(self.payload(target))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_honors_a_configured_threshold(self) -> None:
        target = self.write_file("big.txt", 500)
        (self.project / "docs").mkdir()
        # MERIDIAN-INSTALLATION-CHECK
        (self.project / "docs/EXECUTION_EVIDENCE_PROFILE.md").write_text(
            "`Read-guard threshold`: 1000 lines, overridable per project.\n", encoding="utf-8"
        )
        result = run_hook(self.payload(target))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_router_file_uses_its_own_ceiling(self) -> None:
        # MERIDIAN-INSTALLATION-CHECK
        target = self.write_file("PROJECT_WORKFLOW.md", 500)
        target.write_text("LEAN_DELIVERY\n" * 500, encoding="utf-8")
        write_project_config(self.project)
        # MERIDIAN-INSTALLATION-CHECK
        (self.project / ".cardine").mkdir(exist_ok=True)
        # MERIDIAN-INSTALLATION-CHECK
        (self.project / ".cardine/context-size.json").write_text(
            '{"version": 1, "routerFileLinesCeiling": 100}\n', encoding="utf-8"
        )
        result = run_hook(self.payload(target))
        self.assertEqual(result.returncode, 2)
        self.assertIn("Shrink the file", result.stderr)

    def test_inactive_outside_a_cardine_project(self) -> None:
        outside = Path(self.temporary.name) / "not-a-project"
        outside.mkdir()
        target = outside / "big.txt"
        target.write_text("\n".join(f"line {n}" for n in range(1, 501)) + "\n", encoding="utf-8")
        result = run_hook(
            {"tool_name": "Read", "tool_input": {"file_path": str(target)}, "cwd": str(outside)}
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_allows_when_the_target_file_does_not_exist(self) -> None:
        result = run_hook(self.payload(self.project / "missing.txt"))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_allows_on_malformed_payload(self) -> None:
        result = run_hook("not json")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_ignores_a_non_read_tool_call(self) -> None:
        target = self.write_file("big.txt", 500)
        payload = {"tool_name": "Write", "tool_input": {"file_path": str(target)}, "cwd": str(self.project)}
        result = run_hook(payload)
        self.assertEqual(result.returncode, 0, result.stderr)


class PythonReadGuardTest(unittest.TestCase):
    """Exercise the product entry point in disposable host homes."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.home = self.root / "home"
        self.home.mkdir()
        (self.project / "PROJECT_WORKFLOW.md").write_text("LEAN_DELIVERY\n", encoding="utf-8")
        self.target = self.project / "big.txt"
        self.target.write_text("line\n" * 500, encoding="utf-8")

    def invoke(self, payload: object) -> subprocess.CompletedProcess[str]:
        environment = hook_environment()
        environment.update(HOME=str(self.home), XDG_CONFIG_HOME=str(self.home / ".config"))
        return subprocess.run(
            [sys.executable, str(ROOT / "scripts/cardine_cli.py"), "hook", "read-guard", "--host", "claude"],
            input=json.dumps(payload), text=True, capture_output=True, check=False, env=environment,
        )

    def payload(self, **ranges: object) -> dict:
        return {"hook_event_name": "PreToolUse", "tool_name": "Read", "cwd": str(self.project),
                "tool_input": {"file_path": str(self.target), **ranges}}

    def test_native_ranges_and_external_files(self) -> None:
        for ranges, expected in [({}, 2), ({"offset": 1, "limit": 50}, 0),
                                 ({"offset": 450}, 0), ({"limit": 401}, 2),
                                 ({"offset": 900, "limit": 500}, 0)]:
            with self.subTest(ranges=ranges):
                self.assertEqual(self.invoke(self.payload(**ranges)).returncode, expected)
        self.target = self.root / "external.txt"
        self.target.write_text("line\n" * 500, encoding="utf-8")
        result = self.invoke(self.payload())
        self.assertEqual(result.returncode, 2)
        self.assertIn(str(self.target), result.stderr)
        self.assertEqual(json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_malformed_and_irrelevant_payloads_do_not_deny(self) -> None:
        for payload in [None, [], {}, self.payload(offset="bad"), self.payload(limit=-1),
                        self.payload(offset=True), {**self.payload(), "tool_name": "Write"}]:
            with self.subTest(payload=payload):
                result = self.invoke(payload)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, "")

    def test_repeated_checks_do_not_write(self) -> None:
        def snapshot() -> dict:
            return {str(path.relative_to(self.root)): (path.read_bytes(), path.stat().st_mtime_ns)
                    for path in self.root.rglob("*") if path.is_file()}
        before = snapshot()
        first = self.invoke(self.payload())
        second = self.invoke(self.payload())
        self.assertEqual(first.returncode, 2)
        self.assertEqual((first.stdout, first.stderr), (second.stdout, second.stderr))
        self.assertEqual(snapshot(), before)

    def test_configured_threshold_and_router_ceiling_are_shared(self) -> None:
        docs = self.project / "docs"
        docs.mkdir()
        # MERIDIAN-INSTALLATION-CHECK: project-owned frozen profile filename.
        (docs / "EXECUTION_EVIDENCE_PROFILE.md").write_text(
            "`Read-guard threshold`: 600\n", encoding="utf-8")
        self.assertEqual(self.invoke(self.payload()).returncode, 0)
        write_project_config(self.project)
        # MERIDIAN-INSTALLATION-CHECK: synthetic project settings.
        (self.project / ".cardine/context-size.json").write_text(
            '{"version": 1, "routerFileLinesCeiling": 100}\n', encoding="utf-8")
        self.target = self.project / "PROJECT_WORKFLOW.md"
        self.target.write_text("LEAN_DELIVERY\n" * 500, encoding="utf-8")
        result = self.invoke(self.payload(offset=1, limit=10))
        self.assertEqual(result.returncode, 2)
        self.assertIn("Shrink the file", result.stderr)

    def test_native_and_shell_share_threshold_and_exemptions(self) -> None:
        from cardine.hosts.read_guard import decision
        for name in ["big.txt", "LANGUAGE_POLICY.md", "PROJECT_WORKFLOW.md"]:
            target = self.project / name
            target.write_text("LEAN_DELIVERY\n" * 500, encoding="utf-8")
            native = self.payload()
            native["tool_input"]["file_path"] = str(target)
            shell = {"tool_name": "Bash", "cwd": str(self.project),
                     "tool_input": {"command": f"cat {target}"}}
            self.assertEqual(decision(native, "claude")[0], decision(shell)[0])


if __name__ == "__main__":
    unittest.main()
