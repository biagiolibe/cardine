"""Release notices use a local cache and detached checks."""
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cardine.release import notice


class UpdateNoticeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def cache(self, latest="2.0.0", hours=0, kind="CLI-only"):
        path = self.home / ".cardine/update-check.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps({"checkedAt": (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(),
                                    "installed": "1.0.0", "latest": latest, "kind": kind}))

    def test_notice_and_opt_out(self):
        self.cache()
        self.assertEqual(notice.notice(self.home, "1.0.0"),
                         "Cardine 2.0.0 is available (installed 1.0.0, CLI-only release): cardine self-update --check")
        self.assertIsNone(notice.notice(self.home, "2.0.0"))
        self.assertIsNone(notice.notice(self.home, "3.0.0"))
        for variable in ("CI", "CARDINE_NO_UPDATE_NOTICE"):
            with patch.dict(os.environ, {variable: "1"}):
                self.assertIsNone(notice.notice(self.home, "1.0.0"))
                with patch.object(notice.subprocess, "Popen") as start:
                    notice.refresh_in_background(self.home, "1.0.0")
                    start.assert_not_called()

    def test_missing_and_corrupt(self):
        self.assertIsNone(notice.notice(self.home, "1.0.0"))
        self.cache()
        (self.home / ".cardine/update-check.json").write_text("{")
        self.assertIsNone(notice.notice(self.home, "1.0.0"))

    def test_background_only_when_stale(self):
        self.cache(hours=25)
        with patch.object(notice.subprocess, "Popen") as start:
            notice.refresh_in_background(self.home, "1.0.0")
            start.assert_called_once()
            self.assertTrue(start.call_args.kwargs["start_new_session"])
        self.cache()
        with patch.object(notice.subprocess, "Popen") as start:
            notice.refresh_in_background(self.home, "1.0.0")
            start.assert_not_called()

    def test_refresh_success_and_failure(self):
        with patch("cardine.release.update.fetch_latest_release", return_value=("2.0.0", "CLI-only")):
            notice.refresh(self.home, "1.0.0")
        path = self.home / ".cardine/update-check.json"
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads(path.read_text())["latest"], "2.0.0")
        with patch("cardine.release.update.fetch_latest_release", side_effect=OSError):
            notice.refresh(self.home, "1.0.0")
        self.assertIsNone(json.loads(path.read_text())["latest"])


class PresentationTests(unittest.TestCase):
    def test_guide_terminal_and_pipe(self):
        from cardine import cli
        from io import StringIO
        from contextlib import redirect_stdout, redirect_stderr
        for tty in (True, False):
            error = StringIO()
            error.isatty = lambda: tty
            with patch.object(cli.sys, "argv", ["cardine", "guide"]), \
                 patch("cardine.shared.project_guide.project_guide", return_value={}), \
                 patch("cardine.shared.project_guide.render_project_guide", return_value="guide"), \
                 patch("cardine.release.notice.notice", return_value="update available") as cached, \
                 patch("cardine.release.notice.refresh_in_background") as background, \
                 redirect_stdout(StringIO()), redirect_stderr(error):
                self.assertEqual(cli.main(), 0)
            self.assertEqual(error.getvalue(), "Note: update available\n" if tty else "")
            self.assertEqual(cached.call_count, int(tty))
            self.assertEqual(background.call_count, int(tty))

    def test_console_header(self):
        from types import SimpleNamespace
        from cardine.console.render import _draw_header
        state = SimpleNamespace(snapshot=None, project=Path("project"),
                                framework=SimpleNamespace(version="1.0.0", root_label="root"), error=None)
        palette = {key: 0 for key in ("text", "blocked", "stale", "muted", "line")}
        with patch("cardine.release.notice.notice", return_value="Cardine 2.0.0 is available"), \
             patch("cardine.console.render._put") as put:
            _draw_header(None, state, palette, "All", 120)
        self.assertTrue(any("↑ 2.0.0 available" in call.args[3] for call in put.call_args_list))
