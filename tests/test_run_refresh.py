"""Bringing a task branch up to date with main before CI validates it (task 255)."""
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'tests'))
import test_run_ci
from cardine.integration import candidate
from cardine.integration.decision import IntegrationValidationOutcome
from cardine.lifecycle import engine
from cardine.lifecycle.scope import changed_paths
from cardine.shared.errors import CardineStop
from cardine.shared.layout import names
from cardine.worktree.storage import _lifecycle_paths

LINES = ''.join(f'line {number}\n' for number in range(1, 31))


class RefreshTest(test_run_ci.CiTest):
    def overlapping(self, *, conflicting=False):
        """A delivered task and an advanced main that both changed README.md."""
        (self.primary / 'README.md').write_text(LINES)
        self.git('add', '.')
        self.git('commit', '-m', 'readme')
        locations = self.ready()
        (self.worker / 'README.md').write_text(LINES.replace('line 1\n', 'task line\n'))
        self.git('add', '.', cwd=self.worker)
        self.git('commit', '-m', 'edit readme', cwd=self.worker)
        self.measure(self.worker)
        self.advance_main('main line' if conflicting else None)
        return locations

    def advance_main(self, conflicting):
        (self.primary / 'README.md').write_text(
            LINES.replace('line 1\n', 'main line\n') if conflicting else LINES.replace('line 30\n', 'main line\n'))
        (self.primary / 'other.txt').write_text('from main\n')
        self.git('add', '.')
        self.git('commit', '-m', 'advance main')

    def recorded_base(self):
        from cardine.tasks.identity import resolve_task_identity
        identity = resolve_task_identity(self.primary, '056', 'existing')
        return json.loads(_lifecycle_paths(self.primary, identity)[0].read_text())['base_commit']

    def drive(self, locations, *, limit=12):
        actions = []
        for _ in range(limit):
            result = engine.run_validation_step(locations)
            engine.validate_output(result)
            actions.append(result['action'])
            if result['action'] == 'poll-ci':
                self.checks(self.head())
            if result['action'] == 'validate-candidate':
                return actions, result
        self.fail(f'no candidate after {limit} steps: {actions}')

    def test_full_decision_refreshes_then_validates_and_lands_the_merge_commit(self):
        locations = self.overlapping()
        main = self.git('rev-parse', 'main').stdout.strip()
        old_head = self.git('rev-parse', 'HEAD', cwd=self.worker).stdout.strip()
        first = engine.run_validation_step(locations)
        engine.validate_output(first)
        self.assertEqual((first['outcome'], first['action']), ('next', 'refresh-from-main'))
        self.assertEqual(len(first['diagnostics']), 1)
        self.assertIn(main, first['diagnostics'][0]['message'])
        self.assertIn('README.md', first['diagnostics'][0]['message'])
        parents = self.git('log', '-1', '--format=%P', cwd=self.worker).stdout.split()
        self.assertEqual(sorted(parents), sorted([old_head, main]))
        self.assertEqual(self.git('log', '-1', '--format=%s', cwd=self.worker).stdout.strip(), 'Merge main into task-056')
        self.assertEqual(self.recorded_base(), main)
        self.assertEqual((self.push_count(), self.gh_calls()), (0, 0))
        actions, staged = self.drive(locations)
        self.assertEqual(staged['action'], 'validate-candidate')
        self.assertEqual(self.push_count(), 1)
        self.assertEqual(self.remote_tip(), self.head())
        self.assertEqual(self.git('merge-base', '--is-ancestor', main, self.head(), cwd=self.worker, check=False).returncode, 0)
        integration = json.loads((Path(self.git('rev-parse', '--git-common-dir').stdout.strip()).resolve()
                                  / names().integration_state_name).read_text())
        self.assertEqual(integration['decision'], 'REUSE')
        self.assertEqual(integration['validated_base_commit'], main)

    def test_the_refresh_writes_no_delivery_operation_and_the_next_run_delivers_the_merged_head(self):
        from cardine.lifecycle import receipts
        from cardine.lifecycle.delivery import _operation_path
        locations = self.overlapping()
        operation = _operation_path(self.worker, '056')
        before = operation.read_bytes() if operation.exists() else None
        first = engine.run_validation_step(locations)
        self.assertEqual(first['action'], 'refresh-from-main')
        self.assertEqual(operation.read_bytes() if operation.exists() else None, before)
        self.drive(locations)
        if operation.exists():
            self.assertEqual(receipts._load_intent(operation)['base'], self.git('rev-parse', 'main').stdout.strip())

    def merge_in_progress(self):
        path = self.git('rev-parse', '--git-path', 'MERGE_HEAD', cwd=self.worker).stdout.strip()
        return (self.worker / path).exists()

    def test_conflicting_refresh_stops_and_leaves_the_branch_untouched(self):
        locations = self.overlapping(conflicting=True)
        head, base = self.git('rev-parse', 'HEAD', cwd=self.worker).stdout.strip(), self.recorded_base()
        with self.assertRaises(CardineStop) as raised:
            engine.run_validation_step(locations)
        self.assertEqual(raised.exception.code, 'INTEGRATION_CONFLICT')
        self.assertIn('cardine run 056', raised.exception.detail)
        self.assertFalse(self.merge_in_progress())
        self.assertEqual(self.git('status', '--porcelain', cwd=self.worker).stdout, '')
        self.assertEqual(self.git('rev-parse', 'HEAD', cwd=self.worker).stdout.strip(), head)
        self.assertEqual(self.recorded_base(), base)
        self.assertEqual((self.push_count(), self.gh_calls()), (0, 0))

    def test_after_a_refresh_scope_sees_only_the_task_paths(self):
        locations = self.overlapping()
        old_base = self.recorded_base()
        self.assertEqual(engine.run_validation_step(locations)['action'], 'refresh-from-main')
        self.assertIn('other.txt', changed_paths(self.worker, old_base))
        paths = changed_paths(self.worker, self.recorded_base())
        self.assertIn('README.md', paths)
        self.assertNotIn('other.txt', paths)
        from cardine.lifecycle.execution import enforce_execution_scope
        enforce_execution_scope(self.worker, '056')

    def test_a_rerun_after_a_killed_refresh_only_records_the_base(self):
        locations = self.overlapping()
        main = self.git('rev-parse', 'main').stdout.strip()
        self.git('merge', '--no-ff', '-m', 'Merge main into task-056', main, cwd=self.worker)
        self.assertNotEqual(self.recorded_base(), main)
        actions = []
        while 'refresh-from-main' not in actions and len(actions) < 6:
            actions.append(engine.run_validation_step(locations)['action'])
        self.assertIn('refresh-from-main', actions)
        self.assertEqual(self.recorded_base(), main)
        self.assertEqual(self.git('rev-list', '--merges', '--count', f'{main}..HEAD', cwd=self.worker).stdout.strip(), '1')

    def test_reuse_and_bounded_decisions_do_not_refresh(self):
        locations = self.overlapping()
        from cardine.integration import refresh
        self.assertIsNotNone(refresh.refresh_inputs(locations, self.state()))
        self.git('reset', '-q', '--hard', 'HEAD~1', cwd=self.primary)
        (self.primary / 'other.txt').write_text('independent\n')
        self.git('add', '.')
        self.git('commit', '-m', 'independent')
        self.assertIsNone(refresh.refresh_inputs(locations, self.state()))
        result = engine.run_validation_step(locations)
        self.assertEqual(result['action'], 'poll-ci')

    def test_without_ci_before_landing_nothing_refreshes(self):
        (self.primary / 'README.md').write_text(LINES)
        self.git('add', '.')
        self.git('commit', '-m', 'readme')
        locations = self.ready(enabled=False)
        (self.worker / 'README.md').write_text(LINES.replace('line 1\n', 'task line\n'))
        self.git('add', '.', cwd=self.worker)
        self.git('commit', '-m', 'edit readme', cwd=self.worker)
        self.measure(self.worker)
        self.advance_main(None)
        from cardine.integration import refresh
        self.assertIsNone(refresh.refresh_inputs(locations, self.state()))


for _name in [name for name in dir(test_run_ci.CiTest) if name.startswith('test_')]:
    setattr(RefreshTest, _name, None)

class PolicyRefreshTest(unittest.TestCase):
    """Part 5: a task branch whose policy predates the policy accepted on main."""

    def setUp(self):
        import os
        import tempfile
        from copy import deepcopy
        from unittest import mock
        from cardine.tasks.creation import create_task
        from control_support import adapter
        from project_config_support import write_project_config
        from task_contract_support import VALIDATION, contract_record
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name).resolve()
        self.root = base / 'project'
        self.root.mkdir()
        write_project_config(self.root, 'lean', validation=deepcopy(VALIDATION))
        (self.root / '.gitignore').write_text('.cardine/receipt-authority.json\n.cardine/task-creation.guard\n')
        self.git(self.root, 'init', '-b', 'main')
        self.git(self.root, 'config', 'user.name', 'Refresh Test')
        self.git(self.root, 'config', 'user.email', 'refresh@example.test')
        self.git(self.root, 'add', '.')
        self.git(self.root, 'commit', '-m', 'Policy')
        create_task(self.root, '001', contract_record('001'))
        self.git(self.root, 'add', '.')
        self.git(self.root, 'commit', '-m', 'Task 001')
        for patcher in (mock.patch.dict(os.environ, {'CARDINE_WORKTREE_ROOT': str(base / 'worktrees')}),
                        mock.patch('cardine.lifecycle.control.host_adapter', return_value=adapter('coordinator'))):
            patcher.start()
            self.addCleanup(patcher.stop)
        previous = Path.cwd()
        self.addCleanup(os.chdir, previous)
        os.chdir(self.root)
        from cardine.lifecycle import receipts
        receipts._durable(receipts._local_authority_path(self.root), receipts.encoded(receipts.observed_authority(self.root)))
        self.locations = candidate.locations_for('001', self.root)
        started = engine.dispatch_run(self.locations)
        self.assertEqual(started['action'], 'execution-start', started)
        self.worker = self.locations.worktree

    def git(self, root, *args):
        import subprocess
        return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.DEVNULL, text=True).strip()

    def change_policy_on_main(self, *, accept=True):
        from cardine.lifecycle import receipts
        path = self.root / '.cardine/project.json'
        path.write_bytes(path.read_bytes() + b'\n')
        self.git(self.root, 'add', '.cardine/project.json')
        self.git(self.root, 'commit', '-m', 'Change policy')
        if accept:
            receipts._durable(receipts._local_authority_path(self.root),
                              receipts.encoded(receipts.observed_authority(self.root)))

    def recorded_base(self):
        from cardine.tasks.identity import resolve_task_identity
        identity = resolve_task_identity(self.root, '001', 'existing')
        return json.loads(_lifecycle_paths(self.root, identity)[0].read_text())['base_commit']

    def test_a_clean_task_branch_merges_main_and_the_next_run_passes_authority(self):
        self.change_policy_on_main()
        main = self.git(self.root, 'rev-parse', 'main')
        result = engine.dispatch_run(self.locations)
        engine.validate_output(result)
        self.assertEqual((result['outcome'], result['action']), ('next', 'refresh-from-main'), result['diagnostics'])
        self.assertEqual([item['message'] for item in result['diagnostics']],
                         ['the task branch predates the policy accepted on main; merging main'])
        self.assertEqual(self.git(self.worker, 'rev-parse', 'HEAD^2'), main)
        self.assertEqual(self.recorded_base(), main)
        again = engine.dispatch_run(self.locations)
        engine.validate_output(again)
        self.assertNotIn(again['action'], ('refresh-from-main', 'commit-before-refresh'))
        # The fixture contract has no frozen surface, so the run stops there, past the authority check.
        self.assertNotIn('reauthorization', ' '.join(item['message'] for item in again['diagnostics']))

    def test_uncommitted_changes_merge_nothing(self):
        self.change_policy_on_main()
        (self.worker / 'work.txt').write_text('draft\n')
        head, base = self.git(self.worker, 'rev-parse', 'HEAD'), self.recorded_base()
        result = engine.dispatch_run(self.locations)
        engine.validate_output(result)
        self.assertEqual((result['outcome'], result['action']), ('next', 'commit-before-refresh'))
        self.assertIn('cardine run 001', result['diagnostics'][0]['message'])
        self.assertEqual(self.git(self.worker, 'rev-parse', 'HEAD'), head)
        self.assertEqual(self.recorded_base(), base)

    def test_a_policy_written_on_the_task_branch_keeps_the_stop(self):
        path = self.worker / '.cardine/project.json'
        path.write_bytes(path.read_bytes() + b' \n')
        self.git(self.worker, 'add', '.cardine/project.json')
        self.git(self.worker, 'commit', '-m', 'Task policy')
        self.change_policy_on_main()
        head = self.git(self.worker, 'rev-parse', 'HEAD')
        result = engine.dispatch_run(self.locations)
        engine.validate_output(result)
        self.assertEqual(result['outcome'], 'blocked')
        self.assertEqual(result['stop']['code'], 'TASK_STATE_INVALID')
        self.assertIn('task', result['stop']['detail'])
        self.assertIn(str(self.worker), result['stop']['detail'])
        self.assertNotIn('cardine authorize', result['stop']['detail'])
        self.assertNotIn('developer reauthorization required', result['stop']['detail'])
        self.assertEqual(self.git(self.worker, 'rev-parse', 'HEAD'), head)

    def test_a_main_policy_that_was_not_accepted_keeps_the_stop(self):
        self.change_policy_on_main(accept=False)
        result = engine.dispatch_run(self.locations)
        self.assertEqual(result['outcome'], 'blocked')
        self.assertIn('main', result['stop']['detail'])
        self.assertIn('cardine authorize', result['stop']['detail'])


if __name__ == '__main__':
    unittest.main()
