"""Context-local project names and storage readers."""

from __future__ import annotations
from project_config_support import write_project_config

from contextvars import Context
from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cardine.shared.layout import PRODUCT_NAMES, ProjectNames, names, use
from cardine.console.snapshot import IdentityCache
from cardine.templates import manifest, merge
from cardine.templates.upgrade_support import _unused_adoption_backup
from cardine.shared.models import ManagedFile
from cardine.shared import context, flow, journal, project
from cardine.tasks import audit, contract, identity, recording, state
from cardine.hosts.setup import plan_setup
from cardine.worktree import checkout, storage
from cardine.integration.evidence import candidate_validation_declaration


OTHER_NAMES = ProjectNames(
    project_directory=".other",
    worktree_state_directory="other-worktrees",
    integration_lease_name="other-integration.lock",
    integration_state_name="other-integration.json",
    journal_name="other-journal.jsonl",
    journal_rotated_name="other-journal.1.jsonl",
    user_configuration_directory="other",
    shared_worktrees_context="other_shared_worktrees",
)


class LayoutTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        subprocess.run(["git", "init", "-b", "main", str(self.root)],
                       check=True, capture_output=True)
        (self.root / "tasks").mkdir()
        (self.root / "tasks/042-layout.md").write_text(
            "# Task 042\n\n> **ID**: `042`\n", encoding="utf-8")

    def write_json(self, path, value):
        path = self.root / path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    def test_product_defaults_use_cardine_layout(self):
        self.assertIs(names(), PRODUCT_NAMES)
        self.assertEqual(names().manifest_path, Path(".cardine/manifest.json"))
        self.assertEqual(names().worktree_root, Path(".cardine/worktrees"))
        self.assertEqual(names().user_configuration_path, Path("cardine/config.json"))
        self.assertEqual(names().worktree_state_directory, "cardine-worktrees")
        self.assertEqual(names().integration_lease_name, "cardine-integration.lock")
        self.assertEqual(names().integration_state_name, "cardine-integration.json")
        self.assertEqual(names().journal_name, "cardine-journal.jsonl")
        self.assertEqual(names().journal_rotated_name, "cardine-journal.1.jsonl")
        self.assertEqual(names().shared_worktrees_context, "cardine_shared_worktrees")
        with self.assertRaises(FrozenInstanceError):
            PRODUCT_NAMES.project_directory = ".changed"

    def test_nested_context_restores_after_exception_and_isolates_other_contexts(self):
        with use(OTHER_NAMES):
            self.assertIs(names(), OTHER_NAMES)
            self.assertIs(Context().run(names), PRODUCT_NAMES)
            with self.assertRaisesRegex(ValueError, "test"):
                with use(replace(OTHER_NAMES, project_directory=".inner")):
                    self.assertEqual(names().project_directory, ".inner")
                    raise ValueError("test")
            self.assertIs(names(), OTHER_NAMES)
        self.assertIs(names(), PRODUCT_NAMES)

    def test_task_state_path_changes_only_inside_context(self):
        default = self.root / ".cardine/tasks/042.json"
        self.assertEqual(state.state_path(self.root, "042"), default)
        with use(OTHER_NAMES):
            self.assertEqual(state.state_path(self.root, "042"), self.root / ".other/tasks/042.json")
        self.assertEqual(state.state_path(self.root, "042"), default)

    def test_identity_policy_reads_selected_directory(self):
        self.write_json(OTHER_NAMES.task_identity_path, {"version": 1, "mode": "milestone"})
        self.assertEqual(identity.read_task_identity_policy(self.root).mode, "opaque")
        with use(OTHER_NAMES):
            self.assertEqual(identity.read_task_identity_policy(self.root).mode, "milestone")
        self.assertEqual(identity.read_task_identity_policy(self.root).mode, "opaque")

    def test_project_declaration_reads_selected_directory(self):
        declaration = {"version": 1, "preset": "lean", "ci": "none"}
        self.write_json(OTHER_NAMES.project_declaration_path, declaration)
        self.assertIsNone(project.read_project_declaration(self.root))
        with use(OTHER_NAMES):
            self.assertEqual(project.read_project_declaration(self.root), declaration)
        self.assertIsNone(project.read_project_declaration(self.root))

    def test_execution_evidence_writes_and_reads_selected_directory(self):
        write_project_config(self.root)
        self.write_json(OTHER_NAMES.project_declaration_path, {"version": 1, "preset": "lean"})
        self.assertEqual(contract.execution_entries(self.root, "042"), [])
        with use(OTHER_NAMES):
            recording.record_validation(self.root, "042", "unit", "python3 -m unittest", 0)
            entries = contract.execution_entries(self.root, "042")
            self.assertEqual(entries, [{"id": "unit", "command": "python3 -m unittest", "exitStatus": 0}])
            self.assertTrue((self.root / OTHER_NAMES.execution_evidence_path).is_file())
        self.assertEqual(contract.execution_entries(self.root, "042"), [])
        self.assertFalse((self.root / PRODUCT_NAMES.execution_evidence_path).exists())

    def test_candidate_validation_reads_selected_directory(self):
        self.write_json(OTHER_NAMES.candidate_validation_path, {"version": 1, "state": "none"})
        self.assertEqual(candidate_validation_declaration(self.root), ("undeclared", {}))
        with use(OTHER_NAMES):
            self.assertEqual(candidate_validation_declaration(self.root), ("none", {}))
        self.assertEqual(candidate_validation_declaration(self.root), ("undeclared", {}))

    def test_lifecycle_directory_lease_and_state_change_together(self):
        write_project_config(self.root)
        resolved = identity.resolve_task_identity(self.root, "042", "existing")
        default = storage._lifecycle_paths(self.root, resolved)
        self.assertEqual(default, (self.root / ".git/cardine-worktrees/042.json",
                                  self.root / ".git/cardine-integration.lock",
                                  self.root / ".git/cardine-integration.json"))
        with use(OTHER_NAMES):
            paths = storage._lifecycle_paths(self.root, resolved)
            self.assertEqual(paths, (self.root / ".git/other-worktrees/042.json",
                                     self.root / ".git/other-integration.lock",
                                     self.root / ".git/other-integration.json"))
            self.write_json(OTHER_NAMES.project_declaration_path, {"version": 1, "preset": "lean"})
            self.write_json(OTHER_NAMES.tasks_path / "042.json", {"version": 1, "task_id": "042", "workflow": "single", "status": "queued", "transitions": []})
            self.write_json(paths[0], {"task_id": "042", "branch": "task-042", "worktree": str(self.root)})
            with patch.object(checkout, "_git_worktrees", return_value=[{
                "worktree": str(self.root), "branch": "refs/heads/task-042",
            }]):
                self.assertEqual(len(checkout.registered_worktree_task_states(self.root)), 1)
        self.assertEqual(storage._lifecycle_paths(self.root, resolved), default)
        self.assertEqual(checkout.registered_worktree_task_states(self.root), [])

    def test_journal_write_rotation_and_flow_read_use_selected_names(self):
        journal.append_journal_line(self.root, {"version": 1, "ts": "2026-10-19T12:00:00Z", "result": "ok", "command": "default"})
        default = self.root / ".git/cardine-journal.jsonl"
        before = default.read_bytes()
        with use(OTHER_NAMES):
            journal.append_journal_line(self.root, {"version": 1, "ts": "2026-10-19T12:00:00Z", "result": "ok", "command": "first"})
            with patch.object(journal, "JOURNAL_MAX_BYTES", 0):
                journal.append_journal_line(self.root, {"version": 1, "ts": "2026-10-19T12:01:00Z", "result": "ok", "command": "second"})
            self.assertTrue((self.root / ".git/other-journal.1.jsonl").is_file())
            records, _ = flow._flow_read_journal(self.root)
            self.assertEqual([record["command"] for record in records], ["first", "second"])
        self.assertEqual(default.read_bytes(), before)
        records, _ = flow._flow_read_journal(self.root)
        self.assertEqual([record["command"] for record in records], ["default"])

    # MERIDIAN-OLD-NAME-TEST
    def test_old_journals_are_ignored_and_never_rotated(self):
        old_paths = [self.root / ".git" / name for name in (
            "meridian-journal.jsonl", "meridian-journal.1.jsonl",  # MERIDIAN-OLD-NAME-TEST
        )]
        for path in old_paths:
            self.write_json(path, {"version": 1, "ts": "2026-10-19T12:00:00Z",
                                   "result": "ok", "command": "old"})
        before = [path.read_bytes() for path in old_paths]
        self.assertEqual(flow._flow_read_journal(self.root), ([], 0))
        with patch.object(journal, "JOURNAL_MAX_BYTES", 0):
            journal.append_journal_line(self.root, {"version": 1, "ts": "2026-10-19T12:00:00Z",
                                                   "result": "ok", "command": "new"})
        self.assertEqual([path.read_bytes() for path in old_paths], before)
        self.assertFalse((self.root / ".git/cardine-journal.1.jsonl").exists())
        self.assertEqual([record["command"] for record in flow._flow_read_journal(self.root)[0]], ["new"])

    # MERIDIAN-OLD-NAME-TEST
    def test_old_adoption_backups_do_not_reserve_product_backup_names(self):
        target = self.root / "document.md"
        for kind in ("pre-adoption", "pre-restructure"):
            with self.subTest(kind=kind):
                old = target.with_name(target.name + f".meridian-{kind}.bak")  # MERIDIAN-OLD-NAME-TEST
                old.write_text("old backup")
                expected = target.with_name(target.name + f".cardine-{kind}.bak")
                self.assertEqual(_unused_adoption_backup(target, kind), expected)
                self.assertEqual(old.read_text(), "old backup")
                expected.write_text("current backup")
                self.assertEqual(_unused_adoption_backup(target, kind), expected.with_name(expected.name + ".1"))

    def test_context_configuration_and_references_use_selected_directory(self):
        self.write_json(OTHER_NAMES.context_size_config_path, {
            "version": 1, "fileBytesThreshold": 123, "routerFileLinesCeiling": 45,
        })
        self.assertEqual(context._context_configuration(self.root), (None, 1000))
        with use(OTHER_NAMES):
            self.assertEqual(context._context_configuration(self.root), (123, 45))
            self.assertEqual(context._context_relative_references(
                Path("docs/example.md"), "`.other/example.md` `.other/tasks/042.md`"),
                [Path(".other/example.md")])
        self.assertEqual(context._context_configuration(self.root), (None, 1000))

    def test_flow_targets_read_selected_directory(self):
        self.write_json(OTHER_NAMES.flow_targets_path, {
            "version": 1, "unbacked_blocks": {"window": 1, "max": 0},
        })
        self.assertEqual(flow._flow_targets(self.root, [], []), [])
        with use(OTHER_NAMES):
            self.assertEqual(flow._flow_targets(self.root, [], [])[0]["state"], "insufficient data")
        self.assertEqual(flow._flow_targets(self.root, [], []), [])

    def test_manifest_and_baseline_use_selected_directory(self):
        source = self.root / "source.md"
        source.write_text("baseline", encoding="utf-8")
        managed = ManagedFile(source, Path("docs/example.md"))
        with use(OTHER_NAMES):
            merge.copy_baseline(self.root, ROOT, "single", "1.0.0", [managed])
            self.assertEqual((self.root / ".other/baselines/1.0.0/docs/example.md").read_text(), "baseline")
            value = {"protocolVersion": 2, "workflowMode": "single",
                     "frameworkVersion": "1.4.0", "managedFiles": {}}
            manifest.write_manifest(self.root, value)
            self.assertEqual(manifest.load_manifest(self.root), value)
        self.assertFalse((self.root / PRODUCT_NAMES.baselines_path).exists())
        self.assertFalse((self.root / PRODUCT_NAMES.manifest_path).exists())

    def test_console_identity_cache_observes_context_switch(self):
        write_project_config(self.root)
        cache = IdentityCache()
        default = cache.resolve(self.root, "042")
        with use(OTHER_NAMES):
            self.write_json(OTHER_NAMES.project_declaration_path, {"version": 1, "preset": "lean", "taskIdentity": {"mode": "milestone"}})
            self.assertEqual(cache.resolve(self.root, "042").mode, "milestone")
        self.assertEqual(cache.resolve(self.root, "042"), default)

    def test_setup_plan_uses_selected_paths_in_temporary_home(self):
        def plan():
            return plan_setup(None, self.root / ".codex/config.toml",
                              environment={"XDG_CONFIG_HOME": str(self.root / ".config")},
                              home=self.root, project_root=self.root, framework_root=ROOT)
        default = plan()
        self.assertEqual(default.resolution.path, self.root / ".cardine/worktrees")
        with use(OTHER_NAMES):
            selected = plan()
            self.assertEqual(selected.resolution.path, self.root / ".other/worktrees")
            self.assertEqual(selected.config_action, "none")
            self.assertEqual(selected.candidate_validation_path, self.root / OTHER_NAMES.candidate_validation_path)
            self.assertEqual(selected.project_declaration_path, self.root / OTHER_NAMES.project_declaration_path)
            self.assertEqual(selected.task_identity_path, self.root / OTHER_NAMES.task_identity_path)
        self.assertEqual(plan().resolution, default.resolution)

    def test_task_audit_reads_selected_state_directory(self):
        self.write_json(OTHER_NAMES.tasks_path / "042.json", {"invalid": True})
        self.assertEqual(audit.audit_task_state_projections(self.root, "single"), [])
        with use(OTHER_NAMES):
            results = audit.audit_task_state_projections(self.root, "single")
            self.assertEqual(len(results), 1)
            self.assertIn(".other/tasks/042.json", results[0].detail)
        self.assertEqual(audit.audit_task_state_projections(self.root, "single"), [])

    def test_worktree_root_and_configuration_use_selected_names(self):
        default = storage.resolve_worktree_root(environment={}, home=self.root)
        self.assertEqual(default.path, self.root / ".cardine/worktrees")
        self.assertEqual(default.config_path, self.root / ".config/cardine/config.json")
        with use(OTHER_NAMES):
            selected = storage.resolve_worktree_root(environment={}, home=self.root)
            self.assertEqual(selected.path, self.root / ".other/worktrees")
            self.assertEqual(selected.config_path, self.root / ".config/other/config.json")
            configured_root = self.root / "configured"
            self.write_json(selected.config_path, {"version": 1, "worktreeRoot": str(configured_root)})
            self.assertEqual(storage.resolve_worktree_root(environment={}, home=self.root).path, configured_root)
            self.assertEqual(storage.user_configuration_path({"XDG_CONFIG_HOME": str(self.root / "xdg")}, self.root),
                             self.root / "xdg/other/config.json")
        self.assertEqual(storage.resolve_worktree_root(environment={}, home=self.root), default)


if __name__ == "__main__":
    unittest.main()
