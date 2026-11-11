"""Disposable field cases of work item 10, step 5 (C3e).

A spike, a task that cites its authority and declares a code surface, and a stop
followed by a resume across an interrupted effect, each driven through `run` in a
private project with a private home directory and a local bare remote. The test
plays the implementer; it never touches the real home directory or real hosts.
"""
import contextlib
import io
import json
import shlex
import subprocess
import sys
from pathlib import Path
import unittest

from cardine.lifecycle.engine import run_preview_cli
from cardine.shared.authority import adr_show, authority_entries, resolve_authority_entry
from cardine.shared.errors import CardineError
from cardine.tasks.state_core import dependency_satisfied
from cardine.tasks.transitions import record_spike_outcome
from run_delivery_support import KILLED, TASK, DisposableDelivery

ADR_LOG = ('# Architecture decisions\n\n## ADR-0001 Stops are explicit\n\nA stop names its code.\n\n'
           '## ADR-0002 Unrelated\n\nNot cited.\n')
STANDALONE = '# ADR: Surface\n\n## Decision\n\nA task declares the paths it may change.\n'
AUTHORITY = '- ADR-0001, decision 1.\n- `docs/ADR_SURFACE.md`#Decision'
SPIKE = dict(spike=True, surface='- `docs/**`', files={'docs/result.md': '# Answer\nYes.\n'})


def seed_authority(root):
    (root / 'docs').mkdir(exist_ok=True)
    (root / 'docs/ARCHITECTURE_DECISIONS.md').write_text(ADR_LOG)
    (root / 'docs/ADR_SURFACE.md').write_text(STANDALONE)


def printed(argv):
    """Run `run` as the command line does and return (exit status, parsed stdout)."""
    output = io.StringIO()
    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
        status = run_preview_cli(argv)
    return status, json.loads(output.getvalue())


class SpikeFieldCaseTest(unittest.TestCase):
    def start(self, project):
        project.run()
        return project.run()

    def finish(self, project, outcome):
        worker = project.commit_implementation()
        record_spike_outcome(worker, TASK, outcome)
        project.git('add', '.', cwd=worker)
        project.git('commit', '-m', 'Record outcome', cwd=worker)
        project.deliver()
        self.assertEqual(project.drive()[-1], ('landing', 'cleanup', 'done'))
        return json.loads(project.git('show', 'main:.cardine/tasks/' + TASK + '.json'))

    def test_answered_spike_lands_and_satisfies_dependents(self):
        with DisposableDelivery(**SPIKE) as project:
            self.start(project)
            state = self.finish(project, 'ANSWERED')
            self.assertEqual((state['status'], state['outcome']), ('done', 'ANSWERED'))
            self.assertTrue(dependency_satisfied(state))
            self.assertEqual(project.git('show', 'main:docs/result.md'), '# Answer\nYes.')
            self.assertEqual(project.remote_main(), project.git('rev-parse', 'main'))

    def test_inconclusive_spike_lands_but_never_satisfies_dependents(self):
        with DisposableDelivery(**SPIKE) as project:
            self.start(project)
            state = self.finish(project, 'INCONCLUSIVE')
            self.assertEqual((state['status'], state['outcome']), ('done', 'INCONCLUSIVE'))
            self.assertFalse(dependency_satisfied(state))

    def test_answered_requires_the_committed_deliverable(self):
        with DisposableDelivery(**SPIKE) as project:
            self.start(project)
            with self.assertRaisesRegex(CardineError, 'ANSWERED requires changed frozen deliverables: docs/result.md'):
                record_spike_outcome(project.locations.worktree, TASK, 'ANSWERED')

    def test_spike_without_an_outcome_does_not_land(self):
        with DisposableDelivery(**SPIKE) as project:
            self.start(project)
            project.implement()
            self.assertEqual(project.run()['step'], 'candidate')
            stopped = project.run()
            self.assertEqual((stopped['outcome'], stopped['stop']['code']), ('blocked', 'TASK_STATE_INVALID'))
            self.assertEqual(stopped['diagnostics'][0]['message'], 'spike landing requires an outcome')
            self.assertNotEqual(project.git('branch', '--list', 'task-' + TASK), '')

    def test_work_request_does_not_name_the_outcome_command(self):
        # Finding for C3f: an agent following only the printed work cannot learn `task outcome`.
        with DisposableDelivery(**SPIKE) as project:
            request = self.start(project)
            self.assertEqual(request['step'], 'implementation')
            self.assertNotIn('outcome', json.dumps(request).lower().replace('outcome":', ''))


class AuthorityFieldCaseTest(unittest.TestCase):
    def project(self):
        return DisposableDelivery(authority=AUTHORITY, setup=seed_authority)

    def test_authority_resolves_through_the_log_and_the_standalone_file(self):
        with self.project() as project:
            record = (project.root / 'tasks/001.md').read_text()
            entries = authority_entries(record)
            self.assertEqual(entries, ['ADR-0001, decision 1.', '`docs/ADR_SURFACE.md`#Decision'])
            shown = adr_show(project.root, 'ADR-0001')
            self.assertIn('A stop names its code.', shown)
            self.assertNotIn('Not cited.', shown)
            with self.assertRaisesRegex(CardineError, 'unknown ADR ADR-0009'):
                adr_show(project.root, 'ADR-0009')
            # Finding: the log source is absolute while a cited path stays relative.
            resolved, unresolved = zip(*(resolve_authority_entry(project.root, item) for item in entries))
            self.assertEqual([[Path(row[0]).name for row in rows] for rows in resolved],
                             [['ARCHITECTURE_DECISIONS.md'], ['ADR_SURFACE.md']])
            self.assertEqual(unresolved, ([], []))
            state = json.loads((project.root / '.cardine/tasks/001.json').read_text())
            self.assertEqual(state['contract']['authority'], entries)

    def test_change_outside_the_declared_surface_is_refused_then_lands_once_removed(self):
        with self.project() as project:
            project.run()
            project.run()
            worker = project.commit_implementation()
            (worker / 'stray.txt').write_text('outside\n')
            status, stopped = printed(['001', '--project', str(project.root)])
            self.assertEqual((status, stopped['step'], stopped['outcome']), (2, 'validation', 'blocked'))
            self.assertEqual(stopped['stop']['code'], 'SCOPE_CHANGE_REQUIRED')
            self.assertIn('path outside expected surface: stray.txt', stopped['stop']['detail'])
            with self.assertRaisesRegex(CardineError, 'SCOPE_CHANGE_REQUIRED'):
                project.deliver()
            (worker / 'stray.txt').unlink()
            project.deliver()
            self.assertEqual(project.drive()[-1], ('landing', 'cleanup', 'done'))
            self.assertEqual(project.git('show', 'main:src/result.py'), 'result = 1')
            self.assertEqual(project.git('ls-tree', '-r', '--name-only', 'main').count('stray.txt'), 0)

    def test_several_paths_outside_the_surface_stop_once_with_every_path(self):
        with self.project() as project:
            project.run()
            project.run()
            worker = project.commit_implementation()
            for name in ('stray_b.txt', 'stray_a.txt'):
                (worker / name).write_text('outside\n')
            status, stopped = printed(['001', '--project', str(project.root)])
            self.assertEqual((status, stopped['stop']['code']), (2, 'SCOPE_CHANGE_REQUIRED'))
            detail = stopped['stop']['detail']
            self.assertIn('paths outside expected surface: stray_a.txt, stray_b.txt', detail)
            self.assertTrue(stopped['stop']['human_decision'])
            self.assertEqual(stopped['stop']['resume'], stopped['next']['command'])
            update = detail.split('then run: ', 1)[1].split('. If declined', 1)[0]
            self.assertEqual(shlex.split(update), ['cardine', 'task', 'contract', 'update', '001',
                                                    '--project', str(worker)])
            state_path = worker / '.cardine/tasks/001.json'
            before = state_path.read_bytes()
            self.assertEqual(printed(['001', '--project', str(project.root)])[1]['stop']['code'],
                             'SCOPE_CHANGE_REQUIRED')
            self.assertEqual(state_path.read_bytes(), before)
            record = worker / 'tasks/001.md'
            record.write_text(record.read_text().replace('- `src/**`',
                              '- `src/**`\n- `stray_a.txt`\n- `stray_b.txt`'))
            argv = shlex.split(update)
            result = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] /
                                    'scripts/cardine_cli.py'), *argv[1:]], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            state = json.loads(state_path.read_text())
            self.assertEqual(state['contract']['expectedCodeSurface'],
                             ['src/**', 'stray_a.txt', 'stray_b.txt'])
            self.assertTrue(state['contract_history'])
            project.git('add', '.', cwd=worker)
            project.git('commit', '-m', 'Expand approved surface', cwd=worker)
            project.deliver()
            self.assertEqual(project.drive()[-1], ('landing', 'cleanup', 'done'))
            self.assertEqual(project.git('show', 'main:stray_a.txt'), 'outside')


class StopThenResumeFieldCaseTest(unittest.TestCase):
    def test_printed_resume_converges_after_a_kill_inside_validation(self):
        with DisposableDelivery() as project:
            project.run()
            project.run()
            worker = project.commit_implementation()
            (worker / 'stray.txt').write_text('outside\n')
            status, stopped = printed(['001', '--project', str(project.root)])
            self.assertEqual((status, stopped['stop']['code']), (2, 'SCOPE_CHANGE_REQUIRED'))
            argv = stopped['stop']['resume_argv']
            self.assertEqual(argv[:2], ['cardine', 'run'])
            (worker / 'stray.txt').unlink()
            project.deliver()
            done = project.kill('run', 'after_validation_process')
            self.assertEqual(done.returncode, KILLED, done.stderr)
            for _ in range(12):
                status, result = printed(argv[2:])
                self.assertIn(status, (0,), result)
                if result['outcome'] == 'done':
                    break
            self.assertEqual(result['outcome'], 'done')
            self.assertEqual(project.git('branch', '--list', 'task-' + TASK), '')
            self.assertEqual(project.remote_main(), project.git('rev-parse', 'main'))
            self.assertEqual(project.git('show', 'main:src/result.py'), 'result = 1')


if __name__ == '__main__':
    unittest.main()
