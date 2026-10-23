"""Lean closure gates and shared transition state; closure writes nothing."""
import json
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from project_config_support import write_project_config
from task_contract_support import freeze_record, seal_state
from unittest import mock

import test_execution_boundaries as boundaries

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import cardine_cli
from cardine import cli as owner_cli
from cardine.tasks import transitions as owner_tasks_transitions
import cardine.shared.errors as shared_errors
from cardine.tasks import identity as owner_tasks_identity


from cardine.lifecycle import commands as owner_lifecycle_commands

class TaskCloseTest(unittest.TestCase):
    git = boundaries.ExecutionBoundariesTest.git
    commit = boundaries.ExecutionBoundariesTest.commit
    assert_stop = boundaries.ExecutionBoundariesTest.assert_stop

    def setUp(self):
        boundaries.ExecutionBoundariesTest.setUp(self)
        write_project_config(self.primary, "lean", validation=boundaries.VALIDATION)
        write_project_config(self.worker, "lean", validation=boundaries.VALIDATION)
        identity = owner_tasks_identity.resolve_task_identity(self.worker, '001', 'existing')
        identity.handoff_path.parent.mkdir(parents=True)
        identity.handoff_path.write_text('## Completion Report — 001\n')
        self.commit('Select Lean and commit handoff')
        self.identity = identity
        record = identity.task_path
        record.write_text(record.read_text().replace('Review: REQUIRED', 'Review: NOT_REQUIRED'))
        freeze_record(self.worker, '001', record)
        self.commit('Resolve no-review task')
        owner_lifecycle_commands.execution_start(self.worker, '001')
        self.commit('Start task')

    def snapshot(self):
        return ({p.relative_to(self.worker).as_posix(): p.read_bytes()
                 for p in self.worker.rglob('*') if p.is_file()},
                self.git('ls-files', '--stage'), self.git('rev-parse', 'HEAD'))

    def refused(self, code):
        before = self.snapshot()
        self.assert_stop(code, lambda: owner_tasks_transitions.close_task(self.worker, '001'))
        self.assertEqual(self.snapshot(), before)

    def test_success_verifies_closure_and_leaves_every_record_in_place(self):
        expected = json.loads(cardine_cli.state_path(self.worker, '001').read_text())
        before = self.snapshot()
        result = owner_tasks_transitions.close_task(self.worker, '001')
        self.assertEqual(result['state'], expected)
        self.assertEqual(result['record'], 'tasks/001.md')
        self.assertTrue(result['verified'])
        self.assertFalse(result['staged'])
        self.assertFalse(result['committed'])
        self.assertEqual(self.snapshot(), before)
        self.assertTrue((self.worker / 'tasks/001.md').is_file())
        self.assertFalse((self.worker / 'tasks/done').exists())
        self.assertEqual(self.git('diff', '--cached', '--name-only'), '')

    def test_primary_and_dirty_worktrees_refuse_without_writes(self):
        (self.worker / 'partial').write_text('unfinished')
        self.refused('WRONG_WORKTREE')
        os.chdir(self.primary)
        before = self.git('status', '--porcelain', cwd=self.primary)
        self.assert_stop('WRONG_WORKTREE', lambda: owner_tasks_transitions.close_task(self.primary, '001'))
        self.assertEqual(self.git('status', '--porcelain', cwd=self.primary), before)

    def test_missing_and_uncommitted_handoff_refuse(self):
        self.identity.handoff_path.unlink()
        self.commit('Remove handoff')
        self.refused('HANDOFF_REPORT_MISSING')
        self.identity.handoff_path.write_text('ignored handoff')
        (self.worker / '.gitignore').write_text('tasks/handoffs/\n')
        self.commit('Ignore uncommitted handoff')
        self.refused('HANDOFF_REPORT_MISSING')

    def test_record_path_does_not_decide_closure(self):
        archive = self.worker / 'tasks/done/001.md'
        archive.parent.mkdir()
        self.identity.task_path.rename(archive)
        self.commit('Historical record under done')
        result = owner_tasks_transitions.close_task(self.worker, '001')
        self.assertEqual(result['record'], 'tasks/done/001.md')
        self.assertTrue(archive.is_file())
        self.assertEqual(json.loads(cardine_cli.state_path(self.worker, '001').read_text())['status'], 'in_progress')

    def test_uncommitted_record_refuses_without_writes(self):
        record = self.identity.task_path
        record.write_text(record.read_text() + '\nUncommitted evidence.\n')
        self.refused('WRONG_WORKTREE')

    def test_done_and_invalid_state_refuse(self):
        path = cardine_cli.state_path(self.worker, '001')
        state = json.loads(path.read_text())
        state['transitions'].append(dict(state['transitions'][-1], **{'from': 'in_progress', 'to': 'done'}))
        state['status'] = 'done'
        path.write_text(json.dumps(state))
        seal_state(self.worker, '001')
        self.commit('Already done')
        self.refused('TASK_STATUS_REJECTED')
        path = cardine_cli.state_path(self.worker, '001')
        path.write_text('{}\n')
        self.commit('Invalid state')
        self.refused('TASK_STATE_INVALID')

    def test_cancellation_writes_reason_in_state_and_keeps_the_record(self):
        record = self.identity.task_path
        before = record.read_bytes()
        state = owner_tasks_transitions.transition_task_state(
            self.worker, '001', 'cancelled', cancellation_authority='owner', reason='superseded')
        self.assertEqual(state['status'], 'cancelled')
        self.assertEqual(state['transitions'][-1]['reason'], 'superseded')
        self.assertEqual(state['transitions'][-1]['authority'], 'owner')
        self.assertEqual(state['transitions'][-2]['to'], 'in_progress')
        self.assertEqual(record.read_bytes(), before)
        self.assertFalse((self.worker / 'tasks/done').exists())

    def test_governed_refusal_names_transition_command(self):
        write_project_config(self.primary, "governed")
        write_project_config(self.worker, "governed")
        seal_state(self.worker, '001')
        self.commit('Select Governed')
        # The existing task keeps its original policy after a preset switch.
        result = owner_tasks_transitions.close_task(self.worker, '001')
        self.assertEqual(result['state']['status'], 'in_progress')
        self.assertEqual(result['state']['contract']['preset'], 'lean')

    def test_close_writes_nothing_so_resume_has_no_closure_records_to_commit(self):
        owner_tasks_transitions.close_task(self.worker, '001')
        before = self.snapshot()
        result = owner_lifecycle_commands.execution_start(self.worker, '001', resume=True)
        self.assertEqual(result['status'], 'in_progress')
        self.assertNotIn('next_action', result)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.git('status', '--porcelain'), '')

    def close_from(self, directory):
        os.chdir(directory)
        before = self.git('rev-parse', 'HEAD')
        result = owner_tasks_transitions.close_task(self.worker, '001')
        self.assertEqual(result['state']['status'], 'in_progress')
        self.assertEqual(result['state']['transitions'][-1]['commit'], self.git('rev-parse', 'HEAD^'))
        self.assertEqual(self.git('rev-parse', 'HEAD'), before)
        self.assertEqual(self.git('diff', '--cached', '--name-only'), '')
        self.assertEqual(self.git('diff', '--name-only'), '')
        self.assertEqual(Path.cwd(), directory.resolve())

    def test_close_from_primary(self):
        self.close_from(self.primary)

    def test_close_from_unrelated_directory(self):
        self.close_from(Path(self.temp.name))

    def test_cli_parser_accepts_close_flags(self):
        args = owner_cli.build_parser().parse_args(['task', 'close', '001', '--project', str(self.worker), '--format', 'json'])
        self.assertEqual(args.task_command, 'close')
