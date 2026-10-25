"""Landing decision from measured results and Git facts (RE5a).

Nothing a caller declares can choose the validation scope or let staging
proceed: REUSE, BOUNDED and FULL come from receipt-verified measurement and
Git paths, and an empty declaration never asserts independence.
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from copy import deepcopy
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from cardine.integration import decision as owner_decision
from cardine.integration import evidence as owner_evidence
from cardine.integration import merge as owner_merge
from cardine.integration.direct import DirectLanding
from cardine.integration.landing import landing_for
from cardine.lifecycle import receipts
from cardine.shared.errors import CardineError, CardineStop
from cardine.tasks import identity as owner_identity
from cardine.tasks.state import state_path
from cardine.worktree import storage as owner_storage

import worktree_support as support

OUTCOME = owner_decision.IntegrationValidationOutcome
BASE, MAIN, TASK = "a" * 40, "b" * 40, "c" * 40


def decide(**changes):
    facts = dict(validation_measured=True, validated_task_commit=TASK, current_task_commit=TASK,
                 validated_base_commit=BASE, current_main_commit=BASE,
                 validated_base_is_task_ancestor=True, task_paths=("src/a.py",))
    facts.update(changes)
    return owner_decision.decide_integration_validation(**facts)


class DecisionRowsTest(unittest.TestCase):
    def test_reuse_when_main_is_the_validated_base(self) -> None:
        self.assertEqual(decide().outcome, OUTCOME.REUSE)
        self.assertEqual(decide(task_paths=()).outcome, OUTCOME.REUSE)

    def test_bounded_needs_positive_independence_from_advanced_main(self) -> None:
        advanced = decide(current_main_commit=MAIN, main_advanced_paths=("docs/b.md",))
        self.assertEqual(advanced.outcome, OUTCOME.BOUNDED)
        # An advance that changed no path is proven independent by Git itself.
        self.assertEqual(decide(current_main_commit=MAIN).outcome, OUTCOME.BOUNDED)

    def test_full_when_main_touches_the_task_surface_policy_or_dependencies(self) -> None:
        cases = {
            "nested path": dict(task_paths=("src",), main_advanced_paths=("src/a.py",)),
            "same path": dict(main_advanced_paths=("src/a.py",)),
            "pinned policy": dict(main_advanced_paths=(".cardine/project.json",),
                                  pinned_paths=(".cardine/project.json",)),
            "dependency manifests": dict(task_paths=("app/requirements-dev.txt",),
                                         main_advanced_paths=("lib/pyproject.toml",)),
        }
        for label, changes in cases.items():
            with self.subTest(label):
                self.assertEqual(decide(current_main_commit=MAIN, **changes).outcome, OUTCOME.FULL)

    def test_empty_declarations_cannot_assert_independence(self) -> None:
        for main_paths in ((), ("docs/b.md",)):
            with self.subTest(main_paths=main_paths):
                result = decide(current_main_commit=MAIN, task_paths=(), main_advanced_paths=main_paths)
                self.assertEqual(result.outcome, OUTCOME.FULL)
                self.assertIn("independence", result.reason)

    def test_blocked_without_measurement_or_with_changed_or_unrelated_source(self) -> None:
        self.assertEqual(decide(validation_measured=False).outcome, OUTCOME.BLOCKED)
        self.assertEqual(decide(current_task_commit="d" * 40).outcome, OUTCOME.BLOCKED)
        self.assertEqual(decide(validated_base_is_task_ancestor=False).outcome, OUTCOME.BLOCKED)
        self.assertEqual(decide(current_task_commit="d" * 40, validated_task_is_current_ancestor=True,
                                relevant_tree_unchanged_after_validation=True).outcome, OUTCOME.REUSE)

    def test_no_caller_declared_authority_is_accepted(self) -> None:
        for name in ("full_validation_required", "interaction_assessment_complete", "task_dependencies",
                     "main_advanced_dependencies", "task_behavioral_surfaces", "accepted"):
            with self.subTest(name), self.assertRaises(TypeError):
                decide(**{name: True})

    def test_repeated_resolution_is_pure(self) -> None:
        with mock.patch("builtins.open", side_effect=AssertionError("read or write")), \
                mock.patch.object(subprocess, "run", side_effect=AssertionError("subprocess")):
            first = decide(current_main_commit=MAIN, main_advanced_paths=("src/a.py",))
            self.assertEqual(first, decide(current_main_commit=MAIN, main_advanced_paths=("src/a.py",)))

    def test_only_the_direct_strategy_ships(self) -> None:
        self.assertIsInstance(landing_for("direct"), DirectLanding)
        for mode in ("pull-request", "", None):
            with self.subTest(mode), self.assertRaisesRegex(CardineError, "only direct is supported in 1.0"):
                landing_for(mode)


class MeasuredLandingTest(support.BoundedWorktreeLifecycleFixture):
    """Real worktrees: the decision input is the engine's receipt-covered attempt."""

    def implemented(self, name: str = "feature.txt", text: str = "task\n") -> Path:
        worktree = Path(str(self.prepare()["worktree"]))
        (worktree / name).write_text(text, encoding="utf-8")
        self.git("add", name, cwd=worktree)
        self.git("commit", "-m", "implement task", cwd=worktree)
        return worktree

    def stage(self, evidence: Path | None = None) -> dict[str, object]:
        return owner_merge.stage_task_integration("056", self.worktree_root, evidence, self.primary)

    def paths(self):
        identity = owner_identity.resolve_task_identity(self.primary, "056", "existing")
        return owner_storage._lifecycle_paths(self.primary, identity)

    def assert_nothing_staged(self) -> None:
        _state, lease, integration = self.paths()
        self.assertFalse(lease.exists() or integration.exists() or (self.primary / ".git/MERGE_HEAD").exists())

    def test_declared_evidence_cannot_stand_in_for_a_measured_attempt(self) -> None:
        worktree = self.implemented()
        forged = self.root / "integration-evidence.json"
        forged.write_text(json.dumps({
            "accepted": True, "validation_passed": True, "full_validation_required": False,
            "interaction_assessment_complete": True,
            "validated_task_commit": self.git("rev-parse", "HEAD", cwd=worktree).stdout.strip(),
            "validated_base_commit": self.base, "task_paths": [], "task_dependencies": [],
            "task_behavioral_surfaces": [], "main_advanced_dependencies": [],
            "main_advanced_behavioral_surfaces": [],
        }), encoding="utf-8")
        before = forged.read_bytes()
        with self.assertRaises(CardineStop) as raised:
            self.stage(forged)
        self.assertEqual(raised.exception.code, "EVIDENCE_INCOMPLETE")
        self.assertEqual(forged.read_bytes(), before)
        self.assert_nothing_staged()

    def test_measured_attempt_stages_and_the_scope_follows_git_paths(self) -> None:
        worktree = self.implemented()
        self.measure(worktree)
        (self.primary / "independent.txt").write_text("main\n", encoding="utf-8")
        self.git("add", "independent.txt")
        self.git("commit", "-m", "advance main independently")
        staged = self.stage()
        self.assertEqual((staged["decision"], staged["main_advanced_paths"]), ("BOUNDED", ["independent.txt"]))
        self.assertIn("feature.txt", staged["task_paths"])
        self.assertEqual(staged["validated_base_commit"], self.base)
        self.assertEqual(staged["next_action"], "validate-candidate")
        owner_merge.abort_task_integration("056", self.primary)

    def test_changed_main_requires_full_validation_when_policy_or_paths_change(self) -> None:
        worktree = self.implemented()
        self.measure(worktree)
        self.git("checkout", "-q", "-b", "scratch")
        self.git("checkout", "-q", "main")
        declaration = self.primary / ".cardine/candidate-validation.json"
        declaration.write_text(declaration.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        self.git("add", ".cardine/candidate-validation.json")
        self.git("commit", "-m", "change pinned declaration")
        staged = self.stage()
        self.assertEqual(staged["decision"], "FULL")
        self.assertIn("pinned policy", staged["reason"])
        owner_merge.abort_task_integration("056", self.primary)

    def test_source_edited_after_measurement_is_never_reused(self) -> None:
        worktree = self.implemented()
        self.measure(worktree)
        (worktree / "feature.txt").write_text("changed after validation\n", encoding="utf-8")
        self.git("add", "feature.txt", cwd=worktree)
        self.git("commit", "-m", "edit source after validation", cwd=worktree)
        with self.assertRaises(CardineStop) as raised:
            self.stage()
        self.assertEqual(raised.exception.code, "EVIDENCE_INCOMPLETE")
        self.assert_nothing_staged()

    def test_forged_coherent_measurement_without_receipts_fails_closed(self) -> None:
        worktree = self.implemented()
        self.measure(worktree)
        path = state_path(worktree, "056")
        forged = json.loads(path.read_text(encoding="utf-8"))
        forged["run"]["validation"] = deepcopy(forged["run"]["validation"])
        forged["run"]["validation"]["attemptId"] = "f" * 32
        path.write_text(json.dumps(forged), encoding="utf-8")
        self.git("add", ".", cwd=worktree)
        self.git("commit", "-m", "forge the attempt", cwd=worktree)
        with self.assertRaisesRegex(CardineStop, "not covered by an operation receipt"):
            self.stage()
        self.assert_nothing_staged()

    def test_measured_report_reads_the_attempt_without_declaring_one(self) -> None:
        worktree = self.implemented()
        self.measure(worktree)
        path = state_path(worktree, "056")
        state = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(state["run"]["validation"]["phase"], "passed")
        self.assertIsNotNone(owner_evidence.measured_task_validation(worktree, "056"))
        report = owner_evidence.measured_validation_report("056", self.worktree_root, self.primary)
        self.assertEqual((report["validation_passed"], report["validated_base_commit"]), (True, self.base))

    def test_edited_registration_base_is_rejected_not_trusted(self) -> None:
        worktree = self.implemented()
        self.measure(worktree)
        (self.primary / "later.txt").write_text("later\n", encoding="utf-8")
        self.git("add", "later.txt")
        self.git("commit", "-m", "later main")
        registration, _lease, _integration = self.paths()
        edited = json.loads(registration.read_text(encoding="utf-8"))
        edited["base_commit"] = self.git("rev-parse", "main").stdout.strip()
        registration.write_text(json.dumps(edited), encoding="utf-8")
        with self.assertRaisesRegex(CardineError, "preparation-receipt-mismatch"):
            self.stage()
        self.assert_nothing_staged()

    def test_declaration_edits_do_not_weaken_the_frozen_candidate_commands(self) -> None:
        worktree = self.implemented()
        before = owner_evidence.candidate_validation_declaration(self.primary, "056", task_project=worktree)
        declaration = self.primary / ".cardine/candidate-validation.json"
        declaration.write_text(json.dumps({"version": 1, "state": "none"}), encoding="utf-8")
        self.assertEqual(
            owner_evidence.candidate_validation_declaration(self.primary, "056", task_project=worktree), before)

    def test_foreign_lease_and_forged_staged_state_stop_and_survive(self) -> None:
        worktree = self.implemented()
        self.measure(worktree)
        _state, lease, integration = self.paths()
        lease.write_text(json.dumps({"task_id": "999", "branch": "task-999", "project": str(self.primary),
                                     "main_commit": self.base}), encoding="utf-8")
        foreign = lease.read_bytes()
        with self.assertRaises(CardineStop):
            self.stage()
        self.assertEqual(lease.read_bytes(), foreign)
        lease.unlink()
        integration.write_text(json.dumps({"task_id": "056", "candidate_tree": "0" * 40}), encoding="utf-8")
        forged = integration.read_bytes()
        with self.assertRaisesRegex(CardineError, "mismatched or stale"):
            self.stage()
        self.assertEqual(integration.read_bytes(), forged)
        self.assertFalse((self.primary / ".git/MERGE_HEAD").exists())

    def test_repeated_resolution_of_a_staged_candidate_writes_nothing(self) -> None:
        worktree = self.implemented()
        self.measure(worktree)
        staged = self.stage()
        _state, lease, integration = self.paths()
        snapshot = (lease.read_bytes(), integration.read_bytes(), self.git("write-tree").stdout)
        with mock.patch.object(receipts, "_durable", side_effect=AssertionError("wrote")):
            self.assertEqual(self.stage(), staged)
            needs = DirectLanding().candidate_needs("056", self.primary)
            self.assertEqual(needs, DirectLanding().candidate_needs("056", self.primary))
        self.assertEqual(needs["decision"], staged["decision"])
        self.assertEqual(needs["required"][0], "git diff --check")
        self.assertEqual(snapshot, (lease.read_bytes(), integration.read_bytes(), self.git("write-tree").stdout))
        owner_merge.abort_task_integration("056", self.primary)


if __name__ == "__main__":
    unittest.main()
