"""Developer channel: owner verdict, cancel and abort are confirmed at a terminal."""
import os
from pathlib import Path
import pty
import select
import subprocess
import sys
import tempfile
import time
import unittest

from cardine.lifecycle.control import TERMINAL_PRINCIPAL
from cardine.shared.git import git_output
from cardine.tasks.state import state_path
import test_host_permissions
import test_run_control
import test_run_review

ROOT = Path(__file__).resolve().parents[1]
PROMPT = b"Type '"
CHILD = '''
import os, sys
from pathlib import Path
from cardine.lifecycle import receipts
action, project, kill = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
def seam(name):
    if name == kill:
        os._exit(77)
receipts.boundary = seam
try:
    if action == 'cancel':
        from cardine.lifecycle.control import cancel_task
        cancel_task('001', project, reason='Superseded')
    elif action == 'abort':
        from cardine.lifecycle.control_abort import abort_owned
        abort_owned('056', project)
    elif action == 'owner':
        from cardine.review.verdict import record_review_verdict
        record_review_verdict(project, '001', 'APPROVE', owner=True)
    else:
        from cardine.review.verdict import record_review_verdict
        record_review_verdict(project, '001', 'APPROVE', request_id=sys.argv[4])
except Exception as error:
    print(type(error).__name__ + ': ' + str(error), file=sys.stderr)
    sys.exit(3)
'''


class Terminal(unittest.TestCase):
    """Run a command with a pseudo-terminal as stdin and stdout, or without one."""

    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)

    def environment(self):
        return {**os.environ, 'HOME': self.home.name,
                'PYTHONPATH': os.pathsep.join([str(ROOT / 'src'), str(ROOT / 'tests')])}

    def terminal(self, command, cwd, answer=None, timeout=60):
        """Answer the prompt once; `answer=None` never types, so a prompt would time out."""
        master, slave = pty.openpty()
        process = subprocess.Popen(command, cwd=cwd, env=self.environment(), stdin=slave, stdout=slave,
                                   stderr=subprocess.PIPE, close_fds=True)
        os.close(slave)
        seen, typed, deadline = b'', False, time.monotonic() + timeout
        try:
            while time.monotonic() < deadline:
                ready, _, _ = select.select([master], [], [], 0.2)
                if ready:
                    try:
                        chunk = os.read(master, 4096)
                    except OSError:
                        break
                    if not chunk:
                        break
                    seen += chunk
                    if answer is not None and not typed and PROMPT in seen and seen.rstrip().endswith(b'refuses.'):
                        os.write(master, answer.encode() + b'\n')
                        typed = True
                elif process.poll() is not None:
                    break
            else:
                process.kill()
                self.fail('terminal command did not finish: ' + seen.decode(errors='replace'))
        finally:
            os.close(master)
        stderr = process.stderr.read().decode()
        process.stderr.close()
        return process.wait(timeout=30), seen.decode(errors='replace'), stderr

    def piped(self, command, cwd, answer):
        """Correct text on stdin, but no terminal on either stream."""
        result = subprocess.run(command, cwd=cwd, env=self.environment(), input=answer + '\n',
                                capture_output=True, text=True, timeout=60)
        return result.returncode, result.stdout, result.stderr

    def child(self, action, project, kill='', *extra):
        return [sys.executable, '-c', CHILD, action, str(project), kill, *extra]


class DeveloperChannelTest(Terminal):
    def build(self, action):
        """Return a fixture's project root and the answer that confirms its task and commit."""
        os.chdir(ROOT)  # an earlier fixture's cwd may be gone
        if action == 'abort':
            fixture = test_run_control.RunAbortTest()
            fixture.setUp()
            self.addCleanup(fixture.doCleanups)
            self.addCleanup(fixture.tearDown)
            self.fixture, self.project, self.worker = fixture, fixture.primary, fixture.worker
            self.task, self.head = '056', git_output(self.worker, 'rev-parse', 'HEAD')
            self.state_file = state_path(self.worker, '056')
        else:
            fixture = test_run_control.RunCancelTest() if action == 'cancel' else test_run_review.RunReviewTest()
            fixture.setUp()
            self.addCleanup(fixture.doCleanups)
            self.fixture, self.project = fixture, fixture.root
            self.task, self.head = '001', git_output(self.project, 'rev-parse', 'HEAD')
            self.state_file = state_path(self.project, '001')
        return self.project, f'{self.task} {self.head}'

    def before(self):
        return self.state_file.read_bytes()

    ACTIONS = ('cancel', 'abort', 'owner')

    def result_state(self, action):
        import json
        return json.loads(self.state_file.read_bytes())

    def effect_done(self, action):
        state = self.result_state(action)
        if action == 'cancel':
            return state['status'] == 'cancelled'
        if action == 'owner':
            return state['review']['approved_by'] == 'owner'
        return 'ownedAbortResult' in state.get('run', {})

    def test_accepted_confirmation_applies_each_action_once_and_a_rerun_converges(self):
        for action in self.ACTIONS:
            with self.subTest(action=action):
                project, answer = self.build(action)
                command = self.child(action, project)
                code, output, error = self.terminal(command, project, answer)
                self.assertEqual(code, 0, output + error)
                self.assertTrue(self.effect_done(action))
                self.assertIn(f'task {self.task} at commit {self.head}', output)
                applied = self.before()
                self.assertIn(TERMINAL_PRINCIPAL['session_id'].encode(), applied)
                code, output, error = self.terminal(command, project, answer)
                self.assertEqual(code, 0, output + error)
                self.assertEqual(self.before(), applied)

    def test_real_cli_cancel_is_confirmed_at_the_terminal(self):
        project, answer = self.build('cancel')
        command = [sys.executable, str(ROOT / 'scripts/cardine_cli.py'), 'cancel', '001',
                   '--reason', 'Superseded', '--project', str(project)]
        code, output, error = self.terminal(command, project, answer)
        self.assertEqual(code, 0, output + error)
        self.assertEqual(self.result_state('cancel')['status'], 'cancelled')

    def test_real_cli_owner_verdict_without_terminal_is_refused(self):
        project, answer = self.build('owner')
        before = self.before()
        command = [sys.executable, str(ROOT / 'scripts/cardine_cli.py'), 'review', 'verdict', '001',
                   'APPROVE', '--owner', '--project', str(project)]
        code, _, error = self.piped(command, project, answer)
        self.assertEqual(code, 2, error)
        self.assertIn('host role boundary unavailable', error)
        self.assertEqual(self.before(), before)

    def test_wrong_confirmation_is_refused_without_writing(self):
        for action in self.ACTIONS:
            project, answer = self.build(action)
            for typed in ('', 'yes', self.task, answer.upper(), f'{self.task} {self.head[:12]}',
                          f'001 {"0" * 40}', answer + ' extra'):
                with self.subTest(action=action, typed=typed):
                    before = self.before()
                    code, output, error = self.terminal(self.child(action, project), project, typed)
                    self.assertEqual(code, 3, output + error)
                    self.assertIn('developer confirmation did not match', error)
                    self.assertEqual(self.before(), before)

    def test_end_of_input_is_refused_without_writing(self):
        for action in self.ACTIONS:
            with self.subTest(action=action):
                project, answer = self.build(action)
                before = self.before()
                command = self.child(action, project)
                master, slave = pty.openpty()
                process = subprocess.Popen(command, cwd=project, env=self.environment(), stdin=slave,
                                           stdout=slave, stderr=subprocess.PIPE, close_fds=True)
                os.close(slave)
                try:
                    deadline, seen = time.monotonic() + 60, b''
                    while PROMPT not in seen or not seen.rstrip().endswith(b'refuses.'):
                        self.assertLess(time.monotonic(), deadline)
                        if select.select([master], [], [], 0.2)[0]:
                            seen += os.read(master, 4096)
                    os.write(master, b'\x04')
                    error = process.stderr.read().decode()
                finally:
                    os.close(master)
                    process.stderr.close()
                self.assertEqual(process.wait(timeout=30), 3, error)
                self.assertIn('developer confirmation did not match', error)
                self.assertEqual(self.before(), before)

    def test_no_terminal_is_refused_even_with_the_correct_confirmation(self):
        for action in self.ACTIONS:
            project, answer = self.build(action)
            before = self.before()
            with self.subTest(action=action, streams='both piped'):
                code, output, error = self.piped(self.child(action, project), project, answer)
                self.assertEqual(code, 3, error)
                self.assertIn('host role boundary unavailable', error)
                self.assertNotIn('Developer confirmation', output)
            with self.subTest(action=action, streams='terminal stdin only'):
                master, slave = pty.openpty()
                self.addCleanup(os.close, master)
                try:
                    result = subprocess.run(self.child(action, project), cwd=project, env=self.environment(),
                                            stdin=slave, capture_output=True, text=True, timeout=60)
                finally:
                    os.close(slave)
                self.assertEqual(result.returncode, 3, result.stderr)
                self.assertIn('host role boundary unavailable', result.stderr)
            self.assertEqual(self.before(), before)

    def test_reviewer_session_verdict_is_never_confirmed_by_a_terminal(self):
        project, _ = self.build('owner')
        before = self.before()
        key = self.fixture.key
        code, output, error = self.terminal(self.child('reviewer', project, '', key), project, answer=None)
        self.assertEqual(code, 3, output + error)
        self.assertIn('host role boundary unavailable', error)
        self.assertNotIn('Developer confirmation', output)
        self.assertEqual(self.before(), before)

    def test_interruption_before_and_after_the_confirmation_leaves_no_effect_and_a_rerun_converges(self):
        for action in self.ACTIONS:
            for point in ('before_developer_confirmation', 'after_developer_confirmation'):
                with self.subTest(action=action, point=point):
                    project, answer = self.build(action)
                    before = self.before()
                    code, output, error = self.terminal(self.child(action, project, point), project, answer)
                    self.assertEqual(code, 77, output + error)
                    self.assertEqual(self.before(), before)
                    code, output, error = self.terminal(self.child(action, project), project, answer)
                    self.assertEqual(code, 0, output + error)
                    self.assertTrue(self.effect_done(action))
                    applied = self.before()
                    code, output, error = self.terminal(self.child(action, project), project, answer)
                    self.assertEqual(code, 0, output + error)
                    self.assertEqual(self.before(), applied)

    def test_interruption_after_the_effect_keeps_its_receipt_and_a_confirmed_rerun_converges(self):
        project, answer = self.build('cancel')
        code, output, error = self.terminal(self.child('cancel', project, 'after_cancel_transition'), project, answer)
        self.assertEqual(code, 77, output + error)
        landed = self.before()
        self.assertTrue(self.effect_done('cancel'))
        code, output, error = self.terminal(self.child('cancel', project), project, answer)
        self.assertEqual(code, 0, output + error)
        self.assertEqual(self.before(), landed)
        self.assertEqual(sum(t['to'] == 'cancelled' for t in self.result_state('cancel')['transitions']), 1)


class DeveloperChannelProbeTest(test_host_permissions.Fixture):
    def test_host_rules_still_deny_the_three_commands_to_agents(self):
        for command in ('cardine cancel 001 --reason x', 'cardine --project . abort 001',
                        'cardine review verdict 001 APPROVE --owner',
                        'python3 scripts/cardine_cli.py cancel 001 --reason x', 'python3 -m cardine abort 001'):
            for role in test_host_permissions.permissions.ROLES:
                with self.subTest(role=role, command=command):
                    self.assertFalse(self.decide(role, command))


if __name__ == '__main__':
    unittest.main()
