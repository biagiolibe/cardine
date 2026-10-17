"""Regression coverage for the package entry point's checkout selection."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class CardineCliTests(unittest.TestCase):
    def test_version_uses_checkout_despite_inherited_framework_root(self):
        with tempfile.TemporaryDirectory() as directory:
            other_root = Path(directory)
            (other_root / "VERSION").write_text("9.9.9\n", encoding="utf-8")
            environment = dict(os.environ, MERIDIAN_ROOT=str(other_root))
            environment["PYTHONPATH"] = str(ROOT / "src")
            result = subprocess.run(
                [sys.executable, "-m", "cardine.cli", "--version"],
                cwd=other_root,
                env=environment,
                capture_output=True,
                text=True,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), (ROOT / "VERSION").read_text().strip())
        self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
