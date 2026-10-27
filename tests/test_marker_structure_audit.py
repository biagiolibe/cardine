"""Task 146: standalone marker blocks, managed-copy digest audit, consumer profiles."""

from __future__ import annotations

import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import cardine_cli  # noqa: E402
from cardine.templates import audit as owner_templates_audit
from cardine.templates import catalog as owner_templates_catalog

from cardine.templates import markers as templates_markers
from synthetic_upgrade_support import RELEASED, SyntheticFramework
import cardine.shared.errors as shared_errors
from cardine.templates import marker_audit as owner_templates_marker_audit
from cardine.templates import migrations as owner_templates_migrations

CLI = ROOT / "scripts" / "cardine_cli.py"
REVIEW_PROMPT = "docs/CODE_REVIEW_PROMPT.md"

# A compact stand-in for the 1.2.6 prompt: three inline markers inside prose.
LEGACY_REVIEW_PROMPT = """# Code Review and Integration Prompt

```text
Review and integrate <TASK-ID>.

<!-- CARDINE:BEGIN capability=task-worktree-review v4 -->Run this in a fresh session.<!-- CARDINE:END --> Re-derive evidence.

Review scope. <!-- CARDINE:BEGIN capability=manual-verification-review-check v1 -->Confirm the rationale.<!-- CARDINE:END --> Read cited documents. <!-- CARDINE:BEGIN capability=ci-verified-validation v1 -->Follow the CI-first rule.<!-- CARDINE:END --> Report findings.
```
"""


from cardine.templates import adoption as owner_templates_adoption

def copy_tree(source: Path, destination: Path) -> None:
    for path in source.rglob("*"):
        if path.is_file():
            target = destination / path.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)


class FrameworkFixture(unittest.TestCase):
    MODE = "single"

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        base = Path(self.temporary.name)
        self.framework = base / "framework"
        self.project = base / "project"
        for name in ("templates", "migrations", "capabilities"):
            shutil.copytree(ROOT / name, self.framework / name)
        shutil.copyfile(ROOT / "VERSION", self.framework / "VERSION")
        self.project.mkdir()
        # Row TR2b: these scenarios start from a release that still shipped the two folded documents.
        copy_tree(RELEASED, self.framework / "templates" / "single")
        copy_tree(self.framework / "templates" / "single", self.project)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(CLI),
                "--framework-root",
                str(self.framework),
                *arguments,
                "--project",
                str(self.project),
            ],
            text=True,
            capture_output=True,
            check=False,
        )

    def lock(self) -> None:
        locked = self.run_cli("lock", "--mode", self.MODE)
        self.assertEqual(locked.returncode, 0, locked.stdout + locked.stderr)

    def audit(self) -> tuple[int, str]:
        output = io.StringIO()
        with redirect_stdout(output):
            code = owner_templates_audit.run_audit(self.project, self.framework, self.MODE)
        return code, output.getvalue()

    def manifest(self) -> dict[str, object]:
        return json.loads((self.project / ".cardine/manifest.json").read_text(encoding="utf-8"))


class StandaloneBlockTemplateTest(unittest.TestCase):
    def read(self, relative: str) -> str:
        return (ROOT / "templates/single" / relative).read_text(encoding="utf-8")

    def test_review_prompt_is_folded_into_the_review_procedure_with_its_checklist(self) -> None:
        # TR2b deleted the prompt; REVIEW.md applies a project's `## Project review checklist` section.
        self.assertFalse((ROOT / "templates/single" / REVIEW_PROMPT).exists())
        self.assertIn("Project review checklist", self.read("docs/workflows/REVIEW.md"))

    def test_audit_prompt_runs_the_project_specific_checks_section(self) -> None:
        text = self.read("docs/AUDIT_PROMPT_READ_ONLY.md")
        self.assertEqual(templates_markers.marker_pairs(text), [("audit-prompt", 2)])
        block = templates_markers.extract_marker_block(text, "audit-prompt", 2)
        self.assertIn("## Project-specific checks", block)
        self.assertIn("cite an accepted ADR", block)

    def test_inline_markers_became_complete_standalone_blocks(self) -> None:
        workflow = self.read("PROJECT_WORKFLOW.md")
        block = templates_markers.extract_marker_block(workflow, "validation-scoping", 2)
        self.assertIn("## Validation and completion", block)
        self.assertIn("frozen `validationScoping`", block)
        policy = self.read("docs/CONTEXT_READING_POLICY.md")
        reading = templates_markers.extract_marker_block(policy, "bounded-context-readers", 2)
        self.assertIn("cardine context authority <TASK-ID>", reading)
        self.assertIn("Read large files by range", reading)
        self.assertNotRegex(policy, r"(?m)^\d+\. <!-- CARDINE:BEGIN capability=")

    def test_lifecycle_and_remote_cleanup_are_managed_capabilities(self) -> None:
        text = self.read("docs/WORKTREE_LIFECYCLE.md")
        self.assertEqual(templates_markers.marker_pairs(text), [("worktree-command-locations", 3), ("worktree-lifecycle", 5)])
        # TR2b retired `remote-branch-cleanup` with the integration policy that carried it.
        self.assertFalse((ROOT / "templates/single/docs/INTEGRATION_POLICY.md").exists())

    def test_new_blocks_audit_as_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            copy_tree(ROOT / "templates/single", project)
            results = owner_templates_marker_audit.audit_capability_markers(project, ROOT, "single")
            self.assertFalse([item for item in results if item[0] != "PASS"], results)
            names = " ".join(detail for _status, detail in results)
            for capability in (
                "worktree-lifecycle",
                "bounded-context-readers",
            ):
                self.assertIn(f"capability={capability}", names)


class RetiredInlineMarkerUpgradeTest(FrameworkFixture):
    def write_migration(self, identifier: str, source: str, target: str, paths: list[str], **declared: object) -> None:
        record = {
            "id": identifier, "from": source, "to": target, "description": "Synthetic " + identifier,
            "managedPaths": paths, "verification": ["fixture assertions"], **declared,
        }
        (self.framework / "migrations" / f"{identifier}.json").write_text(json.dumps(record), encoding="utf-8")

    def locked_at_legacy_prompt(self, local_prompt: str | None = None) -> str:
        """Lock a project at 1.2.6 with the legacy prompt, then return the target template."""
        template = self.framework / "templates/single" / REVIEW_PROMPT
        current = template.read_text(encoding="utf-8")
        template.write_text(LEGACY_REVIEW_PROMPT, encoding="utf-8")
        (self.framework / "VERSION").write_text("1.2.6\n", encoding="utf-8")
        self.write_migration("001-synthetic-legacy", "1.2.5", "1.2.6", [])
        shutil.rmtree(self.project)
        self.project.mkdir()
        copy_tree(self.framework / "templates/single", self.project)
        self.lock()
        template.write_text(current, encoding="utf-8")
        (self.framework / "VERSION").write_text("1.2.7\n", encoding="utf-8")
        self.write_migration(
            "002-synthetic-restructure", "1.2.6", "1.2.7", [REVIEW_PROMPT],
            restructures=[{
                "path": REVIEW_PROMPT,
                "replacedBy": {"capability": "code-review-prompt", "capabilityVersion": 3},
                "retiredMarkers": [
                    {"capability": "task-worktree-review", "capabilityVersion": 4},
                    {"capability": "manual-verification-review-check", "capabilityVersion": 1},
                    {"capability": "ci-verified-validation", "capabilityVersion": 1},
                ],
            }],
        )
        if local_prompt is not None:
            (self.project / REVIEW_PROMPT).write_text(local_prompt, encoding="utf-8")
        return current

    def customized_prompt(self) -> str:
        return (
            LEGACY_REVIEW_PROMPT.replace("Run this in a fresh session.", "Run this in a fresh session (project rule).")
            .replace("Review scope.", "Review scope, plus the project's security rule.")
            + "\n## Project review checklist\n\n- Check the migration note.\n"
        )

    def test_prose_around_retired_markers_survives_in_a_backup_and_is_reported(self) -> None:
        current = self.locked_at_legacy_prompt(self.customized_prompt())
        before = (self.project / REVIEW_PROMPT).read_text(encoding="utf-8")

        checked = self.run_cli("upgrade", "--check")
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertRegex(checked.stdout, r"RESTRUCTURE\s+docs/CODE_REVIEW_PROMPT.md")
        self.assertIn("CODE_REVIEW_PROMPT.md.cardine-pre-restructure.bak", checked.stdout)
        self.assertIn("task-worktree-review v4", checked.stdout)
        self.assertEqual((self.project / REVIEW_PROMPT).read_text(encoding="utf-8"), before)

        applied = self.run_cli("upgrade", "--apply")
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        backup = self.project / (REVIEW_PROMPT + ".cardine-pre-restructure.bak")
        self.assertEqual(backup.read_text(encoding="utf-8"), before)
        upgraded = (self.project / REVIEW_PROMPT).read_text(encoding="utf-8")
        self.assertTrue(upgraded.startswith(current.rstrip("\n")))
        self.assertIn("## Project review checklist\n\n- Check the migration note.", upgraded)
        self.assertEqual(
            templates_markers.marker_pairs(upgraded), [("code-review-prompt", 2)]
        )
        self.assertNotIn("project rule", upgraded)
        self.assertIn("project rule", backup.read_text(encoding="utf-8"))
        code, output = self.audit()
        self.assertNotRegex(output, r"(?m)^FAIL\s")

    def test_a_second_restructure_never_overwrites_an_existing_backup(self) -> None:
        self.locked_at_legacy_prompt(self.customized_prompt())
        first = self.project / (REVIEW_PROMPT + ".cardine-pre-restructure.bak")
        first.write_text("earlier backup\n", encoding="utf-8")

        applied = self.run_cli("upgrade", "--apply")

        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        self.assertEqual(first.read_text(encoding="utf-8"), "earlier backup\n")
        second = self.project / (REVIEW_PROMPT + ".cardine-pre-restructure.bak.1")
        self.assertIn("project rule", second.read_text(encoding="utf-8"))

    def test_an_unmodified_legacy_prompt_is_replaced_without_a_backup(self) -> None:
        current = self.locked_at_legacy_prompt()

        applied = self.run_cli("upgrade", "--apply")

        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        self.assertEqual((self.project / REVIEW_PROMPT).read_text(encoding="utf-8"), current)
        self.assertFalse(list(self.project.glob("docs/*.bak*")))

    def test_the_capabilities_of_the_folded_documents_are_no_longer_required(self) -> None:
        # TR2b folded both documents into REVIEW.md and retired every block they alone carried.
        requirements = owner_templates_migrations.capability_requirements(ROOT)
        retired = owner_templates_migrations.retired_capability_ids(ROOT)
        for name in ("ci-verified-validation", "code-review-prompt", "task-worktree-integration",
                     "remote-branch-cleanup", "task-worktree-review", "manual-verification-review-check"):
            self.assertNotIn(name, requirements)
        for name in ("ci-verified-validation", "code-review-prompt", "task-worktree-integration",
                     "remote-branch-cleanup"):
            self.assertIn(name, retired)

    def test_restructure_removes_retired_blocks_from_a_carried_checklist(self) -> None:
        current = self.locked_at_legacy_prompt(
            LEGACY_REVIEW_PROMPT
            + "\n## Project review checklist\n\n"
            + "- Keep this checklist item.\n\n"
            + "<!-- CARDINE:BEGIN capability=task-worktree-review v4 -->Retired review text.<!-- CARDINE:END -->\n\n"
            + "<!-- CARDINE:BEGIN capability=manual-verification-review-check v1 -->Retired manual text.<!-- CARDINE:END -->\n\n"
            + "<!-- CARDINE:BEGIN capability=ci-verified-validation v1 -->Retired CI text.<!-- CARDINE:END -->\n"
        )

        applied = self.run_cli("upgrade", "--apply")

        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        upgraded = (self.project / REVIEW_PROMPT).read_text(encoding="utf-8")
        self.assertTrue(upgraded.startswith(current.rstrip("\n")))
        self.assertTrue(upgraded.endswith("## Project review checklist\n\n- Keep this checklist item.\n"))
        self.assertEqual(templates_markers.marker_pairs(upgraded), [("code-review-prompt", 2)])
        code, output = self.audit()
        self.assertNotRegex(output, r"(?m)^FAIL\\s")

    def test_restructure_reports_an_edited_retired_marker_and_keeps_the_backup(self) -> None:
        local = (
            LEGACY_REVIEW_PROMPT
            + "\n## Project review checklist\n\n"
            + "<!-- CARDINE:BEGIN capability=task-worktree-review v4 -->Edited retired text.<!-- CARDINE:END -->\n"
        )
        self.locked_at_legacy_prompt(local)

        checked = self.run_cli("upgrade", "--check")
        applied = self.run_cli("upgrade", "--apply")

        self.assertIn("edited retired marker content (task-worktree-review v4)", checked.stdout)
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        backup = self.project / (REVIEW_PROMPT + ".cardine-pre-restructure.bak")
        self.assertIn("Edited retired text.", backup.read_text(encoding="utf-8"))
        self.assertNotIn("Edited retired text.", (self.project / REVIEW_PROMPT).read_text(encoding="utf-8"))


class WrappedTextUpgradeTest(unittest.TestCase):
    """A block that newly wraps unmarked text never duplicates a customized copy."""

    def scenario(self, mode: str, relative: str, capability: str, edit: tuple[str, str]) -> tuple[str, str]:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            framework, project = base / "framework", base / "project"
            fixture = SyntheticFramework(framework, "1.2.6")
            template = framework / "templates/single" / relative
            current = template.read_text(encoding="utf-8")
            version = re.search(rf"capability={capability} v(\d+) -->", current).group(1)
            legacy = current.replace(f"<!-- CARDINE:BEGIN capability={capability} v{version} -->\n", "")
            end = legacy.rindex("<!-- CARDINE:END -->\n")
            legacy = legacy[:end] + legacy[end + len("<!-- CARDINE:END -->\n"):]
            template.write_text(legacy, encoding="utf-8")
            (framework / "VERSION").write_text("1.2.6\n", encoding="utf-8")
            project.mkdir()
            copy_tree(framework / "templates/single", project)

            def run(*arguments: str) -> subprocess.CompletedProcess[str]:
                return subprocess.run(
                    [sys.executable, str(CLI), "--framework-root", str(framework), *arguments, "--project", str(project)],
                    text=True, capture_output=True, check=False,
                )

            self.assertEqual(run("lock", "--mode", mode).returncode, 0)
            template.write_text(current, encoding="utf-8")
            fixture.migration("001-synthetic-wrap", "1.2.7", capability=capability,
                              version=int(version), operation="wrap", paths=(relative,))
            local = project / relative
            edited = local.read_text(encoding="utf-8")
            self.assertIn(edit[0], edited)
            local.write_text(edited.replace(*edit, 1), encoding="utf-8")
            checked = run("upgrade", "--check")
            applied = run("upgrade", "--apply")
            self.assertEqual(local.read_text(encoding="utf-8").count(f"capability={capability} v{version}"), 0)
            return checked.stdout, applied.stderr

    def test_a_customized_lean_lifecycle_document_is_a_conflict_not_a_duplicate(self) -> None:
        stdout, stderr = self.scenario(
            "single", "docs/WORKTREE_LIFECYCLE.md", "worktree-lifecycle",
            ("normally issues these single steps", "normally issues these project-specific single steps"),
        )
        self.assertRegex(stdout, r"CONFLICT\s+docs/WORKTREE_LIFECYCLE.md")
        self.assertNotIn("APPEND-MARKERS", stdout)
        self.assertIn("blocking plan items", stderr)

    def test_a_customized_remote_cleanup_section_is_a_conflict_not_a_duplicate(self) -> None:
        stdout, stderr = self.scenario(
            "single", "docs/INTEGRATION_POLICY.md", "remote-branch-cleanup",
            ("may intentionally lack a local", "may, in this project, lack a local"),
        )
        self.assertRegex(stdout, r"CONFLICT\s+docs/INTEGRATION_POLICY.md")
        self.assertNotIn("APPEND-MARKERS", stdout)
        self.assertIn("blocking plan items", stderr)


class ManagedCopyDigestAuditTest(FrameworkFixture):
    def change_template_heading(self, relative: str, replacement: str) -> Path:
        template = self.framework / "templates/single" / relative
        text = template.read_text(encoding="utf-8")
        first_line, remainder = text.split("\n", 1)
        template.write_text(replacement + "\n" + remainder, encoding="utf-8")
        return self.project / relative

    def test_a_drifted_markerless_copy_fails_the_audit(self) -> None:
        self.lock()
        prompts = self.project / "docs/OPERATOR_PROMPTS.md"
        prompts.write_text(prompts.read_text(encoding="utf-8") + "\nLocal edit.\n", encoding="utf-8")

        code, output = self.audit()

        self.assertEqual(code, 2, output)
        self.assertRegex(
            output, r"(?m)^FAIL\s+managed-copy-digest — docs/OPERATOR_PROMPTS\.md: differs"
        )

    def test_upgrade_warns_for_an_edited_markerless_copy_and_the_audit_matches(self) -> None:
        self.lock()
        prompts = self.change_template_heading("docs/OPERATOR_PROMPTS.md", "# Released Operator Prompts")
        prompts.write_text(prompts.read_text(encoding="utf-8") + "\nProject-specific note.\n", encoding="utf-8")

        checked = self.run_cli("upgrade", "--check")
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertRegex(checked.stdout, r"EDITED-COPY\s+docs/OPERATOR_PROMPTS\.md")
        self.assertIn("will fail the digest audit", checked.stdout)
        self.assertIn("WARNING: 1 edited managed copy", checked.stdout)
        self.assertRegex(checked.stdout, r"MERGE\s+docs/OPERATOR_PROMPTS\.md")

        applied = self.run_cli("upgrade", "--apply")
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        self.assertIn("# Released Operator Prompts", prompts.read_text(encoding="utf-8"))
        self.assertIn("Project-specific note.", prompts.read_text(encoding="utf-8"))
        code, output = self.audit()
        self.assertEqual(code, 2, output)
        self.assertIn("managed-copy-digest — docs/OPERATOR_PROMPTS.md: differs", output)

    def test_upgrade_warns_before_a_markerless_copy_conflict(self) -> None:
        self.lock()
        prompts = self.change_template_heading("docs/OPERATOR_PROMPTS.md", "# Released Operator Prompts")
        prompts.write_text(
            prompts.read_text(encoding="utf-8").replace(
                "# Operator Prompts", "# Project Operator Prompts", 1
            ),
            encoding="utf-8",
        )

        checked = self.run_cli("upgrade", "--check")
        self.assertNotEqual(checked.returncode, 0)
        self.assertRegex(checked.stdout, r"EDITED-COPY\s+docs/OPERATOR_PROMPTS\.md")
        self.assertRegex(checked.stdout, r"CONFLICT\s+docs/OPERATOR_PROMPTS\.md")
        applied = self.run_cli("upgrade", "--apply")
        self.assertNotEqual(applied.returncode, 0)
        self.assertIn("blocking plan items", applied.stderr)

    def test_upgrade_does_not_warn_for_an_unedited_markerless_copy(self) -> None:
        self.lock()
        self.change_template_heading("docs/OPERATOR_PROMPTS.md", "# Released Operator Prompts")

        checked = self.run_cli("upgrade", "--check")
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertNotIn("EDITED-COPY", checked.stdout)
        self.assertRegex(checked.stdout, r"REPLACE\s+docs/OPERATOR_PROMPTS\.md")

    def test_upgrade_does_not_warn_for_marker_or_project_editable_files(self) -> None:
        self.lock()
        organization = self.change_template_heading("docs/CODE_ORGANIZATION.md", "# Released Code Organization")
        decisions = self.change_template_heading("docs/ARCHITECTURE_DECISIONS.md", "# Released Architecture Decisions")
        for path in (organization, decisions):
            path.write_text(path.read_text(encoding="utf-8") + "\nProject-specific note.\n", encoding="utf-8")

        checked = self.run_cli("upgrade", "--check")
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertNotIn("EDITED-COPY", checked.stdout)

    def test_project_text_outside_capability_blocks_never_fails(self) -> None:
        self.lock()
        organization = self.project / "docs/CODE_ORGANIZATION.md"
        organization.write_text(
            organization.read_text(encoding="utf-8") + "\n## Project module map\n\n- core\n",
            encoding="utf-8",
        )
        checklist = self.project / REVIEW_PROMPT
        checklist.write_text(
            checklist.read_text(encoding="utf-8") + "\n## Project review checklist\n\n- Check X.\n",
            encoding="utf-8",
        )
        decisions = self.project / "docs/ARCHITECTURE_DECISIONS.md"
        decisions.write_text(decisions.read_text(encoding="utf-8") + "\n## ADR-001\n\nAccepted.\n", encoding="utf-8")

        code, output = self.audit()

        self.assertNotRegex(output, r"(?m)^FAIL\s")
        self.assertNotIn("CODE_ORGANIZATION.md: differs", output)
        self.assertNotIn("ARCHITECTURE_DECISIONS.md: differs", output)
        self.assertIn("PASS           marker-integrity — docs/CODE_ORGANIZATION.md", output)
        self.assertLess(code, 2, output)

    def test_an_edit_inside_a_protected_block_is_still_reported_by_the_marker_rows(self) -> None:
        self.lock()
        lifecycle = self.project / "docs/WORKTREE_LIFECYCLE.md"
        lifecycle.write_text(
            lifecycle.read_text(encoding="utf-8").replace("Exit `0` is success", "Exit `7` is success", 1),
            encoding="utf-8",
        )

        code, output = self.audit()

        self.assertEqual(code, 2, output)
        self.assertRegex(output, r"FAIL\s+marker-integrity — docs/WORKTREE_LIFECYCLE\.md")

    def test_repository_check_and_audit_share_one_comparison(self) -> None:
        recorded = {"a.md": "0" * 64}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "a.md").write_text("changed\n", encoding="utf-8")
            drift = owner_templates_audit.managed_copy_drift(root, recorded)
            self.assertEqual([path for path, _diagnostic in drift], ["a.md"])
            self.assertEqual(owner_templates_audit.managed_copy_drift(root, recorded, skip_paths={"a.md"}), [])


class ConsumerProfileTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def legacy_project(self, mode: str) -> Path:
        project = Path(tempfile.mkdtemp(prefix=mode + "-", dir=self.root))
        copy_tree(ROOT / "templates/single", project)
        locked = subprocess.run(
            [sys.executable, str(CLI), "--framework-root", str(ROOT), "lock", "--mode", mode, "--project", str(project)],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(locked.returncode, 0, locked.stdout + locked.stderr)
        return project

    def audit(self, project: Path, mode: str) -> tuple[int, str]:
        output = io.StringIO()
        with redirect_stdout(output):
            code = owner_templates_audit.run_audit(project, ROOT, mode)
        return code, output.getvalue()

    def test_catalog_ships_a_consumer_profile_per_mode(self) -> None:
        catalog = owner_templates_catalog.load_capability_catalog(ROOT)
        for profile_id, mode in (
            ("governed-sdd-consumer", "single"),
            ("lean-delivery-consumer", "single"),
        ):
            profile = catalog.profile(profile_id)
            self.assertIsNotNone(profile)
            self.assertEqual(profile.version, 1)
            self.assertEqual(profile.distribution, "single")
            self.assertIn("context-reading", dict(profile.capabilities))

    def test_bootstrap_turns_the_legacy_unverified_row_into_declared_profiles(self) -> None:
        for profile_id in ("lean-delivery-consumer", "governed-sdd-consumer"):
            mode = "single"
            with self.subTest(profile=profile_id):
                project = self.legacy_project(mode)
                _code, before = self.audit(project, mode)
                self.assertIn("declaration/legacy-compatibility", before)

                checked = subprocess.run(
                    [sys.executable, str(ROOT / "scripts/dev.py"), "--framework-root", str(ROOT), "profile", "bootstrap",
                     profile_id, "--check", "--project", str(project)],
                    text=True, capture_output=True, check=False,
                )
                self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
                manifest_path = project / ".cardine/manifest.json"
                self.assertNotIn("capabilityProfiles", json.loads(manifest_path.read_text(encoding="utf-8")))

                applied = subprocess.run(
                    [sys.executable, str(ROOT / "scripts/dev.py"), "--framework-root", str(ROOT), "profile", "bootstrap",
                     profile_id, "--apply", "--project", str(project)],
                    text=True, capture_output=True, check=False,
                )
                self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
                declared = json.loads(manifest_path.read_text(encoding="utf-8"))["capabilityProfiles"][profile_id]
                self.assertEqual(declared["profileVersion"], 1)
                for declaration in declared["capabilities"].values():
                    self.assertEqual(declaration["installation"]["state"], "INSTALLED")
                    self.assertEqual(declaration["verification"]["state"], "UNVERIFIED")
                    self.assertTrue(
                        all(host["state"] == "UNVERIFIED" for host in declaration["hostActivation"].values())
                    )
                code, after = self.audit(project, mode)
                self.assertNotIn("declaration/legacy-compatibility", after)
                self.assertNotRegex(after, r"(?m)^FAIL\s")
                self.assertRegex(after, rf"PASS\s+{profile_id}/context-reading/installation")
                self.assertEqual(code, 1, after)

    def test_a_marker_bearing_file_with_project_text_still_bootstraps_and_audits(self) -> None:
        project = self.legacy_project("single")
        policy = project / "docs/CONTEXT_READING_POLICY.md"
        policy.write_text(policy.read_text(encoding="utf-8") + "\n## Project reading notes\n\n- Prefer grep.\n", encoding="utf-8")

        owner_templates_adoption.bootstrap_capability_profile(project, ROOT, "governed-sdd-consumer", apply=True)
        code, output = self.audit(project, "single")
        self.assertNotRegex(output, r"(?m)^FAIL\s")

        policy.write_text(policy.read_text(encoding="utf-8") + "\n- Another note.\n", encoding="utf-8")
        _code, later = self.audit(project, "single")
        self.assertNotRegex(later, r"(?m)^FAIL\s")

    def test_a_configured_evidence_profile_does_not_block_a_lean_consumer(self) -> None:
        project = self.legacy_project("single")
        profile_file = project / "docs/EXECUTION_EVIDENCE_PROFILE.md"
        profile_file.write_text(
            profile_file.read_text(encoding="utf-8").replace("400\n  lines", "800\n  lines"), encoding="utf-8"
        )

        owner_templates_adoption.bootstrap_capability_profile(project, ROOT, "lean-delivery-consumer", apply=True)
        code, output = self.audit(project, "single")

        self.assertNotRegex(output, r"(?m)^FAIL\s")
        self.assertNotIn("EXECUTION_EVIDENCE_PROFILE.md: differs", output)
        evidence = json.loads((project / ".cardine/manifest.json").read_text(encoding="utf-8"))[
            "capabilityProfiles"
        ]["lean-delivery-consumer"]["capabilities"]["execution-evidence"]["installation"]["evidence"]
        self.assertIn("path:docs/EXECUTION_EVIDENCE_PROFILE.md", evidence)
        self.assertLess(code, 2, output)

    def test_bootstrap_does_not_launder_a_drifted_copy_under_the_strict_profile(self) -> None:
        project = self.legacy_project("single")
        catalog = owner_templates_catalog.load_capability_catalog(ROOT)
        for capability_id, _version in catalog.profile("cardine-self-hosting").capabilities:
            for surface in catalog.capability(capability_id).managed_surfaces:
                destination = project / surface.path
                if not destination.exists():
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(ROOT / surface.path, destination)
        manifest_path = project / ".cardine/manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["managedFiles"]["docs/CONTEXT_READING_POLICY.md"] = "0" * 64
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        before = manifest_path.read_text(encoding="utf-8")

        with self.assertRaises(shared_errors.CardineError) as error:
            owner_templates_adoption.bootstrap_capability_profile(project, ROOT, "cardine-self-hosting", apply=True)

        self.assertIn("docs/CONTEXT_READING_POLICY.md", str(error.exception))
        self.assertEqual(manifest_path.read_text(encoding="utf-8"), before)

    def test_a_consumer_profile_installs_in_either_preset(self) -> None:
        for mode, profile in (("single", "governed-sdd-consumer"),
                              ("single", "lean-delivery-consumer")):
            with self.subTest(mode=mode, profile=profile):
                project = self.legacy_project(mode)
                result = owner_templates_adoption.bootstrap_capability_profile(
                    project, ROOT, profile, apply=False
                )
                declarations = result["capabilityProfiles"][profile]["capabilities"]
                self.assertIn("context-reading", declarations)
                self.assertTrue(all(value["installation"]["state"] == "INSTALLED"
                                    for value in declarations.values()))


class RestructureHelpersTest(unittest.TestCase):
    def test_project_sections_ignore_headings_inside_code_fences(self) -> None:
        base = "# T\n\n## Known\n\nbody\n"
        template = "# T\n\n## Known\n\nnew body\n"
        local = "# T\n\n## Known\n\nedited\n\n```text\n## not a heading\n```\n\n## Mine\n\nkeep\n"
        self.assertEqual(owner_templates_migrations.project_sections(local, base, template), ["## Mine\n\nkeep\n"])
        self.assertEqual(
            owner_templates_migrations.restructured_text(local, base, template),
            "# T\n\n## Known\n\nnew body\n\n## Mine\n\nkeep\n",
        )

    def test_a_file_without_project_sections_becomes_the_template(self) -> None:
        template = "# T\n\nbody\n"
        self.assertEqual(owner_templates_migrations.restructured_text("# T\n\nedited\n", "# T\n\nold\n", template), template)

    def test_carried_sections_without_retired_markers_or_with_other_markers_are_unchanged(self) -> None:
        base = "# T\n\n## Known\n\nbody\n"
        template = "# T\n\n## Known\n\nnew body\n"
        local = (
            "# T\n\n## Known\n\nedited\n\n## Mine\n\n"
            "<!-- CARDINE:BEGIN capability=kept-marker v1 -->Keep this.<!-- CARDINE:END -->\n"
        )
        self.assertEqual(
            owner_templates_migrations.project_sections(local, base, template, [("retired-marker", 1)]),
            ["## Mine\n\n<!-- CARDINE:BEGIN capability=kept-marker v1 -->Keep this.<!-- CARDINE:END -->\n"],
        )


if __name__ == "__main__":
    unittest.main()
