"""Framework CLI regression tests for template retirement."""

from __future__ import annotations

from meridian_cli_support import ROOT
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from cardine.templates import audit as owner_templates_audit
from cardine.templates import markers as templates_markers
from cardine.templates import migrations as owner_templates_migrations
from cardine.templates import migration_audit as owner_templates_migration_audit


class MarkerSupersessionTest(unittest.TestCase):
    """`append_only_new_markers` must distinguish an added capability from a
    superseded one by name, not by `(name, version)` pair — task 012 of
    docs/PLAN_TOKEN_EFFICIENCY.md. Under pair comparison, a version bump is
    indistinguishable from an unrelated new capability: the bumped pair is
    absent from both the local and base pair sets exactly like a genuinely
    new one, so the old block gets left in place while the new one is
    appended at the end, where nothing reads it.
    """

    BASE = (
        "intro\n\n"
        "<!-- MERIDIAN:BEGIN capability=mvp v1 -->\n"
        "old rule text.\n"
        "<!-- MERIDIAN:END -->\n\n"
        "tail\n"
    )
    OLD_BLOCK = "<!-- MERIDIAN:BEGIN capability=mvp v1 -->\nold rule text.\n<!-- MERIDIAN:END -->"
    NEW_BLOCK = "<!-- MERIDIAN:BEGIN capability=mvp v2 -->\nnew rule text.\n<!-- MERIDIAN:END -->"

    def test_added_capability_still_appends(self) -> None:
        template = self.BASE + (
            "\n<!-- MERIDIAN:BEGIN capability=other v1 -->\n"
            "new capability.\n"
            "<!-- MERIDIAN:END -->\n"
        )
        result = templates_markers.append_only_new_markers(self.BASE, self.BASE, template)
        self.assertIsNotNone(result)
        self.assertIn("old rule text.", result)
        self.assertIn("new capability.", result)

    def test_bumped_capability_with_unmodified_block_replaces_in_place(self) -> None:
        template = self.BASE.replace(self.OLD_BLOCK, self.NEW_BLOCK)
        result = templates_markers.append_only_new_markers(self.BASE, self.BASE, template)
        self.assertIsNotNone(result)
        self.assertIn("capability=mvp v2", result)
        self.assertIn("new rule text.", result)
        self.assertNotIn("capability=mvp v1", result)
        self.assertNotIn("old rule text.", result)
        # Surrounding project-owned text is preserved untouched, in place.
        self.assertIn("intro", result)
        self.assertIn("tail", result)
        self.assertEqual(result.index("intro"), self.BASE.index("intro"))

    def test_bumped_capability_with_modified_block_returns_none(self) -> None:
        local = self.BASE.replace("old rule text.", "old rule text, locally customized.")
        template = self.BASE.replace(self.OLD_BLOCK, self.NEW_BLOCK)
        result = templates_markers.append_only_new_markers(local, self.BASE, template)
        self.assertIsNone(result)

    def test_local_file_with_two_existing_versions_is_left_untouched(self) -> None:
        local = self.BASE + "\n" + self.NEW_BLOCK + "\n"
        template = self.BASE.replace(self.OLD_BLOCK, self.NEW_BLOCK)
        result = templates_markers.append_only_new_markers(local, self.BASE, template)
        self.assertIsNone(result)

    def test_edited_unchanged_version_block_blocks_an_otherwise_safe_append(self) -> None:
        """A capability whose version does not change must still be checked
        against the base: an unrelated new capability elsewhere in the same
        template must not cause the function to silently accept a project's
        edit to a different, already-current protected block."""
        local = self.BASE.replace("old rule text.", "old rule text, locally edited.")
        template = self.BASE + (
            "\n<!-- MERIDIAN:BEGIN capability=other v1 -->\n"
            "new capability.\n"
            "<!-- MERIDIAN:END -->\n"
        )
        result = templates_markers.append_only_new_markers(local, self.BASE, template)
        self.assertIsNone(result)


class RetiredTextAdvisoryTest(unittest.TestCase):
    def test_scanner_limits_version_paths_and_managed_regions(self) -> None:
        entry = owner_templates_audit.load_retired_text_registry(ROOT)[0]
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            for relative_path in entry["files"]:
                path = project / relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    "intro\n<!-- MERIDIAN:BEGIN capability=example v1 -->\n"
                    + "\n".join(entry["phrases"])
                    + "\n<!-- MERIDIAN:END -->\n"
                    + "\n".join(phrase.upper() for phrase in entry["phrases"]) + "\n",
                    encoding="utf-8",
                )
            for relative_path in ("tasks/001.md", "tasks/handoffs/001.md", "tasks/reviews/001.md", "tasks/done/001.md", "tasks/QUEUE_ARCHIVE.md"):
                path = project / relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("\n".join(entry["phrases"]), encoding="utf-8")
            self.assertEqual(owner_templates_audit.retired_text_advisories(project, ROOT, {"frameworkVersion": "1.2.8"}), [])
            for version in ("1.2.9", "1.2.12"):
                rows = owner_templates_audit.retired_text_advisories(project, ROOT, {"frameworkVersion": version})
                self.assertEqual(len(rows), len(entry["files"]) * len(entry["phrases"]))
                for row in rows:
                    self.assertEqual(row.status, "ADVISORY")
                    self.assertIn("retired capability=reasoning-budget-contract", row.detail)
                    self.assertIn(entry["remedy"], row.detail)
                    self.assertRegex(row.detail, r"docs/[^:]+:(?:9|10|11|12|13):")
            for relative_path in entry["files"]:
                (project / relative_path).write_text("clean project text\n", encoding="utf-8")
            self.assertEqual(owner_templates_audit.retired_text_advisories(project, ROOT, {"frameworkVersion": "1.2.9"}), [])

    def test_phrase_matching_is_literal_and_preserves_inline_line_numbers(self) -> None:
        entry = {"capability": "example", "retiredIn": "1.2.9", "phrases": ["cap [a-z].*"], "files": ["docs/example.md"], "remedy": "Remove by hand."}
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(owner_templates_audit, "load_retired_text_registry", return_value=[entry]):
            project = Path(directory)
            path = project / "docs/example.md"
            path.parent.mkdir()
            path.write_text("cap abc\n<!-- MERIDIAN:BEGIN capability=example v1 -->cap [a-z].*<!-- MERIDIAN:END --> CAP [A-Z].*\n", encoding="utf-8")
            rows = owner_templates_audit.retired_text_advisories(project, ROOT, {"frameworkVersion": "1.2.9"})
            self.assertEqual(len(rows), 1)
            self.assertIn("docs/example.md:2:", rows[0].detail)

    def test_registry_matches_published_schema(self) -> None:
        schema = json.loads((ROOT / "schemas/retired-text-v1.schema.json").read_text(encoding="utf-8"))
        data = json.loads((ROOT / "capabilities/retired-text-v1.json").read_text(encoding="utf-8"))
        self.assertEqual(set(data), set(schema["required"]))
        self.assertEqual(data["version"], schema["properties"]["version"]["const"])
        item = schema["properties"]["retirements"]["items"]
        for entry in owner_templates_audit.load_retired_text_registry(ROOT):
            self.assertEqual(set(entry), set(item["required"]))
            for key, value in entry.items():
                rule = item["properties"][key]
                if rule["type"] == "string":
                    self.assertIsInstance(value, str)
                    if "pattern" in rule:
                        self.assertRegex(value, rule["pattern"])
                else:
                    self.assertIsInstance(value, list)
                    self.assertGreaterEqual(len(value), rule["minItems"])
                    self.assertEqual(len(value), len(set(value)))
                    for text in value:
                        self.assertIsInstance(text, str)
                        self.assertGreaterEqual(len(text), rule["items"]["minLength"])
                        if "pattern" in rule["items"]:
                            self.assertRegex(text, rule["items"]["pattern"])


class CapabilityRetirementTest(unittest.TestCase):
    """`remove_retired_markers` (task 007 of docs/PLAN_TOKEN_EFFICIENCY.md):
    the retirement mirror of `append_only_new_markers`'s supersession case.
    Safe to delete a capability's block only when the local copy still
    matches the project's own locked baseline byte-for-byte; refuse
    otherwise so a local edit under a marker about to be deleted is never
    silently discarded along with it.
    """

    BASE = (
        "intro\n\n"
        "<!-- MERIDIAN:BEGIN capability=old-rule v1 -->\n"
        "retired rule text.\n"
        "<!-- MERIDIAN:END -->\n\n"
        "tail\n"
    )

    def test_retires_an_unmodified_block(self) -> None:
        result = templates_markers.remove_retired_markers(self.BASE, self.BASE, [("old-rule", 1)])
        self.assertIsNotNone(result)
        self.assertNotIn("capability=old-rule", result)
        self.assertNotIn("retired rule text.", result)
        # Surrounding project-owned text survives untouched.
        self.assertIn("intro", result)
        self.assertIn("tail", result)

    def test_retiring_an_already_absent_block_is_idempotent(self) -> None:
        local = self.BASE.replace(
            "<!-- MERIDIAN:BEGIN capability=old-rule v1 -->\n"
            "retired rule text.\n"
            "<!-- MERIDIAN:END -->\n\n",
            "",
        )
        result = templates_markers.remove_retired_markers(local, self.BASE, [("old-rule", 1)])
        self.assertEqual(result, local)

    def test_refuses_to_retire_a_locally_modified_block(self) -> None:
        local = self.BASE.replace("retired rule text.", "retired rule text, locally customized.")
        result = templates_markers.remove_retired_markers(local, self.BASE, [("old-rule", 1)])
        self.assertIsNone(result)

    def test_returns_input_unchanged_when_nothing_in_the_list_applies(self) -> None:
        result = templates_markers.remove_retired_markers(self.BASE, self.BASE, [("unrelated-capability", 1)])
        self.assertEqual(result, self.BASE)

    def test_refuses_when_the_same_block_appears_twice_in_one_file(self) -> None:
        """`str.replace` is content-addressed: deleting only the first of two
        byte-identical occurrences would be a silent partial mutation. Must
        refuse instead, the same duplicate-paste case `audit_duplicate_headings`
        exists to catch."""
        duplicated = self.BASE + (
            "\n<!-- MERIDIAN:BEGIN capability=old-rule v1 -->\n"
            "retired rule text.\n"
            "<!-- MERIDIAN:END -->\n"
        )
        result = templates_markers.remove_retired_markers(duplicated, duplicated, [("old-rule", 1)])
        self.assertIsNone(result)

    def test_removal_collapses_only_the_local_blank_line_gap(self) -> None:
        """The blank-line cleanup after a deletion must be scoped to the
        splice point, never touching an unrelated run of blank lines
        elsewhere in the same file."""
        text = (
            "intro\n\n"
            "<!-- MERIDIAN:BEGIN capability=old-rule v1 -->\n"
            "retired rule text.\n"
            "<!-- MERIDIAN:END -->\n\n"
            "middle\n\n\n\n"
            "tail\n"
        )
        result = templates_markers.remove_retired_markers(text, text, [("old-rule", 1)])
        self.assertIsNotNone(result)
        self.assertEqual(result, "intro\n\nmiddle\n\n\n\ntail\n")

    def test_capability_requirements_drops_a_retired_capability(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        framework = Path(temporary.name)
        migrations = framework / "migrations"
        migrations.mkdir()
        (migrations / "001-add.json").write_text(
            json.dumps(
                {
                    "id": "001-add",
                    "from": "1.0.0",
                    "to": "1.1.0",
                    "capability": "old-rule",
                    "capabilityVersion": 1,
                    "managedPaths": ["AGENTS.md"],
                }
            ),
            encoding="utf-8",
        )
        (migrations / "002-retire.json").write_text(
            json.dumps(
                {
                    "id": "002-retire",
                    "from": "1.1.0",
                    "to": "1.2.0",
                    "removes": [{"capability": "old-rule", "capabilityVersion": 1}],
                    "managedPaths": ["AGENTS.md"],
                }
            ),
            encoding="utf-8",
        )
        requirements = owner_templates_migrations.capability_requirements(framework)
        self.assertNotIn("old-rule", requirements)
        self.assertIn("old-rule", owner_templates_migrations.retired_capability_ids(framework))

    def test_capability_requirements_honors_a_later_reintroduction(self) -> None:
        """A capability retired by one migration and reintroduced by a later
        one must end up required again — removal and addition are applied in
        migration sequence order, not as an unordered set operation."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        framework = Path(temporary.name)
        migrations = framework / "migrations"
        migrations.mkdir()
        (migrations / "001-add.json").write_text(
            json.dumps(
                {
                    "id": "001-add",
                    "from": "1.0.0",
                    "to": "1.1.0",
                    "capability": "reused-rule",
                    "capabilityVersion": 1,
                    "managedPaths": ["AGENTS.md"],
                }
            ),
            encoding="utf-8",
        )
        (migrations / "002-retire.json").write_text(
            json.dumps(
                {
                    "id": "002-retire",
                    "from": "1.1.0",
                    "to": "1.2.0",
                    "removes": [{"capability": "reused-rule", "capabilityVersion": 1}],
                    "managedPaths": ["AGENTS.md"],
                }
            ),
            encoding="utf-8",
        )
        (migrations / "003-reintroduce.json").write_text(
            json.dumps(
                {
                    "id": "003-reintroduce",
                    "from": "1.2.0",
                    "to": "1.3.0",
                    "capability": "reused-rule",
                    "capabilityVersion": 1,
                    "managedPaths": ["AGENTS.md"],
                }
            ),
            encoding="utf-8",
        )
        requirements = owner_templates_migrations.capability_requirements(framework)
        self.assertIn("reused-rule", requirements)
        self.assertEqual(requirements["reused-rule"], (1, "003-reintroduce"))

    def test_removals_for_managed_file_scopes_by_managed_paths(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        framework = Path(temporary.name)
        migrations = framework / "migrations"
        migrations.mkdir()
        (migrations / "001-retire.json").write_text(
            json.dumps(
                {
                    "id": "001-retire",
                    "from": "1.0.0",
                    "to": "1.1.0",
                    "removes": [{"capability": "old-rule", "capabilityVersion": 1, "supersededBy": "new-rule"}],
                    "managedPaths": ["AGENTS.md", "CLAUDE.md"],
                }
            ),
            encoding="utf-8",
        )
        for_agents = owner_templates_migration_audit.removals_for_managed_file(framework, ["001-retire"], Path("AGENTS.md"))
        self.assertEqual(for_agents, [("old-rule", 1, "new-rule")])
        for_unrelated = owner_templates_migration_audit.removals_for_managed_file(
            framework, ["001-retire"], Path("docs/UNRELATED.md")
        )
        self.assertEqual(for_unrelated, [])
