"""Row TR1a, rule 4: template and marker-baseline replacements converge after an interruption.

The shipped, rewritten templates are installed into a disposable project. A
marker-block replacement is killed immediately before and after every effect,
the identical command is run again, and the result must equal an uninterrupted
run with the project's own text intact. The marker-baseline writer is killed
around its single replace and must converge on a fresh generation.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cardine_cli_support import CLI, ROOT
import check_repository
from cardine.lifecycle import receipts
from synthetic_upgrade_support import SyntheticFramework

TEMPLATES = ROOT / "templates" / "single"
FILES = ("AGENTS.md", "CLAUDE.md", "PROJECT_WORKFLOW.md", "LANGUAGE_POLICY.md",
         "docs/CONTEXT_READING_POLICY.md", "docs/workflows/IMPLEMENTATION.md",
         "docs/workflows/REVIEW.md", "docs/workflows/REMEDIATION.md", "docs/LIFECYCLE_ORCHESTRATION.md",
         "tasks/TASK_BLUEPRINT.md", "docs/EXECUTION_EVIDENCE_PROFILE.md", ".codex/rules/meridian.rules",
         ".codex/hooks.json")
COMMANDS = "make test\n"
NOTES = "## Project notes\n\nKeep this paragraph.\n"
UPGRADE_CHILD = '''
import os, sys
sys.path.insert(0, sys.argv[1] + '/scripts')
import cardine_cli
from cardine.lifecycle import receipts
seam = sys.argv[2]
def boundary(name):
    if name == seam:
        os._exit(93)
receipts.boundary = boundary
sys.argv = ['cardine', *sys.argv[3:]]
raise SystemExit(cardine_cli.main())
'''
BASELINE_CHILD = '''
import os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1] + '/scripts')
import check_repository
mode, real = sys.argv[3], os.replace
def replace(source, destination):
    if mode == 'before':
        os._exit(93)
    real(source, destination)
    if mode == 'after':
        os._exit(93)
os.replace = replace
check_repository.write_marker_baselines(Path(sys.argv[2]))
'''


class TemplateReplacementTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        (self.base / "receipts").mkdir()
        patcher = patch.object(tempfile, "tempdir", str(self.base / "receipts"))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.framework = SyntheticFramework(self.base / "framework", "2.0.0", templates={
            path: (TEMPLATES / path).read_text(encoding="utf-8") for path in FILES})
        self.template = self.base / "template"
        self.template.mkdir()
        shutil.copytree(self.framework.root / "templates/single", self.template, dirs_exist_ok=True)
        locked = self.run_cli(self.template, "lock", "--mode", "single")
        self.assertEqual(locked.returncode, 0, locked.stdout + locked.stderr)
        claude = self.template / "CLAUDE.md"
        claude.write_text(claude.read_text(encoding="utf-8").replace(
            "# Fill in the project's run, test, lint, and format commands.\n", COMMANDS))
        workflow = self.template / "PROJECT_WORKFLOW.md"
        workflow.write_text(workflow.read_text(encoding="utf-8") + "\n" + NOTES)
        # The next release replaces the marker block of one file and bumps its version.
        self.framework.migration("001-synthetic-git-workflow", "2.1.0", capability="git-workflow", version=5,
                                 content="Replaced workflow rules.", paths=("PROJECT_WORKFLOW.md",), mode="single")

    def environment(self) -> dict[str, str]:
        return {**os.environ, "TMPDIR": str(self.base / "receipts"), "PYTHONPATH": str(ROOT / "src")}

    def run_cli(self, project: Path, *arguments: str, seam: str = "") -> subprocess.CompletedProcess[str]:
        command = [sys.executable, "-c", UPGRADE_CHILD, str(ROOT), seam] if seam else [sys.executable, str(CLI)]
        return subprocess.run([*command, "--framework-root", str(self.framework.root), *arguments, "--project", str(project)],
                              capture_output=True, text=True, env=self.environment(), timeout=60)

    def copy_project(self, name: str) -> Path:
        project = self.base / name
        shutil.copytree(self.template, project)
        (project / "foreign-work").write_text("preserve this")
        return project

    def tree(self, project: Path) -> dict[str, bytes]:
        return {path.relative_to(project).as_posix(): path.read_bytes().replace(str(project).encode(), b"<project>")
                for path in sorted(project.rglob("*")) if path.is_file()}

    def effects(self, project: Path) -> list[str]:
        return sorted(receipts._load_intent(receipts.operation_path(project.resolve(), "upgrade"))["effects"])

    def test_interrupted_block_replacement_converges_and_keeps_project_text(self) -> None:
        reference = self.copy_project("reference")
        self.assertEqual(self.run_cli(reference, "upgrade", "--apply").returncode, 0)
        expected = self.tree(reference)
        self.assertIn(b"Replaced workflow rules.", expected["PROJECT_WORKFLOW.md"])
        self.assertIn(COMMANDS.encode(), expected["CLAUDE.md"])
        self.assertIn(NOTES.encode(), expected["PROJECT_WORKFLOW.md"])
        names = self.effects(reference)
        self.assertIn("file:upgrade:PROJECT_WORKFLOW.md", names)
        for name in names:
            for when in ("before", "after"):
                with self.subTest(seam=f"{when}_{name}"):
                    project = self.copy_project("project")
                    self.assertEqual(self.run_cli(project, "upgrade", "--apply", seam=f"{when}_{name}").returncode, 93)
                    again = self.run_cli(project, "upgrade", "--apply")
                    self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
                    got = self.tree(project)
                    self.assertEqual(got.pop("foreign-work"), b"preserve this")
                    self.assertEqual(got, {key: value for key, value in expected.items() if key != "foreign-work"})
                    shutil.rmtree(project)

    def test_a_project_edit_made_after_an_interruption_is_not_overwritten(self) -> None:
        project = self.copy_project("project")
        self.assertEqual(self.run_cli(project, "upgrade", "--apply",
                                      seam="before_file:upgrade:PROJECT_WORKFLOW.md").returncode, 93)
        (project / "PROJECT_WORKFLOW.md").write_text("user edit made after the interruption\n")
        snapshot = self.tree(project)
        result = self.run_cli(project, "upgrade", "--apply")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.tree(project), snapshot)


class MarkerBaselineWriteTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        shutil.copytree(ROOT / "templates", self.root / "templates")
        shutil.copytree(ROOT / "capabilities", self.root / "capabilities")
        review = self.root / "templates/single/docs/workflows/REVIEW.md"
        review.write_text(review.read_text(encoding="utf-8").replace("Review in a fresh session", "Review in one fresh session"))
        self.path = self.root / "capabilities/marker-baselines.json"
        self.stale = self.path.read_bytes()

    def write(self, mode: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, "-c", BASELINE_CHILD, str(ROOT), str(self.root), mode],
                              capture_output=True, text=True, env={**os.environ, "PYTHONPATH": str(ROOT / "src")}, timeout=60)

    def fresh(self) -> bytes:
        self.assertEqual(self.write("never").returncode, 0)
        return self.path.read_bytes()

    def test_killing_the_writer_around_its_replace_converges_on_a_fresh_generation(self) -> None:
        expected = self.fresh()
        self.assertNotEqual(expected, self.stale)
        self.path.write_bytes(self.stale)
        for when in ("before", "after"):
            with self.subTest(when=when):
                self.path.write_bytes(self.stale)
                self.assertEqual(self.write(when).returncode, 93)
                # The previous baseline is whole or the new one is complete: never a partial file.
                self.assertIn(self.path.read_bytes(), (self.stale, expected))
                self.assertEqual(self.write("never").returncode, 0)
                self.assertEqual(self.path.read_bytes(), expected)
                self.assertFalse(self.path.with_name(self.path.name + ".tmp").exists())

    def test_the_output_after_an_interruption_passes_the_baseline_check_a_stale_one_fails(self) -> None:
        with self.assertRaises(SystemExit):
            check_repository.check_capability_marker_baselines(self.root)
        for when in ("before", "after"):
            with self.subTest(when=when):
                self.path.write_bytes(self.stale)
                self.assertEqual(self.write(when).returncode, 93)
                self.assertEqual(self.write("never").returncode, 0)
                check_repository.check_capability_marker_baselines(self.root)

    def test_repeating_the_writer_is_byte_identical(self) -> None:
        first = self.fresh()
        self.assertEqual(self.write("never").returncode, 0)
        self.assertEqual(self.path.read_bytes(), first)


if __name__ == "__main__":
    unittest.main()
