"""Regression coverage for the shared CLI installation and Python guard."""

import ast
from importlib.machinery import PathFinder
import tomllib
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CliInstallTest(unittest.TestCase):
    def test_renamed_executables_have_no_old_aliases(self):
        # MERIDIAN-OLD-NAME-TEST
        for old in ("bin/meridian", "scripts/meridian.py"):
            with self.subTest(path=old):
                self.assertFalse((ROOT / old).exists())  # MERIDIAN-OLD-NAME-TEST
                result = subprocess.run(
                    [sys.executable, str(ROOT / old), "--version"],
                    text=True, capture_output=True, check=False,
                )
                self.assertEqual(result.returncode, 2)  # MERIDIAN-OLD-NAME-TEST
                self.assertEqual(result.stdout, "")
        self.assertFalse((ROOT / "scripts/cardine.py").exists())
        scripts = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["scripts"]
        self.assertEqual(scripts, {"cardine": "cardine.cli:main"})  # MERIDIAN-OLD-NAME-TEST

    def test_renamed_modules_have_no_old_aliases(self):
        names = {
            # MERIDIAN-OLD-NAME-TEST
            "scripts": ["meridian"],
            # MERIDIAN-OLD-NAME-TEST
            "tests": ["meridian_cli_support", *(
                # MERIDIAN-OLD-NAME-TEST
                "test_meridian_" + suffix for suffix in (
                    "adoption_audit", "cli_entry", "manifest_protocol",
                    "migration_retirement", "upgrade_lifecycle", "upgrade_merge",
                )
            )],
        }
        for directory, modules in names.items():
            for name in modules:
                with self.subTest(module=name):
                    self.assertIsNone(PathFinder.find_spec(name, [str(ROOT / directory)]))  # MERIDIAN-OLD-NAME-TEST
        sys.path.insert(0, str(ROOT / "tests"))
        import cardine_cli_support
        self.assertTrue(hasattr(cardine_cli_support, "CardineCliFixtureMixin"))
        self.assertFalse(hasattr(cardine_cli_support, "MeridianCliFixtureMixin"))  # MERIDIAN-OLD-NAME-TEST
        self.assertFalse(hasattr(cardine_cli_support, "MeridianCliTest"))  # MERIDIAN-OLD-NAME-TEST

    def test_checkout_cli_has_no_host_allow_rules(self):
        sys.path.insert(0, str(ROOT / "src"))
        from cardine.hosts.claude import CLAUDE_PROJECT_ALLOWLIST
        local = (ROOT / ".codex/rules/local.rules").read_text()
        # MERIDIAN-OLD-NAME-TEST
        for old in ("scripts/meridian.py", "scripts/cardine_cli.py"):
            self.assertNotIn(old, local)  # MERIDIAN-OLD-NAME-TEST
            self.assertFalse(any(old in rule for rule in CLAUDE_PROJECT_ALLOWLIST))  # MERIDIAN-OLD-NAME-TEST
        # MERIDIAN-INSTALLATION-CHECK
        self.assertIn('pattern=["meridian", "worktree", ["evidence", "closure-status", "advance"]', local)

    def test_old_python_exits_before_loading_cli(self):
        wrapper = ROOT / "bin/cardine"
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
            [sys.executable, str(ROOT / "bin/cardine"), "--version"],
            env={key: value for key, value in os.environ.items() if key != "CARDINE_ROOT"},
            text=True, capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn((ROOT / "VERSION").read_text().strip(), result.stdout)
