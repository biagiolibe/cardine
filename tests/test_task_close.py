"""Lean closure gates, shared transition state, and archived Resume recovery."""
import json
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import test_execution_boundaries as boundaries

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import meridian


class TaskCloseTest(unittest.TestCase):
    git = boundaries.ExecutionBoundariesTest.git
    commit = boundaries.ExecutionBoundariesTest.commit
    assert_stop = boundaries.ExecutionBoundariesTest.assert_stop

    def setUp(self):
        boundaries.ExecutionBoundariesTest.setUp(self)
        (self.worker / 'PROJECT_WORKFLOW.md').write_text('LEAN_DELIVERY\n')
        identity = meridian.resolve_task_identity(self.worker, '001', 'existing')
        identity.handoff_path.parent.mkdir(parents=True)
        identity.handoff_path.write_text('## Completion Report — 001\n')
        self.commit('Select Lean and commit handoff')
        self.identity = identity

    def snapshot(self):
        return ({p.relative_to(self.worker).as_posix(): p.read_bytes()
                 for p in self.worker.rglob('*') if p.is_file()},
                self.git('ls-files', '--stage'), self.git('rev-parse', 'HEAD'))

    def refused(self, code):
        before = self.snapshot()
        self.assert_stop(code, lambda: meridian.close_task(self.worker, '001'))
        self.assertEqual(self.snapshot(), before)

    def test_success_stages_exact_archive_and_identical_transition_state_without_commit(self):
        clock = mock.Mock()
        clock.now.return_value = datetime(2026, 10, 15, tzinfo=timezone.utc)
        with mock.patch.object(meridian, 'datetime', clock):
            expected = meridian.transition_task_state(self.worker, '001', 'DONE')
            # Restore only the output of the comparison transition in this fixture.
            meridian.state_path(self.worker, '001').unlink()
            (self.worker / self.record).write_bytes(self.git('show', 'HEAD:tasks/001.md').encode() + b'\n')
            before = self.git('rev-parse', 'HEAD')
            result = meridian.close_task(self.worker, '001')
        self.assertEqual(result['state'], expected)
        self.assertFalse(result['committed'])
        self.assertEqual(self.git('rev-parse', 'HEAD'), before)
        self.assertFalse((self.worker / self.record).exists())
        self.assertTrue((self.worker / 'tasks/done/001.md').is_file())
        self.assertEqual(set(self.git('diff', '--cached', '--name-only', '--no-renames').splitlines()),
                         {'.meridian/tasks/001.json', 'tasks/001.md', 'tasks/done/001.md'})
        self.assertEqual(self.git('diff', '--name-only'), '')
        self.assertIn('Status: DONE', (self.worker / result['archive']).read_text())

    def test_primary_and_dirty_worktrees_refuse_without_writes(self):
        (self.worker / 'partial').write_text('unfinished')
        self.refused('WRONG_WORKTREE')
        os.chdir(self.primary)
        before = self.git('status', '--porcelain', cwd=self.primary)
        self.assert_stop('WRONG_WORKTREE', lambda: meridian.close_task(self.primary, '001'))
        self.assertEqual(self.git('status', '--porcelain', cwd=self.primary), before)

    def test_missing_and_uncommitted_handoff_refuse(self):
        self.identity.handoff_path.unlink()
        self.commit('Remove handoff')
        self.refused('HANDOFF_REPORT_MISSING')
        self.identity.handoff_path.write_text('ignored handoff')
        (self.worker / '.gitignore').write_text('tasks/handoffs/\n')
        self.commit('Ignore uncommitted handoff')
        self.refused('HANDOFF_REPORT_MISSING')

    def test_archived_record_refuses_without_state_write(self):
        archive = self.worker / 'tasks/done/001.md'
        archive.parent.mkdir()
        self.identity.task_path.rename(archive)
        self.commit('Archive without state')
        self.refused('TASK_STATUS_REJECTED')
        self.assertFalse(meridian.state_path(self.worker, '001').exists())

    def test_done_and_invalid_state_refuse_without_archive(self):
        meridian.transition_task_state(self.worker, '001', 'DONE')
        self.commit('Already done')
        self.refused('TASK_STATUS_REJECTED')
        path = meridian.state_path(self.worker, '001')
        path.write_text('{}\n')
        self.commit('Invalid state')
        self.refused('TASK_STATE_INVALID')

    def test_governed_refusal_names_transition_command(self):
        (self.worker / 'PROJECT_WORKFLOW.md').write_text('GOVERNED_SDD\n')
        self.commit('Select Governed')
        self.refused('TASK_STATUS_REJECTED')
        with self.assertRaisesRegex(meridian.MeridianStop, 'meridian task transition'):
            meridian.close_task(self.worker, '001')

    def test_resume_archived_done_with_staged_and_committed_closure(self):
        meridian.close_task(self.worker, '001')
        before = self.snapshot()
        result = meridian.execution_start(self.worker, '001', resume=True)
        self.assertFalse(result['started'])
        self.assertEqual(result['next_action'], 'commit-closure-records')
        self.assertEqual(self.snapshot(), before)
        self.git('commit', '-qm', 'Commit closure')
        before = self.snapshot()
        result = meridian.execution_start(self.worker, '001', resume=True)
        self.assertEqual(result['next_action'], 'worktree-advance')
        self.assertEqual(self.snapshot(), before)
        self.assert_stop('TASK_STATUS_REJECTED', lambda: meridian.execution_start(self.worker, '001'))

    def close_from(self, directory):
        os.chdir(directory)
        before = self.git('rev-parse', 'HEAD')
        result = meridian.close_task(self.worker, '001')
        self.assertEqual(result['state']['status'], 'DONE')
        self.assertEqual(result['state']['transitions'][-1]['commit'], before)
        self.assertEqual(self.git('rev-parse', 'HEAD'), before)
        self.assertEqual(set(self.git('diff', '--cached', '--name-only', '--no-renames').splitlines()),
                         {'.meridian/tasks/001.json', 'tasks/001.md', 'tasks/done/001.md'})
        self.assertEqual(self.git('diff', '--name-only'), '')
        self.assertEqual(Path.cwd(), directory.resolve())

    def test_close_from_primary(self):
        self.close_from(self.primary)

    def test_close_from_unrelated_directory(self):
        self.close_from(Path(self.temp.name))

    def test_cli_parser_accepts_close_flags(self):
        args = meridian.build_parser().parse_args(['task', 'close', '001', '--project', str(self.worker), '--format', 'json'])
        self.assertEqual(args.task_command, 'close')
