"""Regression coverage for the shared CLI installation and Python guard."""

import ast
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CliInstallTest(unittest.TestCase):
    def test_quickstart_installs_one_canonical_checkout_before_host_steps(self):
        quickstart = (ROOT / "docs/QUICKSTART.md").read_text(encoding="utf-8")
        clone = "git clone --branch stable https://github.com/biagiolibe/meridian ~/.local/share/meridian"
        self.assertEqual(quickstart.count(clone), 1)
        for heading in ("## Connect Claude Code", "## Connect Codex"):
            self.assertLess(quickstart.index(clone), quickstart.index(heading))
        for check in (
            'export MERIDIAN_ROOT="$HOME/.local/share/meridian"',
            'export PATH="$MERIDIAN_ROOT/bin:$PATH"',
            "command -v meridian",
            "meridian --version",
            'cat "$MERIDIAN_ROOT/VERSION"',
            'git -C "$MERIDIAN_ROOT" describe --tags --exact-match',
            "zsh -lc 'command -v meridian'",
            "zsh -lc 'python3 --version'",
            "~/.zshenv",
            "~/.bashrc",
        ):
            self.assertIn(check, quickstart)
        for name in ("README.md", "docs/QUICKSTART.md", "docs/HOW_TO_UPGRADE.md"):
            document = (ROOT / name).read_text(encoding="utf-8")
            self.assertNotIn("~/meridian", document)
            self.assertIn("~/.local/share/meridian", document)

    def test_old_python_exits_before_loading_cli(self):
        wrapper = ROOT / "bin/meridian"
        ast.parse(wrapper.read_text(encoding="utf-8"), feature_version=(3, 9))
        for version in ((3, 9, 6), (3, 11, 9)):
            with self.subTest(version=version):
                probe = (
                    "import runpy, sys; "
                    "wrapper = sys.argv[1]; "
                    f"sys.version_info = {version!r}; "
                    "runpy.run_path(wrapper, run_name='__main__')"
                )
                result = subprocess.run(
                    [sys.executable, "-c", probe, str(wrapper)],
                    text=True, capture_output=True, check=False,
                )
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, "")
                self.assertIn("requires Python 3.12", result.stderr)
                self.assertIn(".".join(map(str, version)), result.stderr)
                self.assertIn(sys.executable, result.stderr)
                self.assertIn("docs/QUICKSTART.md#prerequisites", result.stderr)
                self.assertNotIn("Traceback", result.stderr)

    def test_supported_python_runs_cli(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "bin/meridian"), "--version"],
            env={key: value for key, value in os.environ.items() if key != "MERIDIAN_ROOT"},
            text=True, capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn((ROOT / "VERSION").read_text().strip(), result.stdout)
