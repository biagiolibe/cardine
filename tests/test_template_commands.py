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
from synthetic_upgrade_support import SyntheticUpgradeFixtureMixin

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


class RemainingSlashCommandTest(SyntheticUpgradeFixtureMixin, unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        home = Path(self.temporary.name) / "home"
        home.mkdir()
        patcher = patch.dict(os.environ, HOME=str(home), CODEX_HOME=str(home / ".codex"),
                             CLAUDE_CONFIG_DIR=str(home / ".claude"), XDG_CONFIG_HOME=str(home / "xdg"))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.texts = {name: (ROOT / f"commands/cardine-{name}.md").read_text(encoding="utf-8")
                      for name in ("adopt", "upgrade", "task", "audit")}

    def routes(self, name: str) -> list[list[str]]:
        values = {"milestone": "2", "workstream": "HOST", "task ID": "EXAMPLE",
                  "proposed record path": str(Path(self.temporary.name) / "proposed record.md")}
        result = []
        for block in re.findall(r"```bash\n(.*?)```", self.texts[name], re.DOTALL):
            for key, value in values.items():
                block = block.replace(f"<{key}>", value)
            words = shlex.split(block)
            self.assertEqual(words.pop(0), "${CLAUDE_PLUGIN_ROOT}/bin/cardine")
            index = words.index("--project") + 1
            words[index] = str(self.project)
            result.append(words)
        return result

    def invoke(self, route: list[str]) -> tuple[int, str]:
        with patch.object(sys, "argv", ["cardine", "--framework-root", str(self.framework), *route]), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            code = cr.cardine_cli.main()
        return code, output.getvalue()

    def snapshot(self) -> dict[str, bytes]:
        root = Path(self.temporary.name)
        return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}

    def test_four_renamed_routes_exist_without_legacy_command_paths(self) -> None:
        for name, text in self.texts.items():
            with self.subTest(name=name):
                self.assertFalse((ROOT / f"commands/meridian-{name}.md").exists())  # MERIDIAN-OLD-NAME-TEST
                self.assertNotIn("bin/meridian", text)  # MERIDIAN-OLD-NAME-TEST
                self.assertNotIn(".meridian/", text)  # MERIDIAN-OLD-NAME-TEST
                self.assertEqual(findings_for(text), [])
        parsed = {name: [cr.cardine_cli.build_parser().parse_args(route) for route in self.routes(name)]
                  for name in self.texts}
        self.assertEqual(parsed["adopt"], [])
        self.assertIn("no conversion command", self.texts["adopt"])
        self.assertEqual([p.command for p in parsed["upgrade"]], ["upgrade"] * 3)
        self.assertTrue(parsed["upgrade"][0].check)
        self.assertTrue(parsed["upgrade"][1].apply)
        self.assertTrue(parsed["upgrade"][2].owner_reconciled)
        self.assertEqual([p.command for p in parsed["task"]], ["locations", "task", "task", "status"])
        self.assertEqual(parsed["task"][1].identity_command, "next")
        self.assertEqual(parsed["task"][2].task_command, "new")
        self.assertTrue(parsed["task"][3].write)
        self.assertEqual(parsed["audit"][0].command, "audit")
        self.assertIsNone(parsed["audit"][0].mode)
        self.assertIn("GOVERNED_SDD", self.texts["task"])
        self.assertIn("BLOCKED", self.texts["task"])
        self.assertIn("Do not add checkbox status", self.texts["task"])

    def test_documented_checks_repeat_without_project_or_home_writes(self) -> None:
        self.assertEqual(self.run_cli("lock", "--mode", "single").returncode, 0)
        before = self.snapshot()
        for route in (self.routes("upgrade")[0], self.routes("audit")[0], self.routes("task")[0]):
            results = [self.invoke(route) for _ in range(2)]
            self.assertEqual(results[0], results[1])
            if route[0] == "audit":
                # The synthetic legacy lock deliberately has no capabilityProfiles.
                self.assertEqual(results[0][0], 1, results[0][1])
                self.assertIn("SUMMARY worst=UNVERIFIED", results[0][1])
                self.assertIn("FAIL=0", results[0][1])
            else:
                self.assertEqual(results[0][0], 0, results[0][1])
            self.assertEqual(self.snapshot(), before)

    def test_documented_upgrade_retains_adopter_overlay_and_uses_existing_writer(self) -> None:
        self.assertEqual(self.run_cli("lock", "--mode", "single").returncode, 0)
        installed = self.project / "PROJECT_WORKFLOW.md"
        installed.write_text(installed.read_text() + "\nAdopter-owned workflow note.\n", encoding="utf-8")
        source = self.framework / "templates/single/PROJECT_WORKFLOW.md"
        source.write_text(source.read_text().replace("# Workflow", "# Updated workflow", 1), encoding="utf-8")
        (self.framework / "VERSION").write_text("1.1.1\n", encoding="utf-8")
        before = self.snapshot()
        checked = self.invoke(self.routes("upgrade")[0])
        self.assertEqual(checked[0], 0, checked[1])
        self.assertEqual(self.snapshot(), before)
        applied = self.invoke(self.routes("upgrade")[1])
        self.assertEqual(applied[0], 0, applied[1])
        self.assertIn("# Updated workflow", installed.read_text())
        self.assertTrue(installed.read_text().endswith("\nAdopter-owned workflow note.\n"))
        after = self.snapshot()
        repeated = self.invoke(self.routes("upgrade")[0])
        self.assertEqual(repeated[0], 0, repeated[1])
        self.assertEqual(self.snapshot(), after)
        self.assertIn("operation protocol owns recovery", self.texts["upgrade"])
        self.assertIn("Do not copy files", self.texts["upgrade"])
        self.assertIn("only after that manual reconciliation", self.texts["upgrade"])


class SharedSkillTest(unittest.TestCase):
    NAMES = ("cardine-project", "cardine-delivery")
    HOSTS = {"claude": "CLAUDE.md", "codex": "AGENTS.md"}

    def skill(self, name: str) -> str:
        return (ROOT / "skills" / name / "SKILL.md").read_text(encoding="utf-8")

    def test_two_host_neutral_skills_name_only_commands_that_exist(self) -> None:
        for name in self.NAMES:
            text = self.skill(name)
            with self.subTest(name=name):
                self.assertTrue(text.startswith(f"---\nname: {name}\ndescription: "))
                self.assertFalse((ROOT / "skills" / f"{name}-claude-code").exists())
                self.assertEqual(findings_for(text), [])
                self.assertNotIn("MERIDIAN_ROOT", text)

    def test_route_matrix_is_the_same_for_both_presets_and_hosts(self) -> None:
        text = self.skill("cardine-delivery")
        for preset in ("lean", "governed"):
            for host, entry in self.HOSTS.items():
                with self.subTest(preset=preset, host=host):
                    self.assertIn("`.cardine/project.json`", text)
                    self.assertIn("(`lean` or\n`governed`)", text)
                    self.assertIn("`AGENTS.md` or `CLAUDE.md`", text)
                    for route in ("Proceed with <TASK-ID>", "Address review <TASK-ID>", "Review <TASK-ID>",
                                  "Accept <TASK-ID>", "Run lifecycle <TASK-ID>"):
                        self.assertIn(f"`{route}`", text)
        self.assertIn("Review <TASK-ID>`: independent review", text)

    def test_accept_and_lifecycle_route_to_the_existing_orchestration_document(self) -> None:
        for name in self.NAMES:
            self.assertNotIn("workflows/LIFECYCLE.md", self.skill(name))
        text = self.skill("cardine-delivery")
        self.assertIn("`Accept <TASK-ID>` and `Run lifecycle <TASK-ID>`: follow `docs/LIFECYCLE_ORCHESTRATION.md`", text)
        for name in self.NAMES:
            for document in re.findall(r"`(docs/[A-Z_]+\.md)`", self.skill(name)):
                with self.subTest(document=document):
                    self.assertTrue((TEMPLATES / document).is_file())

    def test_project_skill_keeps_setup_consented_and_checks_read_only(self) -> None:
        text = self.skill("cardine-project")
        for word in ("init", "adopt", "upgrade", "setup", "doctor"):
            self.assertIn(f"- {word.capitalize()}:", text)
        self.assertIn("only after explicit consent", text)
        self.assertIn("separate operation from init", text)
        self.assertIn("never proof that a host rule, hook, or profile is in force", text)
        self.assertIn("Never choose them by default", text)


if __name__ == "__main__":
    unittest.main()
