"""Installation discovery remains explicit, read-only, and product-independent."""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from cardine.console import snapshot as product
import console_support as support


class LegacyBoundaryTest(support.RepoCase):
    def setUp(self):
        super().setUp()
        support.LeanEffectiveStateFixture.setup_project(self, {"001": "x", "002": " "},
                                                       {"002": "001"})
        (self.project / ".cardine/project.json").unlink()
        self.write(self.project, "PROJECT_WORKFLOW.md", "LEAN_DELIVERY\n")
        self.write(self.project, ".meridian/manifest.json", json.dumps({"workflowMode": "lean-delivery"}))
        self.commit(self.project, "Meridian fixture")

    queue = support.LeanEffectiveStateFixture.queue

    def test_product_missing_state_never_selects_installation_reader(self):
        self.write(self.project, ".cardine/project.json", '{"version": 1, "preset": "lean"}')
        snapshot = product.load_snapshot(self.project)
        # Without task states the product lists nothing; queue rows and records are not a fallback.
        self.assertEqual(snapshot.done_count, 0)
        self.assertEqual(snapshot.tasks, ())
