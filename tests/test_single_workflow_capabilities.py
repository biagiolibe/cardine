"""The single distribution keeps canonical versions and rejects local tampering."""

import contextlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from cardine_cli_support import CLI, ROOT
from synthetic_upgrade_support import SyntheticFramework
from project_config_support import write_project_config
import check_repository
from cardine.shared.errors import CardineError
from cardine.templates.catalog import load_capability_catalog, parse_capability_catalog
from cardine.templates.files import managed_files
from cardine.templates.markers import marker_pairs


class SingleWorkflowCapabilitiesTest(unittest.TestCase):
    def test_every_live_marker_occurrence_matches_the_required_version(self):
        catalog = json.loads((ROOT / "capabilities/markers-v1.json").read_text())["capabilities"]
        seen = set()
        for item in managed_files(ROOT):
            for capability, version in marker_pairs(item.source.read_text()):
                with self.subTest(path=item.target, capability=capability):
                    self.assertFalse(catalog[capability]["retired"])
                    self.assertEqual(version, catalog[capability]["requiredVersion"])
                seen.add(capability)
        self.assertTrue({key for key, entry in catalog.items() if entry["required"] and not entry["retired"]} <= seen)

    def test_lifecycle_keeps_v12_and_bounded_worktree_keeps_v8(self):
        pairs = dict(marker_pairs((ROOT / "templates/single/docs/LIFECYCLE_ORCHESTRATION.md").read_text()))
        self.assertEqual(pairs["lifecycle-orchestration"], 12)
        pairs = dict(marker_pairs((ROOT / "templates/single/PROJECT_WORKFLOW.md").read_text()))
        self.assertEqual(pairs["bounded-worktree-lifecycle"], 8)
        check_repository.check_capability_required_versions(ROOT)
        text = (ROOT / "templates/single/PROJECT_WORKFLOW.md").read_text()
        self.assertIn("queued -> in_progress", text)
        self.assertIn("until landing writes `done`", text)
        self.assertIn("taskIdentity.mode", text)
        for item in managed_files(ROOT):
            text = item.source.read_text()
            self.assertNotIn("task transition <TASK-ID> ACCEPTED", text)
            self.assertNotIn("READY_FOR_REVIEW", text)
            self.assertNotIn("Lean start adds no machine state", text)
            # MERIDIAN-OLD-NAME-TEST: reject the retired standalone command declaration.
            self.assertNotIn(".meridian/candidate-validation.json", text)

    def test_later_v3_lifecycle_occurrence_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT / "templates/single", root / "templates/single")
            shutil.copytree(ROOT / "capabilities", root / "capabilities")
            later = root / "templates/single/docs/workflows/IMPLEMENTATION.md"
            later.write_text(later.read_text() + "\n<!-- MERIDIAN:BEGIN capability=lifecycle-orchestration v3 -->\nOld variant.\n<!-- MERIDIAN:END -->\n")
            output = io.StringIO()
            with contextlib.redirect_stdout(output), self.assertRaises(SystemExit):
                check_repository.check_capability_required_versions(root)
            self.assertIn("requiredVersion=12", output.getvalue())
            self.assertIn("ships v3", output.getvalue())

    def test_catalog_and_dependencies_use_the_reading_policy(self):
        catalog = load_capability_catalog(ROOT)
        self.assertIsNone(catalog.capability("context-budgeting"))
        policy = catalog.capability("context-reading")
        self.assertEqual(policy.version, 1)
        self.assertEqual([surface.path for surface in policy.managed_surfaces], ["docs/CONTEXT_READING_POLICY.md"])
        for capability in catalog.capabilities:
            self.assertEqual(capability.distribution, "single")
            self.assertNotIn("context-budgeting", dict(capability.dependencies))
        for profile in catalog.profiles:
            self.assertEqual(profile.distribution, "single")
            self.assertIn("context-reading", dict(profile.capabilities))

    def test_catalog_rejects_workflow_selection_and_unknown_distribution(self):
        original = json.loads((ROOT / "capabilities/catalog-v1.json").read_text())
        for group in ("capabilities", "profiles"):
            for change in ({"workflowModes": ["single"]}, {"distribution": "other"}):
                with self.subTest(group=group, change=change):
                    catalog = json.loads(json.dumps(original))
                    next(iter(catalog[group].values())).update(change)
                    with self.assertRaises(CardineError):
                        parse_capability_catalog(catalog)

    def test_reading_policy_retains_read_guards_and_evidence_without_counters(self):
        text = (ROOT / "templates/single/docs/CONTEXT_READING_POLICY.md").read_text()
        for required in ("Task-first loading", "Read-guard threshold", "Evidence tiers", "bounded", "authority-excerpt"):
            self.assertIn(required, text)
        for retired in ("budget show", "budget spend", "Budget usage:", "budget.jsonl"):
            self.assertNotIn(retired, text)

    def test_both_presets_refuse_a_tampered_same_version_block(self):
        for preset, mode in (("lean", "single"), ("governed", "single")):
            with self.subTest(preset=preset), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                framework = root / "framework"
                fixture = SyntheticFramework(framework, "2.0.0")
                project = root / "project"
                shutil.copytree(framework / "templates/single", project)
                write_project_config(project, preset)
                def cli(*args):
                    return subprocess.run([sys.executable, str(CLI), "--framework-root", str(framework),
                                           *args, "--project", str(project)], capture_output=True, text=True)
                locked = cli("lock", "--mode", mode)
                self.assertEqual(locked.returncode, 0, locked.stdout + locked.stderr)
                path = project / "PROJECT_WORKFLOW.md"
                text = path.read_text().replace("capability=git-workflow v15 -->", "capability=git-workflow v15 -->\nTampered policy.", 1)
                path.write_text(text)
                fixture.migration("001-synthetic-policy", "2.1.0", capability="git-workflow", version=16,
                                  content="Updated canonical policy.", paths=("PROJECT_WORKFLOW.md",), mode=mode)
                before = {p.relative_to(project): p.read_bytes() for p in project.rglob("*") if p.is_file()}
                checked = cli("upgrade", "--check")
                self.assertNotEqual(checked.returncode, 0, checked.stdout + checked.stderr)
                self.assertIn("CONFLICT PROJECT_WORKFLOW.md", checked.stdout)
                self.assertEqual(before, {p.relative_to(project): p.read_bytes() for p in project.rglob("*") if p.is_file()})
