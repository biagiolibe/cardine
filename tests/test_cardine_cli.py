"""Regression coverage for package and compatibility entry-point parity."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[1]


class CardineCliTests(unittest.TestCase):
    def test_version_uses_checkout_without_inherited_framework_root(self):
        environment = {key: value for key, value in os.environ.items() if key != "MERIDIAN_ROOT"}
        environment["PYTHONPATH"] = str(ROOT / "src")
        result = subprocess.run(
            [sys.executable, "-m", "cardine.cli", "--version"],
            cwd=tempfile.gettempdir(), env=environment, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), (ROOT / "VERSION").read_text().strip())
        self.assertEqual(result.stderr, "")

    def test_all_entry_points_preserve_arguments_output_and_exit_codes(self):
        with tempfile.TemporaryDirectory() as directory:
            other_root = Path(directory)
            (other_root / "VERSION").write_text("9.9.9\n", encoding="utf-8")
            # Build the console wrapper from the actual packaging declaration,
            # without requiring an installed editable package in clean clones.
            target = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["scripts"]["cardine"]
            module, function = target.split(":")
            command = other_root / "cardine"
            command.write_text(f"import sys\nfrom {module} import {function}\nsys.exit({function}())\n", encoding="utf-8")
            imported = (
                "import sys; "
                f"sys.path.insert(0, {str(ROOT / 'scripts')!r}); "
                "import meridian; raise SystemExit(meridian.main())"
            )
            entries = [
                [sys.executable, str(ROOT / "bin/meridian")],
                [sys.executable, str(ROOT / "scripts/meridian.py")],
                [sys.executable, "-c", imported],
                [sys.executable, str(command)],
                [sys.executable, "-m", "cardine.cli"],
            ]
            for inherited in (False, True):
                environment = {key: value for key, value in os.environ.items() if key != "MERIDIAN_ROOT"}
                environment["PYTHONPATH"] = str(ROOT / "src")
                if inherited:
                    environment["MERIDIAN_ROOT"] = str(other_root)
                for arguments, code in [
                    (["--version"], 0), (["--help"], 0), (["--unknown"], 2),
                    (["worktree", "--unknown"], 64),
                    (["--framework-root", str(ROOT), "--version"], 0),
                ]:
                    results = []
                    for entry in entries:
                        with self.subTest(entry=entry, inherited=inherited, arguments=arguments):
                            result = subprocess.run(
                                [*entry, *arguments], cwd=other_root, env=environment,
                                capture_output=True, text=True,
                            )
                            self.assertEqual(result.returncode, code, result.stderr)
                            results.append((result.returncode, result.stdout, result.stderr))
                    self.assertTrue(all(result == results[0] for result in results), results)
                    if arguments == ["--version"]:
                        expected = "9.9.9" if inherited else (ROOT / "VERSION").read_text().strip()
                        self.assertEqual(results[0][1], expected + "\n")
                    if arguments[0] == "--framework-root":
                        self.assertEqual(results[0][1], (ROOT / "VERSION").read_text())

    def test_legacy_imports_preserve_owner_and_class_identities(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        import meridian
        from cardine import cli
        from cardine.shared import models
        from cardine.templates import adopt_command, upgrade

        self.assertIs(meridian.main, cli.main)
        self.assertIs(meridian.MeridianArgumentParser, cli.MeridianArgumentParser)
        self.assertIs(meridian.ManagedFile, models.ManagedFile)
        self.assertIs(meridian.PlanItem, models.PlanItem)
        self.assertIs(meridian.apply_plan, upgrade.apply_plan)
        self.assertIs(meridian.adopt_project, adopt_command.adopt_project)
        self.assertLess(len((ROOT / "scripts/meridian.py").read_text().splitlines()), 100)


if __name__ == "__main__":
    unittest.main()
