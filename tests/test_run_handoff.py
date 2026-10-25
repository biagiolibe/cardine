"""Optional completion prose never replaces current measured lifecycle facts."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from cardine.lifecycle import receipts
from cardine.tasks.contract import verify_execution_evidence
from cardine.tasks.validation import host_observations_complete
import test_run_validation

ROOT = Path(__file__).resolve().parents[1]


class RunHandoffTest(unittest.TestCase):
    def setUp(self):
        self.fixture = test_run_validation.RunValidationTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.worker = self.fixture.worker
        self.git = self.fixture.git

    def test_absent_paraphrased_and_false_report_fields_change_no_gate_or_fact(self):
        progress = self.fixture.run_attempt()
        summary = self.worker / 'tasks/handoffs/001.md'
        before = self.fixture.state()
        head = self.git('rev-parse', 'HEAD')
        for text in (None, 'A free-form summary.\n',
                     '- Validation: exit 99\n- Worktree: `foreign`\n- Acceptance criteria: unresolved\n'):
            if text is None:
                summary.unlink()
            else:
                summary.write_text(text)
            for _ in range(2):
                verify_execution_evidence(self.worker, '001')
                self.assertEqual(self.fixture.run_attempt(), progress)
            self.assertEqual(self.fixture.state(), before)
            self.assertEqual(self.git('rev-parse', 'HEAD'), head)
            self.assertEqual(summary.read_text() if summary.exists() else None, text)

    def test_report_success_cannot_replace_failed_actual_validation(self):
        self.fixture.configure({'one': 'exit 19'})
        self.fixture.run_attempt()
        (self.worker / 'tasks/handoffs/001.md').write_text('- Validation: all passed; host enforced\n')
        from cardine.shared.errors import CardineStop
        with self.assertRaises(CardineStop) as caught:
            verify_execution_evidence(self.worker, '001')
        self.assertEqual(caught.exception.code, 'EVIDENCE_INCOMPLETE')

    def test_typed_host_observation_is_required_despite_completion_prose(self):
        self.fixture.configure({'codex': 'printf actual-host-check'}, profiles={'codex': 'enforced'})
        progress = self.fixture.run_attempt()
        self.assertTrue(host_observations_complete(self.fixture.state()['contract'], progress))
        before = self.fixture.state()
        changed = deepcopy(before)
        changed['run']['validation']['hostObservations'] = []
        with receipts.task_lock(self.worker, '001'):
            receipts.write_operation(self.worker, '001', changed, previous=before, kind='fixture-missing-observation')
        (self.worker / 'tasks/handoffs/001.md').write_text('- [codex]: verified and enforced\n')
        from cardine.shared.errors import CardineStop
        with self.assertRaises(CardineStop) as caught:
            verify_execution_evidence(self.worker, '001')
        self.assertEqual(caught.exception.code, 'EVIDENCE_INCOMPLETE')
        rerun = self.fixture.run_attempt()
        self.assertNotEqual(rerun['attemptId'], progress['attemptId'])
        self.assertTrue(host_observations_complete(self.fixture.state()['contract'], rerun))
        self.assertEqual(self.fixture.run_attempt(), rerun)
        verify_execution_evidence(self.worker, '001')

    def test_missing_command_never_claims_host_success(self):
        self.fixture.configure({'one': 'true'}, profiles={'codex': 'enforced'})
        progress = self.fixture.run_attempt()
        self.assertFalse(host_observations_complete(self.fixture.state()['contract'], progress))
        from cardine.lifecycle.engine import run_validation_step, resolve_run_locations
        result = run_validation_step(resolve_run_locations('001', self.worker))
        self.assertEqual(result['step'], 'implementation')
        self.assertEqual(result['diagnostics'][0]['code'], 'ACCEPTANCE_UNMET')

    def test_observation_must_match_actual_command_log_and_exit(self):
        self.fixture.configure({'codex': 'true'}, profiles={'codex': 'enforced'})
        progress = self.fixture.run_attempt()
        contract = self.fixture.state()['contract']
        for key, value in [('observed', False), ('exitStatus', 7),
                           ('commandId', 'foreign'), ('evidence', 'invented')]:
            changed = deepcopy(progress)
            changed['hostObservations'][0][key] = value
            self.assertFalse(host_observations_complete(contract, changed))
        changed = deepcopy(progress)
        changed['runs'][-1][0]['exitStatus'] = 7
        self.assertFalse(host_observations_complete(contract, changed))

    def test_cli_has_no_report_gate_or_report_argument(self):
        from cardine.cli import build_parser
        from contextlib import redirect_stderr
        import io
        for argv in (['execution', 'handoff-check', '001'], ['execution', 'ready-check', '001', 'report.md']):
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
                build_parser().parse_args(argv)
            self.assertEqual(caught.exception.code, 2)
        from cardine.stops.registry import load_stop_registry
        self.assertFalse(any(code.startswith('HANDOFF_') for code in load_stop_registry()))

    def baseline_fixture(self):
        # Render the actual managed-template baseline; publication uses RE1b's
        # operation writer in a disposable consumer, never this repository.
        sys.path.insert(0, str(ROOT / 'scripts'))
        import check_repository
        return receipts.encoded(check_repository.current_marker_baselines(ROOT))

    def kill_baseline(self, point, content):
        target = self.worker / 'baseline-input.json'
        target.write_bytes(content)
        # An input file outside the expected code surface is used only by this
        # fixture's explicit publication command, not by the run engine.
        script = '''
import os,sys
from pathlib import Path
from cardine.lifecycle import receipts
from cardine.tasks.state import read_task_state
from cardine.stops.render import stop_error
root=Path(sys.argv[1]); content=(root/'baseline-input.json').read_bytes()
def kill(name):
    if name == sys.argv[2]: os._exit(77)
receipts.boundary=kill
original_link=os.link
original_durable=receipts._durable
def around(path, effect):
    if Path(path).name == 'marker-baselines.json':
        kill('before_baseline_write')
        result=effect()
        kill('after_baseline_write')
        return result
    return effect()
def link(source,target,*args,**kwargs):
    return around(target,lambda:original_link(source,target,*args,**kwargs))
def durable(path,content):
    return around(path,lambda:original_durable(path,content))
os.link=link
receipts._durable=durable
with receipts.task_lock(root,'001'):
    if receipts.pending_operation(root,'001'):
        receipts.replay_operation(root,'001',kind='fixture-baseline')
    else:
        state=read_task_state(root,'001','single',stop_factory=stop_error)
        receipts.write_operation(root,'001',state,previous=state,kind='fixture-baseline',
                                files={'capabilities/marker-baselines.json':content})
'''
        self.baseline_script = script
        env = {**os.environ, 'PYTHONPATH': str(ROOT / 'src')}
        result = subprocess.run([sys.executable, '-c', script, str(self.worker), point],
                                env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 77, result.stderr)

    def replay_baseline(self):
        with receipts.task_lock(self.worker, '001'):
            return receipts.replay_operation(self.worker, '001', kind='fixture-baseline')


def baseline_recovery(point):
    def test(self):
        content = self.baseline_fixture()
        head = self.git('rev-parse', 'HEAD')
        self.kill_baseline(point, content)
        env = {**os.environ, 'PYTHONPATH': str(ROOT / 'src')}
        result = subprocess.run([sys.executable, '-c', self.baseline_script, str(self.worker), 'no-kill'],
                                env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        state = self.fixture.state()
        self.assertEqual((self.worker / 'capabilities/marker-baselines.json').read_bytes(), content)
        self.assertEqual(self.baseline_fixture(), content)
        self.assertEqual(sum(r['kind'] == 'fixture-baseline' for r in state['run']['receipts']), 1)
        self.assertEqual(self.git('rev-parse', 'HEAD'), head)
    return test


def baseline_negative(point):
    def test(self):
        from cardine.shared.errors import CardineError
        self.kill_baseline(point, self.baseline_fixture())
        policy = self.worker / '.cardine/project.json'
        saved_policy = policy.read_bytes()
        policy.write_bytes(saved_policy + b'\n')
        with self.assertRaises(CardineError):
            self.replay_baseline()
        self.assertEqual(policy.read_bytes(), saved_policy + b'\n')
        policy.write_bytes(saved_policy)
        path = self.worker / 'capabilities/marker-baselines.json'
        path.parent.mkdir(exist_ok=True)
        original = path.read_bytes() if path.exists() else None
        path.write_text('foreign output; preserve\n')
        with self.assertRaises(CardineError):
            self.replay_baseline()
        self.assertEqual(path.read_text(), 'foreign output; preserve\n')
        if original is None:
            path.unlink()
        else:
            path.write_bytes(original)
        intent_path = receipts._intent_path(self.worker, '001')
        intent = receipts._load_intent(intent_path)
        receipts._save_intent(intent_path, dict(intent, task_id='foreign'))
        with self.assertRaises(CardineError):
            self.replay_baseline()
    return test


for _point in ('before_staged_pair', 'after_staged_pair', 'before_baseline_write', 'after_baseline_write',
               'before_state_replace', 'after_state_replace'):
    setattr(RunHandoffTest, 'test_baseline_recovery_' + _point, baseline_recovery(_point))
    setattr(RunHandoffTest, 'test_baseline_negative_' + _point, baseline_negative(_point))


if __name__ == '__main__':
    unittest.main()
