"""Terminal styling and spinner behavior."""
import contextlib
import io
import unittest
from unittest.mock import patch

from cardine.shared import terminal


class TerminalStyleTest(unittest.TestCase):
    def test_plain_and_colored_marks(self):
        with patch.object(terminal, 'enabled', return_value=False):
            self.assertNotIn('\x1b', terminal.done(terminal.step(2, 4, 'Fetch')))
        with patch.object(terminal, 'enabled', return_value=True):
            for method, code in ((terminal.done, '32'), (terminal.skipped, '33'), (terminal.failed, '31')):
                self.assertIn(f'\x1b[{code}m', method('step'))

    def test_spinner_uses_stderr_and_clears(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(terminal, 'enabled', return_value=True), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            with terminal.spinner('Working'):
                pass
        self.assertEqual(stdout.getvalue(), '')
        self.assertIn('Working', stderr.getvalue())
        self.assertTrue(stderr.getvalue().endswith('\r\x1b[2K'))
        stderr = io.StringIO()
        with patch.object(terminal, 'enabled', return_value=False), contextlib.redirect_stderr(stderr):
            with terminal.spinner('Working'):
                pass
        self.assertEqual(stderr.getvalue(), '')
