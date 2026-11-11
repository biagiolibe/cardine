"""Bootstrap detection is read-only and follows its documented priority."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cardine.shared.project_defaults import detect_test, resolve_choices


class ProjectDefaultsTests(unittest.TestCase):
    def test_detection_sources(self):
        cases = [("Makefile", "test:\n", "make test"),
                 ("package.json", '{"scripts":{"test":"jest"}}', "npm test"),
                 ("pyproject.toml", "[tool.pytest.ini_options]\n", "python3 -m pytest"),
                 ("pytest.ini", "", "python3 -m pytest"),
                 ("setup.cfg", "[tool:pytest]\n", "python3 -m pytest"),
                 ("tox.ini", "[pytest]\n", "python3 -m pytest"),
                 ("conftest.py", "", "python3 -m pytest"),
                 ("test_example.py", "", "python3 -m unittest")]
        for filename, content, command in cases:
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / filename).write_text(content)
                with patch("subprocess.run", side_effect=AssertionError("subprocess")):
                    self.assertEqual((command, filename if filename != "test_example.py" else "test_*.py"), detect_test(root))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "tests").mkdir()
            self.assertEqual(("python3 -m unittest", "tests/"), detect_test(root))

    def test_placeholder_and_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "package.json").write_text('{"scripts":{"test":"echo \\"Error: no test specified\\" && exit 1"}}')
            self.assertEqual((None, None), detect_test(root))
            self.assertIsNone(resolve_choices(root)["validation"]["value"])

    def test_flags_override_defaults(self):
        choices = resolve_choices(Path("."), name="My Name", slug="custom", preset="governed",
                                  language="Italian", task_identity="milestone", test="check")
        self.assertTrue(all(choice["source"] == "flag" for choice in choices.values()))
        self.assertEqual("check", choices["validation"]["value"]["commands"]["test"])
