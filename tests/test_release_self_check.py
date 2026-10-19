"""Framework CLI regression tests for release self check."""

from __future__ import annotations

from cardine_cli_support import ROOT
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from http.client import BadStatusLine, IncompleteRead
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError, URLError
from cardine import cli as owner_cli
from cardine.release import update as owner_release_update
import cardine.shared.constants as shared_constants


class FakeLatestReleaseResponse:
    def __init__(self, payload: bytes):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self, limit: int) -> bytes:
        return self.payload[:limit]


class SelfCheckPluginRefTest(unittest.TestCase):
    def report(self, settings: object | None, latest: str | None = "1.2.7", *, raw: str | None = None) -> str:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            if raw is not None:
                path.write_text(raw, encoding="utf-8")
            elif settings is not None:
                path.write_text(json.dumps(settings), encoding="utf-8")
            report = owner_release_update.plugin_ref_report(path, latest)
            expected_files = [path.name] if raw is not None or settings is not None else []
            self.assertEqual([item.name for item in Path(directory).iterdir()], expected_files)
        return report

    @staticmethod
    def declared(ref: str) -> dict[str, object]:
        return {"extraKnownMarketplaces": {"meridian": {"source": {"source": "github", "repo": "biagiolibe/meridian", "ref": ref}}}}

    def test_stable_ref(self) -> None:
        self.assertEqual(self.report(self.declared("stable")), "Plugin ref: stable")

    def test_current_tag(self) -> None:
        self.assertIn("(latest release)", self.report(self.declared("v1.2.7")))

    def test_old_tag_names_the_remedy(self) -> None:
        report = self.report(self.declared("v1.2.6"))
        self.assertIn("older than latest release 1.2.7", report)
        self.assertIn('"stable" or "v1.2.7"', report)

    def test_tag_with_unknown_latest(self) -> None:
        self.assertIn("latest release unknown", self.report(self.declared("v1.2.6"), None))

    def test_missing_unreadable_or_undeclared_settings_are_unknown(self) -> None:
        for report in (self.report(None), self.report(None, raw="{not json"), self.report({}), self.report({"extraKnownMarketplaces": []})):
            self.assertTrue(report.startswith("Plugin ref: unknown ("), report)

    def test_self_check_prints_ref_and_keeps_exit_codes(self) -> None:
        installed = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        payload = json.dumps({"tag_name": f"v{installed}", "body": "CLI-only release: x\n"}).encode("utf-8")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text(json.dumps(self.declared("stable")), encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                result = owner_release_update.run_self_check(ROOT, urlopen_fn=mock.Mock(return_value=FakeLatestReleaseResponse(payload)), settings_path=path)
            self.assertEqual(result, 0)
            self.assertIn("Plugin ref: stable", output.getvalue())
            output = io.StringIO()
            with redirect_stdout(output):
                result = owner_release_update.run_self_check(ROOT, urlopen_fn=mock.Mock(side_effect=URLError("offline")), settings_path=path)
            self.assertEqual(result, shared_constants.SELF_CHECK_UNKNOWN)
            self.assertIn("Plugin ref: stable", output.getvalue())


class SelfCheckLatestTest(unittest.TestCase):
    def run_check(
        self, payload: dict[str, object] | bytes
    ) -> tuple[int, str, mock.Mock]:
        encoded = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
        opener = mock.Mock(return_value=FakeLatestReleaseResponse(encoded))
        output = io.StringIO()
        with redirect_stdout(output):
            result = owner_release_update.run_self_check(ROOT, urlopen_fn=opener)
        return result, output.getvalue(), opener

    def test_up_to_date_release(self) -> None:
        installed = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        result, output, opener = self.run_check(
            {
                "tag_name": f"v{installed}",
                "body": "CLI-only release: no managed files changed.\n",
            }
        )

        self.assertEqual(result, 0)
        self.assertIn("Status: UP_TO_DATE", output)
        request = opener.call_args.args[0]
        self.assertEqual(opener.call_args.kwargs["timeout"], 3.0)
        self.assertEqual(request.full_url, shared_constants.LATEST_RELEASE_URL)
        self.assertEqual(request.full_url, "https://api.github.com/repos/biagiolibe/cardine/releases/latest")
        self.assertEqual(request.get_header("User-agent"), f"cardine/{installed}")
        self.assertNotIn("meridian", request.full_url + request.get_header("User-agent"))  # MERIDIAN-OLD-NAME-TEST
        self.assertIsNone(request.get_header("Authorization"))

    def test_update_available_release(self) -> None:
        result, output, _ = self.run_check(
            {
                "tag_name": "v999.0.0",
                "body": "Template-changing release: migration 999.\n",
            }
        )

        self.assertEqual(result, shared_constants.SELF_CHECK_UPDATE_AVAILABLE)
        self.assertIn("Kind: template-changing", output)
        self.assertIn("Status: UPDATE_AVAILABLE", output)

    def test_offline_is_unknown(self) -> None:
        opener = mock.Mock(side_effect=URLError("offline"))
        output = io.StringIO()
        with redirect_stdout(output):
            result = owner_release_update.run_self_check(ROOT, urlopen_fn=opener)

        self.assertEqual(result, shared_constants.SELF_CHECK_UNKNOWN)
        self.assertIn("Status: UNKNOWN", output.getvalue())
        self.assertIn("network error: offline", output.getvalue())

    def test_interrupted_response_is_unknown(self) -> None:
        response = mock.MagicMock()
        response.__enter__.return_value.read.side_effect = IncompleteRead(
            b'{"tag_name": "v999.0.0"',
            10,
        )
        opener = mock.Mock(return_value=response)
        output = io.StringIO()
        with redirect_stdout(output):
            result = owner_release_update.run_self_check(ROOT, urlopen_fn=opener)

        self.assertEqual(result, shared_constants.SELF_CHECK_UNKNOWN)
        self.assertIn("Status: UNKNOWN", output.getvalue())
        self.assertIn("network error:", output.getvalue())

    def test_malformed_http_status_line_is_unknown(self) -> None:
        opener = mock.Mock(side_effect=BadStatusLine("garbled status"))
        output = io.StringIO()
        with redirect_stdout(output):
            result = owner_release_update.run_self_check(ROOT, urlopen_fn=opener)

        self.assertEqual(result, shared_constants.SELF_CHECK_UNKNOWN)
        self.assertIn("Status: UNKNOWN", output.getvalue())
        self.assertIn("network error: garbled status", output.getvalue())

    def test_rate_limited_is_unknown(self) -> None:
        opener = mock.Mock(
            side_effect=HTTPError(
                shared_constants.LATEST_RELEASE_URL,
                403,
                "rate limit exceeded",
                hdrs=None,
                fp=None,
            )
        )
        output = io.StringIO()
        with redirect_stdout(output):
            result = owner_release_update.run_self_check(ROOT, urlopen_fn=opener)

        self.assertEqual(result, shared_constants.SELF_CHECK_UNKNOWN)
        self.assertIn("Status: UNKNOWN", output.getvalue())
        self.assertIn("GitHub returned HTTP 403", output.getvalue())

    def test_malformed_response_is_unknown(self) -> None:
        result, output, _ = self.run_check(b"not-json")

        self.assertEqual(result, shared_constants.SELF_CHECK_UNKNOWN)
        self.assertIn("Status: UNKNOWN", output)
        self.assertIn("malformed response", output)

    def test_cli_dispatches_check_latest_without_real_network(self) -> None:
        installed = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        response = FakeLatestReleaseResponse(
            json.dumps(
                {
                    "tag_name": f"v{installed}",
                    "body": "CLI-only release: no managed files changed.\n",
                }
            ).encode("utf-8")
        )
        output = io.StringIO()
        with (
            mock.patch.object(
                sys,
                "argv",
                [
                    "cardine",
                    "--framework-root",
                    str(ROOT),
                    "self-check",
                    "--check-latest",
                ],
            ),
            mock.patch.object(owner_release_update, "urlopen", return_value=response) as opener,
            redirect_stdout(output),
        ):
            result = owner_cli.main()

        self.assertEqual(result, 0)
        self.assertIn("Status: UP_TO_DATE", output.getvalue())
        opener.assert_called_once()

    def test_self_check_without_opt_in_flag_never_opens_network(self) -> None:
        with (
            mock.patch.object(sys, "argv", ["cardine", "self-check"]),
            mock.patch.object(owner_release_update, "urlopen") as opener,
            redirect_stderr(io.StringIO()),
            self.assertRaises(SystemExit) as raised,
        ):
            owner_cli.main()

        self.assertEqual(raised.exception.code, 2)
        opener.assert_not_called()
