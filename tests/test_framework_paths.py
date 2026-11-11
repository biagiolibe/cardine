"""Exercise framework asset resolution across installation layouts."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cardine.shared import paths
from cardine.shared.errors import CardineError


class FrameworkPathsTest(unittest.TestCase):
    def test_precedence_and_fallbacks(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ):
            checkout = Path(temporary).resolve()
            package = checkout / "src/cardine"
            bundled = package / "_framework"
            bundled.mkdir(parents=True)
            (checkout / "VERSION").touch()
            (bundled / "VERSION").touch()
            override = checkout / "override"
            override.mkdir()
            with patch.object(paths, "PACKAGE_ROOT", package):
                os.environ["CARDINE_ROOT"] = str(override)
                self.assertEqual(paths.framework_root(), override)

                os.environ["CARDINE_ROOT"] = str(checkout / "absent")
                self.assertEqual(paths.framework_root(), bundled)

                os.environ.pop("CARDINE_ROOT")
                self.assertEqual(paths.framework_root(), bundled)

                (bundled / "VERSION").unlink()
                self.assertEqual(paths.framework_root(), checkout)

                (checkout / "VERSION").unlink()
                with self.assertRaises(CardineError):
                    paths.framework_root()

    def test_wheel_does_not_require_a_source_checkout(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ):
            package = Path(temporary).resolve() / "site-packages/cardine"
            bundled = package / "_framework"
            bundled.mkdir(parents=True)
            (bundled / "VERSION").touch()
            os.environ.pop("CARDINE_ROOT", None)
            with patch.object(paths, "PACKAGE_ROOT", package):
                self.assertIsNone(paths.source_checkout())
                self.assertEqual(paths.framework_root(), bundled)
