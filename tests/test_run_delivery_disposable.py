"""Disposable end-to-end delivery of a no-review task to landing (C3c).

The test plays the implementer and `run` performs every other step against a
private project, a private home directory, and a local bare remote.
"""
import io
import contextlib
import shlex
import unittest

from cardine.lifecycle.engine import run_preview_cli
from run_delivery_support import KILLED, TASK, DisposableDelivery

LANDING = [('candidate', 'C6', 'next'),
           ('candidate', 'validate-candidate', 'next'), ('landing', 'finalize', 'next'),
           ('landing', 'cleanup', 'done')]


class DisposableDeliveryTest(unittest.TestCase):
    def assert_landed(self, project):
        branches = project.git('branch', '--list', 'task-' + TASK)
        self.assertEqual(branches, '')
        # Cleanup unregisters the worktree and keeps only an empty placeholder directory.
        self.assertEqual(project.git('worktree', 'list', '--porcelain').count('worktree '), 1)
        self.assertEqual(list(project.locations.worktree.iterdir()), [])
        self.assertEqual(project.remote_main(), project.git('rev-parse', 'main'))
        self.assertEqual(project.git('status', '--porcelain'), '')
        self.assertEqual(project.git('show', 'main:src/result.py'), 'result = 1')
        self.assertEqual(project.drive()[-1][2], 'done')  # A rerun after landing converges.
        self.assertEqual(project.remote_main(), project.git('rev-parse', 'main'))

    def test_queued_task_lands_and_is_cleaned(self):
        with DisposableDelivery() as project:
            first = project.run()
            self.assertEqual((first['step'], first['action'], first['outcome']), ('worktree', 'execution-start', 'next'))
            self.assertTrue(project.locations.worktree.is_dir())
            self.assertEqual(project.run()['step'], 'implementation')
            project.implement()
            self.assertEqual(project.drive(), LANDING)
            self.assert_landed(project)
            self.assertEqual(project.git('log', '-1', '--format=%s'), 'Integrate ' + TASK)

    def test_evidence_incomplete_is_recovered_through_run(self):
        with DisposableDelivery() as project:
            project.run()
            project.implement()
            report = project.closure()
            self.assertEqual((report['step'], report['stop_reason']), ('C5', 'EVIDENCE_INCOMPLETE'))
            argv = shlex.split(report['resume'])
            self.assertEqual(argv[:3], ['cardine', 'run', TASK])
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(run_preview_cli(argv[2:]), 0)
            after = project.closure()
            self.assertEqual((after['step'], after['stop_reason']), ('C6', None))
            self.assertEqual(project.drive()[-1][2], 'done')
            self.assert_landed(project)

    def converge_after_kill(self, mode, point):
        with DisposableDelivery() as project:
            project.run()
            if mode == 'deliver':
                project.commit_implementation()
            else:
                project.implement()
            done = project.kill(mode, point)
            self.assertEqual(done.returncode, KILLED, done.stderr)
            if mode == 'deliver':
                project.deliver()
            project.drive()
            self.assert_landed(project)

    def test_rerun_after_a_kill_before_the_delivery_commit_converges(self):
        self.converge_after_kill('deliver', 'before_delivery_commit')

    def test_rerun_after_a_kill_before_the_delivery_state_write_converges(self):
        self.converge_after_kill('deliver', 'before_delivery_state')

    def test_rerun_after_a_kill_before_the_merge_commit_converges(self):
        self.converge_after_kill('run', 'before_finalize_commit')

    def test_rerun_after_a_kill_before_the_push_converges(self):
        self.converge_after_kill('run', 'before_cleanup_push')

    def test_rerun_after_a_kill_after_the_worktree_removal_converges(self):
        self.converge_after_kill('run', 'after_cleanup_worktree')


if __name__ == '__main__':
    unittest.main()


INIT_RECORD = """# Task 001 — Document the defaults

> **ID**: `001`
> **Category**: Quick

## Objective

Document the defaults.

## Acceptance Criteria

- README.md lists the defaults.

## Expected code surface

- `README.md`

## Dependencies

None.

## Validation

- `whitespace`: `git diff --check HEAD~1`
"""


class InitializedProjectDeliveryTest(unittest.TestCase):
    """A project from `init` or `adopt`, a task from `task new`, and an agent that only calls `run`."""

    def test_quick_task_lands_through_run_alone(self):
        self.deliver_quick_task('init')

    def test_existing_project_adopts_and_lands_through_run_alone(self):
        self.deliver_quick_task('adopt')

    def deliver_quick_task(self, bootstrap):
        import json, os, subprocess, sys, tempfile
        from pathlib import Path
        cardine = Path(__file__).resolve().parents[1] / 'bin' / 'cardine'
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            project, origin = base / 'project', base / 'origin.git'
            for name in ('home', 'tmp', 'project'):
                (base / name).mkdir()
            env = {**os.environ, 'HOME': str(base / 'home'), 'TMPDIR': str(base / 'tmp'),
                   'CARDINE_WORKTREE_ROOT': str(base / 'worktrees'),
                   'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1',
                   'GIT_AUTHOR_NAME': 'Init Test', 'GIT_AUTHOR_EMAIL': 'init@example.invalid',
                   'GIT_COMMITTER_NAME': 'Init Test', 'GIT_COMMITTER_EMAIL': 'init@example.invalid'}

            def call(*argv, cwd=project):
                return subprocess.run(list(argv), cwd=cwd, env=env, text=True, capture_output=True, check=True).stdout

            def commit(message, *paths, cwd=project):
                call('git', 'add', *(paths or ('-A',)), cwd=cwd)
                call('git', 'commit', '-q', '-m', message, cwd=cwd)

            call('git', 'init', '-q', '--bare', '-b', 'main', str(origin), cwd=base)
            call('git', 'init', '-q', '-b', 'main')
            call('git', 'remote', 'add', 'origin', str(origin))
            validation = base / 'validation.json'
            check = 'git diff --check HEAD~1' if bootstrap == 'init' else 'git diff --check'
            validation.write_text(json.dumps({'commands': {'whitespace': check},
                'baseline': ['whitespace'], 'candidate': {'REUSE': [], 'BOUNDED': ['whitespace'],
                                                          'FULL': ['whitespace']}}))
            choices = ('--name', 'Example', '--slug', 'example', '--preset', 'lean', '--language', 'English',
                       '--task-identity', 'opaque', '--validation', str(validation))
            existing = {'README.md': '# Example\n\nOur service.\n', '.gitignore': 'build/\n',
                        'AGENTS.md': '# Agent notes\n\nUse the make targets.\n',
                        'PROJECT_PLAN.md': '# Roadmap\n\n- Ship v2.\n'}
            if bootstrap == 'init':
                call(sys.executable, str(cardine), 'init', '--project', '.', '--apply', *choices)
                self.assertFalse((project / 'PROJECT_PLAN.md').exists())
                self.assertFalse((project / 'TECH_DESIGN.md').exists())
            else:
                for name, text in existing.items():
                    (project / name).write_text(text)
                commit('Existing project')
                adopted = json.loads(call(sys.executable, str(cardine), 'adopt', '--project', '.', '--apply', *choices))
                self.assertEqual(adopted['outcome'], 'done', adopted)
                for name in ('README.md', '.gitignore'):
                    self.assertEqual((project / name).read_text(), existing[name])
                self.assertTrue((project / 'AGENTS.md').read_text().endswith(existing['AGENTS.md']))
                self.assertEqual((project / 'PROJECT_PLAN.md').read_text(), existing['PROJECT_PLAN.md'])
            commit('Initialize Cardine')
            record = base / 'proposal.md'
            record.write_text(INIT_RECORD.replace('git diff --check HEAD~1', check))
            call(sys.executable, str(cardine), 'task', 'new', '001', '--quick', '--record', str(record),
                 '--project', '.')
            commit('Add task 001')
            call('git', 'push', '-q', 'origin', 'main')
            outcomes = []
            for _ in range(10):
                result = json.loads(call(sys.executable, str(cardine), 'run', '001', '--project', str(project)))
                outcomes.append((result['step'], result['outcome']))
                self.assertNotEqual(result['outcome'], 'blocked', result)
                if result['outcome'] == 'done':
                    break
                self.assertEqual(result['next']['argv'][:2], ['cardine', 'run'], result)
                work = result['work']
                if work and work['role'] == 'implementer':
                    worktree = Path(work['worktree'])
                    readme = worktree / 'README.md'
                    if 'Defaults' not in readme.read_text():
                        readme.write_text(readme.read_text() + '\n## Defaults\n\n- `timeout`: 30 seconds.\n')
                        commit('Document the defaults', 'README.md', cwd=worktree)
            self.assertEqual(outcomes[-1], ('landing', 'done'), outcomes)
            self.assertIn('## Defaults', call('git', '--git-dir', str(origin), 'show', 'main:README.md'))
