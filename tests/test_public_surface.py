"""Keep the published CLI inventory and compatibility labels in sync."""

import argparse
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import meridian  # noqa: E402


def command_parsers(parser, prefix="meridian"):
    result = {}
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, child in action.choices.items():
                command = f"{prefix} {name}"
                result[command] = child
                result.update(command_parsers(child, command))
    return result


class PublicSurfaceTest(unittest.TestCase):
    def test_inventory_matches_every_parser_command_exactly_once(self):
        document = (ROOT / "docs/PUBLIC_SURFACE.md").read_text(encoding="utf-8")
        rows = re.findall(r"^\| `(meridian [^`]+)` \| ([^|]+) \|$", document, re.MULTILINE)
        self.assertTrue(rows)
        self.assertEqual(len(rows), len(dict(rows)), "duplicate command classifications")
        parsers = command_parsers(meridian.build_parser())
        self.assertEqual(set(dict(rows)), set(parsers))
        for command, tier in rows:
            with self.subTest(command=command):
                self.assertIn(tier, {"Stable", "Host-facing", "Experimental", "Internal"})
                label = {"Experimental": "experimental", "Internal": "framework-internal"}.get(tier)
                if label:
                    self.assertIn(label, parsers[command].format_help().lower())

    def test_experimental_surfaces_are_named_in_readme(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8").lower()
        self.assertRegex(readme, r"console[^\n]*experimental")
        self.assertRegex(readme, r"`meridian usage`[^\n]*experimental")
