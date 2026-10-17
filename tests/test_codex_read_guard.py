"""Decision-table tests for the Codex Bash read guard (task 041)."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from codex_read_guard import decision, extract_targets  # noqa: E402
import meridian  # noqa: E402


class CodexReadGuardTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.project = Path(self.temporary.name)
        self.external = tempfile.TemporaryDirectory()
        (self.project / "tasks").mkdir()
        (self.project / "PROJECT_WORKFLOW.md").write_text("workflow\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()
        self.external.cleanup()

    def write(self, name: str, lines: int) -> None:
        target = self.project / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("\n".join(str(number) for number in range(lines)) + "\n", encoding="utf-8")

    def payload(self, command: str) -> dict:
        return {"tool_name": "Bash", "cwd": str(self.project), "tool_input": {"command": command}}

    def test_decision_table(self) -> None:
        self.write("one.txt", 500)
        self.write("two.txt", 500)
        cases = {
            "sed -n '1,50p' one.txt": True,
            "sed -n '1,240p' one.txt && sed -n '1,240p' two.txt": False,
            "cat one.txt": False,
            "rg needle one.txt": True,
            "python -c 'print(open(\"one.txt\").read())'": True,
            "nl one.txt | sed -n '1,401p'": False,
            "head -n 401 one.txt": False,
            "tail -400 one.txt": True,
        }
        for command, allowed in cases.items():
            with self.subTest(command=command):
                self.assertEqual(decision(self.payload(command))[0], allowed)

    def test_clamps_ranges_and_ignores_small_files(self) -> None:
        self.write("big.txt", 500)
        self.write("small.txt", 50)
        self.assertFalse(decision(self.payload("sed -n '1,999p' big.txt"))[0])
        self.assertTrue(decision(self.payload("cat small.txt"))[0])

    def test_external_absolute_large_file_denies(self) -> None:
        target = Path(self.external.name) / "external-big.txt"
        target.write_text("x\n" * 500, encoding="utf-8")
        allowed, reason = decision(self.payload(f"cat {target}"))
        self.assertFalse(allowed)
        self.assertIn(f"{target} (500 lines)", reason or "")

    def test_exempt_and_non_meridian_cwds_allow(self) -> None:
        self.write("LANGUAGE_POLICY.md", 500)
        self.assertTrue(decision(self.payload("cat LANGUAGE_POLICY.md"))[0])
        payload = self.payload("cat LANGUAGE_POLICY.md")
        payload["cwd"] = str(self.project / "outside")
        self.assertTrue(decision(payload)[0])

    def test_router_files_are_exempt_only_up_to_the_declared_ceiling(self) -> None:
        (self.project / "PROJECT_WORKFLOW.md").write_text("LEAN_DELIVERY\n" * 500, encoding="utf-8")
        self.assertTrue(decision(self.payload("cat PROJECT_WORKFLOW.md"))[0])
        (self.project / ".meridian").mkdir()
        (self.project / ".meridian/context-size.json").write_text(
            '{"version": 1, "routerFileLinesCeiling": 100}\n', encoding="utf-8"
        )
        allowed, reason = decision(self.payload("cat PROJECT_WORKFLOW.md"))
        self.assertFalse(allowed)
        self.assertIn("Shrink the file", reason or "")

    def test_malformed_input_allows(self) -> None:
        self.assertTrue(decision({})[0])
        self.assertTrue(decision({"tool_name": "Bash", "cwd": str(self.project), "tool_input": {}})[0])

    def test_recorded_payload_fixtures_are_bash_shapes(self) -> None:
        fixtures = ROOT / "tests/fixtures/codex_hook_payloads"
        for path in fixtures.glob("*.json"):
            payload = json.loads(path.read_text(encoding="utf-8"))
            with self.subTest(path=path.name):
                self.assertEqual(payload["hook_event_name"], "PreToolUse")
                self.assertEqual(payload["tool_name"], "Bash")
                self.assertIsInstance(payload["tool_input"]["command"], str)

    def test_cli_emits_stderr_and_structured_denial(self) -> None:
        self.write("big.txt", 500)
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts/meridian.py"), "hook", "read-guard", "--host", "codex"],
            input=json.dumps(self.payload("cat big.txt")), text=True, capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("Blocked: shell read", result.stderr)
        self.assertEqual(json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_distribution_registers_the_verified_project_hook(self) -> None:
        hook_path = ROOT / "templates/workflows/governed-sdd/.codex/hooks.json"
        hook = json.loads(hook_path.read_text(encoding="utf-8"))
        entry = hook["hooks"]["PreToolUse"][0]
        self.assertEqual(entry["matcher"], "Bash")
        self.assertEqual(entry["hooks"][0]["command"], "meridian hook read-guard --host codex")
        managed = {str(item.source.relative_to(ROOT / "templates/workflows/governed-sdd"))
                   for item in meridian.managed_files(ROOT, "governed-sdd")}
        self.assertIn(".codex/hooks.json", managed)


if __name__ == "__main__":
    unittest.main()
