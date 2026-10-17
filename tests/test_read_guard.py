"""Regression tests for hooks/read-guard.sh (task 035): mechanical
enforcement of the file-read discipline docs/CONTEXT_BUDGET_POLICY.md
already states in prose -- a `Read` of a large file with no `offset`/`limit`
is denied unless the file is exempt or the project isn't a Meridian one.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "hooks" / "read-guard.sh"

GOVERNED_HEADER = (
    "| Order | ID | Priority | Status | Dependencies |\n|---:|---|---|---|---|\n"
)


def run_hook(payload: dict) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
    )


class ReadGuardTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.project = Path(self.temporary.name)
        (self.project / "tasks").mkdir()
        (self.project / "PROJECT_WORKFLOW.md").write_text(
            "<!-- MERIDIAN:BEGIN capability=execution-assets v1 -->\n<!-- MERIDIAN:END -->\n"
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
        self.assertIn("meridian context authority", result.stderr)
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
        result = run_hook(self.payload(target))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_allows_the_active_tasks_own_file_over_the_threshold(self) -> None:
        (self.project / "tasks/QUEUE.md").write_text(
            GOVERNED_HEADER + "| 1 | TASK-002 | P0 | IN_PROGRESS | — |\n", encoding="utf-8"
        )
        target = self.write_file("tasks/TASK-002.md", 500)
        result = run_hook(self.payload(target))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_allows_language_policy_over_the_threshold(self) -> None:
        target = self.write_file("LANGUAGE_POLICY.md", 500)
        result = run_hook(self.payload(target))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_allows_a_file_an_entry_router_declares_always_loaded(self) -> None:
        target = self.write_file("AGENTS.md", 500)
        router = self.project / "docs/workflows/ENTRY_ROUTER.md"
        router.parent.mkdir(parents=True)
        router.write_text("`AGENTS.md` and `CLAUDE.md` are always loaded at session start.\n", encoding="utf-8")
        result = run_hook(self.payload(target))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_honors_a_configured_threshold(self) -> None:
        target = self.write_file("big.txt", 500)
        (self.project / "docs").mkdir()
        (self.project / "docs/EXECUTION_EVIDENCE_PROFILE.md").write_text(
            "`Read-guard threshold`: 1000 lines, overridable per project.\n", encoding="utf-8"
        )
        result = run_hook(self.payload(target))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_router_file_uses_its_own_ceiling(self) -> None:
        target = self.write_file("PROJECT_WORKFLOW.md", 500)
        target.write_text("LEAN_DELIVERY\n" * 500, encoding="utf-8")
        (self.project / ".meridian").mkdir()
        (self.project / ".meridian/context-size.json").write_text(
            '{"version": 1, "routerFileLinesCeiling": 100}\n', encoding="utf-8"
        )
        result = run_hook(self.payload(target))
        self.assertEqual(result.returncode, 2)
        self.assertIn("Shrink the file", result.stderr)

    def test_inactive_outside_a_meridian_project(self) -> None:
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
        result = subprocess.run(
            ["bash", str(HOOK)], input="not json", capture_output=True, text=True, check=False,
            cwd=str(self.project),
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_ignores_a_non_read_tool_call(self) -> None:
        target = self.write_file("big.txt", 500)
        payload = {"tool_name": "Write", "tool_input": {"file_path": str(target)}, "cwd": str(self.project)}
        result = run_hook(payload)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
