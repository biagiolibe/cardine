"""Configured bootstrap, ownership and interruption boundaries in disposable homes."""
from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from cardine_cli_support import ROOT
from cardine.cli import build_parser, main
from cardine.lifecycle import receipts
from cardine.shared.errors import CardineError
from cardine.shared.project import resolve_project_configuration
from cardine.tasks.status import load_task_status
from cardine.tasks.status_render import stale_views
from cardine.templates.init import apply_init, init_cli, plan_init
from cardine.templates.manifest import load_manifest


VALIDATION = {"commands": {"test": "python3 -m example_tests"}, "baseline": ["test"],
              "candidate": {"REUSE": [], "BOUNDED": ["test"], "FULL": ["test"]}}


class Interrupted(BaseException):
    pass


class InitTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name).resolve()
        self.root = self.home / "project"
        self.receipt_root = self.home / "receipts"
        self.receipt_root.mkdir()
        for patcher in (patch.dict(os.environ, HOME=str(self.home), XDG_CONFIG_HOME=str(self.home / "xdg")),
                        patch.object(tempfile, "tempdir", str(self.receipt_root))):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.validation = self.home / "validation.json"
        self.validation.write_text(json.dumps(VALIDATION))

    def plan(self, root=None, **overrides):
        choices = dict(name="Example Project", slug="example-project", preset="lean", language="Italian",
                       task_identity="opaque", validation=VALIDATION)
        choices.update(overrides)
        return plan_init(root or self.root, ROOT, **choices)

    def tree(self, root):
        return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}

    def args(self):
        return ["init", "--project", str(self.root), "--check", "--name", "Example Project",
                "--slug", "example-project", "--preset", "lean", "--language", "Italian",
                "--task-identity", "opaque", "--validation", str(self.validation)]

    def test_every_policy_choice_and_operation_is_required(self):
        args = self.args()
        for flag in ("--project", "--check", "--name", "--slug", "--preset", "--language",
                     "--task-identity", "--validation"):
            reduced = args.copy()
            index = reduced.index(flag)
            del reduced[index:index + (1 if flag == "--check" else 2)]
            with self.subTest(flag=flag), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    build_parser().parse_args(reduced)
        self.assertFalse(self.root.exists())

    def test_preview_repeats_without_writes_and_apply_is_idempotent(self):
        before = self.tree(self.home)
        for _ in range(2):
            with patch.object(sys, "argv", ["cardine", *self.args()]), contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(), 0)
            self.assertIn("choices:", output.getvalue())
            self.assertIn("manifest.json", output.getvalue())
            self.assertEqual(self.tree(self.home), before)
        args = build_parser().parse_args([x if x != "--check" else "--apply" for x in self.args()])
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(init_cli(args, ROOT), 0)
        self.assertIn("result: initialized", output.getvalue())
        after = self.tree(self.home)
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(init_cli(args, ROOT), 0)
        self.assertIn("result: no-op", output.getvalue())
        self.assertEqual(self.tree(self.home), after)
        self.assertFalse((self.home / ".codex").exists())

    def test_both_presets_and_identities_generate_valid_empty_status_and_lock(self):
        for preset in ("lean", "governed"):
            for identity in ("opaque", "milestone"):
                with self.subTest(preset=preset, identity=identity):
                    root = self.home / f"{preset}-{identity}"
                    plan = self.plan(root, preset=preset, task_identity=identity)
                    self.assertTrue(apply_init(plan))
                    config = resolve_project_configuration(root)
                    self.assertEqual(config["preset"], preset)
                    self.assertEqual(config["taskIdentity"]["mode"], identity)
                    self.assertEqual(config["validation"], VALIDATION)
                    model = load_task_status(root)
                    self.assertEqual(model["diagnostics"], [])
                    self.assertEqual(model["totals"]["total"], 0)
                    self.assertEqual(stale_views(root), [])
                    self.assertEqual(load_manifest(root, ROOT)["workflowMode"], "single")
                    self.assertTrue((root / "tasks/done").is_dir())
                    self.assertIn('`Italian`', (root / "LANGUAGE_POLICY.md").read_text())
                    self.assertFalse((root / ".meridian").exists())
                    self.assertEqual(list((root / ".cardine/tasks").iterdir()), [])
                    self.assertNotIn("ADR-0001", (root / "docs/ARCHITECTURE_DECISIONS.md").read_text())
                    # Baselines are pristine template bytes, not configured consumer bytes.
                    for relative, content in plan.outputs.items():
                        if relative.startswith(".cardine/baselines/"):
                            self.assertEqual((root / relative).read_bytes(), content)

    def test_explicit_empty_validation_is_valid_but_missing_choices_are_not(self):
        empty = {"commands": {}, "baseline": [], "candidate": dict.fromkeys(("REUSE", "BOUNDED", "FULL"), [])}
        apply_init(self.plan(validation=empty))
        self.assertEqual(resolve_project_configuration(self.root)["validation"], empty)
        for invalid in ({}, {**VALIDATION, "candidate": {"FULL": []}}, {**VALIDATION, "baseline": ["unknown"]}):
            with self.assertRaises(CardineError):
                self.plan(self.home / "invalid", validation=invalid)

    def test_existing_unrelated_project_files_are_preserved_and_conflicts_are_refused(self):
        self.root.mkdir()
        (self.root / "app.py").write_text("# user code\n")
        (self.root / "README.md").write_text("# user readme\n")
        before = self.tree(self.home)
        with self.assertRaisesRegex(CardineError, "conflicts"):
            self.plan()
        self.assertEqual(before, self.tree(self.home))
        (self.root / "README.md").unlink()
        apply_init(self.plan())
        self.assertEqual((self.root / "app.py").read_text(), "# user code\n")

    def test_identical_foreign_file_has_no_ownership(self):
        plan = self.plan()
        self.root.mkdir()
        (self.root / "AGENTS.md").write_bytes(plan.outputs["AGENTS.md"])
        with self.assertRaisesRegex(CardineError, "conflicts"):
            apply_init(plan)

    def test_symlinks_directories_changed_inputs_and_owned_edits_are_preserved(self):
        outside = self.home / "outside"
        outside.mkdir()
        self.root.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(CardineError):
            self.plan()
        self.root.unlink()
        plan = self.plan()
        self.root.mkdir()
        (self.root / "docs").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(CardineError):
            apply_init(plan)
        self.assertEqual(list(outside.iterdir()), [])
        (self.root / "docs").unlink()
        apply_init(self.plan())
        before = self.tree(self.home)
        with self.assertRaisesRegex(CardineError, "inputs"):
            self.plan(preset="governed")
        self.assertEqual(before, self.tree(self.home))
        (self.root / "AGENTS.md").write_text("user edit\n")
        with self.assertRaisesRegex(CardineError, "changed"):
            self.plan()
        self.assertEqual((self.root / "AGENTS.md").read_text(), "user edit\n")

    def test_every_effect_and_plan_and_result_boundary_converges(self):
        reference = self.home / "reference"
        reference_plan = self.plan(reference)
        apply_init(reference_plan)
        expected = self.tree(reference)
        intent = receipts._load_intent(reference_plan.receipt)
        seams = [f"{when}_{name}" for name in intent["effects"] for when in ("before", "after")]
        seams += [f"{when}_init_{step}" for step in ("plan", "result") for when in ("before", "after")]
        self.assertTrue(any("baselines/" in name for name in seams))
        self.assertTrue(any("manifest.json" in name for name in seams))
        self.assertTrue(any("tasks/QUEUE.md" in name for name in seams))
        for index, seam in enumerate(seams):
            with self.subTest(seam=seam):
                root = self.home / f"retry-{index}"
                # Directory labels contain the anchor, while file labels are relative.
                actual_seam = seam.replace(str(reference), str(root))
                def interrupt(name):
                    if name == actual_seam:
                        raise Interrupted(name)
                with patch.object(receipts, "boundary", interrupt):
                    with self.assertRaises(Interrupted):
                        apply_init(self.plan(root))
                apply_init(self.plan(root))
                self.assertEqual(self.tree(root), expected)
                snapshot = self.tree(root)
                receipt = self.plan(root).receipt.read_bytes()
                self.assertFalse(apply_init(self.plan(root)))
                self.assertEqual(self.tree(root), snapshot)
                self.assertEqual(self.plan(root).receipt.read_bytes(), receipt)

    def test_real_process_kill_then_retry_preserves_exact_owned_outputs(self):
        child = '''
import os, sys, tempfile
from pathlib import Path
from cardine.lifecycle import receipts
from cardine.templates.init import apply_init, plan_init
import json
tempfile.tempdir = sys.argv[3]
def boundary(name):
    if name == sys.argv[4]: os._exit(93)
receipts.boundary = boundary
apply_init(plan_init(Path(sys.argv[1]), Path(sys.argv[2]), name='Example Project',
    slug='example-project', preset='lean', language='Italian', task_identity='opaque',
    validation=json.loads(sys.argv[5])))
'''
        command = [sys.executable, "-c", child, str(self.root), str(ROOT), str(self.receipt_root),
                   "after_file:.cardine/manifest.json", json.dumps(VALIDATION)]
        env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
        self.assertEqual(subprocess.run(command, env=env, capture_output=True).returncode, 93)
        plan = self.plan()
        before = receipts._load_intent(plan.receipt)
        apply_init(plan)
        after = receipts._load_intent(plan.receipt)
        self.assertEqual(before["operation_id"], after["operation_id"])
        self.assertEqual(after["result"], {"done": True})
        self.assertEqual(stale_views(self.root), [])

    def test_interrupted_apply_refuses_changed_owned_outputs_and_changed_policy(self):
        def interrupt(name):
            if name == "after_file:AGENTS.md":
                raise Interrupted(name)
        with patch.object(receipts, "boundary", interrupt):
            with self.assertRaises(Interrupted):
                apply_init(self.plan())
        before = self.tree(self.home)
        with self.assertRaisesRegex(CardineError, "inputs"):
            self.plan(language="English")
        self.assertEqual(before, self.tree(self.home))
        (self.root / "AGENTS.md").write_text("user overlay after interruption\n")
        before = self.tree(self.home)
        with self.assertRaisesRegex(CardineError, "changed"):
            self.plan()
        self.assertEqual(before, self.tree(self.home))


if __name__ == "__main__":
    unittest.main()
