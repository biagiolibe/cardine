"""Closed output envelope, executable quoting and diagnostic isolation."""
from contextlib import redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from cardine.lifecycle.engine import command_reference, envelope, render_output, resolve_run, run_preview_cli
from cardine.lifecycle.model import Guardrail, RunFacts, WorkRequest
import test_run_resolution as fixtures

ROOT = Path(__file__).resolve().parents[1]


class RunOutputTests(unittest.TestCase):
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

    def test_guardrail_resume_equals_next_and_shell_argv(self):
        result = resolve_run(RunFacts('001', Path('/tmp/a ; $(touch BAD)'), 'queued',
                                     guardrail=Guardrail('SCOPE_CHANGE_REQUIRED', 'Outside surface')))
        self.assertEqual(result['stop']['resume'], result['next']['command'])
        self.assertEqual(result['stop']['resume_argv'], result['next']['argv'])
        self.assertEqual(shlex.split(result['next']['command']), result['next']['argv'])

    def test_invalid_invocation_is_single_json_object(self):
        for argv in ([], ['001', '--unknown'], ['001', '--project', '/missing/project']):
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(run_preview_cli(argv), 64)
            result = json.loads(output.getvalue())
            self.assertIsNone(result['step'])
            self.assertIsNone(result['next'])
            self.assertIsNone(result['stop'])

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

    def test_emitted_command_executes_unchanged_and_preview_never_logs(self):
        bindir = self.base / 'bin'
        bindir.mkdir()
        executable = bindir / 'cardine'
        executable.write_text('#!' + sys.executable + '\nfrom cardine.cli import main\nraise SystemExit(main())\n')
        executable.chmod(0o755)
        environment = {**os.environ, 'PATH': str(bindir) + os.pathsep + os.environ['PATH'],
                       'PYTHONPATH': str(ROOT / 'src'), 'CARDINE_WORKTREE_ROOT': str(self.base / 'worktrees')}
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        first = subprocess.run(['cardine', 'run', '001', '--project', str(self.root)],
                               cwd=self.base, env=environment, text=True, capture_output=True, check=True)
        result = json.loads(first.stdout)
        second = subprocess.run(result['next']['command'], shell=True, cwd=self.base,
                                env=environment, text=True, capture_output=True, check=True)
        self.assertEqual(first.stdout, second.stdout)
        self.assertEqual(first.stderr + second.stderr, '')
        self.assertFalse((self.base / 'SENTINEL').exists())
        after = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(before, after)


if __name__ == '__main__':
    unittest.main()
