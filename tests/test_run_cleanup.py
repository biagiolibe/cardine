"""Delivery/cleanup with a real bare origin, exact refs and killed subprocesses."""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'tests'))
from cardine.integration import candidate, cleanup, merge
from cardine.lifecycle import engine, receipts
from cardine.shared.errors import CardineError
from cardine.worktree.checkout import inspect_task_worktree, prepare_task_worktree
import worktree_support as support


class CleanupTest(support.BoundedWorktreeLifecycleFixture):
    def setUp(self):
        super().setUp()
        self.origin = self.root / 'origin.git'
        subprocess.run(['git', 'init', '--bare', '-b', 'main', str(self.origin)], check=True, capture_output=True)
        self.git('remote', 'add', 'origin', str(self.origin))
        self.git('push', 'origin', 'main')
        self.worker = Path(self.prepare()['worktree'])
        (self.worker / 'feature.txt').write_text('implemented\n')
        self.git('add', '.', cwd=self.worker)
        self.git('commit', '-m', 'implement', cwd=self.worker)
        self.measure(self.worker)
        merge.stage_task_integration('056', self.worktree_root, None, self.primary)
        candidate.run_candidate_validation('056', self.primary)
        self.landed = merge.finalize_task_integration('056', None, self.primary)['merge_commit']
        self.locations = candidate.locations_for('056', self.primary)

    def finish(self):
        return cleanup.finish_delivery(self.locations)

    def remote(self, ref='main'):
        result = subprocess.run(['git', '--git-dir', str(self.origin), 'rev-parse', '--verify', '-q',
                                 'refs/heads/' + ref], capture_output=True, text=True)
        return result.stdout.strip() or None

    def own_remote(self):
        # Exercise the deletion adapter with the same exact ref/SHA binding the
        # verified CI push supplies. Full CI ownership is tested separately.
        sha = self.git('rev-parse', 'task-056').stdout.strip()
        self.git('push', 'origin', 'task-056')
        with mock.patch.object(cleanup, '_owned_remote', return_value=dict(ref='refs/heads/task-056', sha=sha)):
            intent = cleanup._new_intent(self.locations, delivery=True)
        receipts._save_intent(candidate.operation_path(self.locations, 'cleanup'), intent)
        return sha

    def kill(self, point):
        script = '''
import os, sys
from pathlib import Path
from cardine.lifecycle import receipts
from cardine.integration.cleanup import finish_delivery
from cardine.integration.candidate import locations_for
receipts.boundary = lambda name: os._exit(97) if name == sys.argv[2] else None
finish_delivery(locations_for('056', Path(sys.argv[1])))
'''
        done = subprocess.run([sys.executable, '-c', script, str(self.primary), point],
            cwd=self.primary, capture_output=True, text=True,
            env={**os.environ, 'PYTHONPATH': str(ROOT / 'src'), 'HOME': str(self.root), 'GIT_CONFIG_GLOBAL': os.devnull})
        self.assertEqual(done.returncode, 97, done.stderr)

    def test_push_cleanup_and_identical_repeat(self):
        count = self.git('rev-list', '--count', 'main').stdout
        self.assertEqual(self.finish()['status'], 'cleaned')
        self.assertEqual(self.remote(), self.landed)
        self.assertFalse(self.git('branch', '--list', 'task-056').stdout)
        self.assertEqual(list(self.worker.iterdir()), [])
        with mock.patch.object(receipts, '_durable', side_effect=AssertionError('repeat wrote')):
            self.assertEqual(self.finish()['status'], 'cleaned')
        self.assertEqual(self.git('rev-list', '--count', 'main').stdout, count)
        result = engine.run_integration_step(self.locations)
        self.assertEqual(result['outcome'], 'done')
        engine.validate_output(result)
        done = subprocess.run([sys.executable, '-m', 'cardine.cli', 'run', '056', '--project', str(self.primary)],
                              cwd=self.root, capture_output=True, text=True,
                              env={**os.environ, 'PYTHONPATH': str(ROOT / 'src')})
        self.assertEqual(done.returncode, 0, done.stderr + done.stdout)
        self.assertEqual(json.loads(done.stdout)['outcome'], 'done')

    def test_unrecorded_remote_task_is_preserved(self):
        self.git('push', 'origin', 'task-056')
        tip = self.remote('task-056')
        self.finish()
        self.assertEqual(self.remote('task-056'), tip)

    def test_recorded_remote_is_compare_deleted(self):
        self.own_remote()
        self.finish()
        self.assertIsNone(self.remote('task-056'))

    def test_failed_main_push_never_deletes_task(self):
        self.own_remote()
        hook = self.origin / 'hooks/pre-receive'
        hook.write_text('#!/bin/sh\necho "protected branch" >&2\nexit 1\n')
        hook.chmod(0o755)
        with self.assertRaisesRegex(CardineError, 'main push not observed'):
            self.finish()
        self.assertIsNotNone(self.remote('task-056'))
        self.assertTrue((self.worker / '.git').exists())

    def test_lost_push_response_is_reconciled(self):
        real = cleanup._run_git
        def lost(root, *args, **kwargs):
            result = real(root, *args, **kwargs)
            if args[:2] == ('push', 'origin'):
                return subprocess.CompletedProcess([], 1, '', 'lost response')
            return result
        with mock.patch.object(cleanup, '_run_git', side_effect=lost):
            self.finish()
        self.assertEqual(self.remote(), self.landed)

    def test_uncertain_timeout_retries_without_deleting_work(self):
        real = cleanup._run_git
        def timeout(root, *args, **kwargs):
            if args[:2] == ('push', 'origin'):
                raise subprocess.TimeoutExpired('git', 120)
            return real(root, *args, **kwargs)
        with mock.patch.object(cleanup, '_run_git', side_effect=timeout), self.assertRaises(CardineError):
            self.finish()
        self.assertTrue((self.worker / '.git').exists())
        self.finish()
        self.assertEqual(self.remote(), self.landed)

    def test_remote_advancement_preserves_task(self):
        self.own_remote()
        self.git('push', 'origin', 'main')
        # An unrelated remote main is not proven by the local tracking ref.
        self.git('update-ref', 'refs/heads/main', self.base, cwd=self.origin)
        with mock.patch.object(cleanup, '_push', side_effect=CardineError('refused')):
            with self.assertRaises(CardineError):
                self.finish()
        self.assertIsNotNone(self.remote('task-056'))

    def test_compare_delete_race_preserves_new_tip(self):
        self.own_remote()
        real = cleanup._run_git
        def race(root, *args, **kwargs):
            if args[:1] == ('push',) and args[1].startswith('--force-with-lease='):
                self.git('update-ref', 'refs/heads/task-056', self.landed, cwd=self.origin)
            return real(root, *args, **kwargs)
        with mock.patch.object(cleanup, '_run_git', side_effect=race), self.assertRaises(CardineError):
            self.finish()
        self.assertEqual(self.remote('task-056'), self.landed)
        self.assertTrue((self.worker / '.git').exists())

    def test_changed_remote_or_foreign_owner_intent_is_rejected(self):
        self.own_remote()
        path = candidate.operation_path(self.locations, 'cleanup')
        intent = receipts._load_intent(path)
        for field, value in (('task', '057'), ('project', '/foreign'), ('origin', '/foreign'),
                             ('worker', '/foreign'), ('authority', {})):
            with self.subTest(field=field):
                changed = json.loads(json.dumps(intent))
                changed['binding'][field] = value
                receipts._save_intent(path, changed)
                with self.assertRaises(CardineError):
                    self.finish()
                self.assertTrue((self.worker / '.git').exists())
        receipts._save_intent(path, intent)
        self.git('remote', 'set-url', 'origin', '/foreign')
        with self.assertRaises(CardineError):
            self.finish()

    def test_changed_lifecycle_and_dirty_worker_are_preserved(self):
        self.own_remote()
        (self.worker / 'foreign.txt').write_text('keep')
        with self.assertRaises(CardineError):
            self.finish()
        self.assertEqual((self.worker / 'foreign.txt').read_text(), 'keep')

    def test_reused_path_and_branch_are_preserved_after_completion(self):
        self.finish()
        (self.worker / 'foreign').write_text('keep')
        with self.assertRaises(CardineError):
            self.finish()
        (self.worker / 'foreign').unlink()
        self.git('branch', 'task-056', self.landed)
        with self.assertRaises(CardineError):
            self.finish()
        self.assertTrue(self.git('branch', '--list', 'task-056').stdout)

    def test_changed_push_destination_is_refused_before_publication(self):
        other = self.root / 'foreign.git'
        subprocess.run(['git', 'init', '--bare', str(other)], check=True, capture_output=True)
        self.git('config', 'remote.origin.pushurl', str(other))
        with self.assertRaisesRegex(CardineError, 'destinations differ'):
            self.finish()
        self.assertNotEqual(self.remote(), self.landed)
        self.assertTrue((self.worker / '.git').exists())
        self.assertFalse(subprocess.run(['git', '--git-dir', str(other), 'show-ref'],
                                       capture_output=True).stdout)

    def test_intent_replaced_inside_effect_is_preserved(self):
        self.own_remote()
        path = candidate.operation_path(self.locations, 'cleanup')
        def replace(name):
            if name == 'before_cleanup_push':
                value = receipts._load_intent(path)
                value['binding']['task'] = '057'
                receipts._save_intent(path, value)
        with mock.patch.object(receipts, 'boundary', side_effect=replace), self.assertRaises(CardineError):
            self.finish()
        self.assertEqual(receipts._load_intent(path)['binding']['task'], '057')
        self.assertNotEqual(self.remote(), self.landed)
        self.assertTrue((self.worker / '.git').exists())

    def test_protected_remote_deletion_preserves_local_work(self):
        self.own_remote()
        hook = self.origin / 'hooks/pre-receive'
        hook.write_text('#!/bin/sh\nwhile read old new ref; do\n'
                        'case "$new" in 0000000000000000000000000000000000000000) '
                        'echo "protected branch" >&2; exit 1;; esac\ndone\n')
        hook.chmod(0o755)
        with self.assertRaisesRegex(CardineError, 'compare-delete refused'):
            self.finish()
        self.assertEqual(self.remote(), self.landed)
        self.assertIsNotNone(self.remote('task-056'))
        self.assertTrue((self.worker / '.git').exists())

    def test_absent_recorded_remote_is_idempotent_success(self):
        self.own_remote()
        self.git('update-ref', '-d', 'refs/heads/task-056', cwd=self.origin)
        self.finish()
        self.assertIsNone(self.remote('task-056'))

    def test_lost_delete_response_is_observed_before_retry(self):
        self.own_remote()
        real = cleanup._run_git
        def lost(root, *args, **kwargs):
            result = real(root, *args, **kwargs)
            if args[:1] == ('push',) and args[1].startswith('--force-with-lease='):
                raise subprocess.TimeoutExpired('git', 120)
            return result
        with mock.patch.object(cleanup, '_run_git', side_effect=lost):
            self.finish()
        self.assertIsNone(self.remote('task-056'))

    def test_changed_lifecycle_bytes_are_preserved(self):
        self.own_remote()
        intent = receipts._load_intent(candidate.operation_path(self.locations, 'cleanup'))
        target = Path(intent['binding']['lifecycle'])
        target.write_bytes(b'foreign lifecycle')
        with self.assertRaises(CardineError):
            self.finish()
        self.assertEqual(target.read_bytes(), b'foreign lifecycle')
        self.assertTrue((self.worker / '.git').exists())

    def test_same_tip_branch_recreation_during_partial_cleanup_is_preserved(self):
        self.own_remote()
        self.kill('after_cleanup_worktree')
        sha = self.git('rev-parse', 'task-056').stdout.strip()
        self.git('branch', '-d', 'task-056')
        self.git('branch', 'task-056', sha)
        with self.assertRaises(CardineError):
            self.finish()
        self.assertEqual(self.git('rev-parse', 'task-056').stdout.strip(), sha)

    def test_reused_registered_worktree_during_partial_cleanup_is_preserved(self):
        self.own_remote()
        self.kill('before_cleanup_worktree')
        self.git('worktree', 'remove', str(self.worker))
        self.git('worktree', 'add', str(self.worker), 'task-056')
        with self.assertRaises(CardineError):
            self.finish()
        self.assertTrue((self.worker / '.git').exists())

    def test_preexisting_matching_ci_ref_does_not_grant_deletion(self):
        from test_run_ci import CiTest
        fixture = CiTest()
        fixture.setUp()
        try:
            locations = fixture.ready()
            expected = fixture.head()
            fixture.git('push', 'origin', expected + ':refs/heads/task-056')
            fixture.checks(fixture.head())
            self.assertEqual(fixture.gate(locations)['phase'], 'passed')
            self.assertFalse(fixture.state()['run']['ci']['push']['owned'])
            self.assertIsNone(cleanup._owned_remote(locations, fixture.state()))
            fixture.git('add', '.', cwd=fixture.worker)
            fixture.git('commit', '-m', 'Record CI result', cwd=fixture.worker)
            merge.stage_task_integration('056', fixture.worktree_root, None, fixture.primary)
            candidate.run_candidate_validation('056', fixture.primary)
            merge.finalize_task_integration('056', None, fixture.primary)
            cleanup.finish_delivery(locations)
            self.assertEqual(fixture.remote_tip(), expected)
        finally:
            fixture.tearDown()
            fixture.doCleanups()

    def test_real_ci_receipt_owns_the_deleted_remote_ref(self):
        from test_run_ci import CiTest
        fixture = CiTest()
        fixture.setUp()
        try:
            locations = fixture.ready()
            fixture.checks(fixture.head())
            self.assertEqual(fixture.gate(locations)['phase'], 'passed')
            fixture.git('add', '.', cwd=fixture.worker)
            fixture.git('commit', '-m', 'Record CI result', cwd=fixture.worker)
            merge.stage_task_integration('056', fixture.worktree_root, None, fixture.primary)
            candidate.run_candidate_validation('056', fixture.primary)
            merge.finalize_task_integration('056', None, fixture.primary)
            # A Git URL rewrite can change transport while the GitHub repository
            # spelling stays identical. The CI receipt pins that effective origin.
            from test_run_ci import REPOSITORY
            foreign = fixture.root / 'foreign.git'
            fixture.git('clone', '--bare', str(fixture.origin), str(foreign))
            fixture.git('config', '--unset', f'url.{fixture.origin}.insteadOf')
            fixture.git('config', f'url.{foreign}.insteadOf', REPOSITORY)
            with self.assertRaisesRegex(CardineError, 'changed CI push ownership'):
                cleanup.finish_delivery(locations)
            self.assertIsNotNone(fixture.remote_tip())
            fixture.git('config', '--unset', f'url.{foreign}.insteadOf')
            fixture.git('config', f'url.{fixture.origin}.insteadOf', REPOSITORY)
            fixture.git('config', 'extensions.worktreeConfig', 'true')
            fixture.git('config', '--worktree', 'remote.origin.url', str(foreign))
            with self.assertRaisesRegex(CardineError, 'changed CI push ownership'):
                cleanup.finish_delivery(locations)
            fixture.git('config', '--worktree', '--unset', 'remote.origin.url')
            result = cleanup.finish_delivery(locations)
            self.assertEqual(result['status'], 'cleaned')
            self.assertIsNone(fixture.remote_tip())
            self.assertEqual(fixture.push_count(), 3)  # Task push, main push, compare-delete.
        finally:
            fixture.tearDown()
            fixture.doCleanups()

    def test_every_effect_boundary_replays_identically(self):
        for label in ('cleanup_push', 'cleanup_remote', 'cleanup_worktree', 'cleanup_placeholder',
                      'cleanup_branch', 'cleanup_lifecycle'):
            for side in ('before', 'after'):
                with self.subTest(point=side + '_' + label):
                    fixture = CleanupTest('test_recorded_remote_is_compare_deleted')
                    fixture.setUp()
                    try:
                        fixture.own_remote()
                        fixture.kill(side + '_' + label)
                        path = candidate.operation_path(fixture.locations, 'cleanup')
                        original = receipts._load_intent(path)
                        # Every effect retry independently rejects foreign ownership.
                        foreign = json.loads(json.dumps(original))
                        foreign['binding']['task'] = '057'
                        receipts._save_intent(path, foreign)
                        with self.assertRaises(CardineError):
                            fixture.finish()
                        receipts._save_intent(path, original)
                        # Changed actual inputs cannot be covered by the old receipt.
                        fixture.git('remote', 'set-url', 'origin', '/foreign')
                        with self.assertRaises(CardineError):
                            fixture.finish()
                        fixture.git('remote', 'set-url', 'origin', str(fixture.origin))
                        first = fixture.finish()
                        self.assertEqual(fixture.finish()['merge_commit'], first['merge_commit'])
                        self.assertEqual(fixture.remote(), fixture.landed)
                        self.assertIsNone(fixture.remote('task-056'))
                        self.assertFalse(fixture.git('branch', '--list', 'task-056').stdout)
                    finally:
                        fixture.tearDown()
                        fixture.doCleanups()


if __name__ == '__main__':
    unittest.main()
