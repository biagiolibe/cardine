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
    def test_error_class_has_no_old_name_alias(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        import cardine_cli
        from cardine import cli
        from cardine.shared import errors

        self.assertIs(cardine_cli.CardineError, errors.CardineError)
        self.assertTrue(issubclass(errors.CardineError, RuntimeError))
        for module in (errors, cli, cardine_cli):
            with self.subTest(module=module.__name__):
                self.assertFalse(hasattr(module, "MeridianError"))  # MERIDIAN-OLD-NAME-TEST

    def test_stop_class_has_no_old_name_alias(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        import cardine_cli
        from cardine import cli
        from cardine.shared import errors

        self.assertIs(cardine_cli.CardineStop, errors.CardineStop)
        self.assertTrue(issubclass(errors.CardineStop, errors.CardineError))
        for module in (errors, cli, cardine_cli):
            with self.subTest(module=module.__name__):
                self.assertFalse(hasattr(module, "MeridianStop"))  # MERIDIAN-OLD-NAME-TEST

    def test_parser_class_has_no_old_name_alias(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        import cardine_cli
        from cardine import cli

        self.assertIs(cardine_cli.CardineArgumentParser, cli.CardineArgumentParser)
        self.assertIs(type(cli.build_parser()), cli.CardineArgumentParser)
        for module in (cli, cardine_cli):
            with self.subTest(module=module.__name__):
                self.assertFalse(hasattr(module, "MeridianArgumentParser"))  # MERIDIAN-OLD-NAME-TEST

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
                "import cardine_cli; raise SystemExit(cardine_cli.main())"
            )
            entries = [
                [sys.executable, str(ROOT / "bin/cardine")],
                [sys.executable, str(ROOT / "scripts/cardine_cli.py")],
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
                    (["adopt"], 2), (["finalize-adoption"], 2),
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
        import cardine_cli
        from cardine import cli
        from cardine.shared import models
        from cardine.templates import upgrade

        self.assertIs(cardine_cli.main, cli.main)
        self.assertIs(cardine_cli.CardineArgumentParser, cli.CardineArgumentParser)
        self.assertIs(cardine_cli.ManagedFile, models.ManagedFile)
        self.assertIs(cardine_cli.PlanItem, models.PlanItem)
        self.assertIs(cardine_cli.apply_plan, upgrade.apply_plan)
        self.assertLess(len((ROOT / "scripts/cardine_cli.py").read_text().splitlines()), 100)


if __name__ == "__main__":
    unittest.main()
