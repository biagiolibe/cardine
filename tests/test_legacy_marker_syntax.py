"""The product reads only the Cardine marker syntax; the old syntax is plain text."""

from __future__ import annotations

import re
import unittest

from cardine.shared.constants import CAPABILITY_MARKER, MARKED_BLOCK
from cardine.templates import markers as templates_markers

from cardine_cli_support import CardineCliFixtureMixin

MERIDIAN_BLOCK = "<!-- MERIDIAN:BEGIN capability=example v1 -->\nRule.\n<!-- MERIDIAN:END -->\n"
POINTER = "<!-- MERIDIAN:CLAUDE-AGENTS-POINTER v1 -->\n\n# Project Claude entry point\n"


class MeridianBlockIsPlainTextTest(unittest.TestCase):
    def test_marker_readers_find_nothing(self) -> None:
        self.assertEqual(CAPABILITY_MARKER.findall(MERIDIAN_BLOCK), [])
        self.assertEqual(MARKED_BLOCK.findall(MERIDIAN_BLOCK), [])
        self.assertEqual(templates_markers.marker_pairs(MERIDIAN_BLOCK), [])
        self.assertEqual(templates_markers.marker_blocks(MERIDIAN_BLOCK, "example", 1), [])
        self.assertIsNone(templates_markers.find_capability_marker_version(MERIDIAN_BLOCK, "example"))
        self.assertIsNone(templates_markers.extract_marker_block(MERIDIAN_BLOCK, "example", 1))
        self.assertIsNone(templates_markers.extract_marked_block(MERIDIAN_BLOCK, "example", 1))

    def test_a_meridian_pointer_is_not_an_agents_pointer(self) -> None:
        self.assertFalse(templates_markers.is_agents_pointer(POINTER))
        self.assertTrue(templates_markers.is_agents_pointer(POINTER.replace("MERIDIAN", "CARDINE")))

    def test_an_incoming_cardine_block_is_appended_beside_a_meridian_block(self) -> None:
        template = "# Profile\n\n<!-- CARDINE:BEGIN capability=example v1 -->\nIncoming rule.\n<!-- CARDINE:END -->\n"
        local = "# Profile\n\n" + MERIDIAN_BLOCK
        upgraded = templates_markers.append_only_new_markers(local, "# Profile\n", template)
        self.assertIsNotNone(upgraded)
        self.assertTrue(upgraded.startswith(local.rstrip("\n")))
        self.assertEqual(upgraded.count("CARDINE:BEGIN capability=example v1"), 1)
        self.assertEqual(upgraded.count("MERIDIAN:BEGIN capability=example v1"), 1)


class MeridianBlockIsNotUpgradedTest(CardineCliFixtureMixin, unittest.TestCase):
    def meridian_agents(self) -> str:
        agents = self.project / "AGENTS.md"
        text = agents.read_text(encoding="utf-8")
        renamed = re.sub(r"CARDINE:(BEGIN|END)", r"MERIDIAN:\1", text)
        self.assertNotEqual(text, renamed)
        agents.write_text(renamed, encoding="utf-8")
        return renamed

    def test_audit_does_not_check_a_meridian_block(self) -> None:
        self.assertEqual(self.run_cli("lock", "--mode", "single").returncode, 0)
        agents = self.project / "AGENTS.md"
        agents.write_text(
            re.sub(r"CARDINE:(BEGIN|END)", r"MERIDIAN:\1", agents.read_text(encoding="utf-8")).replace(
                "`Proceed with <TASK-ID>`", "`Proceed with <TASK-ID>` (edited)", 1
            ),
            encoding="utf-8",
        )
        integrity = [
            line for line in self.run_cli("audit", "--mode", "single").stdout.splitlines()
            if "marker-integrity" in line
        ]
        self.assertTrue(any("CLAUDE.md: capability=command-triggers" in line for line in integrity))
        self.assertFalse(any("AGENTS.md" in line for line in integrity), integrity)

    def test_upgrade_does_not_retire_a_meridian_block(self) -> None:
        self.assertEqual(self.run_cli("lock", "--mode", "single").returncode, 0)
        local = self.meridian_agents()
        template = self.framework / "templates/single/AGENTS.md"
        template.write_text(
            re.sub(
                r"<!-- CARDINE:BEGIN capability=command-triggers v1 -->.*?<!-- CARDINE:END -->\n?",
                "", template.read_text(encoding="utf-8"), flags=re.DOTALL,
            ),
            encoding="utf-8",
        )
        self.write_synthetic_migration(
            "999-retire-command-triggers", "1.1.0", "1.1.1", ["AGENTS.md"],
            removes=[{"capability": "command-triggers", "capabilityVersion": 1}],
        )
        (self.framework / "VERSION").write_text("1.1.1\n", encoding="utf-8")
        applied = self.run_cli("upgrade", "--apply")
        self.assertNotIn("RETIRE-MARKERS", applied.stdout)
        self.assertEqual((self.project / "AGENTS.md").read_text(encoding="utf-8"), local, applied.stdout)
