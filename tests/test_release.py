"""Tests for the local-only release preparation command."""

from __future__ import annotations

import json
import io
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import release  # noqa: E402


class ReleasePrepareTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        for directory in (".claude-plugin", "releases", "migrations", "scripts", "tests"):
            (self.root / directory).mkdir()
        (self.root / "VERSION").write_text("1.0.0\n", encoding="utf-8")
        (self.root / ".claude-plugin/plugin.json").write_text('{"version": "1.0.0"}\n', encoding="utf-8")
        (self.root / "releases/1.0.0.json").write_text(json.dumps({
            "version": "1.0.0", "releaseDate": "2026-01-01", "gitTag": "v1.0.0",
            "protocolVersion": 2, "workflowBaselineVersion": "1.0.0",
            "baselineChanged": False, "migrations": [],
        }), encoding="utf-8")
        self.write_changelog("### Added\n\n- New command.")
        (self.root / "scripts/meridian.py").write_text("PROTOCOL_VERSION = 2\n", encoding="utf-8")
        (self.root / "scripts/check_repository.py").write_text("", encoding="utf-8")
        (self.root / "scripts/prepare_release.py").write_text("", encoding="utf-8")
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Meridian Test")
        self.git("config", "user.email", "meridian@example.invalid")
        self.git("add", ".")
        self.git("commit", "-qm", "initial")
        self.git("tag", "v1.0.0")

    def git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["git", *args], cwd=self.root, text=True, capture_output=True, check=True)

    def write_changelog(self, body: str) -> None:
        (self.root / "CHANGELOG.md").write_text(
            f"# Changelog\n\n## [Unreleased]\n\n{body}\n\n## [1.0.0]\n\nOld release.\n", encoding="utf-8"
        )

    def invoke(self, *args: str) -> int:
        return release.main([*args, "--root", str(self.root)])

    def test_fragment_headings_enforce_both_version_selection_forms(self) -> None:
        for heading in release.CHANGELOG_HEADINGS:
            fragment = self.add_fragment(text=f"### {heading}\n\n- Release item.\n")
            self.git("add", ".")
            self.git("commit", "-qm", f"fragment {heading}")
            for bump, version in (("patch", "1.0.2"), ("minor", "1.2.3"), ("major", "2.0.0")):
                refused = (bump == "patch" and heading in {"Added", "Deprecated", "Removed"}) or (bump == "minor" and heading == "Removed")
                for selection in (("--bump", bump), ("--version", version)):
                    with self.subTest(heading=heading, selection=selection):
                        errors = io.StringIO()
                        with redirect_stderr(errors), redirect_stdout(io.StringIO()):
                            self.assertEqual(self.invoke("prepare", *selection, "--dry-run"), int(refused))
                        if refused:
                            self.assertIn(f"{bump} releases must not contain {heading}", errors.getvalue())
                            self.assertIn(str(fragment.relative_to(self.root)), errors.getvalue())
                        self.assertEqual(self.git("status", "--porcelain").stdout, "")
                        self.assertEqual((self.root / "VERSION").read_text(), "1.0.0\n")

    def test_migrations_require_minor_for_both_version_selection_forms(self) -> None:
        self.write_changelog("### Upgrade notes\n\n- Apply the migration.")
        for bump, version in (("patch", "1.0.1"), ("minor", "1.1.0"), ("major", "2.0.0")):
            (self.root / "migrations/001-test.json").write_text(json.dumps({"id": "001-test", "to": version}))
            self.git("add", ".")
            self.git("commit", "-qm", f"migration {version}")
            for selection in (("--bump", bump), ("--version", version)):
                with self.subTest(selection=selection):
                    errors = io.StringIO()
                    with redirect_stderr(errors), redirect_stdout(io.StringIO()):
                        self.assertEqual(self.invoke("prepare", *selection, "--dry-run"), int(bump == "patch"))
                    if bump == "patch":
                        self.assertIn("patch releases must not add migrations", errors.getvalue())
                        self.assertIn("001-test", errors.getvalue())
                    self.assertEqual(self.git("status", "--porcelain").stdout, "")

    def test_existing_migration_does_not_require_minor(self) -> None:
        (self.root / "migrations/001-old.json").write_text('{"id":"001-old","to":"1.0.0"}', encoding="utf-8")
        ledger_path = self.root / "releases/1.0.0.json"
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        ledger.update(baselineChanged=True, migrations=["001-old"])
        ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-qm", "existing migration")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(self.invoke("prepare", "--bump", "patch", "--dry-run"), 0)

    def test_preflight_failures_write_nothing(self) -> None:
        cases = [
            ("branch", lambda: self.git("checkout", "-qb", "feature"), "current branch"),
            ("dirty", lambda: (self.root / "extra").write_text("x", encoding="utf-8"), "working tree"),
            ("mismatch", lambda: ((self.root / ".claude-plugin/plugin.json").write_text('{"version": "1.0.1"}\n', encoding="utf-8"), self.git("add", ".claude-plugin/plugin.json"), self.git("commit", "-qm", "mismatch")), "must agree"),
            ("tag", lambda: self.git("tag", "v1.0.1"), "tag v1.0.1"),
            ("empty", lambda: (self.write_changelog(""), self.git("add", "CHANGELOG.md"), self.git("commit", "-qm", "empty")), "empty body"),
        ]
        for _name, mutate, message in cases:
            with self.subTest(_name), mock.patch("sys.stderr") as stderr:
                mutate()
                before = self.git("status", "--porcelain").stdout
                self.assertEqual(self.invoke("--version", "1.0.1"), 1)
                self.assertIn(message, "".join(str(call) for call in stderr.write.call_args_list))
                self.assertEqual(self.git("status", "--porcelain").stdout, before)
            self.tearDown()
            self.setUp()

    def test_prepare_refuses_template_changes_without_migration(self) -> None:
        for relative in ("templates/workflows/lean-delivery/PROJECT_WORKFLOW.md", "templates/skills/example.md"):
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("New template text.\n")
        self.git("add", ".")
        self.git("commit", "-qm", "unmigrated templates")
        errors = io.StringIO()
        with redirect_stderr(errors):
            self.assertEqual(self.invoke("prepare", "--bump", "minor", "--dry-run"), 1)
        self.assertIn("cannot label release CLI-only", errors.getvalue())
        self.assertIn("templates/workflows/lean-delivery/PROJECT_WORKFLOW.md", errors.getvalue())
        self.assertIn("templates/skills/example.md", errors.getvalue())

    def test_non_template_changes_remain_cli_only(self) -> None:
        (self.root / "scripts/example.py").write_text("# CLI fix\n")
        self.git("add", ".")
        self.git("commit", "-qm", "CLI fix")
        self.assertEqual(release.preflight(self.root, "1.0.1")[2], release.CLI_ONLY)

    def test_missing_previous_tag_cannot_claim_cli_only(self) -> None:
        self.git("tag", "-d", "v1.0.0")
        with self.assertRaisesRegex(release.ReleaseError, "cannot compare templates"):
            release.preflight(self.root, "1.0.1")

    def test_cli_only_dry_run_writes_nothing(self) -> None:
        before = self.git("status", "--porcelain").stdout
        self.assertEqual(self.invoke("--bump", "patch", "--dry-run"), 0)
        self.assertEqual(self.git("status", "--porcelain").stdout, before)

    def test_prepare_word_matches_legacy_prepare_form(self) -> None:
        legacy = io.StringIO()
        named = io.StringIO()
        with redirect_stdout(legacy):
            self.assertEqual(self.invoke("--bump", "patch", "--dry-run"), 0)
        with redirect_stdout(named):
            self.assertEqual(self.invoke("prepare", "--bump", "patch", "--dry-run"), 0)
        self.assertEqual(named.getvalue(), legacy.getvalue())

    def test_dry_run_prints_only_new_changelog_section(self) -> None:
        self.write_changelog("### Added\n\n- New command." + "\n\n## [0.9.9]\n\n" + "Old release.\n" * 500)
        self.git("add", "CHANGELOG.md")
        self.git("commit", "-qm", "long changelog")
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(self.invoke("--bump", "patch", "--dry-run"), 0)
        text = output.getvalue()
        self.assertTrue(text.startswith("Derived release kind: CLI-only release\nVersion: 1.0.1\nWould write:"))
        self.assertIn("Derived release kind: CLI-only release", text)
        self.assertIn("Version: 1.0.1", text)
        self.assertIn("Would write: VERSION, .claude-plugin/plugin.json, releases/1.0.1.json, CHANGELOG.md", text)
        self.assertIn("## [1.0.1]", text)
        self.assertNotIn("## [0.9.9]", text)
        self.assertLess(len(text), 500)

    def test_template_change_needs_upgrade_notes(self) -> None:
        (self.root / "migrations/001-test.json").write_text('{"id":"001-test","to":"1.1.0"}', encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-qm", "migration")
        with redirect_stderr(io.StringIO()):
            self.assertEqual(self.invoke("--version", "1.1.0"), 1)

    def test_template_change_and_protocol_gate(self) -> None:
        (self.root / "migrations/001-test.json").write_text('{"id":"001-test","to":"1.1.0"}', encoding="utf-8")
        self.write_changelog("### Upgrade notes\n\n- Apply the migration.")
        (self.root / "scripts/meridian.py").write_text("PROTOCOL_VERSION = 3\n", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-qm", "migration")
        with redirect_stderr(io.StringIO()):
            self.assertEqual(self.invoke("--version", "1.1.0"), 1)
        with mock.patch.object(release, "validate", return_value=(0, [])):
            self.assertEqual(self.invoke("--version", "1.1.0", "--protocol-reviewed"), 0)
        record = json.loads((self.root / "releases/1.1.0.json").read_text(encoding="utf-8"))
        self.assertEqual(record["migrations"], ["001-test"])
        self.assertTrue(record["baselineChanged"])

    def test_no_release_path_prints_an_agent_evaluation_reminder(self) -> None:
        cli_only = io.StringIO()
        with redirect_stdout(cli_only):
            self.assertEqual(self.invoke("--bump", "patch", "--dry-run"), 0)
        self.assertNotIn("run_agent_evals", cli_only.getvalue())

        (self.root / "migrations/001-test.json").write_text('{"id":"001-test","to":"1.1.0"}', encoding="utf-8")
        self.write_changelog("### Upgrade notes\n\n- Apply the migration.")
        self.git("add", ".")
        self.git("commit", "-qm", "migration")
        dry_run = io.StringIO()
        with redirect_stdout(dry_run):
            self.assertEqual(self.invoke("--version", "1.1.0", "--dry-run"), 0)
        prepared = io.StringIO()
        with mock.patch.object(release, "validate", return_value=(0, [])), redirect_stdout(prepared):
            self.assertEqual(self.invoke("--version", "1.1.0"), 0)
        for text in (dry_run.getvalue(), prepared.getvalue()):
            self.assertNotIn("run_agent_evals", text)
        self.assertEqual(self.git("log", "-1", "--format=%s").stdout.strip(), "Release 1.1.0")

    def test_directing_a_migration_release_to_publish_prints_no_agent_evaluation_reminder(self) -> None:
        (self.root / "migrations/001-test.json").write_text('{"id":"001-test","to":"1.0.1"}', encoding="utf-8")
        (self.root / "VERSION").write_text("1.0.1\n", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-qm", "migration and bump")
        errors = io.StringIO()
        with redirect_stderr(errors):
            self.assertEqual(self.invoke("--bump", "patch"), 1)
        self.assertIn("run python3 scripts/release.py publish --confirm v1.0.1", errors.getvalue())
        self.assertNotIn("run_agent_evals", errors.getvalue())

    def test_validation_failure_rolls_back(self) -> None:
        with mock.patch.object(release, "validate", return_value=(7, ["test", "failure"])), redirect_stderr(io.StringIO()):
            self.assertEqual(self.invoke("--version", "1.0.1"), 7)
        self.assertFalse((self.root / "releases/1.0.1.json").exists())
        self.assertEqual((self.root / "VERSION").read_text(encoding="utf-8"), "1.0.0\n")
        self.assertEqual(self.git("status", "--porcelain").stdout, "")

    def test_prepare_directs_an_already_prepared_release_to_publish(self) -> None:
        (self.root / "VERSION").write_text("1.0.1\n", encoding="utf-8")
        (self.root / ".claude-plugin/plugin.json").write_text('{"version": "1.0.1"}\n', encoding="utf-8")
        (self.root / "releases/1.0.1.json").write_text(json.dumps({
            "version": "1.0.1", "gitTag": "v1.0.1", "baselineChanged": False, "migrations": [],
        }), encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-qm", "Prepare release in migration task")
        with mock.patch("sys.stderr") as stderr:
            self.assertEqual(self.invoke("--bump", "patch"), 1)
        self.assertIn("publish --confirm v1.0.1", "".join(str(call) for call in stderr.write.call_args_list))

    def test_prepare_names_pending_fragments_for_migration_release(self) -> None:
        (self.root / "migrations/001-test.json").write_text('{"id":"001-test","to":"1.0.1"}', encoding="utf-8")
        (self.root / "VERSION").write_text("1.0.1\n", encoding="utf-8")
        (self.root / "changelog.d").mkdir()
        fragment = self.root / "changelog.d/223.md"
        fragment.write_text("### Fixed\n\n- Pending fix.\n", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-qm", "Prepare migration with pending fragment")
        errors = io.StringIO()
        with redirect_stderr(errors):
            self.assertEqual(self.invoke("--bump", "patch"), 1)
        self.assertIn("changelog.d/223.md", errors.getvalue())
        self.assertIn("changelog render --version 1.0.1 --prepared --write", errors.getvalue())
        self.assertTrue(fragment.exists())
        self.assertEqual(self.git("status", "--porcelain").stdout, "")

    def test_commit_contains_only_release_files(self) -> None:
        with mock.patch.object(release, "validate", return_value=(0, [])):
            self.assertEqual(self.invoke("--version", "1.0.1"), 0)
        self.assertEqual(self.git("log", "-1", "--format=%s").stdout.strip(), "Release 1.0.1")
        files = self.git("show", "--format=", "--name-only", "HEAD").stdout.splitlines()
        self.assertEqual(files, [".claude-plugin/plugin.json", "CHANGELOG.md", "VERSION", "releases/1.0.1.json"])

    def add_fragment(self, name: str = "116.md", text: str = "### Added\n\n- Fragment.\n") -> Path:
        directory = self.root / "changelog.d"
        directory.mkdir(exist_ok=True)
        path = directory / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_prepare_accepts_fragments_only_and_consumes_them(self) -> None:
        self.write_changelog("")
        fragment = self.add_fragment()
        self.git("add", ".")
        self.git("commit", "-qm", "fragment")
        with mock.patch.object(release, "validate", return_value=(0, [])):
            self.assertEqual(self.invoke("--version", "1.1.0"), 0)
        self.assertFalse(fragment.exists())
        self.assertIn("### Added\n\n- Fragment.", (self.root / "CHANGELOG.md").read_text(encoding="utf-8"))

    def test_prepare_renders_legacy_before_fragments_and_reports_both(self) -> None:
        self.add_fragment(text="### Fixed\n\n- Fragment fix.\n")
        self.git("add", ".")
        self.git("commit", "-qm", "fragment")
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(self.invoke("--version", "1.0.1", "--dry-run"), 0)
        text = output.getvalue()
        self.assertLess(text.index("- New command."), text.index("- Fragment fix."))
        self.assertIn("uses both legacy", text)

    def test_prepare_rejects_no_legacy_body_or_fragments(self) -> None:
        self.write_changelog("")
        self.git("add", "CHANGELOG.md")
        self.git("commit", "-qm", "empty")
        with mock.patch("sys.stderr") as stderr:
            self.assertEqual(self.invoke("--version", "1.0.1"), 1)
        self.assertIn("changelog.d has no fragments", "".join(str(call) for call in stderr.write.call_args_list))

    def test_rollback_restores_consumed_fragments(self) -> None:
        self.write_changelog("")
        fragment = self.add_fragment()
        self.git("add", ".")
        self.git("commit", "-qm", "fragment")
        with mock.patch.object(release, "validate", return_value=(7, ["test", "failure"])), redirect_stderr(io.StringIO()):
            self.assertEqual(self.invoke("--version", "1.1.0"), 7)
        self.assertEqual(fragment.read_text(encoding="utf-8"), "### Added\n\n- Fragment.\n")


class ChangelogFragmentTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "changelog.d").mkdir()

    def fragment(self, name: str, text: str) -> Path:
        path = self.root / "changelog.d" / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_rendering_is_ordered_and_deterministic(self) -> None:
        self.fragment("20.md", "### Fixed\n\n- Later fix.\n\n### Added\n\n- Later addition.\n")
        self.fragment("10.md", "### Added\n\n- Earlier addition.\n")
        first, paths = release.render_fragments(self.root)
        second, _ = release.render_fragments(self.root)
        self.assertEqual(first, second)
        self.assertEqual([path.name for path in paths], ["10.md", "20.md"])
        self.assertEqual(first, "### Added\n\n- Earlier addition.\n- Later addition.\n\n### Fixed\n\n- Later fix.")

    def test_malformed_fragments_are_rejected(self) -> None:
        cases = (
            ("bad-name.txt", "### Added\n\n- Item.\n"),
            ("1.md", "# Added\n\n- Item.\n"),
            ("1.md", "## Added\n\n- Item.\n"),
            ("1.md", "### Other\n\n- Item.\n"),
        )
        for name, text in cases:
            with self.subTest(name=name, text=text):
                for path in (self.root / "changelog.d").iterdir():
                    path.unlink()
                self.fragment(name, text)
                with self.assertRaises(release.FragmentError):
                    release.render_fragments(self.root)
        for text in ("### Added\n", "### Added\n\n- One.\n\n### Added\n\n- Two.\n", "outside\n\n### Added\n\n- One.\n", "### Added\n\nnot a bullet\n"):
            with self.subTest(text=text):
                for path in (self.root / "changelog.d").iterdir():
                    path.unlink()
                self.fragment("1.md", text)
                with self.assertRaises(release.FragmentError):
                    release.render_fragments(self.root)

    def test_changelog_render_prints_and_write_consumes_fragments(self) -> None:
        (self.root / "CHANGELOG.md").write_text("# Changelog\n\n## [Unreleased]\n\n", encoding="utf-8")
        path = self.fragment("1.md", "### Documentation\n\n- Document it.\n")
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(release.main(["changelog", "render", "--version", "1.0.1", "--root", str(self.root)]), 0)
        self.assertIn("### Documentation", output.getvalue())
        self.assertTrue(path.exists())
        self.assertEqual(release.main(["changelog", "render", "--version", "1.0.1", "--write", "--root", str(self.root)]), 0)
        self.assertFalse(path.exists())
        self.assertIn("### Documentation", (self.root / "CHANGELOG.md").read_text(encoding="utf-8"))

    def test_prepared_render_merges_headings_and_preserves_other_sections(self) -> None:
        (self.root / "VERSION").write_text("1.0.1\n", encoding="utf-8")
        prefix = "# Changelog\n\n## [Unreleased]\n\n- Future.\n\n## [1.0.1]"
        suffix = "## [1.0.0]\n\nOld release.\n"
        kind = "Template-changing release: baseline advances."
        original = prefix + f"\n\n{kind}\n\n### Fixed\n\n- Existing fix.\n\n### Upgrade notes\n\n- Existing upgrade.\n\n" + suffix
        changelog = self.root / "CHANGELOG.md"
        changelog.write_text(original, encoding="utf-8")
        self.fragment("20.md", "### Fixed\n\n- Later fix.\n\n### Upgrade notes\n\n- Later upgrade.\n")
        self.fragment("10.md", "### Added\n\n- Addition.\n\n### Fixed\n\n- Earlier fix.\n")
        command = ["changelog", "render", "--version", "1.0.1", "--prepared", "--root", str(self.root)]
        with redirect_stdout(io.StringIO()):
            self.assertEqual(release.main(command), 0)
            self.assertEqual(changelog.read_text(encoding="utf-8"), original)
            self.assertEqual(len(release.fragment_paths(self.root)), 2)
            self.assertEqual(release.main([*command, "--write"]), 0)
        expected_body = f"{kind}\n\n### Added\n\n- Addition.\n\n### Fixed\n\n- Existing fix.\n- Earlier fix.\n- Later fix.\n\n### Upgrade notes\n\n- Existing upgrade.\n- Later upgrade."
        expected = prefix + "\n\n" + expected_body + "\n\n" + suffix
        self.assertEqual(changelog.read_text(encoding="utf-8"), expected)
        self.assertEqual(release.fragment_paths(self.root), [])
        with redirect_stdout(io.StringIO()):
            self.assertEqual(release.main([*command, "--write"]), 0)
        self.assertEqual(changelog.read_text(encoding="utf-8"), expected)

    def test_prepared_render_failure_preserves_fragments(self) -> None:
        (self.root / "VERSION").write_text("1.0.1\n", encoding="utf-8")
        path = self.fragment("1.md", "### Fixed\n\n- Fix.\n")
        changelog = self.root / "CHANGELOG.md"
        for body in ("## [1.0.0]\n", "## [1.0.1]\n\nMissing kind.\n"):
            changelog.write_text(body, encoding="utf-8")
            with redirect_stderr(io.StringIO()):
                self.assertEqual(release.main(["changelog", "render", "--version", "1.0.1", "--prepared", "--write", "--root", str(self.root)]), 1)
            self.assertTrue(path.exists())
            self.assertEqual(changelog.read_text(encoding="utf-8"), body)

    def test_fragments_merge_without_conflict_while_unreleased_edits_conflict(self) -> None:
        root = self.root
        (root / "CHANGELOG.md").write_text("## [Unreleased]\n\n- base\n", encoding="utf-8")
        (root / "changelog.d" / "README.md").write_text("metadata\n", encoding="utf-8")
        def git(*args: str) -> None:
            subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)
        git("init", "-q", "-b", "main")
        git("config", "user.name", "Meridian Test")
        git("config", "user.email", "meridian@example.invalid")
        git("add", ".")
        git("commit", "-qm", "initial")
        git("checkout", "-qb", "one")
        self.fragment("1.md", "### Added\n\n- One.\n")
        git("add", ".")
        git("commit", "-qm", "one")
        git("checkout", "-q", "main")
        git("checkout", "-qb", "two")
        self.fragment("2.md", "### Added\n\n- Two.\n")
        git("add", ".")
        git("commit", "-qm", "two")
        self.assertEqual(subprocess.run(["git", "merge", "--no-commit", "one"], cwd=root, capture_output=True).returncode, 0)
        git("merge", "--abort")
        git("checkout", "-q", "main")
        git("checkout", "-qb", "legacy-one")
        (root / "CHANGELOG.md").write_text("## [Unreleased]\n\n- one\n", encoding="utf-8")
        git("commit", "-am", "legacy one")
        git("checkout", "-q", "main")
        git("checkout", "-qb", "legacy-two")
        (root / "CHANGELOG.md").write_text("## [Unreleased]\n\n- two\n", encoding="utf-8")
        git("commit", "-am", "legacy two")
        self.assertNotEqual(subprocess.run(["git", "merge", "--no-commit", "legacy-one"], cwd=root, capture_output=True).returncode, 0)


class ReleasePublishTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "project"
        self.root.mkdir()
        self.remote = Path(self.temporary.name) / "origin.git"
        subprocess.run(["git", "init", "--bare", "-q", str(self.remote)], check=True)
        for directory in (".claude-plugin", "releases", "scripts", "bin"):
            (self.root / directory).mkdir()
        (self.root / "VERSION").write_text("1.0.0\n", encoding="utf-8")
        (self.root / ".claude-plugin/plugin.json").write_text('{"version": "1.0.0"}\n', encoding="utf-8")
        (self.root / "CHANGELOG.md").write_text("# Changelog\n", encoding="utf-8")
        (self.root / "releases/1.0.0.json").write_text(json.dumps({
            "version": "1.0.0", "gitTag": "v1.0.0", "baselineChanged": False, "migrations": [],
        }), encoding="utf-8")
        (self.root / "scripts/check_repository.py").write_text("", encoding="utf-8")
        (self.root / "scripts/prepare_release.py").write_text("", encoding="utf-8")
        (self.root / "bin/meridian").write_text("#!/bin/sh\necho UP_TO_DATE\n", encoding="utf-8")
        (self.root / "bin/meridian").chmod(0o755)
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Meridian Test")
        self.git("config", "user.email", "meridian@example.invalid")
        self.git("add", ".")
        self.git("commit", "-qm", "initial")
        self.git("tag", "v1.0.0")
        self.git("remote", "add", "origin", str(self.remote))
        self.git("push", "-qu", "origin", "main")
        self.prepare_release()

    def git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["git", *args], cwd=self.root, text=True, capture_output=True, check=True)

    def prepare_release(self) -> None:
        (self.root / "VERSION").write_text("1.0.1\n", encoding="utf-8")
        (self.root / ".claude-plugin/plugin.json").write_text('{"version": "1.0.1"}\n', encoding="utf-8")
        (self.root / "CHANGELOG.md").write_text("# Changelog\n\n## [1.0.1]\n", encoding="utf-8")
        (self.root / "releases/1.0.1.json").write_text(json.dumps({
            "version": "1.0.1", "gitTag": "v1.0.1", "baselineChanged": False, "migrations": [],
        }), encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-qm", "Release 1.0.1")

    def invoke(self, *args: str) -> int:
        return release.main(["publish", *args, "--root", str(self.root)])

    def verify(self, *args: str) -> int:
        return release.main(["verify", *args, "--root", str(self.root)])

    def workflow_entry(self, run_id: str = "4", *, head: str | None = None, event: str = "push") -> str:
        return json.dumps([{
            "databaseId": run_id,
            "url": f"https://example.invalid/run/{run_id}",
            "headSha": head or self.git("rev-parse", "HEAD").stdout.strip(),
            "event": event,
        }])

    def successful_workflow(self, polls: list[subprocess.CompletedProcess[str]] | None = None):
        original = release.run_command
        responses = list(polls or [subprocess.CompletedProcess([], 0, self.workflow_entry(), "")])

        def gh(root: Path, command: list[str]) -> subprocess.CompletedProcess[str]:
            if command[:3] == ["gh", "run", "list"]:
                return responses.pop(0)
            if command[:3] == ["gh", "run", "watch"]:
                return subprocess.CompletedProcess(command, 0, "", "")
            if command[:3] == ["gh", "release", "view"]:
                return subprocess.CompletedProcess(command, 0, '{"isDraft": false, "isPrerelease": false, "url": "https://example.invalid/release"}', "")
            if command[:2] == ["gh", "api"]:
                if "--repo" in command:
                    return subprocess.CompletedProcess(command, 1, "", "unknown flag: --repo")
                return subprocess.CompletedProcess(command, 0, '{"tag_name": "v1.0.1"}', "")
            return original(root, command)

        return gh

    def test_publish_preflight_refuses_unmigrated_templates(self) -> None:
        path = self.root / "templates/example.md"
        path.parent.mkdir()
        path.write_text("Changed template.\n")
        self.git("add", ".")
        self.git("commit", "-qm", "unmigrated template")
        with self.assertRaisesRegex(release.ReleaseError, "templates/example.md"):
            release.publish_preflight(self.root, "1.0.1")

    def test_pending_fragments_block_publish_before_any_push(self) -> None:
        directory = self.root / "changelog.d"
        directory.mkdir()
        (directory / "README.md").write_text("Fragment instructions.\n", encoding="utf-8")
        for name in ("20.md", "10.md"):
            (directory / name).write_text("### Fixed\n\n- Pending fix.\n", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-qm", "Add pending fragments")
        remote_before = self.git("ls-remote", "origin").stdout
        errors = io.StringIO()
        with mock.patch.object(release, "validate") as validate, mock.patch.object(release, "run_command") as command, redirect_stderr(errors):
            self.assertEqual(self.invoke("--confirm", "v1.0.1"), 1)
            validate.assert_not_called()
            command.assert_not_called()
        self.assertIn("changelog.d/10.md, changelog.d/20.md", errors.getvalue())
        self.assertIn("changelog render --version 1.0.1 --prepared --write", errors.getvalue())
        self.assertEqual(self.git("ls-remote", "origin").stdout, remote_before)
        self.assertEqual(self.git("tag", "--list").stdout, "v1.0.0\n")

    def test_readme_only_does_not_block_prepared_release(self) -> None:
        (self.root / "changelog.d").mkdir()
        (self.root / "changelog.d/README.md").write_text("Instructions.\n", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-qm", "Add fragment instructions")
        head, kind, migrations, commits = release.publish_preflight(self.root, "1.0.1")
        self.assertEqual(head, self.git("rev-parse", "HEAD").stdout.strip())
        self.assertEqual(kind, release.CLI_ONLY)
        self.assertEqual(migrations, [])
        self.assertTrue(commits)

    def test_confirmation_is_required_and_exact(self) -> None:
        for confirm in ([], ["--confirm", "v1.0.2"]):
            with self.subTest(confirm=confirm), mock.patch.object(release, "validate") as validate, redirect_stderr(io.StringIO()):
                self.assertEqual(self.invoke(*confirm), 1)
                validate.assert_not_called()
                self.assertEqual(self.git("ls-remote", "--tags", "origin").stdout, "")

    def test_preconditions_refuse_without_push(self) -> None:
        cases = [
            ("branch", lambda: self.git("checkout", "-qb", "feature"), "current branch"),
            ("dirty", lambda: (self.root / "dirty").write_text("x", encoding="utf-8"), "working tree"),
            ("versions", lambda: ((self.root / ".claude-plugin/plugin.json").write_text('{"version": "1.0.2"}\n', encoding="utf-8"), self.git("add", "."), self.git("commit", "-qm", "wrong version")), "must agree"),
            ("ledger-tag", lambda: ((self.root / "releases/1.0.1.json").write_text(json.dumps({"version": "1.0.1", "gitTag": "v1.0.2", "baselineChanged": False, "migrations": []}), encoding="utf-8"), self.git("add", "."), self.git("commit", "-qm", "wrong tag")), "gitTag"),
            ("cli-migrations", lambda: ((self.root / "releases/1.0.1.json").write_text(json.dumps({"version": "1.0.1", "gitTag": "v1.0.1", "baselineChanged": False, "migrations": ["001-test"]}), encoding="utf-8"), self.git("add", "."), self.git("commit", "-qm", "wrong migrations")), "CLI-only"),
            ("local-tag", lambda: self.git("tag", "v1.0.1"), "local tag"),
            ("remote-tag", lambda: (self.git("tag", "v1.0.1"), self.git("push", "origin", "v1.0.1"), self.git("tag", "-d", "v1.0.1")), "origin tag"),
        ]
        for name, mutate, expected in cases:
            with self.subTest(name=name), mock.patch("sys.stderr") as stderr:
                mutate()
                self.assertEqual(self.invoke("--confirm", "v1.0.1"), 1)
                self.assertIn(expected, "".join(str(call) for call in stderr.write.call_args_list))
            self.tearDown()
            self.setUp()

    def test_template_changing_release_and_multi_commit_publish(self) -> None:
        (self.root / "migrations").mkdir()
        (self.root / "migrations/001-test.json").write_text('{"id": "001-test", "to": "1.0.1"}', encoding="utf-8")
        (self.root / "releases/1.0.1.json").write_text(json.dumps({
            "version": "1.0.1", "gitTag": "v1.0.1", "baselineChanged": True, "migrations": ["001-test"],
        }), encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-qm", "Add release migration")
        self.git("commit", "--allow-empty", "-qm", "Document release migration")
        output = io.StringIO()
        with mock.patch.object(release, "validate", return_value=(0, [])), redirect_stdout(output):
            self.assertEqual(self.invoke("--confirm", "v1.0.1", "--no-wait"), 0)
        text = output.getvalue()
        self.assertIn("Template-changing release", text)
        self.assertIn("Migrations: 001-test", text)
        self.assertIn("Add release migration", text)
        self.assertIn("Document release migration", text)

    def test_template_changing_ledger_migration_must_exist_and_target_version(self) -> None:
        (self.root / "migrations").mkdir()
        (self.root / "migrations/001-test.json").write_text('{"id": "001-test", "to": "1.0.2"}', encoding="utf-8")
        (self.root / "releases/1.0.1.json").write_text(json.dumps({
            "version": "1.0.1", "gitTag": "v1.0.1", "baselineChanged": True, "migrations": ["001-test"],
        }), encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-qm", "Wrong migration target")
        with mock.patch("sys.stderr") as stderr:
            self.assertEqual(self.invoke("--confirm", "v1.0.1"), 1)
        self.assertIn("must exist and target 1.0.1", "".join(str(call) for call in stderr.write.call_args_list))

    def test_origin_must_be_parent_of_release_commit(self) -> None:
        self.git("checkout", "-qb", "other", "origin/main")
        self.git("commit", "--allow-empty", "-qm", "ahead")
        self.git("push", "-q", "origin", "HEAD:main")
        self.git("checkout", "-q", "main")
        self.git("fetch", "-q", "origin")
        with redirect_stderr(io.StringIO()):
            self.assertEqual(self.invoke("--confirm", "v1.0.1"), 1)

    def test_push_order_and_no_forbidden_git_flags(self) -> None:
        commands: list[list[str]] = []
        original_run_command = release.run_command
        original_run_git = release.run_git

        def record_command(root: Path, command: list[str]) -> subprocess.CompletedProcess[str]:
            commands.append(command)
            return original_run_command(root, command)

        def record_git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
            commands.append(["git", *args])
            return original_run_git(root, *args)

        with mock.patch.object(release, "validate", return_value=(0, [])), mock.patch.object(release, "run_command", side_effect=record_command), mock.patch.object(release, "run_git", side_effect=record_git):
            self.assertEqual(self.invoke("--confirm", "v1.0.1", "--no-wait"), 0)
        pushes = [command for command in commands if command[:2] == ["git", "push"]]
        release_commit = self.git("rev-parse", "HEAD").stdout.strip()
        self.assertEqual(pushes, [
            ["git", "push", "origin", "main"],
            ["git", "push", "origin", "v1.0.1"],
            ["git", "push", "origin", f"{release_commit}:refs/heads/stable"],
        ])
        self.assertEqual(self.git("ls-remote", "--heads", "origin", "stable").stdout.split()[0], release_commit)
        self.assertFalse(any(flag in command for command in commands for flag in ("--force", "--force-with-lease", "--delete")))

    def test_stable_advances_by_fast_forward_from_previous_release(self) -> None:
        previous = self.git("rev-parse", "HEAD~1").stdout.strip()
        self.git("push", "-q", "origin", f"{previous}:refs/heads/stable")
        with mock.patch.object(release, "validate", return_value=(0, [])):
            self.assertEqual(self.invoke("--confirm", "v1.0.1", "--no-wait"), 0)
        self.assertEqual(self.git("ls-remote", "--heads", "origin", "stable").stdout.split()[0], self.git("rev-parse", "HEAD").stdout.strip())

    def test_non_fast_forward_stable_is_blocked_before_push(self) -> None:
        self.git("checkout", "-qb", "diverged", "HEAD~1")
        self.git("commit", "--allow-empty", "-qm", "diverged")
        diverged = self.git("rev-parse", "HEAD").stdout.strip()
        self.git("push", "-q", "origin", f"{diverged}:refs/heads/stable")
        self.git("checkout", "-q", "main")
        errors = io.StringIO()
        with mock.patch.object(release, "validate", return_value=(0, [])), redirect_stderr(errors):
            self.assertEqual(self.invoke("--confirm", "v1.0.1", "--no-wait"), 1)
        release_commit = self.git("rev-parse", "HEAD").stdout.strip()
        self.assertIn(diverged, errors.getvalue())
        self.assertIn(release_commit, errors.getvalue())
        self.assertEqual(self.git("ls-remote", "--heads", "origin", "stable").stdout.split()[0], diverged)
        self.assertEqual(self.git("ls-remote", "--tags", "origin", "v1.0.1").stdout.split()[0], release_commit)
        self.assertEqual(self.git("ls-remote", "--heads", "origin", "main").stdout.split()[0], release_commit)

    def test_stable_requires_plugin_version_equal_to_the_tag(self) -> None:
        release.ensure_plugin_version_matches(self.root, "HEAD", "1.0.1")
        with self.assertRaisesRegex(release.ReleaseError, "declares version 1.0.0, not 1.0.1"):
            release.ensure_plugin_version_matches(self.root, "HEAD~1", "1.0.1")
        self.git("tag", "v1.0.1", "HEAD~1")
        with self.assertRaisesRegex(release.ReleaseError, "declares version 1.0.0"):
            release.advance_stable(self.root, "v1.0.1", "1.0.1")
        self.assertEqual(self.git("ls-remote", "--heads", "origin", "stable").stdout, "")

    def test_rejected_main_push_stops_before_tag(self) -> None:
        original = release.run_command

        def reject_main(root: Path, command: list[str]) -> subprocess.CompletedProcess[str]:
            if command == ["git", "push", "origin", "main"]:
                return subprocess.CompletedProcess(command, 1, "", "rejected")
            return original(root, command)

        with mock.patch.object(release, "validate", return_value=(0, [])), mock.patch.object(release, "run_command", side_effect=reject_main), redirect_stderr(io.StringIO()):
            self.assertEqual(self.invoke("--confirm", "v1.0.1", "--no-wait"), 1)
        self.assertEqual(self.git("tag", "--list", "v1.0.1").stdout, "")

    def test_validation_failure_stops_before_push(self) -> None:
        with mock.patch.object(release, "validate", return_value=(9, ["validation", "failed"])), redirect_stderr(io.StringIO()):
            self.assertEqual(self.invoke("--confirm", "v1.0.1", "--no-wait"), 1)
        self.assertEqual(self.git("ls-remote", "--heads", "origin", "main").stdout.count("refs/heads/main"), 1)
        self.assertEqual(self.git("tag", "--list", "v1.0.1").stdout, "")

    def test_no_wait_and_missing_gh_paths(self) -> None:
        with mock.patch.object(release, "validate", return_value=(0, [])):
            self.assertEqual(self.invoke("--confirm", "v1.0.1", "--no-wait"), 0)
        self.tearDown()
        self.setUp()
        with mock.patch.object(release, "validate", return_value=(0, [])), mock.patch.object(release.shutil, "which", return_value=None):
            self.assertEqual(self.invoke("--confirm", "v1.0.1"), 0)

    def test_workflow_lookup_polls_until_a_matching_result(self) -> None:
        polls = [
            subprocess.CompletedProcess([], 0, "[]", ""),
            subprocess.CompletedProcess([], 0, self.workflow_entry("other-event", event="workflow_dispatch"), ""),
            subprocess.CompletedProcess([], 0, self.workflow_entry("other-commit", head="not-the-tag"), ""),
            subprocess.CompletedProcess([], 0, self.workflow_entry("selected"), ""),
        ]
        with mock.patch.object(release.shutil, "which", return_value="gh"), mock.patch.object(release, "run_command", side_effect=self.successful_workflow(polls)) as command, mock.patch.object(release.time, "monotonic", side_effect=range(1000)), mock.patch.object(release.time, "sleep") as sleep:
            release.wait_for_publication(self.root, "1.0.1", "owner/repository", self.git("rev-parse", "HEAD").stdout.strip())
        self.assertEqual(sum(call.args[1][:3] == ["gh", "run", "list"] for call in command.call_args_list), 4)
        self.assertEqual(sleep.call_count, 3)
        watched = [call.args[1] for call in command.call_args_list if call.args[1][:3] == ["gh", "run", "watch"]]
        self.assertEqual(watched, [["gh", "run", "watch", "selected", "--exit-status"]])

    def test_workflow_lookup_retries_transient_error(self) -> None:
        polls = [
            subprocess.CompletedProcess([], 0, "not JSON", ""),
            subprocess.CompletedProcess([], 1, "", "temporary outage"),
            subprocess.CompletedProcess([], 0, self.workflow_entry(), ""),
        ]
        with mock.patch.object(release.shutil, "which", return_value="gh"), mock.patch.object(release, "run_command", side_effect=self.successful_workflow(polls)) as command, mock.patch.object(release.time, "monotonic", side_effect=range(1000)), mock.patch.object(release.time, "sleep"):
            release.wait_for_publication(self.root, "1.0.1", "owner/repository", self.git("rev-parse", "HEAD").stdout.strip())
        self.assertEqual(sum(call.args[1][:3] == ["gh", "run", "list"] for call in command.call_args_list), 3)

    def test_workflow_lookup_timeout_explains_safe_resume(self) -> None:
        with mock.patch.object(release.shutil, "which", return_value="gh"), mock.patch.object(release, "run_command", return_value=subprocess.CompletedProcess([], 0, "[]", "")), mock.patch.object(release.time, "monotonic", side_effect=(0, 121)), mock.patch.object(release.time, "sleep"):
            with self.assertRaisesRegex(release.ReleaseError, "nothing was retried or moved") as raised:
                release.wait_for_publication(self.root, "1.0.1", "owner/repository", self.git("rev-parse", "HEAD").stdout.strip())
        message = str(raised.exception)
        self.assertIn("the push of main and tag v1.0.1 completed", message)
        self.assertIn("gh run list", message)
        self.assertIn("gh release view", message)
        self.assertIn("release.py verify --version 1.0.1", message)
        self.assertNotIn("list index out of range", message)

    def test_release_verification_uses_supported_fields_and_latest_api(self) -> None:
        commands: list[list[str]] = []

        workflow = self.successful_workflow()

        def gh(root: Path, command: list[str]) -> subprocess.CompletedProcess[str]:
            commands.append(command)
            return workflow(root, command)

        with mock.patch.object(release.shutil, "which", return_value="gh"), mock.patch.object(release, "run_command", side_effect=gh), mock.patch.object(release.time, "monotonic", side_effect=range(1000)), mock.patch.object(release.time, "sleep"):
            release.wait_for_publication(self.root, "1.0.1", "owner/repository", self.git("rev-parse", "HEAD").stdout.strip())
        view = next(command for command in commands if command[:3] == ["gh", "release", "view"])
        fields = view[view.index("--json") + 1].split(",")
        self.assertTrue(set(fields) <= {"isDraft", "isPrerelease", "url"})
        self.assertEqual(view[-2:], ["--repo", "owner/repository"])
        api = next(command for command in commands if command[:2] == ["gh", "api"])
        self.assertEqual(api, ["gh", "api", "repos/owner/repository/releases/latest"])

    def test_latest_release_mismatch_draft_and_prerelease_are_rejected(self) -> None:
        for release_response, latest_response in (
            ('{"isDraft": false, "isPrerelease": false, "url": "https://example.invalid/release"}', '{"tag_name": "v9.9.9"}'),
            ('{"isDraft": true, "isPrerelease": false, "url": "https://example.invalid/release"}', '{"tag_name": "v1.0.1"}'),
            ('{"isDraft": false, "isPrerelease": true, "url": "https://example.invalid/release"}', '{"tag_name": "v1.0.1"}'),
        ):
            def gh(root: Path, command: list[str]) -> subprocess.CompletedProcess[str]:
                if command[:3] == ["gh", "run", "list"]:
                    return subprocess.CompletedProcess(command, 0, self.workflow_entry(), "")
                if command[:3] == ["gh", "run", "watch"]:
                    return subprocess.CompletedProcess(command, 0, "", "")
                if command[:3] == ["gh", "release", "view"]:
                    return subprocess.CompletedProcess(command, 0, release_response, "")
                if command[:2] == ["gh", "api"]:
                    return subprocess.CompletedProcess(command, 0, latest_response, "")
                return subprocess.CompletedProcess(command, 1, "", "unexpected command")

            with self.subTest(release_response=release_response), mock.patch.object(release.shutil, "which", return_value="gh"), mock.patch.object(release, "run_command", side_effect=gh), mock.patch.object(release.time, "monotonic", side_effect=range(1000)), mock.patch.object(release.time, "sleep"):
                with self.assertRaisesRegex(release.ReleaseError, "published, stable, and latest"):
                    release.wait_for_publication(self.root, "1.0.1", "owner/repository", self.git("rev-parse", "HEAD").stdout.strip())

    def test_latest_api_failure_after_push_explains_safe_resume(self) -> None:
        def gh(root: Path, command: list[str]) -> subprocess.CompletedProcess[str]:
            if command[:3] == ["gh", "run", "list"]:
                return subprocess.CompletedProcess(command, 0, self.workflow_entry(), "")
            if command[:3] == ["gh", "run", "watch"]:
                return subprocess.CompletedProcess(command, 0, "", "")
            if command[:3] == ["gh", "release", "view"]:
                return subprocess.CompletedProcess(command, 0, '{"isDraft": false, "isPrerelease": false, "url": "https://example.invalid/release"}', "")
            if command[:2] == ["gh", "api"]:
                return subprocess.CompletedProcess(command, 1, "", "GitHub unavailable")
            return subprocess.CompletedProcess(command, 1, "", "unexpected command")

        with mock.patch.object(release.shutil, "which", return_value="gh"), mock.patch.object(release, "run_command", side_effect=gh), mock.patch.object(release.time, "monotonic", side_effect=range(1000)), mock.patch.object(release.time, "sleep"):
            with self.assertRaisesRegex(release.PostPushVerificationError, "main and tag v1.0.1 completed") as raised:
                release.wait_for_publication(self.root, "1.0.1", "owner/repository", self.git("rev-parse", "HEAD").stdout.strip())
        message = str(raised.exception)
        self.assertIn("nothing was retried or moved", message)
        self.assertIn("publication was not confirmed", message)
        self.assertIn("release.py verify --version 1.0.1", message)
        self.assertIn("gh run list", message)
        self.assertIn("gh release view", message)

    def test_publish_reports_post_push_verification_without_publish_failed_prefix(self) -> None:
        original = release.run_command

        def gh(root: Path, command: list[str]) -> subprocess.CompletedProcess[str]:
            if command[:3] == ["gh", "run", "list"]:
                return subprocess.CompletedProcess(command, 0, self.workflow_entry(), "")
            if command[:3] == ["gh", "run", "watch"]:
                return subprocess.CompletedProcess(command, 0, "", "")
            if command[:3] == ["gh", "release", "view"]:
                return subprocess.CompletedProcess(command, 0, '{"isDraft": false, "isPrerelease": false, "url": "https://example.invalid/release"}', "")
            if command[:2] == ["gh", "api"]:
                return subprocess.CompletedProcess(command, 1, "", "GitHub unavailable")
            return original(root, command)

        stderr = io.StringIO()
        with mock.patch.object(release, "validate", return_value=(0, [])), mock.patch.object(release.shutil, "which", return_value="gh"), mock.patch.object(release, "run_command", side_effect=gh), mock.patch.object(release, "github_repository", return_value="owner/repository"), mock.patch.object(release.time, "monotonic", side_effect=range(1000)), mock.patch.object(release.time, "sleep"), redirect_stderr(stderr):
            self.assertEqual(self.invoke("--confirm", "v1.0.1"), 1)
        message = stderr.getvalue()
        self.assertNotIn("release publish failed", message)
        self.assertIn("main and tag v1.0.1 completed", message)
        self.assertIn("release.py verify --version 1.0.1", message)

    def test_verify_succeeds_without_git_writes(self) -> None:
        self.git("tag", "v1.0.1")
        self.git("push", "-q", "origin", "v1.0.1", "HEAD:refs/heads/stable")
        commands: list[list[str]] = []
        original_git = release.run_git

        def record_git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
            commands.append(["git", *args])
            return original_git(root, *args)

        with mock.patch.object(release.shutil, "which", return_value="gh"), mock.patch.object(release, "run_git", side_effect=record_git), mock.patch.object(release, "run_command", side_effect=self.successful_workflow()), mock.patch.object(release, "github_repository", return_value="owner/repository"), mock.patch.object(release.time, "monotonic", side_effect=range(1000)), mock.patch.object(release.time, "sleep"):
            self.assertEqual(self.verify("--version", "1.0.1"), 0)
        self.assertFalse(any(command[1] in {"push", "tag", "commit", "reset", "checkout"} for command in commands))

    def test_verify_reports_stable_mismatch_without_changing_anything(self) -> None:
        self.git("tag", "v1.0.1")
        self.git("push", "-q", "origin", "v1.0.1")
        before = self.git("ls-remote", "origin", "refs/heads/main", "refs/tags/*").stdout
        for setup in (lambda: None, lambda: self.git("push", "-q", "origin", "HEAD~1:refs/heads/stable")):
            setup()
            errors = io.StringIO()
            with mock.patch.object(release.shutil, "which", return_value="gh"), mock.patch.object(release, "run_command", side_effect=self.successful_workflow()), mock.patch.object(release, "github_repository", return_value="owner/repository"), mock.patch.object(release.time, "monotonic", side_effect=range(1000)), mock.patch.object(release.time, "sleep"), redirect_stderr(errors):
                self.assertEqual(self.verify("--version", "1.0.1"), 1)
            self.assertIn("origin stable is", errors.getvalue())
            self.assertIn("nothing was changed", errors.getvalue())
        self.assertEqual(self.git("ls-remote", "origin", "refs/heads/main", "refs/tags/*").stdout, before)
        self.assertEqual(self.git("ls-remote", "--heads", "origin", "stable").stdout.split()[0], self.git("rev-parse", "HEAD~1").stdout.strip())

    def test_verify_requires_remote_tag(self) -> None:
        with mock.patch("sys.stderr") as stderr:
            self.assertEqual(self.verify("--version", "1.0.1"), 1)
        self.assertIn("origin tag v1.0.1 does not exist", "".join(str(call) for call in stderr.write.call_args_list))

    def test_workflow_failure_does_not_move_tag(self) -> None:
        original = release.run_command

        def gh(root: Path, command: list[str]) -> subprocess.CompletedProcess[str]:
            if command[:3] == ["gh", "run", "list"]:
                return subprocess.CompletedProcess(command, 0, self.workflow_entry(), "")
            if command[:3] == ["gh", "run", "watch"]:
                return subprocess.CompletedProcess(command, 1, "", "failed")
            return original(root, command)

        with mock.patch.object(release, "validate", return_value=(0, [])), mock.patch.object(release.shutil, "which", return_value="gh"), mock.patch.object(release, "run_command", side_effect=gh), redirect_stderr(io.StringIO()):
            self.assertEqual(self.invoke("--confirm", "v1.0.1"), 1)
        self.assertEqual(self.git("rev-parse", "v1.0.1").stdout.strip(), self.git("rev-parse", "HEAD").stdout.strip())


class FailureVisibilityProbe(unittest.TestCase):
    def test_genuine_assertion_is_visible(self) -> None:
        if os.environ.get("MERIDIAN_FAILURE_VISIBILITY_PROBE") == "1":
            self.fail("intentional assertion failure visibility probe")


class FailureVisibilityTest(unittest.TestCase):
    def test_genuine_assertion_in_this_module_remains_visible(self) -> None:
        environment = {**os.environ, "MERIDIAN_FAILURE_VISIBILITY_PROBE": "1"}
        result = subprocess.run(
            [sys.executable, "-m", "unittest", "tests.test_release.FailureVisibilityProbe.test_genuine_assertion_is_visible"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
            env=environment,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("AssertionError: intentional assertion failure visibility probe", result.stderr)


if __name__ == "__main__":
    unittest.main()
