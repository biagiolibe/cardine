"""Closed output envelope, executable quoting and diagnostic isolation."""
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from dataclasses import replace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from cardine.lifecycle.engine import command_reference, envelope, render_output, resolve_run, run_preview_cli, validate_output
from cardine.lifecycle.model import Guardrail, RunFacts, WorkRequest
from cardine.stops.render import emit_run, stop_error, outcome_for_code
from cardine.stops.registry import load_stop_registry
import test_run_resolution as fixtures

ROOT = Path(__file__).resolve().parents[1]


class RunOutputTests(unittest.TestCase):
    def test_shared_renderer_dispatches_all_outcomes_without_false_stops(self):
        base = RunFacts('001', Path('/tmp/project'), 'in_progress')
        examples = [resolve_run(base),
                    resolve_run(replace(base, validation_failed=True, contract_ready=True, worktree_ready=True)),
                    resolve_run(replace(base, contract_ready=True, worktree_ready=True,
                                        implementation_delivered=True, validation_passed=True, review_pending=True)),
                    resolve_run(replace(base, status='done', landing_complete=True)),
                    resolve_run(replace(base, guardrail=Guardrail('RULE_CONFLICT', 'Decision required')))]
        examples.append({**examples[0], 'outcome': 'progress', 'action': 'record-contract'})
        for result in examples:
            with self.subTest(outcome=result['outcome']):
                stdout, stderr = StringIO(), StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = emit_run(result, validate_output)
                self.assertEqual(json.loads(stdout.getvalue()), result)
                self.assertEqual(code, 2 if result['stop'] else 0)
                self.assertEqual('BLOCKED' in stderr.getvalue(), result['stop'] is not None)
                if result['stop']:
                    self.assertIn('; resume: ' + result['next']['command'], stderr.getvalue())

    def test_every_registered_diagnostic_uses_its_resolution(self):
        for code, entry in load_stop_registry().items():
            expected = {'guardrail': 'blocked', 'recoverable': 'next', 'failing-work': 'iterate'}[entry['resolution']]
            self.assertEqual(outcome_for_code(code), expected)
            text = str(stop_error(code, 'measured cause', resume='cardine status --project /tmp/project'))
            self.assertEqual(text.startswith('BLOCKED '), entry['human_decision'])

    def test_output_interruption_and_repeat_leave_resolution_unchanged(self):
        facts = RunFacts('001', Path('/tmp/project'), 'in_progress', pending_step='candidate')
        first = resolve_run(facts)
        for boundary in ('stdout', 'stderr'):
            result = first if boundary == 'stdout' else resolve_run(replace(
                facts, pending_step=None, guardrail=Guardrail('RULE_CONFLICT', 'Decision required')))
            before = render_output(result)
            with patch('sys.' + boundary + '.write', side_effect=BrokenPipeError):
                with self.assertRaises(BrokenPipeError):
                    emit_run(result, validate_output)
            self.assertEqual(render_output(result), before)
        self.assertEqual(resolve_run(facts), first)

    def test_closed_schema_and_envelope_fields(self):
        schema = json.loads((ROOT / 'schemas/run-v1.schema.json').read_text())
        result = resolve_run(RunFacts('001', Path('/tmp/project'), 'queued'))
        self.assertEqual(set(result), set(schema['required']))
        self.assertFalse(schema['additionalProperties'])
        self.assertEqual(result['action'], 'none')
        self.assertEqual(result['evidence'], [])
        self.assertEqual(result['stop'], None)
        self.assertEqual(json.loads(render_output(result)), result)
        for name in ('next', 'stop', 'work'):
            nested = next(item for item in schema['properties'][name]['anyOf'] if item['type'] == 'object')
            self.assertFalse(nested['additionalProperties'])

    def test_cross_field_rejections(self):
        for kw in ({'outcome': 'blocked'}, {'outcome': 'unknown'}, {'retry_after_seconds': -1},
                   {'retry_after_seconds': True}, {'retry_after_seconds': 1}):
            with self.assertRaises(ValueError):
                envelope('001', '/tmp/project', step='contract', **kw)
        with self.assertRaises(ValueError):
            envelope('001', '/tmp/project', step='landing', outcome='done',
                     next_command=command_reference(['cardine'], 'invalid'))
        with self.assertRaises(ValueError):
            resolve_run(RunFacts('001', Path('/tmp/project'), 'queued',
                                guardrail=Guardrail('VALIDATION_FAILED', 'not a guardrail')))

        invalid = resolve_run(RunFacts('001', Path('/tmp/project'), 'queued',
                                       guardrail=Guardrail('RULE_CONFLICT', 'Decision required')))
        invalid['stop']['code'] = 'VALIDATION_FAILED'
        with self.assertRaises(ValueError):
            render_output(invalid)

    def test_guardrail_resume_equals_next_and_shell_argv(self):
        result = resolve_run(RunFacts('001', Path('/tmp/a ; $(touch BAD)'), 'queued',
                                     guardrail=Guardrail('SCOPE_CHANGE_REQUIRED', 'Outside surface')))
        self.assertEqual(result['stop']['resume'], result['next']['command'])
        self.assertEqual(result['stop']['resume_argv'], result['next']['argv'])
        self.assertEqual(shlex.split(result['next']['command']), result['next']['argv'])

    def test_scope_guidance_quotes_worktree_and_excludes_unsafe_causes(self):
        from cardine.lifecycle.engine import diagnostic_result
        from cardine.lifecycle.model import RunLocations
        from cardine.lifecycle.scope import enforce_scope
        from cardine.shared.errors import CardineStop
        primary = Path('/tmp/primary project')
        worker = Path('/tmp/worktree ; $(touch BAD)')
        locations = RunLocations('001', primary, primary / '.git', worker, worker)
        state = {'task_id': '001', 'contract': {'recordPath': 'tasks/001.md',
                                                  'expectedCodeSurface': ['src/**']}}
        for paths, surface, proposed in [({'outside.txt'}, ['src/**'], True),
                                         ({'../unsafe'}, ['src/**'], False),
                                         (set(), [], False), (set(), ['../bad'], False)]:
            state['contract']['expectedCodeSurface'] = surface
            with patch('cardine.lifecycle.scope.changed_paths', return_value=paths):
                with self.assertRaises(CardineStop) as caught:
                    enforce_scope(worker, state, 'base')
            result = diagnostic_result(locations, caught.exception)
            detail = result['stop']['detail']
            self.assertEqual('Approval is requested' in detail, proposed)
            if proposed:
                update = detail.split('then run: ', 1)[1].split('. If declined', 1)[0]
                self.assertEqual(shlex.split(update), ['cardine', 'task', 'contract', 'update', '001',
                                                       '--project', str(worker)])
                stderr = StringIO()
                with redirect_stdout(StringIO()), redirect_stderr(stderr):
                    self.assertEqual(emit_run(result, validate_output), 2)
                self.assertIn(update, stderr.getvalue())

    def test_invalid_invocation_is_single_json_object(self):
        for argv in ([], ['001', '--unknown'], ['001', '--project', '/missing/project']):
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(run_preview_cli(argv), 64)
            result = json.loads(output.getvalue())
            self.assertIsNone(result['step'])
            self.assertIsNone(result['next'])
            self.assertIsNone(result['stop'])

    def test_wait_budget_arguments_and_continuations(self):
        from cardine.lifecycle import engine
        from types import SimpleNamespace
        location = SimpleNamespace(task_id='001', primary=Path('/project'))
        base = envelope('001', '/project', step='candidate', outcome='waiting', action='poll-ci',
                        retry_after_seconds=10, next_command=command_reference(
                            ['cardine', 'run', '001', '--project', '/project'], 'retry'))
        for extra, expected in (([], (900, 0)), (['--ci-wait-seconds', '0', '--lease-wait-seconds', '0'], (0, 0)),
                                (['--ci-wait-seconds', '1200', '--lease-wait-seconds', '3'], (1200, 0))):
            with self.subTest(extra=extra), patch.object(engine, 'resolve_run_locations', return_value=location), \
                    patch.object(engine, 'dispatch_run', return_value=__import__('copy').deepcopy(base)) as dispatch, \
                    redirect_stdout(StringIO()) as output:
                self.assertEqual(run_preview_cli(['001', *extra]), 0)
            self.assertEqual((dispatch.call_args.kwargs['ci_wait_seconds'], dispatch.call_args.kwargs['lease_seconds']), expected)
            result = json.loads(output.getvalue())
            self.assertIn('--ci-wait-seconds', result['next']['argv'])
            if '--lease-wait-seconds' in extra:
                self.assertEqual(result['next']['argv'][-2:], extra[-2:])
        for flag in ('--ci-wait-seconds', '--lease-wait-seconds'):
            for value in ('-1', 'abc', '1.5'):
                with redirect_stdout(StringIO()):
                    self.assertEqual(run_preview_cli(['001', flag, value]), 64)

    def test_lease_release_resumes_same_invocation(self):
        from cardine.lifecycle import engine
        from types import SimpleNamespace
        location = SimpleNamespace(task_id='001', primary=Path('/project'))
        waiting = envelope('001', '/project', step='candidate', outcome='waiting', action='wait-for-lease',
                           retry_after_seconds=5, next_command=command_reference(
                               ['cardine', 'run', '001', '--project', '/project'], 'retry'))
        done = envelope('001', '/project', step='landing', outcome='done')
        with patch.object(engine, 'resolve_run_locations', return_value=location), \
                patch.object(engine, 'dispatch_run', side_effect=[waiting, done]) as dispatch, \
                patch('cardine.integration.candidate.wait_for_lease', return_value=True), \
                redirect_stdout(StringIO()) as output:
            self.assertEqual(run_preview_cli(['001', '--lease-wait-seconds', '2']), 0)
        self.assertEqual(dispatch.call_count, 2)
        self.assertEqual(json.loads(output.getvalue())['outcome'], 'done')

    def test_default_lease_budget_is_180_seconds(self):
        from cardine.lifecycle import engine
        from types import SimpleNamespace
        location = SimpleNamespace(task_id='001', primary=Path('/project'))
        waiting = envelope('001', '/project', step='candidate', outcome='waiting', action='wait-for-lease',
                           retry_after_seconds=5, next_command=command_reference(
                               ['cardine', 'run', '001', '--project', '/project'], 'retry'))
        with patch.object(engine, 'resolve_run_locations', return_value=location), \
                patch.object(engine, 'dispatch_run', return_value=waiting), \
                patch.object(engine.time, 'monotonic', return_value=0), \
                patch('cardine.integration.candidate.wait_for_lease', return_value=False) as wait, \
                redirect_stdout(StringIO()):
            self.assertEqual(run_preview_cli(['001']), 0)
        self.assertEqual(wait.call_args.kwargs['seconds'], 180)

    def test_lease_timeout_preserves_both_explicit_budgets(self):
        from cardine.lifecycle import engine
        from types import SimpleNamespace
        location = SimpleNamespace(task_id='001', primary=Path('/project'))
        for step in ('candidate', 'landing'):
            waiting = envelope('001', '/project', step=step, outcome='waiting', action='wait-for-lease',
                               retry_after_seconds=5, next_command=command_reference(
                                   ['cardine', 'run', '001', '--project', '/project'], 'retry'))
            with self.subTest(step=step), patch.object(engine, 'resolve_run_locations', return_value=location), \
                    patch.object(engine, 'dispatch_run', return_value=waiting), \
                    patch('cardine.integration.candidate.wait_for_lease', return_value=False), \
                    redirect_stdout(StringIO()) as output:
                self.assertEqual(run_preview_cli(['001', '--ci-wait-seconds', '12', '--lease-wait-seconds', '2']), 0)
            result = json.loads(output.getvalue())
            self.assertEqual(result['outcome'], 'waiting')
            self.assertEqual(result['next']['argv'][-4:], ['--ci-wait-seconds', '12', '--lease-wait-seconds', '2'])
            self.assertGreater(result['retry_after_seconds'], 0)
            self.assertIn('2 seconds', result['diagnostics'][0]['message'])

    def test_structured_work_is_closed_and_role_bound(self):
        request = WorkRequest('implementer', Path('/tmp/worktree'), 'sha256:contract',
                              ('src/*',), ('contract:acceptance',), ('task-check',), ('committed-source',))
        facts = RunFacts('001', Path('/tmp/project'), 'in_progress', contract_ready=True,
                         worktree_ready=True, implementation_work=request)
        self.assertEqual(resolve_run(facts)['work'], request.as_json())
        invalid = resolve_run(facts)
        invalid['work']['untrusted_extra'] = True
        with self.assertRaises(ValueError):
            render_output(invalid)
        with self.assertRaises(ValueError):
            RunFacts('001', Path('/tmp/project'), 'in_progress', review_work=request)


class RunPreviewConsumerTests(fixtures.RunLocationTests):
    # Location tests stay in their own module, avoiding inherited duplicate tests.
    test_primary_linked_nested_and_unrelated_cwd = None
    test_registry_unique_dedup_missing_and_ambiguous = None
    test_reads_do_not_change_consumer_bytes_or_create_worktree = None

    def test_resolved_unknown_failure_is_registered_guardrail(self):
        for error in (ValueError('bad bytes'), RuntimeError('unknown adapter failure'), PermissionError('denied')):
            stdout, stderr = StringIO(), StringIO()
            with patch('cardine.tasks.state.read_task_state', side_effect=error), \
                    redirect_stdout(stdout), redirect_stderr(stderr):
                code = run_preview_cli(['001', '--project', str(self.root)])
            result = json.loads(stdout.getvalue())
            self.assertEqual(code, 2)
            self.assertEqual(result['outcome'], 'blocked')
            self.assertEqual(result['stop']['code'], 'COMMAND_REFUSED')
            self.assertEqual(result['next']['argv'][-1], str(self.root))
            self.assertTrue(stderr.getvalue().startswith('BLOCKED COMMAND_REFUSED:'))

    def test_resolved_recoverable_keeps_exact_quoted_command(self):
        from cardine.lifecycle.engine import diagnostic_result
        from cardine.lifecycle.model import RunLocations
        resume = command_reference(['cardine', 'run', '001', '--project', str(self.root)], 'retry')
        locations = RunLocations('001', self.root, self.root / '.git', self.base, self.root)
        result = diagnostic_result(locations, stop_error('WORKTREE_RELOCATE', 'Owned checkout', resume=resume['command']))
        self.assertEqual(result['outcome'], 'next')
        self.assertEqual(result['next']['command'], resume['command'])
        self.assertIsNone(result['stop'])
        from cardine.shared.errors import CardineStop
        unknown = diagnostic_result(locations, CardineStop('UNRECOGNIZED', 'unknown cause'))
        self.assertEqual(unknown['stop']['code'], 'COMMAND_REFUSED')
        self.assertEqual(unknown['outcome'], 'blocked')
        # The emitted text runs unchanged, including shell metacharacters.
        from stop_recovery_support import run_recovery
        recovered = run_recovery(result['next']['command'], self.base, self.base / 'worktrees')
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        self.assertEqual(json.loads(recovered.stdout)['task_id'], '001')

    def test_emitted_command_executes_unchanged_and_preview_never_logs(self):
        bindir = self.base / 'bin'
        bindir.mkdir()
        executable = bindir / 'cardine'
        executable.write_text('#!' + sys.executable + '\nfrom cardine.cli import main\nraise SystemExit(main())\n')
        executable.chmod(0o755)
        environment = {**os.environ, 'PATH': str(bindir) + os.pathsep + os.environ['PATH'],
                       'PYTHONPATH': str(ROOT / 'src'), 'CARDINE_WORKTREE_ROOT': str(self.base / 'worktrees')}
        def snapshot():
            # `run` now creates the task worktree and branch, which live under .git.
            return {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*')
                    if p.is_file() and '.git' not in p.relative_to(self.root).parts}
        before = snapshot()
        first = subprocess.run(['cardine', 'run', '001', '--project', str(self.root)],
                               cwd=self.base, env=environment, text=True, capture_output=True, check=True)
        result = json.loads(first.stdout)
        live_log = self.root / '.git' / 'cardine-operations' / '001.live.log'
        self.assertIn('run 001 started', live_log.read_text())
        self.assertIn('run finished: step worktree, outcome next', live_log.read_text())
        self.assertNotIn('cardine:', first.stdout + first.stderr)
        self.assertEqual((result['step'], result['action']), ('worktree', 'execution-start'))
        # The emitted text runs unchanged, including shell metacharacters. The
        # started task then stops on this fixture's missing frozen code surface.
        second = subprocess.run(result['next']['command'], shell=True, cwd=self.base,
                                env=environment, text=True, capture_output=True)
        self.assertEqual(json.loads(second.stdout)['task_id'], '001')
        self.assertNotEqual(json.loads(second.stdout)['action'], 'execution-start')
        review = resolve_run(RunFacts('001', self.root, 'in_progress', contract_ready=True,
                                     worktree_ready=True, implementation_delivered=True,
                                     validation_passed=True))
        reviewed = subprocess.run(review['next']['command'], shell=True, cwd=self.base,
                                  env=environment, text=True, capture_output=True)
        # The owner command cannot record a verdict without a terminal.
        self.assertEqual(reviewed.returncode, 2)
        self.assertIn('review requires the task branch', reviewed.stderr)
        global_option = subprocess.run(['cardine', '--framework-root', str(ROOT), 'run', '001',
                                       '--project', str(self.root)], cwd=self.base, env=environment,
                                      text=True, capture_output=True)
        self.assertEqual(global_option.stdout, second.stdout)
        self.assertFalse((self.base / 'SENTINEL').exists())
        self.assertEqual(before, snapshot())


if __name__ == '__main__':
    unittest.main()
