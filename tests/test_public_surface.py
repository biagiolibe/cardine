"""Keep the published CLI inventory and compatibility labels in sync."""

import argparse
from contextlib import redirect_stderr
import io
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import cardine_cli  # noqa: E402
from cardine import cli as owner_cli


def command_parsers(parser, prefix="cardine"):
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
        rows = re.findall(r"^\| `(cardine [^`]+)` \| ([^|]+) \|$", document, re.MULTILINE)
        self.assertTrue(rows)
        self.assertEqual(len(rows), len(dict(rows)), "duplicate command classifications")
        parsers = command_parsers(owner_cli.build_parser())
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

    def test_maintainer_commands_are_absent_from_user_cli(self):
        parser = owner_cli.build_parser()
        commands = command_parsers(parser)
        for name in ("profile", "report", "generate-claude-md", "generate-entry-routers", "agent-evals"):
            with self.subTest(command=name):
                self.assertNotIn(f"cardine {name}", commands)
                self.assertNotRegex(parser.format_help(), rf"(?m)^    {re.escape(name)}\s")
                with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    parser.parse_args([name])
