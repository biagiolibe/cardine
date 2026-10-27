"""Command-local observations, effect invalidation and measured Git budgets."""
import ast
from dataclasses import FrozenInstanceError
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from cardine.lifecycle import receipts
from cardine.lifecycle.engine import resolve_run_locations
from cardine.shared import git
from cardine.shared.errors import CardineError
from cardine.shared.project import read_project_declaration
from cardine.tasks.state_core import write_state_bytes
import test_run_delivery
import test_run_preparation

ROOT = Path(__file__).resolve().parents[1]


class CommandContextTest(unittest.TestCase):
    def fixture(self, module, name):
        fixture = getattr(module, name)()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        return fixture

    def measured(self, function):
        calls = []
        run = subprocess.run
        def count(command, *args, **kwargs):
            if command[0] == 'git':
                calls.append(command)
            return run(command, *args, **kwargs)
        with patch.object(git.subprocess, 'run', side_effect=count):
            result = function()
        return result, calls

    def test_command_budgets_and_noop_delivery_writes_nothing(self):
        fixture = self.fixture(test_run_delivery, 'RunDeliveryTest')
        from cardine.lifecycle import engine
        with patch.object(engine, 'resolve_run_locations', wraps=engine.resolve_run_locations) as resolve:
            result, calls = self.measured(fixture.deliver)
        self.assertEqual(resolve.call_count, 1)
        self.assertLessEqual(len(calls), 80)  # Before: 161.
        with patch.object(receipts, '_durable', side_effect=AssertionError('no-op wrote bytes')):
            replay, calls = self.measured(fixture.deliver)
        self.assertEqual(replay, result)
        self.assertLessEqual(len(calls), 42)  # Before: 84.
        self.assertFalse(any('add' in call or 'commit' in call for call in calls))
        _, calls = self.measured(fixture.state)
        self.assertLessEqual(len(calls), 5)
        from cardine.console.snapshot import load_snapshot
        _, calls = self.measured(lambda: load_snapshot(fixture.root))
        self.assertLessEqual(len(calls), 26)  # Receipt-bound source and committed delivery proof (RE7a).
        preparation = self.fixture(test_run_preparation, 'RunPreparationTest')
        _, calls = self.measured(preparation.prepare)
        self.assertLessEqual(len(calls), 18)  # Before: 46.

    def test_git_effect_invalidates_refs_and_worktree_registration(self):
        fixture = self.fixture(test_run_preparation, 'RunPreparationTest')
        with git.command_scope():
            first = git._git_worktrees(fixture.root)
            before = git.git_output(fixture.root, 'rev-parse', 'HEAD')
            prepared = fixture.prepare()
            self.assertEqual(len(git._git_worktrees(fixture.root)), len(first) + 1)
            git.git_output(fixture.root, 'commit', '--allow-empty', '-m', 'New observed fact')
            self.assertNotEqual(git.git_output(fixture.root, 'rev-parse', 'HEAD'), before)
            self.assertIn(prepared['worktree'], [r['worktree'] for r in git._git_worktrees(fixture.root)])

    def test_durable_effect_invalidates_declaration_and_git_facts(self):
        fixture = self.fixture(test_run_preparation, 'RunPreparationTest')
        path = fixture.root / '.cardine/project.json'
        import json
        with git.command_scope():
            first = read_project_declaration(fixture.root)
            git.git_output(fixture.root, 'status', '--porcelain')
            value = json.loads(path.read_bytes())
            value['project'] = {'name': 'Changed project', 'slug': 'changed-project'}
            write_state_bytes(path, receipts.encoded(value))
            self.assertNotEqual(read_project_declaration(fixture.root), first)
            self.assertTrue(git.git_output(fixture.root, 'status', '--porcelain'))

    def test_scope_reads_once_and_never_survives_the_next_command(self):
        fixture = self.fixture(test_run_preparation, 'RunPreparationTest')
        def read_twice():
            with git.command_scope():
                one = git._run_git(fixture.root, 'rev-parse', 'HEAD')
                one.stdout = 'caller mutation'
                return git.git_output(fixture.root, 'rev-parse', 'HEAD')
        first, calls = self.measured(read_twice)
        self.assertEqual(len(calls), 1)
        self.assertNotEqual(first, 'caller mutation')
        _, calls = self.measured(read_twice)
        self.assertEqual(len(calls), 1)

    def test_runtime_is_measured_once_and_a_foreign_runtime_is_rejected(self):
        measured = receipts.runtime_digest_once()
        with patch.object(Path, 'glob', side_effect=AssertionError('runtime rehashed')):
            self.assertEqual(receipts.runtime_digest_once(), measured)
            self.assertEqual(receipts.runtime_digest_once(), measured)
        with patch.object(receipts, '__file__', '/foreign/src/cardine/lifecycle/receipts.py'):
            with self.assertRaisesRegex(CardineError, 'reauthorization'):
                receipts.runtime_digest_once()

    def test_run_context_is_immutable_and_carries_resolution_inputs(self):
        fixture = self.fixture(test_run_preparation, 'RunPreparationTest')
        prepared = fixture.prepare()
        context = resolve_run_locations('001', fixture.root)
        self.assertEqual(context.primary, fixture.root)
        self.assertEqual(context.worktree, Path(prepared['worktree']))
        self.assertEqual(context.common_dir, git.canonical_git_common_dir(fixture.root))
        self.assertEqual(context.runtime_digest, receipts.runtime_digest_once())
        self.assertIsInstance(context.project_declaration, str)
        self.assertIsNotNone(context.record_path)
        with self.assertRaises(FrozenInstanceError):
            context.task_id = '002'

    def test_product_git_subprocesses_use_the_single_gateway(self):
        offenders = []
        gateway_calls = []
        for path in (ROOT / 'src/cardine').rglob('*.py'):
            if 'legacy' in path.relative_to(ROOT / 'src/cardine').parts:
                continue
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and isinstance(node.func.value, ast.Name) and node.func.value.id == 'subprocess'
                        and node.func.attr in ('run', 'Popen', 'call', 'check_call', 'check_output')):
                    continue
                if path == ROOT / 'src/cardine/shared/git.py':
                    gateway_calls.append(node)
                    continue
                command = node.args[0] if node.args else next((k.value for k in node.keywords if k.arg == 'args'), None)
                if (isinstance(command, (ast.List, ast.Tuple)) and command.elts
                        and isinstance(command.elts[0], ast.Constant) and command.elts[0].value == 'git'):
                    offenders.append(f'{path.relative_to(ROOT)}:{node.lineno}')
        self.assertEqual(offenders, [])
        self.assertEqual(len(gateway_calls), 1)


if __name__ == '__main__':
    unittest.main()
