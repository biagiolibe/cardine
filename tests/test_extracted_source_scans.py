"""Stop scans must include package implementations after every extraction."""

import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import check_repository as checker  # noqa: E402


class ExtractedSourceScanTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "capabilities").mkdir()
        (self.root / "capabilities/stop-codes-v1.json").write_text(json.dumps({
            "version": 1, "stops": [{"code": "EXTRACTED_STOP", "class": "judgment"}],
        }))
        self.source = self.root / "src/cardine/shared/example.py"
        self.source.parent.mkdir(parents=True)

    def failure(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit):
            checker.check_stop_code_registry(self.root)
        return output.getvalue()

    def test_registered_mention_in_an_extracted_module_is_live(self):
        self.source.write_text('report("C1", "EXTRACTED_STOP")\n')
        checker.check_stop_code_registry(self.root)

    def test_unregistered_stop_in_an_extracted_module_is_rejected(self):
        self.source.write_text('raise Error("UNKNOWN_STOP", "EXTRACTED_STOP")\n')
        self.assertIn("src/cardine/shared/example.py:1: unregistered stop code UNKNOWN_STOP", self.failure())

    def test_console_readiness_label_is_not_an_uncoded_stop(self):
        self.source.write_text('report("C1", "EXTRACTED_STOP")\n')
        console = self.root / "src/cardine/console/example.py"
        console.parent.mkdir(parents=True)
        console.write_text('readiness = "BLOCKED: " + detail\n')
        checker.check_stop_code_registry(self.root)

    def test_uncoded_stop_in_an_extracted_module_is_rejected(self):
        self.source.write_text('raise Error("BLOCKED: detail")\n')
        self.assertIn("src/cardine/shared/example.py:1: BLOCKED without a registered stop code", self.failure())
