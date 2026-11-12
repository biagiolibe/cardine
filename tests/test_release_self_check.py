"""Framework CLI regression tests for release self check."""

from __future__ import annotations

from cardine_cli_support import ROOT
import io
import json
import os
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


class ReleaseKindLineTest(unittest.TestCase):
    def test_both_punctuations_and_rejection(self) -> None:
        from cardine.release.version import release_kind_from_body
        for body, kind in (("CLI-only release. x", "CLI-only"), ("CLI-only release: x", "CLI-only"),
                           ("\nTemplate-changing release. x", "template-changing"),
                           ("Template-changing release: x", "template-changing")):
            self.assertEqual(release_kind_from_body(body), kind)
        for body in ("", "CLI-only release x", "Release: x"):
            with self.assertRaises(ValueError):
                release_kind_from_body(body)


class FakeLatestReleaseResponse:
    def __init__(self, payload: bytes):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self, limit: int) -> bytes:
        return self.payload[:limit]


class SelfCheckPluginTest(unittest.TestCase):
    @staticmethod
    def installed(*versions: str) -> dict[str, object]:
        return {"plugins": {"cardine@cardine": [{"version": version} for version in versions]}}

    def report(self, registry: object | None, latest: str | None = "1.2.7", *, raw: str | None = None) -> str:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plugins/installed_plugins.json"
            if raw is not None or registry is not None:
                path.parent.mkdir()
                path.write_text(raw if raw is not None else json.dumps(registry), encoding="utf-8")
            before = {item.relative_to(directory): item.read_bytes()
                      for item in Path(directory).rglob("*") if item.is_file()}
            report = owner_release_update.installed_plugin_report(path, latest)
            after = {item.relative_to(directory): item.read_bytes()
                     for item in Path(directory).rglob("*") if item.is_file()}
            self.assertEqual(after, before)
        return report

    def test_current_and_newer_versions(self) -> None:
        self.assertEqual(self.report(self.installed("1.2.7", "1.3.0")),
                         "Plugin: 1.2.7, 1.3.0 (latest release)")

    def test_old_version_names_the_remedy(self) -> None:
        self.assertEqual(self.report(self.installed("1.2.6", "1.2.7")),
                         "Plugin: 1.2.6, 1.2.7 (older than latest release 1.2.7; run cardine self-update --apply)")

    def test_unknown_latest(self) -> None:
        self.assertEqual(self.report(self.installed("1.2.6"), None),
                         "Plugin: 1.2.6 (latest release unknown)")

    def test_not_installed(self) -> None:
        for registry in (None, {}, {"plugins": {"other@other": [{"version": "1.0.0"}]}}, self.installed()):
            with self.subTest(registry=registry):
                self.assertEqual(self.report(registry), "Plugin: not installed")

    def test_unreadable_or_invalid_registry(self) -> None:
        self.assertTrue(self.report(None, raw="{not json").startswith("Plugin: unknown ("))
        for registry in ([], {"plugins": []}, {"plugins": {"cardine@cardine": {}}},
                         {"plugins": {"cardine@cardine": [{}]}}, self.installed("not-a-version")):
            with self.subTest(registry=registry):
                self.assertTrue(self.report(registry).startswith("Plugin: unknown ("))
        with mock.patch.object(Path, "read_text", side_effect=PermissionError("denied")):
            self.assertIn("unreadable", owner_release_update.installed_plugin_report(Path("registry"), None))

    def test_config_directory_resolution(self) -> None:
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": "/custom/claude"}):
            self.assertEqual(owner_release_update.claude_plugin_registry_path(),
                             Path("/custom/claude/plugins/installed_plugins.json"))
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": ""}), mock.patch.object(Path, "home", return_value=Path("/example-home")):
            self.assertEqual(owner_release_update.claude_plugin_registry_path(),
                             Path("/example-home/.claude/plugins/installed_plugins.json"))

    def test_self_check_prints_plugin_and_keeps_exit_codes_without_writes(self) -> None:
        installed = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        payload = json.dumps({"tag_name": f"v{installed}", "body": "CLI-only release: x\n"}).encode("utf-8")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plugins/installed_plugins.json"
            path.parent.mkdir()
            path.write_text(json.dumps(self.installed(installed)), encoding="utf-8")
            before = path.read_bytes()
            with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": directory}):
                for opener, expected, line in (
                    (mock.Mock(return_value=FakeLatestReleaseResponse(payload)), 0, f"Plugin: {installed} (latest release)"),
                    (mock.Mock(side_effect=URLError("offline")), shared_constants.SELF_CHECK_UNKNOWN,
                     f"Plugin: {installed} (latest release unknown)"),
                ):
                    output = io.StringIO()
                    with redirect_stdout(output):
                        result = owner_release_update.run_self_check(ROOT, urlopen_fn=opener)
                    self.assertEqual(result, expected)
                    self.assertIn(line, output.getvalue())
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(sorted(str(item.relative_to(directory)) for item in Path(directory).rglob("*")),
                             ["plugins", "plugins/installed_plugins.json"])


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
