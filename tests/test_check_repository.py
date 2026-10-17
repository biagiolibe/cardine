"""Regression tests for the repository validation checks."""

from __future__ import annotations

import contextlib
import io
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import check_repository as cr  # noqa: E402


class LocalMarkdownLinksTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        root_patch = patch.object(cr, "ROOT", self.root)
        root_patch.start()
        self.addCleanup(root_patch.stop)

    def write(self, name: str, text: str = "") -> None:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def test_queue_link_to_archived_record_is_informational(self) -> None:
        self.write("tasks/QUEUE.md", "[Task](220-example.md#objective)")
        self.write("tasks/done/220-example.md")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            cr.check_local_markdown_links()
        self.assertIn("INFO:", output.getvalue())
        self.assertIn("tasks/QUEUE.md: 220-example.md", output.getvalue())
        self.assertIn("integrate stage relinks it", output.getvalue())

    def test_missing_targets_still_fail(self) -> None:
        cases = (
            ("tasks/QUEUE.md", "220-example.md", None),
            ("tasks/OTHER.md", "220-example.md", "tasks/done/220-example.md"),
            ("README.md", "missing.md", None),
            ("tasks/QUEUE.md", "nested/record.md", "tasks/done/record.md"),
            ("tasks/QUEUE.md", "record.txt", "tasks/done/record.txt"),
            ("tasks/QUEUE.md", "../record.md", "tasks/done/record.md"),
        )
        for source, target, archive in cases:
            with self.subTest(source=source, target=target):
                self.write(source, f"[Missing]({target})")
                if archive:
                    self.write(archive)
                output = io.StringIO()
                with contextlib.redirect_stdout(output), self.assertRaises(SystemExit):
                    cr.check_local_markdown_links()
                self.assertIn(f"broken local Markdown link in {source}: {target}", output.getvalue())
                (self.root / source).unlink()


class PluginVersionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / ".claude-plugin").mkdir()
        (self.root / "VERSION").write_text("1.2.3\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_plugin_version(self, version: str) -> None:
        manifest = {"name": "meridian", "version": version}
        (self.root / ".claude-plugin" / "plugin.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )

    def test_matching_plugin_version_passes(self) -> None:
        self.write_plugin_version("1.2.3")

        cr.check_plugin_version(self.root)

    def test_mismatched_plugin_version_names_both_values(self) -> None:
        self.write_plugin_version("1.2.2")
        output = io.StringIO()

        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit):
            cr.check_plugin_version(self.root)

        self.assertIn("1.2.2", output.getvalue())
        self.assertIn("1.2.3", output.getvalue())


class CapabilityMarkerBaselineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        shutil.copytree(ROOT / "templates", self.root / "templates")
        shutil.copytree(ROOT / "migrations", self.root / "migrations")
        shutil.copytree(ROOT / "capabilities", self.root / "capabilities")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_committed_baseline_matches_the_repository_as_shipped(self) -> None:
        # No SystemExit means every recorded baseline matches the live templates.
        cr.check_capability_marker_baselines(self.root)

    def test_a_hand_edit_that_changes_marker_content_without_a_version_bump_fails(self) -> None:
        target = self.root / "templates/workflows/governed-sdd/docs/workflows/IMPLEMENTATION.md"
        text = target.read_text(encoding="utf-8")
        target.write_text(
            text.replace(
                "If any acceptance criterion cannot be evaluated",
                "If any acceptance criterion is an UNAUTHORIZED HAND EDIT",
                1,
            ),
            encoding="utf-8",
        )
        with self.assertRaises(SystemExit):
            cr.check_capability_marker_baselines(self.root)

    def test_a_hand_edit_to_agents_md_is_caught_too(self) -> None:
        """AGENTS.md is the single source of truth the generator copies from
        (task 004); an edit there is exactly as unauthorized as one in
        CLAUDE.md, and must not silently become the new v1 just because the
        generator will faithfully propagate it."""
        target = self.root / "templates/workflows/governed-sdd/docs/workflows/IMPLEMENTATION.md"
        text = target.read_text(encoding="utf-8")
        target.write_text(
            text.replace(
                "If any acceptance criterion cannot be evaluated",
                "If any acceptance criterion is an UNAUTHORIZED HAND EDIT",
                1,
            ),
            encoding="utf-8",
        )
        with self.assertRaises(SystemExit):
            cr.check_capability_marker_baselines(self.root)

    def test_write_marker_baselines_makes_a_deliberate_change_pass_again(self) -> None:
        target = self.root / "templates/workflows/governed-sdd/docs/workflows/IMPLEMENTATION.md"
        text = target.read_text(encoding="utf-8")
        target.write_text(
            text.replace(
                "If any acceptance criterion cannot be evaluated",
                "If any acceptance criterion is deliberately reworded",
                1,
            ),
            encoding="utf-8",
        )
        with self.assertRaises(SystemExit):
            cr.check_capability_marker_baselines(self.root)
        cr.write_marker_baselines(self.root)
        cr.check_capability_marker_baselines(self.root)

    def test_a_version_bump_without_regenerating_the_baseline_still_fails(self) -> None:
        """Bumping the version *and* changing the content is the legitimate
        path, but it still requires the explicit `--write-marker-baselines`
        step; skipping that must not silently pass."""
        target = self.root / "templates/workflows/governed-sdd/AGENTS.md"
        text = target.read_text(encoding="utf-8")
        text = text.replace(
            "<!-- MERIDIAN:BEGIN capability=command-triggers v3 -->",
            "<!-- MERIDIAN:BEGIN capability=command-triggers v4 -->",
            1,
        )
        target.write_text(text, encoding="utf-8")
        with self.assertRaises(SystemExit):
            cr.check_capability_marker_baselines(self.root)

    def test_missing_baseline_file_fails(self) -> None:
        (self.root / "migrations" / "marker-baselines" / "CAPABILITY_MARKER_BASELINES.json").unlink()
        with self.assertRaises(SystemExit):
            cr.check_capability_marker_baselines(self.root)

    def test_capability_catalog_is_valid_as_shipped(self) -> None:
        cr.check_capability_catalog(self.root)

    def test_capability_catalog_rejects_an_unresolved_dependency(self) -> None:
        path = self.root / "capabilities/catalog-v1.json"
        catalog = json.loads(path.read_text(encoding="utf-8"))
        catalog["capabilities"]["read-guard"]["dependencies"][0]["version"] = 999
        path.write_text(json.dumps(catalog), encoding="utf-8")
        with self.assertRaises(SystemExit):
            cr.check_capability_catalog(self.root)

    def _remove_marker_block(self, target: Path, capability: str, version: int) -> None:
        import re

        text = target.read_text(encoding="utf-8")
        pattern = re.compile(
            rf"<!-- MERIDIAN:BEGIN capability={capability} v{version} -->\n?.*?<!-- MERIDIAN:END -->\n?",
            re.DOTALL,
        )
        match = pattern.search(text)
        self.assertIsNotNone(match, f"capability={capability} v{version} not found in {target}")
        target.write_text(text[: match.start()] + text[match.end() :], encoding="utf-8")

    def test_a_capability_removed_without_a_removes_declaration_still_fails(self) -> None:
        """The baseline guard's original task-014 behavior: an absence with
        no accounting migration is still an unauthorized change, retirement
        infrastructure or not."""
        self._remove_marker_block(self.root / "templates/workflows/governed-sdd/docs/workflows/IMPLEMENTATION.md", "spike-routing", 2)
        with self.assertRaises(SystemExit):
            cr.check_capability_marker_baselines(self.root)

    def test_a_capability_removed_by_a_declared_migration_passes(self) -> None:
        """Task 007: `check_capability_marker_baselines` must reuse the same
        `removes` declaration `meridian upgrade` honors, not a second,
        independent notion of what a legitimate removal looks like."""
        self._remove_marker_block(self.root / "templates/workflows/governed-sdd/docs/workflows/IMPLEMENTATION.md", "spike-routing", 2)
        (self.root / "migrations" / "999-retire-spike-routing.json").write_text(
            '{"id": "999-retire-spike-routing", "from": "1.1.20", "to": "1.1.21", '
            '"description": "test-only", "removes": '
            '[{"capability": "spike-routing", "capabilityVersion": 1}], '
            '"managedPaths": ["AGENTS.md", "CLAUDE.md"], "verification": ["test-only"]}',
            encoding="utf-8",
        )
        # No SystemExit: the recorded baseline's spike-routing entry is
        # stale relative to the live templates, but its absence is explained.
        cr.check_capability_marker_baselines(self.root)


class GovernedReviewWorktreeContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        shutil.copytree(ROOT / "templates", self.root / "templates")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_shipped_review_contract_passes(self) -> None:
        cr.check_governed_review_worktree_contract(self.root)

    def test_retired_primary_checkout_instruction_fails(self) -> None:
        review = (
            self.root
            / "templates/workflows/governed-sdd/docs/workflows/REVIEW.md"
        )
        review.write_text(
            review.read_text(encoding="utf-8")
            + "\nThe reviewer uses that same primary checkout.\n",
            encoding="utf-8",
        )
        with self.assertRaises(SystemExit):
            cr.check_governed_review_worktree_contract(self.root)

    def test_preflight_must_precede_substantive_review_boundary(self) -> None:
        review = (
            self.root
            / "templates/workflows/governed-sdd/docs/workflows/REVIEW.md"
        )
        text = review.read_text(encoding="utf-8")
        begin = re.search(r"<!-- MERIDIAN:BEGIN capability=task-worktree-review-procedure v\d+ -->", text).group(0)
        boundary = re.search(r"<!-- MERIDIAN:BEGIN capability=review-mode-boundary v\d+ -->", text).group(0)
        text = text.replace(begin, "TEMP-PREFLIGHT", 1)
        text = text.replace(boundary, begin, 1).replace("TEMP-PREFLIGHT", boundary, 1)
        review.write_text(text, encoding="utf-8")
        with self.assertRaises(SystemExit):
            cr.check_governed_review_worktree_contract(self.root)


class GovernedLifecycleTextTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        shutil.copytree(ROOT / "templates", self.root / "templates")
        shutil.copy(ROOT / "PROJECT_WORKFLOW.md", self.root / "PROJECT_WORKFLOW.md")
        self.workflows = self.root / "templates/workflows"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def append(self, relative: str, addition: str) -> None:
        path = self.workflows / relative
        path.write_text(path.read_text(encoding="utf-8") + addition, encoding="utf-8")

    def test_shipped_templates_pass(self) -> None:
        cr.check_governed_lifecycle_text(self.root)

    def test_each_retired_or_placeholder_text_fails(self) -> None:
        for phrase in cr.FORBIDDEN_TEMPLATE_TEXT:
            with self.subTest(phrase=phrase):
                self.append("lean-delivery/PROJECT_WORKFLOW.md", f"\n{phrase}\n")
                with self.assertRaises(SystemExit):
                    cr.check_governed_lifecycle_text(self.root)
                shutil.copy(ROOT / "templates/workflows/lean-delivery/PROJECT_WORKFLOW.md", self.workflows / "lean-delivery/PROJECT_WORKFLOW.md")

    def test_managed_block_that_edits_a_queue_row_fails_in_either_template(self) -> None:
        for relative in ("governed-sdd/docs/workflows/REVIEW.md", "lean-delivery/PROJECT_WORKFLOW.md"):
            with self.subTest(relative=relative):
                path = self.workflows / relative
                original = path.read_text(encoding="utf-8")
                path.write_text(
                    original.replace("<!-- MERIDIAN:END -->", "The reviewer updates its queue row.\n<!-- MERIDIAN:END -->", 1),
                    encoding="utf-8",
                )
                with self.assertRaises(SystemExit):
                    cr.check_governed_lifecycle_text(self.root)
                path.write_text(original, encoding="utf-8")

    def test_governed_block_naming_a_literal_location_fails_but_execution_assets_may(self) -> None:
        path = self.workflows / "governed-sdd/docs/workflows/REMEDIATION.md"
        original = path.read_text(encoding="utf-8")
        path.write_text(original.replace("<!-- MERIDIAN:END -->", "Read tasks/reviews/X.md.\n<!-- MERIDIAN:END -->", 1), encoding="utf-8")
        with self.assertRaises(SystemExit):
            cr.check_governed_lifecycle_text(self.root)
        path.write_text(original, encoding="utf-8")
        execution_assets = (self.workflows / "governed-sdd/PROJECT_WORKFLOW.md").read_text(encoding="utf-8")
        self.assertIn("tasks/handoffs/<TASK-ID>.md", execution_assets)
        cr.check_governed_lifecycle_text(self.root)

    def test_reviewer_identity_rule_in_a_second_place_fails(self) -> None:
        self.append("governed-sdd/docs/PULL_REQUEST_POLICY.md", '\n```bash\ngit commit --author="x <x@x>" -m m\n```\n')
        with self.assertRaises(SystemExit):
            cr.check_governed_lifecycle_text(self.root)

    def test_repository_copy_must_not_keep_the_smoke_line(self) -> None:
        path = self.root / "PROJECT_WORKFLOW.md"
        path.write_text(path.read_text(encoding="utf-8") + "\nProject integration smoke command: `none`.\n", encoding="utf-8")
        with self.assertRaises(SystemExit):
            cr.check_governed_lifecycle_text(self.root)


class CheckMigrationsVersionGateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        shutil.copytree(ROOT / "templates", self.root / "templates")
        shutil.copytree(ROOT / "capabilities", self.root / "capabilities")
        (self.root / "migrations").mkdir()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_chain(self, *steps: tuple[str, str], version: str) -> None:
        for index, (source, target) in enumerate(steps, start=1):
            migration_id = f"{index:03d}-step"
            (self.root / "migrations" / f"{migration_id}.json").write_text(
                json.dumps(
                    {
                        "id": migration_id,
                        "from": source,
                        "to": target,
                        "description": "test-only",
                        "managedPaths": ["AGENTS.md"],
                        "verification": ["test-only"],
                    }
                ),
                encoding="utf-8",
            )
        (self.root / "VERSION").write_text(f"{version}\n", encoding="utf-8")

    def run_check(self) -> str:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            cr.check_migrations(self.root)
        return output.getvalue()

    def test_version_equal_to_last_migration_passes(self) -> None:
        self.write_chain(("1.0.0", "1.0.1"), ("1.0.1", "1.0.2"), version="1.0.2")

        self.run_check()

    def test_version_ahead_of_last_migration_passes_for_cli_only_release(self) -> None:
        self.write_chain(("1.0.0", "1.0.1"), version="1.0.3")

        self.run_check()

    def test_version_compares_numerically_not_lexically(self) -> None:
        self.write_chain(("1.0.0", "1.0.9"), version="1.0.10")

        self.run_check()

    def test_last_migration_ahead_of_version_fails(self) -> None:
        self.write_chain(("1.0.0", "1.0.1"), ("1.0.1", "1.0.4"), version="1.0.3")
        output = io.StringIO()

        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit):
            cr.check_migrations(self.root)

        self.assertIn("ahead of the current release", output.getvalue())

    def test_non_contiguous_migration_chain_still_fails(self) -> None:
        self.write_chain(("1.0.0", "1.0.1"), ("1.0.5", "1.0.6"), version="1.0.6")
        output = io.StringIO()

        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit):
            cr.check_migrations(self.root)

        self.assertIn("not contiguous", output.getvalue())

    def test_same_version_migration_fails_and_names_the_file(self) -> None:
        self.write_chain(("1.0.0", "1.0.0"), version="1.0.0")
        output = io.StringIO()

        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit):
            cr.check_migrations(self.root)

        self.assertIn("migrations/001-step.json", output.getvalue())
        self.assertIn("same version", output.getvalue())

    def initialize_tagged_release(self, version: str, migrations: list[str]) -> None:
        (self.root / "releases").mkdir()
        (self.root / "releases" / f"{version}.json").write_text(
            json.dumps({"migrations": migrations}), encoding="utf-8"
        )
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=self.root, check=True)
        subprocess.run(["git", "config", "user.name", "Meridian Test"], cwd=self.root, check=True)
        subprocess.run(["git", "config", "user.email", "meridian@example.invalid"], cwd=self.root, check=True)
        (self.root / "README.md").write_text("# Test\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=self.root, check=True)
        subprocess.run(["git", "commit", "-qm", "initial"], cwd=self.root, check=True)
        subprocess.run(["git", "tag", f"v{version}"], cwd=self.root, check=True)

    def test_migration_to_tagged_version_requires_its_release_ledger_entry(self) -> None:
        self.write_chain(("1.0.0", "1.0.1"), version="1.0.1")
        self.initialize_tagged_release("1.0.1", [])
        output = io.StringIO()

        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit):
            cr.check_migrations(self.root)

        self.assertIn("migrations/001-step.json", output.getvalue())
        self.assertIn("release-ledger", output.getvalue())

    def test_migration_in_tagged_release_ledger_passes(self) -> None:
        self.write_chain(("1.0.0", "1.0.1"), version="1.0.1")
        self.initialize_tagged_release("1.0.1", ["001-step"])

        self.run_check()

    def test_malformed_adopt_existing_paths_declaration_fails(self) -> None:
        self.write_chain(("1.0.0", "1.0.1"), version="1.0.1")
        path = self.root / "migrations/001-step.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record["adoptExistingPaths"] = "AGENTS.md"
        path.write_text(json.dumps(record), encoding="utf-8")
        output = io.StringIO()

        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit):
            cr.check_migrations(self.root)

        self.assertIn("adoptExistingPaths must be a list", output.getvalue())


class CheckReleasesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "migrations").mkdir()
        (self.root / "releases").mkdir()
        (self.root / "VERSION").write_text("1.0.2\n", encoding="utf-8")
        (self.root / "migrations" / "001-step.json").write_text(
            json.dumps({"id": "001-step", "from": "1.0.0", "to": "1.0.1"}),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_release(self, version: str, filename: str | None = None, **overrides: object) -> None:
        record = {
            "version": version,
            "releaseDate": "2026-01-01",
            "gitTag": f"v{version}",
            "protocolVersion": 2,
            "workflowBaselineVersion": "1.0.1",
            "baselineChanged": False,
            "migrations": [],
        }
        record.update(overrides)
        (self.root / "releases" / f"{filename or version}.json").write_text(
            json.dumps(record), encoding="utf-8"
        )

    def assert_fails(self, message: str) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit):
            cr.check_releases(self.root)
        self.assertIn(message, output.getvalue())

    def test_valid_ledger_passes(self) -> None:
        self.write_release("1.0.1", baselineChanged=True, migrations=["001-step"])
        self.write_release("1.0.2")

        cr.check_releases(self.root)

    def test_numeric_ordering_passes(self) -> None:
        (self.root / "VERSION").write_text("1.0.10\n", encoding="utf-8")
        self.write_release("1.0.9")
        self.write_release("1.0.10")

        cr.check_releases(self.root)

    def test_missing_record_for_current_version_fails(self) -> None:
        self.write_release("1.0.1", baselineChanged=True, migrations=["001-step"])

        self.assert_fails("is missing for the current VERSION")

    def test_filename_version_mismatch_fails(self) -> None:
        self.write_release("1.0.1", filename="1.0.2")

        self.assert_fails("does not match the filename")

    def test_non_monotonic_versions_fail(self) -> None:
        self.write_release("1.0.2")
        self.write_release("1.0.02")

        self.assert_fails("monotonically increasing")

    def test_baseline_changed_inconsistent_with_migrations_fails(self) -> None:
        self.write_release("1.0.1", baselineChanged=False, migrations=["001-step"])
        self.write_release("1.0.2")

        self.assert_fails("baselineChanged")

    def test_prerelease_suffix_fails(self) -> None:
        (self.root / "VERSION").write_text("1.0.2-rc.1\n", encoding="utf-8")
        self.write_release("1.0.2-rc.1")

        self.assert_fails("prerelease or build suffix")

    def test_build_suffix_fails(self) -> None:
        (self.root / "VERSION").write_text("1.0.2+dev\n", encoding="utf-8")
        self.write_release("1.0.2+dev")

        self.assert_fails("prerelease or build suffix")

    def test_latest_baseline_mismatch_fails(self) -> None:
        self.write_release("1.0.2", workflowBaselineVersion="1.0.0")

        self.assert_fails("migration-derived baseline")


class MachinePathTest(unittest.TestCase):
    """The guard rejects home-directory paths in tracked text files."""

    # Built at runtime so this file does not contain a forbidden path itself.
    FORBIDDEN = {
        "macos": "/Us" + "ers/alice/dev/project",
        "linux": "/ho" + "me/alice/project",
        "windows": "C:\\Us" + "ers\\alice\\project",
    }

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def track(self, name: str, content: bytes) -> None:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        subprocess.run(["git", "-C", str(self.root), "add", name], check=True)

    def assert_fails(self, fragment: str, **kwargs: object) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit):
            cr.check_no_machine_paths(self.root, **kwargs)
        self.assertIn(fragment, output.getvalue())

    def test_clean_tree_passes(self) -> None:
        self.track("README.md", b"Use <checkout>/scripts and ../meridian-task-1.\n")
        self.track("docs/a.md", b"path `/Us" + b"ers/<name>/x` placeholder\n")
        self.track("image.bin", b"\xff\xfe" + self.FORBIDDEN["macos"].encode())

        cr.check_no_machine_paths(self.root)

    def test_each_forbidden_form_fails_naming_file_and_line(self) -> None:
        for label, value in self.FORBIDDEN.items():
            with self.subTest(label):
                self.track(f"docs/{label}.md", f"ok\nsee {value} here\n".encode())
                self.assert_fails(f"docs/{label}.md:2")
                subprocess.run(
                    ["git", "-C", str(self.root), "rm", "-q", "-f", f"docs/{label}.md"],
                    check=True,
                )

    def test_untracked_file_is_ignored(self) -> None:
        (self.root / "scratch.md").write_text(self.FORBIDDEN["macos"], encoding="utf-8")

        cr.check_no_machine_paths(self.root)

    def test_allowed_exception_passes_only_for_that_file(self) -> None:
        self.track("frozen.md", self.FORBIDDEN["linux"].encode())
        cr.check_no_machine_paths(self.root, allowed=frozenset({"frozen.md"}))

        self.track("other.md", self.FORBIDDEN["linux"].encode())
        self.assert_fails("other.md:1", allowed=frozenset({"frozen.md"}))

    def test_repository_has_no_machine_paths(self) -> None:
        cr.check_no_machine_paths()


class ManagedDigestTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "project"
        shutil.copytree(ROOT, self.root, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        self.target = self.root / "docs/CONTEXT_BUDGET_POLICY.md"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def manifest(self) -> dict[str, object]:
        return json.loads((self.root / ".meridian/manifest.json").read_text(encoding="utf-8"))

    def write_manifest(self, manifest: dict[str, object]) -> None:
        (self.root / ".meridian/manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )

    def drift(self) -> None:
        self.target.write_text(self.target.read_text(encoding="utf-8") + "\nDrift.\n", encoding="utf-8")

    def test_no_drift_passes_without_writing(self) -> None:
        before = (self.root / ".meridian/manifest.json").read_bytes()

        cr.check_managed_digests(self.root)

        self.assertEqual(before, (self.root / ".meridian/manifest.json").read_bytes())

    def test_drift_names_file_digests_and_refresh_command(self) -> None:
        self.drift()
        output = io.StringIO()

        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit):
            cr.check_managed_digests(self.root)

        message = output.getvalue()
        self.assertIn("docs/CONTEXT_BUDGET_POLICY.md", message)
        self.assertIn("expected", message)
        self.assertIn("got", message)
        self.assertIn("--write-managed-digests", message)

    def test_stale_digest_evidence_fails(self) -> None:
        manifest = self.manifest()
        profiles = manifest["capabilityProfiles"]
        assert isinstance(profiles, dict)
        capabilities = profiles["meridian-self-hosting"]["capabilities"]
        assert isinstance(capabilities, dict)
        installation = capabilities["context-budgeting"]["installation"]
        assert isinstance(installation, dict)
        installation["evidence"][0] = "sha256:" + "0" * 64
        self.write_manifest(manifest)
        output = io.StringIO()

        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit):
            cr.check_managed_digests(self.root)

        self.assertIn("stale digest evidence", output.getvalue())

    def test_refresh_fixes_drift_and_is_idempotent(self) -> None:
        self.drift()

        changes = cr.write_managed_digests(self.root)
        after_first_write = (self.root / ".meridian/manifest.json").read_bytes()
        cr.check_managed_digests(self.root)

        self.assertTrue(any("docs/CONTEXT_BUDGET_POLICY.md" in change for change in changes))
        self.assertEqual([], cr.write_managed_digests(self.root))
        self.assertEqual(after_first_write, (self.root / ".meridian/manifest.json").read_bytes())

    def test_refresh_restores_a_declared_surface_the_upgrade_dropped(self) -> None:
        manifest = self.manifest()
        managed_files = manifest["managedFiles"]
        assert isinstance(managed_files, dict)
        managed_files.pop("docs/COMPLETION_REPORT_TEMPLATE.md")
        self.write_manifest(manifest)
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit):
            cr.check_managed_digests(self.root)
        self.assertIn("has no managedFiles digest", output.getvalue())

        changes = cr.write_managed_digests(self.root)

        self.assertEqual(1, len(changes))
        self.assertIn("docs/COMPLETION_REPORT_TEMPLATE.md", changes[0])
        cr.check_managed_digests(self.root)
        restored = self.manifest()["managedFiles"]
        assert isinstance(restored, dict)
        self.assertEqual(sorted(restored), list(restored))

    def test_refresh_recomputes_evidence_after_an_upgrade_rewrote_managed_files(self) -> None:
        manifest = self.manifest()
        managed_files = manifest["managedFiles"]
        assert isinstance(managed_files, dict)
        managed_files["docs/CONTEXT_BUDGET_POLICY.md"] = "0" * 64
        profiles = manifest["capabilityProfiles"]
        assert isinstance(profiles, dict)
        capabilities = profiles["meridian-self-hosting"]["capabilities"]
        assert isinstance(capabilities, dict)
        capabilities["context-budgeting"]["installation"]["evidence"] = ["sha256:" + "1" * 64]
        self.write_manifest(manifest)

        cr.write_managed_digests(self.root)

        cr.check_managed_digests(self.root)
        self.assertEqual([], cr.write_managed_digests(self.root))

    def test_refresh_refuses_a_missing_listed_file(self) -> None:
        self.target.unlink()
        output = io.StringIO()

        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit):
            cr.write_managed_digests(self.root)

        self.assertIn("listed file is missing: docs/CONTEXT_BUDGET_POLICY.md", output.getvalue())

    def test_repository_check_and_profile_doctor_agree_on_drift(self) -> None:
        self.drift()
        check_output = io.StringIO()
        doctor_output = io.StringIO()
        with contextlib.redirect_stdout(check_output), self.assertRaises(SystemExit):
            cr.check_managed_digests(self.root)
        with contextlib.redirect_stdout(doctor_output):
            doctor_status = cr.meridian.profile_doctor(
                self.root, self.root, "meridian-self-hosting"
            )

        self.assertEqual(2, doctor_status, doctor_output.getvalue())
        expected = "drifted managed-copy surface docs/CONTEXT_BUDGET_POLICY.md"
        self.assertIn(expected, check_output.getvalue())
        self.assertIn(expected, doctor_output.getvalue())

    def test_completion_template_and_unchained_validation_rule_are_declared(self) -> None:
        manifest = self.manifest()
        managed_files = manifest["managedFiles"]
        assert isinstance(managed_files, dict)
        self.assertIn("docs/COMPLETION_REPORT_TEMPLATE.md", managed_files)

        profiles = manifest["capabilityProfiles"]
        assert isinstance(profiles, dict)
        capabilities = profiles["meridian-self-hosting"]["capabilities"]
        assert isinstance(capabilities, dict)
        execution_evidence = capabilities["execution-evidence"]
        assert isinstance(execution_evidence, dict)
        surfaces = execution_evidence["managedSurface"]
        assert isinstance(surfaces, list)
        self.assertIn(
            {"form": "managed-copy", "path": "docs/COMPLETION_REPORT_TEMPLATE.md"},
            surfaces,
        )

        profile = (self.root / "docs/EXECUTION_EVIDENCE_PROFILE.md").read_text(encoding="utf-8")
        self.assertIn("Run every validation command of record as its own command", profile)
        self.assertIn("Never join it with `&&` or `;`", profile)


class SelfHostingBaselineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "project"
        shutil.copytree(ROOT, self.root, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        self.manifest_path = self.root / ".meridian/manifest.json"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def set_baseline(self, version: str) -> None:
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        manifest["workflowBaselineVersion"] = version
        self.manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    def test_current_baseline_passes(self) -> None:
        cr.check_self_hosting_baseline(self.root)

    def test_lagging_baseline_fails_and_names_the_fix(self) -> None:
        self.set_baseline("1.1.49")
        output = io.StringIO()

        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit):
            cr.check_self_hosting_baseline(self.root)

        message = output.getvalue()
        self.assertIn("1.1.49", message)
        self.assertIn("upgrade --project . --check", message)
        self.assertIn("--apply", message)

    def test_migration_ahead_of_version_is_not_required_yet(self) -> None:
        source = sorted((self.root / "migrations").glob("*.json"))[-1]
        data = json.loads(source.read_text(encoding="utf-8"))
        data["id"] = "999-ahead-of-version"
        data["from"] = data["to"]
        data["to"] = "99.0.0"
        (self.root / "migrations/999-ahead-of-version.json").write_text(json.dumps(data), encoding="utf-8")

        cr.check_self_hosting_baseline(self.root)


class CatalogSurfaceMigrationTest(unittest.TestCase):
    """A catalog surface added after a release must be carried by a migration."""

    ADDED = "docs/NEW_SURFACE.md"

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "capabilities").mkdir()
        (self.root / "migrations").mkdir()
        (self.root / "VERSION").write_text("1.2.8\n", encoding="utf-8")
        self.previous = {
            "capabilities": {"alpha": {"managedSurfaces": [{"path": "docs/A.md"}]}}
        }
        current = {
            "capabilities": {
                "alpha": {"managedSurfaces": [{"path": "docs/A.md"}, {"path": self.ADDED}]},
                "beta": {"managedSurfaces": [{"path": "docs/B.md"}]},
            }
        }
        (self.root / "capabilities/catalog-v1.json").write_text(
            json.dumps(current), encoding="utf-8"
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_migration(self, name: str, to: str, managed_paths: list[str]) -> None:
        (self.root / "migrations" / name).write_text(
            json.dumps({"id": name[:-5], "to": to, "managedPaths": managed_paths}),
            encoding="utf-8",
        )

    def test_additions_name_only_new_paths_of_known_capabilities(self) -> None:
        current = json.loads((self.root / "capabilities/catalog-v1.json").read_text())

        self.assertEqual(
            cr.catalog_surface_additions(self.previous, current), [("alpha", self.ADDED)]
        )

    def test_added_surface_without_a_listing_migration_fails_naming_both(self) -> None:
        self.write_migration("001-other.json", "1.2.8", ["docs/A.md"])
        output = io.StringIO()

        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit):
            cr.check_catalog_surface_migrations(self.root, self.previous, "1.2.7")

        self.assertIn("alpha", output.getvalue())
        self.assertIn(self.ADDED, output.getvalue())

    def test_listing_in_a_next_release_migration_passes(self) -> None:
        self.write_migration("001-other.json", "1.2.8", ["docs/A.md", self.ADDED])

        cr.check_catalog_surface_migrations(self.root, self.previous, "1.2.7")

    def test_a_listing_in_an_already_released_migration_does_not_count(self) -> None:
        self.write_migration("001-old.json", "1.2.7", [self.ADDED])

        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit):
            cr.check_catalog_surface_migrations(self.root, self.previous, "1.2.7")

    def test_unchanged_catalog_passes_without_migrations(self) -> None:
        unchanged = json.loads((self.root / "capabilities/catalog-v1.json").read_text())

        cr.check_catalog_surface_migrations(self.root, unchanged, "1.2.7")


class StopCodeRegistryCheckTest(unittest.TestCase):
    TEST_NAME = "tests.test_emit.EmitTest.test_tool_line"

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        for directory in ("capabilities", "templates", "scripts", "tests"):
            (self.root / directory).mkdir()
        (self.root / "scripts/meridian.py").write_text("", encoding="utf-8")
        (self.root / "tests/test_emit.py").write_text(
            "class EmitTest:\n    def test_tool_line(self):\n        pass\n", encoding="utf-8"
        )
        self.registry = [
            {"code": "ALPHA_STOP", "class": "tool", "test": self.TEST_NAME},
            {"code": "BETA_STOP", "class": "judgment"},
        ]
        self.text = "Stop with `ALPHA_STOP` or `BETA_STOP`; returns `REUSE`, `FULL`.\n"
        self.write()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write(self) -> None:
        (self.root / "capabilities/stop-codes-v1.json").write_text(
            json.dumps({"version": 1, "stops": self.registry}), encoding="utf-8"
        )
        (self.root / "templates/workflow.md").write_text(self.text, encoding="utf-8")

    def failure(self) -> str:
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit):
            cr.check_stop_code_registry(self.root)
        return output.getvalue()

    def test_registered_text_passes_and_unrelated_uppercase_lists_are_ignored(self) -> None:
        cr.check_stop_code_registry(self.root)

    def test_unregistered_token_after_blocked_names_file_line_and_token(self) -> None:
        self.text += "\nThen BLOCKED GAMMA_STOP: detail.\n"
        self.write()
        self.assertIn("templates/workflow.md:3: unregistered stop code GAMMA_STOP", self.failure())

    def test_unregistered_token_in_a_stop_code_list_fails(self) -> None:
        self.text = "Stop with `ALPHA_STOP`, `GAMMA_STOP`, or `BETA_STOP`.\n"
        self.write()
        self.assertIn("templates/workflow.md:1: unregistered stop code GAMMA_STOP", self.failure())

    def test_console_style_quoted_list_in_tests_is_checked(self) -> None:
        (self.root / "tests/test_project_console.py").write_text(
            'REASONS = (\n    "ALPHA_STOP", "BETA_STOP",\n    "GAMMA_STOP",\n)\n', encoding="utf-8"
        )
        self.assertIn("tests/test_project_console.py:3: unregistered stop code GAMMA_STOP", self.failure())

    def test_tool_code_without_a_test_or_with_a_missing_test_fails(self) -> None:
        del self.registry[0]["test"]
        self.write()
        self.assertIn("ALPHA_STOP is class tool but has no test field", self.failure())
        self.registry[0]["test"] = "tests.test_emit.EmitTest.test_absent"
        self.write()
        self.assertIn("ALPHA_STOP names a test that does not exist", self.failure())

    def test_registered_code_mentioned_nowhere_fails(self) -> None:
        self.registry.append({"code": "DEAD_STOP", "class": "judgment"})
        self.write()
        self.assertIn("DEAD_STOP is registered but no managed text or CLI output mentions it", self.failure())

    def test_code_emitted_only_by_the_cli_is_not_dead(self) -> None:
        self.registry.append({"code": "CLI_STOP", "class": "judgment"})
        self.write()
        (self.root / "scripts/meridian.py").write_text('report("C1", "CLI_STOP")\n', encoding="utf-8")
        cr.check_stop_code_registry(self.root)

    def test_blocked_line_without_a_code_in_managed_text_fails(self) -> None:
        self.text += "BLOCKED: some free-form reason.\n"
        self.write()
        self.assertIn("templates/workflow.md:2: BLOCKED without a registered stop code", self.failure())
        self.text = "If it cannot be read, return `BLOCKED` without changing files.\n"
        self.write()
        self.assertIn("templates/workflow.md:1: BLOCKED without a registered stop code", self.failure())

    def test_coded_placeholder_and_verdict_enumerations_in_managed_text_pass(self) -> None:
        self.text += (
            "Report `BLOCKED ALPHA_STOP` or `BLOCKED <CODE>`.\n"
            "Return APPROVE, CHANGES_REQUESTED, or BLOCKED.\n"
            "## Attempt <N> - <CHANGES_REQUESTED | APPROVE | BLOCKED>\n"
        )
        self.write()
        cr.check_stop_code_registry(self.root)

    def test_verdict_proximity_does_not_exempt_a_stop(self) -> None:
        self.text += "After two `CHANGES_REQUESTED` verdicts, stop and report `BLOCKED`.\n"
        self.write()
        self.assertIn("templates/workflow.md:2: BLOCKED without a registered stop code", self.failure())

    def test_uncoded_blocked_in_the_cli_fails_and_coded_forms_pass(self) -> None:
        cli = self.root / "scripts/meridian.py"
        cli.write_text('STATE = "BLOCKED"\nFORMAT = f"BLOCKED {code}: {detail}; resume: {resume}"\n'
                       'print("BLOCKED ALPHA_STOP: detail")\n', encoding="utf-8")
        cr.check_stop_code_registry(self.root)
        cli.write_text('x = 1\nraise MeridianError("validation BLOCKED: bad id")\n', encoding="utf-8")
        self.assertIn("scripts/meridian.py:2: BLOCKED without a registered stop code", self.failure())
        cli.write_text('print(f"BLOCKED: {error}")\n', encoding="utf-8")
        self.assertIn("scripts/meridian.py:1: BLOCKED without a registered stop code", self.failure())
        cli.write_text('print("BLOCKED NOT_REGISTERED: detail")\n', encoding="utf-8")
        self.assertIn("scripts/meridian.py:1: BLOCKED without a registered stop code", self.failure())

    def test_repository_passes(self) -> None:
        cr.check_stop_code_registry(ROOT)



class PrivateNameGuardTest(unittest.TestCase):
    """Exercise matching without recording real consumer identities."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        self.denied = frozenset({hashlib.sha256(b"example").hexdigest()})

    def track(self, name: str, content: bytes) -> None:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        subprocess.run(["git", "-C", str(self.root), "add", name], check=True)

    def test_plain_identifier_and_path_matches_include_task_archives(self) -> None:
        for value in ("Example", "EXAMPLE_ROUTING", "../example", "example-domain", "example.md"):
            with self.subTest(value=value):
                self.track("tasks/done/record.md", ("safe\n" + value).encode())
                output = io.StringIO()
                with contextlib.redirect_stdout(output), self.assertRaises(SystemExit):
                    cr.check_no_private_names(self.root, self.denied)
                self.assertIn("tasks/done/record.md:2", output.getvalue())
                self.assertNotIn(value, output.getvalue())

    def test_substrings_and_untracked_files_are_ignored(self) -> None:
        self.track("safe.md", b"refusal examples preexample example2")
        (self.root / "scratch.md").write_text("example")
        cr.check_no_private_names(self.root, self.denied)
        # The production hashes must also leave this known substring intact.
        cr.check_no_private_names(self.root)

    def test_binary_artifacts_cannot_hide_ascii_names(self) -> None:
        self.track("artifact.bin", b"\xff EXAMPLE \xfe")
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit):
            cr.check_no_private_names(self.root, self.denied)


if __name__ == "__main__":
    unittest.main()
