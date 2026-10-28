"""Row TR1b: every `cardine` command a template names exists in the argparse tree (inventory R4)."""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import shlex
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import check_repository as cr  # noqa: E402

TEMPLATES = ROOT / "templates" / "single"


def tree() -> dict[str, dict]:
    return cr.command_tree(cr.cardine_cli.build_parser())


def findings_for(text: str, name: str = "docs/EXAMPLE.md") -> list[str]:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return cr.unknown_template_commands(Path(directory), tree())


class TemplateCommandTest(unittest.TestCase):
    def test_every_command_the_shipped_templates_name_exists(self) -> None:
        self.assertEqual(cr.unknown_template_commands(TEMPLATES, tree()), [])

    def test_the_walk_sees_the_commands_the_templates_rely_on(self) -> None:
        commands = tree()
        for words in (("init",), ("run",), ("review", "verdict"), ("worktree", "integrate", "stage"), ("context", "size"),
                      ("task", "close"), ("execution", "start")):
            node = commands
            for word in words:
                self.assertIn(word, node, words)
                node = node[word]

    def test_a_made_up_command_is_reported_with_its_file_and_line(self) -> None:
        self.assertEqual(findings_for("Intro.\n\nRun `cardine frobnicate <TASK-ID>`.\n"),
                         ["docs/EXAMPLE.md:3: unknown command `cardine frobnicate`"])

    def test_a_made_up_subcommand_is_reported_although_its_prefix_exists(self) -> None:
        self.assertEqual(findings_for("`cardine review verdcit <TASK-ID> APPROVE`"),
                         ["docs/EXAMPLE.md:1: unknown command `cardine review verdcit`"])
        self.assertEqual(findings_for("`cardine worktree integrate staging`"),
                         ["docs/EXAMPLE.md:1: unknown command `cardine worktree integrate staging`"])

    def test_the_adopt_command_that_no_longer_exists_is_reported(self) -> None:
        self.assertEqual(findings_for("Do not run `cardine adopt`."),
                         ["docs/EXAMPLE.md:1: unknown command `cardine adopt`"])

    def test_arguments_flags_and_placeholders_end_the_command(self) -> None:
        for text in ("`cardine run <TASK-ID> --project .`", "`cardine adr show ADR-0001`", "`cardine status --write`",
                     "`cardine context size --role <role>`", "`cardine task outcome <TASK-ID> INCONCLUSIVE`",
                     "`cardine locations`", "a bare mention of cardine without a command, `cardine`"):
            with self.subTest(text=text):
                self.assertEqual(findings_for(text), [])

    def test_a_command_split_across_lines_is_read_whole(self) -> None:
        self.assertEqual(findings_for("run `cardine execution\nstart <TASK-ID>`"), [])
        self.assertEqual(len(findings_for("run `cardine execution\nstrat <TASK-ID>`")), 1)

    def test_json_and_rules_assets_are_read_too(self) -> None:
        self.assertEqual(findings_for('{"command": "cardine hook read-guard --host codex"}', ".codex/hooks.json"), [])
        self.assertEqual(findings_for('{"command": "cardine hook read-gaurd --host codex"}', ".codex/hooks.json"),
                         [".codex/hooks.json:1: unknown command `cardine hook read-gaurd`"])

    def test_the_repository_check_fails_on_the_first_finding_and_is_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repository"
            shutil.copytree(ROOT / "templates", root / "templates")
            target = root / "templates/single/docs/CONTEXT_READING_POLICY.md"
            cr.check_template_commands(root)  # unchanged templates pass
            target.write_text(target.read_text(encoding="utf-8") + "\nRun `cardine frobnicate`.\n", encoding="utf-8")
            snapshot = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
            previous = Path.cwd()
            os.chdir(directory)
            try:
                for _ in range(2):  # repeat from an unrelated directory
                    with self.assertRaises(SystemExit):
                        cr.check_template_commands(root)
            finally:
                os.chdir(previous)
            self.assertEqual(snapshot, {path: path.read_bytes() for path in root.rglob("*") if path.is_file()})


class InitSlashCommandTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name).resolve()
        patcher = patch.dict(os.environ, HOME=str(self.home), XDG_CONFIG_HOME=str(self.home / "xdg"))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.text = (ROOT / "commands/cardine-init.md").read_text(encoding="utf-8")
        self.validation = self.home / "validation.json"
        self.validation.write_text(json.dumps({"commands": {}, "baseline": [],
                                              "candidate": {"REUSE": [], "BOUNDED": [], "FULL": []}}))
        values = {"project path": str(self.home / "project with spaces"), "project name": "Example Project",
                  "project slug": "example-project", "lean|governed": "lean", "conversation language": "Italian",
                  "opaque|milestone": "opaque", "validation JSON path": str(self.validation)}
        self.routes = []
        for block in re.findall(r"```bash\n(.*?)```", self.text, re.DOTALL):
            for key, value in values.items():
                block = block.replace(f"<{key}>", value)
            words = shlex.split(block)
            self.assertEqual(words[0], "${CLAUDE_PLUGIN_ROOT}/bin/cardine")
            self.routes.append(words[1:])

    def test_renamed_command_routes_to_argparse_with_all_inputs(self) -> None:
        self.assertFalse((ROOT / "commands/meridian-init.md").exists())
        parsed = [cr.cardine_cli.build_parser().parse_args(route) for route in self.routes]
        self.assertEqual([args.command for args in parsed], ["init", "init", "setup"])
        self.assertTrue(parsed[0].check)
        self.assertTrue(parsed[1].apply)
        self.assertEqual([word if word != "--check" else "--apply" for word in self.routes[0]], self.routes[1])
        self.assertEqual(parsed[0].name, "Example Project")
        self.assertEqual(parsed[0].validation, self.validation)
        self.assertTrue(parsed[2].check)
        self.assertIn("only after explicit confirmation", self.text)

    def test_documented_preview_repeats_without_project_or_home_writes(self) -> None:
        before = {p.relative_to(self.home): p.read_bytes() for p in self.home.rglob("*") if p.is_file()}
        for _ in range(2):
            with patch.object(sys, "argv", ["cardine", *self.routes[0]]), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cr.cardine_cli.main(), 0)
            self.assertEqual(before, {p.relative_to(self.home): p.read_bytes()
                                      for p in self.home.rglob("*") if p.is_file()})
            self.assertEqual(list(self.home.iterdir()), [self.validation])

    def test_cli_owns_bootstrap_and_setup_stays_separate(self) -> None:
        self.assertIn("Do not copy templates", self.text)
        self.assertNotRegex(self.text, r"(?im)^\s*\d+\. (?:Copy|Replace|Write|Create)")
        self.assertIn("separate operation", self.text)
        self.assertIn("does not invalidate initialization", self.text)


if __name__ == "__main__":
    unittest.main()
