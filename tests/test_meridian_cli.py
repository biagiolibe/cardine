"""Regression tests for the deterministic framework-upgrade CLI."""

from __future__ import annotations

import importlib
import io
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from http.client import BadStatusLine, IncompleteRead
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError, URLError


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "meridian.py"
MARKER_BEGIN = re.compile(r"<!-- MERIDIAN:BEGIN capability=([a-z0-9-]+) v(\d+) -->")
MARKER_END = "<!-- MERIDIAN:END -->"

sys.path.insert(0, str(ROOT / "scripts"))
import meridian  # noqa: E402


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
            report = meridian.plugin_ref_report(path, latest)
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
                result = meridian.run_self_check(ROOT, urlopen_fn=mock.Mock(return_value=FakeLatestReleaseResponse(payload)), settings_path=path)
            self.assertEqual(result, 0)
            self.assertIn("Plugin ref: stable", output.getvalue())
            output = io.StringIO()
            with redirect_stdout(output):
                result = meridian.run_self_check(ROOT, urlopen_fn=mock.Mock(side_effect=URLError("offline")), settings_path=path)
            self.assertEqual(result, meridian.SELF_CHECK_UNKNOWN)
            self.assertIn("Plugin ref: stable", output.getvalue())


class SelfCheckLatestTest(unittest.TestCase):
    def run_check(
        self, payload: dict[str, object] | bytes
    ) -> tuple[int, str, mock.Mock]:
        encoded = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
        opener = mock.Mock(return_value=FakeLatestReleaseResponse(encoded))
        output = io.StringIO()
        with redirect_stdout(output):
            result = meridian.run_self_check(ROOT, urlopen_fn=opener)
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
        self.assertEqual(request.full_url, meridian.LATEST_RELEASE_URL)
        self.assertIsNone(request.get_header("Authorization"))

    def test_update_available_release(self) -> None:
        result, output, _ = self.run_check(
            {
                "tag_name": "v999.0.0",
                "body": "Template-changing release: migration 999.\n",
            }
        )

        self.assertEqual(result, meridian.SELF_CHECK_UPDATE_AVAILABLE)
        self.assertIn("Kind: template-changing", output)
        self.assertIn("Status: UPDATE_AVAILABLE", output)

    def test_offline_is_unknown(self) -> None:
        opener = mock.Mock(side_effect=URLError("offline"))
        output = io.StringIO()
        with redirect_stdout(output):
            result = meridian.run_self_check(ROOT, urlopen_fn=opener)

        self.assertEqual(result, meridian.SELF_CHECK_UNKNOWN)
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
            result = meridian.run_self_check(ROOT, urlopen_fn=opener)

        self.assertEqual(result, meridian.SELF_CHECK_UNKNOWN)
        self.assertIn("Status: UNKNOWN", output.getvalue())
        self.assertIn("network error:", output.getvalue())

    def test_malformed_http_status_line_is_unknown(self) -> None:
        opener = mock.Mock(side_effect=BadStatusLine("garbled status"))
        output = io.StringIO()
        with redirect_stdout(output):
            result = meridian.run_self_check(ROOT, urlopen_fn=opener)

        self.assertEqual(result, meridian.SELF_CHECK_UNKNOWN)
        self.assertIn("Status: UNKNOWN", output.getvalue())
        self.assertIn("network error: garbled status", output.getvalue())

    def test_rate_limited_is_unknown(self) -> None:
        opener = mock.Mock(
            side_effect=HTTPError(
                meridian.LATEST_RELEASE_URL,
                403,
                "rate limit exceeded",
                hdrs=None,
                fp=None,
            )
        )
        output = io.StringIO()
        with redirect_stdout(output):
            result = meridian.run_self_check(ROOT, urlopen_fn=opener)

        self.assertEqual(result, meridian.SELF_CHECK_UNKNOWN)
        self.assertIn("Status: UNKNOWN", output.getvalue())
        self.assertIn("GitHub returned HTTP 403", output.getvalue())

    def test_malformed_response_is_unknown(self) -> None:
        result, output, _ = self.run_check(b"not-json")

        self.assertEqual(result, meridian.SELF_CHECK_UNKNOWN)
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
                    "meridian",
                    "--framework-root",
                    str(ROOT),
                    "self-check",
                    "--check-latest",
                ],
            ),
            mock.patch.object(meridian, "urlopen", return_value=response) as opener,
            redirect_stdout(output),
        ):
            result = meridian.main()

        self.assertEqual(result, 0)
        self.assertIn("Status: UP_TO_DATE", output.getvalue())
        opener.assert_called_once()

    def test_self_check_without_opt_in_flag_never_opens_network(self) -> None:
        with (
            mock.patch.object(sys, "argv", ["meridian", "self-check"]),
            mock.patch.object(meridian, "urlopen") as opener,
            redirect_stderr(io.StringIO()),
            self.assertRaises(SystemExit) as raised,
        ):
            meridian.main()

        self.assertEqual(raised.exception.code, 2)
        opener.assert_not_called()


class MeridianCliTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.framework = root / "framework"
        self.project = root / "project"
        shutil.copytree(ROOT / "templates", self.framework / "templates")
        shutil.copytree(ROOT / "migrations", self.framework / "migrations")
        shutil.copytree(ROOT / "release-baselines", self.framework / "release-baselines")
        shutil.copytree(ROOT / "capabilities", self.framework / "capabilities")
        (self.framework / "VERSION").write_text("1.1.0\n", encoding="utf-8")
        self.project.mkdir()
        self.copy_governed_templates()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def copy_governed_templates(self) -> None:
        source = self.framework / "templates" / "workflows" / "governed-sdd"
        for path in source.rglob("*"):
            if path.is_file():
                destination = self.project / path.relative_to(source)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, destination)

    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(CLI),
                "--framework-root",
                str(self.framework),
                *arguments,
                "--project",
                str(self.project),
            ],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_upgrade_check_reports_retired_text_without_writes_or_exit_change(self) -> None:
        (self.framework / "VERSION").write_text(meridian.read_version(ROOT) + "\n", encoding="utf-8")
        locked = self.run_cli("lock", "--mode", "governed-sdd")
        self.assertEqual(locked.returncode, 0, locked.stdout + locked.stderr)
        baseline = self.run_cli("upgrade", "--check")
        self.assertEqual(baseline.returncode, 0, baseline.stdout + baseline.stderr)
        self.assertNotIn("retired-text", baseline.stdout)
        for relative_path in meridian.load_retired_text_registry(ROOT)[0]["files"]:
            path = self.project / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as stream:
                stream.write("\nFresh SESSION at the declared VALUE\n")
        before = {path.relative_to(self.project): path.read_bytes() for path in self.project.rglob("*") if path.is_file()}
        checked = self.run_cli("upgrade", "--check")
        self.assertEqual(checked.returncode, baseline.returncode, checked.stdout + checked.stderr)
        self.assertEqual(checked.stdout.count("ADVISORY       retired-text"), 2)
        self.assertIn("retired capability=reasoning-budget-contract", checked.stdout)
        after = {path.relative_to(self.project): path.read_bytes() for path in self.project.rglob("*") if path.is_file()}
        self.assertEqual(after, before)

    def configure_1_1_40_to_1_1_41_upgrade(self) -> None:
        """Lock the entry points immediately before migration 044."""
        workflow = self.framework / "templates/workflows/governed-sdd"
        for name in ("AGENTS.md", "CLAUDE.md"):
            current = workflow / name
            old_text = current.read_text(encoding="utf-8").replace(
                "MERIDIAN:BEGIN capability=command-triggers v3",
                "MERIDIAN:BEGIN capability=command-triggers v2",
            ).replace(
                "- `Restart rejected <TASK-ID>` — read `docs/workflows/LIFECYCLE.md`.\n",
                "",
            )
            current.write_text(old_text, encoding="utf-8")
            (self.project / name).write_text(old_text, encoding="utf-8")
        (self.framework / "VERSION").write_text("1.1.40\n", encoding="utf-8")
        self.assertEqual(self.run_cli("lock", "--mode", "governed-sdd").returncode, 0)
        for name in ("AGENTS.md", "CLAUDE.md"):
            source = ROOT / "templates/workflows/governed-sdd" / name
            (workflow / name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        (self.framework / "VERSION").write_text("1.1.41\n", encoding="utf-8")

    def configure_1_1_53_to_1_1_54_manual_proceed_upgrade(self) -> tuple[Path, Path]:
        """Lock the two governed worktree capabilities immediately before 056."""
        workflow = self.framework / "templates/workflows/governed-sdd"
        implementation = workflow / "docs/workflows/IMPLEMENTATION.md"
        project_workflow = workflow / "PROJECT_WORKFLOW.md"
        current_implementation = implementation.read_text(encoding="utf-8")
        current_workflow = project_workflow.read_text(encoding="utf-8")
        legacy_implementation = "\n".join((
            "<!-- MERIDIAN:BEGIN capability=task-worktree-boundary v4 -->",
            "The coordinator runs `meridian worktree prepare` before starting this worker",
            "and passes its returned branch, absolute worktree path, primary checkout, and",
            "worktree root as launch inputs. Start in that exact existing directory; do not",
            "use host automatic isolation or create another checkout. Before reading the",
            "task, implementation files, or diff, run `meridian worktree check <TASK-ID>",
            "--project <primary-checkout> --format json`. Any blocked",
            "result stops all task work and preserves both checkouts. Run every later read,",
            "implementation, validation, status, and handoff operation in the same verified",
            "worktree, never the primary checkout.",
            "<!-- MERIDIAN:END -->",
            "",
        ))
        legacy_workflow = "\n".join((
            "<!-- MERIDIAN:BEGIN capability=bounded-worktree-lifecycle v3 -->",
            "The coordinator runs `meridian worktree prepare` before creating an",
            "implementer, reviewer, or remediation session and passes the returned existing",
            "path, branch, primary checkout, and worktree root as durable launch inputs.",
            "Every worker starts in that exact directory and runs read-only `meridian",
            "worktree check` before any task, handoff, implementation, or diff read. Hosts",
            "must not create a substitute checkout. Integration uses `meridian worktree",
            "integrate stage`, separately recorded candidate validation, and `integrate",
            "finalize` or `integrate abort`; verified post-push cleanup uses `meridian",
            "worktree cleanup`. See `docs/WORKTREE_LIFECYCLE.md`.",
            "Absolute paths are runtime launch inputs only. A handoff or other tracked",
            "record that names the worktree uses the `handoff_worktree` value returned by",
            "`meridian worktree prepare`, the path relative to the worktree root, never an",
            "absolute path.",
            "<!-- MERIDIAN:END -->",
            "",
        ))
        previous_implementation = re.sub(
            r"<!-- MERIDIAN:BEGIN capability=task-worktree-boundary v10 -->.*?<!-- MERIDIAN:END -->\n",
            legacy_implementation,
            current_implementation,
            count=1,
            flags=re.DOTALL,
        )
        previous_workflow = re.sub(
            r"<!-- MERIDIAN:BEGIN capability=bounded-worktree-lifecycle v5 -->.*?<!-- MERIDIAN:END -->\n",
            legacy_workflow,
            current_workflow,
            count=1,
            flags=re.DOTALL,
        )
        self.assertNotEqual(previous_implementation, current_implementation)
        self.assertNotEqual(previous_workflow, current_workflow)
        for source, previous, relative in (
            (implementation, previous_implementation, Path("docs/workflows/IMPLEMENTATION.md")),
            (project_workflow, previous_workflow, Path("PROJECT_WORKFLOW.md")),
        ):
            source.write_text(previous, encoding="utf-8")
            (self.project / relative).write_text(previous, encoding="utf-8")
        (self.framework / "VERSION").write_text("1.1.53\n", encoding="utf-8")
        locked = self.run_cli("lock", "--mode", "governed-sdd")
        self.assertEqual(locked.returncode, 0, locked.stdout + locked.stderr)
        implementation.write_text(current_implementation, encoding="utf-8")
        project_workflow.write_text(current_workflow, encoding="utf-8")
        (self.framework / "VERSION").write_text("1.1.54\n", encoding="utf-8")
        return self.project / "docs/workflows/IMPLEMENTATION.md", self.project / "PROJECT_WORKFLOW.md"

    def install_entry_router(self, include_restart: bool = True) -> None:
        lifecycle_triggers = (
            "`Restart rejected <TASK-ID>`, " if include_restart else ""
        ) + "`Run lifecycle <TASK-ID>`, or `Accept <TASK-ID>`"
        router = (
            "# Project entry router\n\n"
            "- Status or design question: `docs/workflows/STATUS_DESIGN.md`.\n"
            "- `Proceed with <TASK-ID>`: `docs/workflows/IMPLEMENTATION.md`.\n"
            "- `Review <TASK-ID>`: `docs/workflows/REVIEW.md`.\n"
            "- `Address review <TASK-ID>`: `docs/workflows/REMEDIATION.md`.\n"
            f"- {lifecycle_triggers}: `docs/workflows/LIFECYCLE.md`.\n"
            "- Explicit audit: `docs/AUDIT_PROMPT_READ_ONLY.md`.\n"
        )
        router_path = self.project / meridian.ENTRY_ROUTER_PATH
        router_path.parent.mkdir(parents=True, exist_ok=True)
        router_path.write_text(router, encoding="utf-8")
        (self.project / meridian.ENTRY_ROUTER_MAP_PATH).write_text(
            json.dumps(meridian.ENTRY_ROUTER_ROUTES, indent=2) + "\n", encoding="utf-8"
        )
        for route, relative in meridian.ENTRY_ROUTER_ROUTES.items():
            target = self.project / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            text = target.read_text(encoding="utf-8") if target.is_file() else "# Routed procedure\n"
            missing = [
                token
                for token in meridian.ENTRY_ROUTER_SAFEGUARDS[route]
                if token not in text.lower()
            ]
            if missing:
                target.write_text(text.rstrip() + "\n\n" + " ".join(missing) + "\n", encoding="utf-8")
        for target, output in meridian.entry_router_outputs(self.project).items():
            (self.project / target).write_text(output, encoding="utf-8")

    def reset_project_to_installed_baseline(self) -> None:
        """Overwrite every managed project file with the exact content
        `.meridian/baselines/<installed version>` recorded at `lock` time,
        simulating a vanilla consumer that never diverged from its installed
        release — the premise `--stop-before-retirement`'s content-cap tests
        need, since `setUp()` otherwise leaves the real repository's own
        current AGENTS.md/CLAUDE.md in the project directory."""
        manifest = json.loads((self.project / ".meridian/manifest.json").read_text(encoding="utf-8"))
        baseline_root = self.project / ".meridian/baselines" / str(
            manifest.get("workflowBaselineVersion", manifest["frameworkVersion"])
        )
        for path in baseline_root.rglob("*"):
            if path.is_file():
                destination = self.project / path.relative_to(baseline_root)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, destination)

    def make_route_rule_physically_present(self, moved: str) -> None:
        """Insert the `route-rule` source marker literally into both
        AGENTS.md/CLAUDE.md and their recorded 1.1.0 baseline copies.

        `configure_long_lag_move_fixture` declares `route-rule` as a purely
        transient capability (task 036's own edge case: never physically
        written to any template, only proven via the migration ledger) so
        that its *first* test can exercise that narrow path. A real
        long-lag consumer like consumer project B instead has the marker literally present
        in its locked content the whole time. Tests that resume a capped
        upgrade to completion need that realistic shape: task 036's
        transient-source proof only consults the *currently pending*
        migration list, so it cannot see an establishing migration that a
        prior, already-applied capped run already consumed — a composition
        gap in task 036 itself, out of scope here, and irrelevant to consumer project B's
        real content."""
        manifest = json.loads((self.project / ".meridian/manifest.json").read_text(encoding="utf-8"))
        baseline_root = self.project / ".meridian/baselines" / str(
            manifest.get("workflowBaselineVersion", manifest["frameworkVersion"])
        )
        for relative in (Path("AGENTS.md"), Path("CLAUDE.md")):
            for root in (self.project, baseline_root):
                path = root / relative
                path.write_text(path.read_text(encoding="utf-8") + "\n" + moved + "\n", encoding="utf-8")

    def configure_long_lag_move_fixture(self) -> tuple[str, Path]:
        """Create a compact three-release add/move/retire transition.

        The installed v1.1.0 snapshot predates ``route-rule``.  Migration 001
        declares that marker for both entry points, migration 002 duplicates it
        into its managed home, and migration 003 retires the transient entry
        point copy.  The target templates intentionally contain only the
        compact router marker and the managed destination.
        """
        workflow = self.framework / "templates/workflows/governed-sdd"
        agents = workflow / "AGENTS.md"
        claude = workflow / "CLAUDE.md"
        router_v1 = (
            "<!-- MERIDIAN:BEGIN capability=entry-router v1 -->\n"
            "Read the entry-point procedures.\n<!-- MERIDIAN:END -->\n"
        )
        router_v2 = (
            "<!-- MERIDIAN:BEGIN capability=entry-router v2 -->\n"
            "Read the managed procedures.\n<!-- MERIDIAN:END -->\n"
        )
        moved = (
            "<!-- MERIDIAN:BEGIN capability=route-rule v1 -->\n"
            "Run the managed route rule.\n<!-- MERIDIAN:END -->"
        )
        agents.write_text("# Agent entry point\n\n" + router_v1, encoding="utf-8")
        claude.write_text("# Claude entry point\n\n" + router_v1, encoding="utf-8")
        target = workflow / "docs/workflows/IMPLEMENTATION.md"
        target.unlink()
        (self.project / "docs/workflows/IMPLEMENTATION.md").unlink()
        for path in (self.framework / "migrations").glob("*.json"):
            path.unlink()
        (self.framework / "VERSION").write_text("1.1.0\n", encoding="utf-8")
        self.assertEqual(self.run_cli("lock", "--mode", "governed-sdd").returncode, 0)

        agents.write_text("# Agent entry point\n\n" + router_v2, encoding="utf-8")
        claude.write_text("# Compact Claude router\n", encoding="utf-8")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# Implementation\n\n" + moved + "\n", encoding="utf-8")
        digest = meridian.marker_block_sha256(moved)

        establish = {
            "id": "001-establish-route-rule",
            "from": "1.1.0",
            "to": "1.1.1",
            "description": "test-only source marker introduction",
            "capability": "route-rule",
            "capabilityVersion": 1,
            "managedPaths": ["AGENTS.md", "CLAUDE.md"],
            "verification": ["test-only"],
        }
        (self.framework / "migrations/001-establish-route-rule.json").write_text(
            json.dumps(establish), encoding="utf-8"
        )
        moves = [
            {
                "stage": stage,
                "source": {
                    "path": source,
                    "capability": "route-rule",
                    "capabilityVersion": 1,
                    "markerSha256": digest,
                },
                "target": {
                    "path": "docs/workflows/IMPLEMENTATION.md",
                    "capability": "route-rule",
                    "capabilityVersion": 1,
                    "markerSha256": digest,
                },
            }
            for stage in ("additive", "retirement")
            for source in ("AGENTS.md", "CLAUDE.md")
        ]
        for identifier, version, stage in (
            ("002-add-route-rule", "1.1.2", "additive"),
            ("003-retire-route-rule", "1.1.3", "retirement"),
        ):
            record = {
                "id": identifier,
                "from": "1.1.1" if stage == "additive" else "1.1.2",
                "to": version,
                "description": "test-only capability move",
                "capabilityMoves": [move for move in moves if move["stage"] == stage],
                "managedPaths": ["AGENTS.md", "CLAUDE.md", "docs/workflows/IMPLEMENTATION.md"],
                "verification": ["test-only"],
            }
            if stage == "retirement":
                # Mirrors the real repository's command-triggers v1->v2 gap
                # (task 037): an ordinary marker version bump riding along
                # with the retirement migration, declared here so a capped
                # upgrade can gate it to this migration instead of pulling it
                # in unconditionally from the live template.
                record["capabilities"] = [{"capability": "entry-router", "capabilityVersion": 2}]
            (self.framework / "migrations" / f"{identifier}.json").write_text(
                json.dumps(record),
                encoding="utf-8",
            )
        (self.framework / "VERSION").write_text("1.1.3\n", encoding="utf-8")
        return moved, target

    def configure_version_split_fixture(self) -> None:
        for path in (self.framework / "migrations").glob("*.json"):
            path.unlink()
        migration = {
            "id": "001-initial-baseline",
            "from": "1.0.0",
            "to": "1.1.0",
            "description": "test-only initial baseline",
            "managedPaths": ["PROJECT_WORKFLOW.md"],
            "verification": ["test-only"],
        }
        (self.framework / "migrations/001-initial-baseline.json").write_text(
            json.dumps(migration), encoding="utf-8"
        )
        (self.framework / "VERSION").write_text("1.1.0\n", encoding="utf-8")
        locked = self.run_cli("lock", "--mode", "governed-sdd")
        self.assertEqual(locked.returncode, 0, locked.stdout + locked.stderr)

    def add_version_split_migration(self) -> None:
        migration = {
            "id": "002-next-baseline",
            "from": "1.1.0",
            "to": "1.1.1",
            "description": "test-only next baseline",
            "managedPaths": ["PROJECT_WORKFLOW.md"],
            "verification": ["test-only"],
        }
        (self.framework / "migrations/002-next-baseline.json").write_text(
            json.dumps(migration), encoding="utf-8"
        )
        workflow = self.framework / "templates/workflows/governed-sdd/PROJECT_WORKFLOW.md"
        workflow.write_text(
            workflow.read_text(encoding="utf-8") + "\nVersion split marker.\n",
            encoding="utf-8",
        )
        (self.framework / "VERSION").write_text("1.1.1\n", encoding="utf-8")

    def test_upgrade_crosses_a_long_lag_capability_move_and_preserves_entry_points(self) -> None:
        moved, target = self.configure_long_lag_move_fixture()
        agents = self.project / "AGENTS.md"
        agents.write_text(agents.read_text(encoding="utf-8") + "\nProject-owned agent text.\n", encoding="utf-8")
        pointer = self.project / "CLAUDE.md"
        pointer.write_text(
            "<!-- MERIDIAN:CLAUDE-AGENTS-POINTER v1 -->\n\n# Project Claude entry point\n",
            encoding="utf-8",
        )

        checked = self.run_cli("upgrade", "--check")
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertIn("APPEND-RETIRE-MARKERS AGENTS.md", checked.stdout)
        self.assertIn("POINTER-VERIFIED CLAUDE.md", checked.stdout)

        applied = self.run_cli("upgrade", "--apply")
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        self.assertIn("Project-owned agent text.", agents.read_text(encoding="utf-8"))
        self.assertNotIn("capability=route-rule", agents.read_text(encoding="utf-8"))
        self.assertEqual(pointer.read_text(encoding="utf-8"), "<!-- MERIDIAN:CLAUDE-AGENTS-POINTER v1 -->\n\n# Project Claude entry point\n")
        self.assertEqual(target.read_text(encoding="utf-8"), "# Implementation\n\n" + moved + "\n")

    def test_upgrade_blocks_a_long_lag_move_with_a_modified_or_duplicated_source_marker(self) -> None:
        moved, _target = self.configure_long_lag_move_fixture()
        agents = self.project / "AGENTS.md"
        original = agents.read_text(encoding="utf-8")
        agents.write_text(original + "\n" + moved + "\n" + moved + "\n", encoding="utf-8")

        checked = self.run_cli("upgrade", "--check")
        self.assertEqual(checked.returncode, 2, checked.stdout + checked.stderr)
        self.assertIn("CONFLICT AGENTS.md", checked.stdout)
        applied = self.run_cli("upgrade", "--apply")
        self.assertEqual(applied.returncode, 2, applied.stdout + applied.stderr)
        self.assertEqual(agents.read_text(encoding="utf-8"), original + "\n" + moved + "\n" + moved + "\n")

        modified = moved.replace("Run the managed route rule.", "Run the locally modified route rule.")
        agents.write_text(original + "\n" + modified + "\n", encoding="utf-8")
        checked_modified = self.run_cli("upgrade", "--check")
        self.assertEqual(checked_modified.returncode, 2, checked_modified.stdout + checked_modified.stderr)
        applied_modified = self.run_cli("upgrade", "--apply")
        self.assertEqual(applied_modified.returncode, 2, applied_modified.stdout + applied_modified.stderr)
        self.assertEqual(agents.read_text(encoding="utf-8"), original + "\n" + modified + "\n")

    def test_stop_before_retirement_caps_the_plan_before_the_retirement_migration(self) -> None:
        self.configure_long_lag_move_fixture()
        self.reset_project_to_installed_baseline()
        agents = self.project / "AGENTS.md"
        original_agents = agents.read_text(encoding="utf-8")
        pointer = self.project / "CLAUDE.md"
        pointer.write_text(
            "<!-- MERIDIAN:CLAUDE-AGENTS-POINTER v1 -->\n\n# Project Claude entry point\n",
            encoding="utf-8",
        )

        checked = self.run_cli("upgrade", "--check", "--stop-before-retirement")
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertIn("Meridian 1.1.0 -> 1.1.2", checked.stdout)
        self.assertIn("MIGRATION 001-establish-route-rule", checked.stdout)
        self.assertIn("MIGRATION 002-add-route-rule", checked.stdout)
        self.assertNotIn("MIGRATION 003-retire-route-rule", checked.stdout)
        self.assertNotIn("APPEND-RETIRE-MARKERS", checked.stdout)
        self.assertNotIn("RETIRE-MARKERS", checked.stdout)

        applied = self.run_cli("upgrade", "--apply", "--stop-before-retirement")
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)

        # AGENTS.md must survive byte-for-byte: route-rule is a purely
        # declared, transient capability (never physically present in any
        # template — task 036's exact scenario) that only migration 002
        # additively moves into docs/workflows/IMPLEMENTATION.md, and the
        # undeclared-in-this-migration entry-router bump the live template
        # already carries must not leak in either — it is declared against
        # the excluded, capped-out 003, exactly like the real
        # command-triggers gap this task fixes.
        self.assertEqual(agents.read_text(encoding="utf-8"), original_agents)
        self.assertNotIn("entry-router v2", agents.read_text(encoding="utf-8"))
        self.assertEqual(
            pointer.read_text(encoding="utf-8"),
            "<!-- MERIDIAN:CLAUDE-AGENTS-POINTER v1 -->\n\n# Project Claude entry point\n",
        )

        implementation = self.project / "docs/workflows/IMPLEMENTATION.md"
        self.assertIn("capability=route-rule v1", implementation.read_text(encoding="utf-8"))

        manifest = json.loads((self.project / ".meridian/manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["frameworkVersion"], "1.1.2")
        self.assertEqual(
            manifest["appliedMigrations"],
            ["001-establish-route-rule", "002-add-route-rule"],
        )

    def test_stop_before_retirement_upgrade_can_later_complete_in_full(self) -> None:
        moved, target = self.configure_long_lag_move_fixture()
        self.reset_project_to_installed_baseline()
        self.make_route_rule_physically_present(moved)
        (self.project / "CLAUDE.md").write_text(
            "<!-- MERIDIAN:CLAUDE-AGENTS-POINTER v1 -->\n\n# Project Claude entry point\n",
            encoding="utf-8",
        )
        self.assertEqual(self.run_cli("upgrade", "--apply", "--stop-before-retirement").returncode, 0)

        # A plain check (no flag) now sees the remaining migration as pending,
        # with no false conflict from the intermediate stopping point.
        resumed_check = self.run_cli("upgrade", "--check")
        self.assertEqual(resumed_check.returncode, 0, resumed_check.stdout + resumed_check.stderr)
        self.assertIn("Meridian 1.1.2 -> 1.1.3", resumed_check.stdout)
        self.assertIn("MIGRATION 003-retire-route-rule", resumed_check.stdout)

        resumed_apply = self.run_cli("upgrade", "--apply")
        self.assertEqual(resumed_apply.returncode, 0, resumed_apply.stdout + resumed_apply.stderr)
        agents = self.project / "AGENTS.md"
        self.assertNotIn("capability=route-rule", agents.read_text(encoding="utf-8"))
        self.assertEqual(target.read_text(encoding="utf-8"), "# Implementation\n\n" + moved + "\n")
        manifest = json.loads((self.project / ".meridian/manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["frameworkVersion"], "1.1.3")
        self.assertEqual(
            manifest["appliedMigrations"],
            ["001-establish-route-rule", "002-add-route-rule", "003-retire-route-rule"],
        )

    def test_stop_before_retirement_is_a_noop_with_no_pending_retirement(self) -> None:
        moved, _target = self.configure_long_lag_move_fixture()
        self.reset_project_to_installed_baseline()
        self.make_route_rule_physically_present(moved)
        (self.project / "CLAUDE.md").write_text(
            "<!-- MERIDIAN:CLAUDE-AGENTS-POINTER v1 -->\n\n# Project Claude entry point\n",
            encoding="utf-8",
        )
        self.assertEqual(self.run_cli("upgrade", "--apply", "--stop-before-retirement").returncode, 0)
        self.assertEqual(self.run_cli("upgrade", "--apply").returncode, 0)

        # Every migration, including the retirement one, is now applied; a
        # further capped run has nothing left to cap and must behave exactly
        # like a plain, already-current check.
        plain = self.run_cli("upgrade", "--check")
        capped = self.run_cli("upgrade", "--check", "--stop-before-retirement")
        self.assertEqual(plain.returncode, 0, plain.stdout + plain.stderr)
        self.assertEqual(plain.stdout, capped.stdout)

    def test_lock_rejects_a_prerelease_framework_version_without_writing(self) -> None:
        (self.framework / "VERSION").write_text("1.2.0-rc.1\n", encoding="utf-8")

        locked = self.run_cli("lock", "--mode", "governed-sdd")

        self.assertNotEqual(locked.returncode, 0)
        self.assertIn("prerelease", locked.stderr)
        self.assertIn("1.2.0-rc.1", locked.stderr)
        self.assertFalse((self.project / ".meridian").exists())

    def test_upgrade_apply_rejects_a_prerelease_target_before_touching_files(self) -> None:
        self.assertEqual(self.run_cli("lock", "--mode", "governed-sdd").returncode, 0)
        manifest_path = self.project / ".meridian/manifest.json"
        manifest_before = manifest_path.read_bytes()
        workflow = self.framework / "templates/workflows/governed-sdd/PROJECT_WORKFLOW.md"
        workflow.write_text(workflow.read_text(encoding="utf-8") + "\nPrerelease marker.\n", encoding="utf-8")
        project_workflow = self.project / "PROJECT_WORKFLOW.md"
        workflow_before = project_workflow.read_bytes()
        (self.framework / "VERSION").write_text("1.2.0-rc.1\n", encoding="utf-8")

        applied = self.run_cli("upgrade", "--apply")

        self.assertNotEqual(applied.returncode, 0)
        self.assertIn("prerelease", applied.stderr)
        self.assertEqual(manifest_path.read_bytes(), manifest_before)
        self.assertEqual(project_workflow.read_bytes(), workflow_before)

    def test_build_metadata_is_accepted_but_never_persisted(self) -> None:
        (self.framework / "VERSION").write_text("1.1.0+dev.5\n", encoding="utf-8")

        locked = self.run_cli("lock", "--mode", "governed-sdd")

        self.assertEqual(locked.returncode, 0, locked.stderr)
        manifest_text = (self.project / ".meridian/manifest.json").read_text(encoding="utf-8")
        self.assertEqual(json.loads(manifest_text)["frameworkVersion"], "1.1.0")
        self.assertNotIn("+dev", manifest_text)

    def test_version_flag_prints_full_semver(self) -> None:
        for raw in ("1.2.0", "1.2.0-rc.1", "1.2.0-rc.1+build.7", "1.2.0+build.7"):
            (self.framework / "VERSION").write_text(raw + "\n", encoding="utf-8")
            shown = subprocess.run(
                [sys.executable, str(CLI), "--framework-root", str(self.framework), "--version"],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(shown.returncode, 0, shown.stderr)
            self.assertEqual(shown.stdout.strip(), raw)

    def test_parse_semver_separates_prerelease_and_build(self) -> None:
        parsed = meridian.parse_semver("1.2.3-rc.1+build.9")
        self.assertEqual((parsed.major, parsed.minor, parsed.patch), (1, 2, 3))
        self.assertEqual((parsed.prerelease, parsed.build), ("rc.1", "build.9"))
        for invalid in ("1.2", "1.2.3-", "01.2.3", "v1.2.3", "1.2.3+"):
            with self.assertRaises(meridian.MeridianError):
                meridian.parse_semver(invalid)

    def test_lock_and_apply_clean_template_upgrade(self) -> None:
        locked = self.run_cli("lock", "--mode", "governed-sdd")
        self.assertEqual(locked.returncode, 0, locked.stderr)

        workflow = self.framework / "templates/workflows/governed-sdd/PROJECT_WORKFLOW.md"
        workflow.write_text(workflow.read_text(encoding="utf-8") + "\nUpgrade marker.\n", encoding="utf-8")
        (self.framework / "VERSION").write_text("1.1.1\n", encoding="utf-8")

        checked = self.run_cli("upgrade", "--check")
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertIn("REPLACE  PROJECT_WORKFLOW.md", checked.stdout)

        applied = self.run_cli("upgrade", "--apply")
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertIn("Upgrade marker.", (self.project / "PROJECT_WORKFLOW.md").read_text(encoding="utf-8"))
        manifest = json.loads((self.project / ".meridian/manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["frameworkVersion"], "1.1.1")
        self.assertEqual(
            manifest["appliedMigrations"],
            [
                "001-review-remediation-record",
                "002-lifecycle-orchestration",
                "003-framework-updater",
                "004-validation-scoping",
            ],
        )
        baselines = sorted(path.name for path in (self.project / ".meridian/baselines").iterdir())
        self.assertEqual(baselines, ["1.1.1"], "stale 1.1.0 baseline should be pruned after upgrade")

        workflow.write_text(workflow.read_text(encoding="utf-8") + "\nSecond upgrade marker.\n", encoding="utf-8")
        (self.framework / "VERSION").write_text("1.1.2\n", encoding="utf-8")
        second_apply = self.run_cli("upgrade", "--apply")
        self.assertEqual(second_apply.returncode, 0, second_apply.stderr)
        baselines_after_second = sorted(
            path.name for path in (self.project / ".meridian/baselines").iterdir()
        )
        self.assertEqual(
            baselines_after_second,
            ["1.1.2"],
            "only the current workflowBaselineVersion's baseline should remain after a second upgrade",
        )

    def test_cli_only_upgrade_advances_framework_without_rekeying_baseline(self) -> None:
        self.configure_version_split_fixture()
        baseline_root = self.project / ".meridian/baselines/1.1.0"
        baseline_before = {
            path.relative_to(baseline_root): path.read_bytes()
            for path in baseline_root.rglob("*")
            if path.is_file()
        }
        manifest_path = self.project / ".meridian/manifest.json"
        manifest_before = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest_before["workflowBaselineVersion"], "1.1.0")

        (self.framework / "VERSION").write_text("1.1.1\n", encoding="utf-8")
        checked = self.run_cli("upgrade", "--check")
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertIn("Meridian 1.1.0 -> 1.1.0", checked.stdout)
        self.assertIn(
            "Framework: 1.1.0 -> 1.1.1 (CLI-only; no baseline change)",
            checked.stdout,
        )
        self.assertNotIn("MIGRATION ", checked.stdout)
        self.assertNotIn("CONFLICT ", checked.stdout)
        self.assertTrue(
            all(line.startswith("KEEP") for line in checked.stdout.splitlines()[2:]),
            checked.stdout,
        )

        applied = self.run_cli("upgrade", "--apply")
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        manifest_after = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest_after["frameworkVersion"], "1.1.1")
        self.assertEqual(manifest_after["workflowBaselineVersion"], "1.1.0")
        self.assertEqual(manifest_after["protocolVersion"], meridian.PROTOCOL_VERSION)
        self.assertEqual(
            {
                key: value
                for key, value in manifest_after.items()
                if key not in {"frameworkVersion", "protocolVersion"}
            },
            {
                key: value
                for key, value in manifest_before.items()
                if key not in {"frameworkVersion", "protocolVersion"}
            },
        )
        self.assertEqual(
            {
                path.relative_to(baseline_root): path.read_bytes()
                for path in baseline_root.rglob("*")
                if path.is_file()
            },
            baseline_before,
        )
        self.assertEqual(
            sorted(path.name for path in baseline_root.parent.iterdir()),
            ["1.1.0"],
        )

        current = self.run_cli("upgrade", "--check")
        self.assertEqual(current.returncode, 0, current.stdout + current.stderr)
        self.assertIn("Framework: 1.1.1 -> 1.1.1", current.stdout)
        self.assertNotIn("CLI-only", current.stdout)
        self.assertNotIn("MIGRATION ", current.stdout)
        self.assertNotIn("CONFLICT ", current.stdout)

    def test_manifest_protocol_compatibility_for_upgrade_check_and_audit(self) -> None:
        self.assertEqual(self.run_cli("lock", "--mode", "governed-sdd").returncode, 0)
        manifest_path = self.project / ".meridian/manifest.json"
        commands = (
            ("upgrade --check", ("upgrade", "--check")),
            ("audit", ("audit", "--mode", "governed-sdd")),
        )
        cases = (
            ("newer", meridian.PROTOCOL_VERSION + 1, 2),
            ("equal", meridian.PROTOCOL_VERSION, 0),
            ("lower", meridian.PROTOCOL_VERSION - 1, 0),
            ("missing", None, 0),
        )

        for command_name, command in commands:
            for case_name, protocol_version, expected_returncode in cases:
                with self.subTest(command=command_name, protocol=case_name):
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    if protocol_version is None:
                        manifest.pop("protocolVersion", None)
                    else:
                        manifest["protocolVersion"] = protocol_version
                    manifest_path.write_text(
                        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )

                    result = self.run_cli(*command)
                    if command_name == "audit" and case_name != "newer":
                        expected_returncode = 1
                    self.assertEqual(
                        result.returncode,
                        expected_returncode,
                        result.stdout + result.stderr,
                    )
                    if case_name == "newer":
                        self.assertIn("update your Meridian checkout", result.stderr)

    def test_upgrade_apply_rejects_newer_protocol_before_touching_project(self) -> None:
        self.assertEqual(self.run_cli("lock", "--mode", "governed-sdd").returncode, 0)
        manifest_path = self.project / ".meridian/manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["protocolVersion"] = meridian.PROTOCOL_VERSION + 1
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        project_before = {
            path.relative_to(self.project): path.read_bytes()
            for path in self.project.rglob("*")
            if path.is_file()
        }

        applied = self.run_cli("upgrade", "--apply")

        self.assertEqual(applied.returncode, 2, applied.stdout + applied.stderr)
        self.assertIn("update your Meridian checkout", applied.stderr)
        self.assertEqual(
            {
                path.relative_to(self.project): path.read_bytes()
                for path in self.project.rglob("*")
                if path.is_file()
            },
            project_before,
        )

    def test_upgrade_apply_rewrites_lower_protocol_to_current(self) -> None:
        self.assertEqual(self.run_cli("lock", "--mode", "governed-sdd").returncode, 0)
        manifest_path = self.project / ".meridian/manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["protocolVersion"] = meridian.PROTOCOL_VERSION - 1
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        applied = self.run_cli("upgrade", "--apply")

        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        rewritten = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(rewritten["protocolVersion"], meridian.PROTOCOL_VERSION)

    def test_manifest_protocol_version_must_be_an_integer(self) -> None:
        self.assertEqual(self.run_cli("lock", "--mode", "governed-sdd").returncode, 0)
        manifest_path = self.project / ".meridian/manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["protocolVersion"] = "1"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        checked = self.run_cli("upgrade", "--check")

        self.assertEqual(checked.returncode, 2, checked.stdout + checked.stderr)
        self.assertIn("manifest protocolVersion must be an integer", checked.stderr)

    def test_migration_upgrade_advances_and_rekeys_workflow_baseline(self) -> None:
        self.configure_version_split_fixture()
        self.add_version_split_migration()

        checked = self.run_cli("upgrade", "--check")
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertIn("Meridian 1.1.0 -> 1.1.1", checked.stdout)
        self.assertIn("Framework: 1.1.0 -> 1.1.1", checked.stdout)
        self.assertIn("MIGRATION 002-next-baseline", checked.stdout)

        applied = self.run_cli("upgrade", "--apply")
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        manifest = json.loads(
            (self.project / ".meridian/manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["frameworkVersion"], "1.1.1")
        self.assertEqual(manifest["workflowBaselineVersion"], "1.1.1")
        self.assertEqual(
            sorted(path.name for path in (self.project / ".meridian/baselines").iterdir()),
            ["1.1.1"],
        )

    def test_upgrade_from_1_2_7_reports_migration_062(self) -> None:
        (self.framework / "VERSION").write_text("1.2.7\n", encoding="utf-8")
        locked = self.run_cli("lock", "--mode", "governed-sdd")
        self.assertEqual(locked.returncode, 0, locked.stdout + locked.stderr)

        (self.framework / "VERSION").write_text("1.2.8\n", encoding="utf-8")
        checked = self.run_cli("upgrade", "--check")

        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertIn("Meridian 1.2.7 -> 1.2.8", checked.stdout)
        self.assertIn("MIGRATION 062-primary-project-declaration-and-review-authority", checked.stdout)

    def test_upgrade_migrates_a_tracked_legacy_budget_file_only_on_apply(self) -> None:
        (self.framework / "VERSION").write_text("1.2.8\n", encoding="utf-8")
        subprocess.run(("git", "init", str(self.project)), check=True, capture_output=True, text=True)
        locked = self.run_cli("lock", "--mode", "governed-sdd")
        self.assertEqual(locked.returncode, 0, locked.stdout + locked.stderr)
        legacy = self.project / ".meridian/budget.json"
        legacy.write_text('{"TASK-001:1": {"diagnostic": 1}}\n', encoding="utf-8")
        subprocess.run(("git", "-C", str(self.project), "add", "."), check=True, capture_output=True, text=True)
        subprocess.run(
            ("git", "-C", str(self.project), "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
             "commit", "-m", "legacy budget"),
            check=True, capture_output=True, text=True,
        )

        checked = self.run_cli("upgrade", "--check")
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertIn("MIGRATE  .meridian/budget.json", checked.stdout)
        self.assertEqual(
            subprocess.run(("git", "-C", str(self.project), "status", "--porcelain"),
                           check=True, capture_output=True, text=True).stdout,
            "",
        )

        applied = self.run_cli("upgrade", "--apply")
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        self.assertIn("commit its deletion", applied.stderr)
        self.assertFalse(legacy.exists())
        self.assertIn("D  .meridian/budget.json", subprocess.run(
            ("git", "-C", str(self.project), "status", "--porcelain"),
            check=True, capture_output=True, text=True,
        ).stdout)

    def test_legacy_manifest_uses_framework_version_as_baseline_fallback(self) -> None:
        self.configure_version_split_fixture()
        manifest_path = self.project / ".meridian/manifest.json"
        legacy_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        del legacy_manifest["workflowBaselineVersion"]
        manifest_path.write_text(
            json.dumps(legacy_manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        self.add_version_split_migration()

        checked = self.run_cli("upgrade", "--check")
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertIn("MIGRATION 002-next-baseline", checked.stdout)
        applied = self.run_cli("upgrade", "--apply")
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["frameworkVersion"], "1.1.1")
        self.assertEqual(manifest["workflowBaselineVersion"], "1.1.1")

    def test_spike_blueprint_upgrade_preserves_consumer_text_and_task_records(self) -> None:
        blueprint = self.framework / "templates/workflows/governed-sdd/tasks/TASK_BLUEPRINT.md"
        current = blueprint.read_text(encoding="utf-8")
        previous = (ROOT / "tests/fixtures/task-blueprint-v15.md").read_text(encoding="utf-8")
        self.assertIn("capability=task-blueprint v15", previous)
        blueprint.write_text(previous, encoding="utf-8")
        (self.framework / "VERSION").write_text("1.2.11\n", encoding="utf-8")
        self.copy_governed_templates()
        self.assertEqual(self.run_cli("lock", "--mode", "governed-sdd").returncode, 0)
        installed = self.project / "tasks/TASK_BLUEPRINT.md"
        installed.write_text(previous + "\nConsumer-owned task note.\n", encoding="utf-8")
        records = {}
        for status in ("IN_PROGRESS", "ANSWERED", "INCONCLUSIVE"):
            record = self.project / "tasks" / f"probe-{status}.md"
            records[record] = f"Class: SPIKE\nStatus: {status}\n" + previous
            record.write_text(records[record], encoding="utf-8")
        blueprint.write_text(current, encoding="utf-8")
        (self.framework / "VERSION").write_text("1.2.12\n", encoding="utf-8")
        checked = self.run_cli("upgrade", "--check")
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertIn("MIGRATION 065-spike-blueprint-worktree-closure", checked.stdout)
        applied = self.run_cli("upgrade", "--apply")
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        upgraded = installed.read_text(encoding="utf-8")
        self.assertEqual(upgraded, current + "\nConsumer-owned task note.\n")
        self.assertNotIn("committed directly to `main`", upgraded)
        self.assertNotIn("Branch:      throwaway, never merged", upgraded)
        self.assertIn("probe code is never merged or pushed", upgraded)
        self.assertIn("ordinary governed worktree closure and integration", upgraded)
        for record, content in records.items():
            self.assertEqual(record.read_text(encoding="utf-8"), content)
        audit = self.run_cli("audit")
        # This legacy lock fixture has no capabilityProfiles; audit reports
        # UNVERIFIED for that declaration independently of marker integrity.
        self.assertIn("tasks/TASK_BLUEPRINT.md: capability=task-blueprint v18 matches the released text", audit.stdout)
        self.assertNotIn("FAIL           marker-integrity", audit.stdout)
        self.assertNotIn("DRIFT", audit.stdout)
        repeated = self.run_cli("upgrade", "--check")
        self.assertEqual(repeated.returncode, 0, repeated.stdout + repeated.stderr)
        self.assertNotIn("CONFLICT", repeated.stdout)

    def test_clean_upgrade_installs_host_impact_declarations_and_preserves_consumer_text(self) -> None:
        """Migration 043 upgrades the two managed host-impact files without
        replacing consumer-owned text outside their protected regions."""
        (self.framework / "VERSION").write_text("1.1.39\n", encoding="utf-8")
        self.assertEqual(self.run_cli("lock", "--mode", "governed-sdd").returncode, 0)

        blueprint = self.framework / "templates/workflows/governed-sdd/tasks/TASK_BLUEPRINT.md"
        current = blueprint.read_text(encoding="utf-8")
        declaration = current.split("\n## Host impact\n", 1)[1].split("\n## Goal\n", 1)[0]
        previous = current.replace("capability=task-blueprint v18", "capability=task-blueprint v11", 1)
        previous = previous.replace("\n## Host impact\n" + declaration, "", 1)

        installed_baseline = self.project / ".meridian/baselines/1.1.39"
        for root in (self.project, installed_baseline):
            path = root / "tasks/TASK_BLUEPRINT.md"
            path.write_text(previous, encoding="utf-8")
        (self.project / "tasks/TASK_BLUEPRINT.md").write_text(
            previous + "\nProject-owned task note.\n", encoding="utf-8"
        )

        implementation = self.framework / "templates/workflows/governed-sdd/docs/workflows/IMPLEMENTATION.md"
        routed = implementation.read_text(encoding="utf-8")
        routing = routed.split(
            "<!-- MERIDIAN:BEGIN capability=host-impact-routing v2 -->", 1
        )[1].split("<!-- MERIDIAN:END -->", 1)[0]
        previous_routed = routed.replace(
            "<!-- MERIDIAN:BEGIN capability=host-impact-routing v2 -->" + routing + "<!-- MERIDIAN:END -->\n\n",
            "",
            1,
        )
        for root in (self.project, installed_baseline):
            path = root / "docs/workflows/IMPLEMENTATION.md"
            path.write_text(previous_routed, encoding="utf-8")

        (self.framework / "VERSION").write_text("1.1.40\n", encoding="utf-8")
        checked = self.run_cli("upgrade", "--check")
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertIn("MIGRATION 043-host-impact-task-declaration", checked.stdout)

        applied = self.run_cli("upgrade", "--apply")
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        upgraded_blueprint = (self.project / "tasks/TASK_BLUEPRINT.md").read_text(encoding="utf-8")
        self.assertIn("capability=task-blueprint v18", upgraded_blueprint)
        self.assertIn("Classification: NOT_APPLICABLE", upgraded_blueprint)
        self.assertIn("Classification: REQUIRED", upgraded_blueprint)
        self.assertIn("Project-owned task note.", upgraded_blueprint)
        upgraded_routing = (self.project / "docs/workflows/IMPLEMENTATION.md").read_text(encoding="utf-8")
        self.assertIn("capability=host-impact-routing v2", upgraded_routing)
        self.assertIn("return `BLOCKED HOST_IMPACT_DECLARATION_INVALID`", upgraded_routing)
        manifest = json.loads((self.project / ".meridian/manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["frameworkVersion"], "1.1.40")
        self.assertEqual(manifest["appliedMigrations"][-1], "043-host-impact-task-declaration")

    def test_clean_upgrade_installs_isolated_task_worktree_contract(self) -> None:
        """Migration 045 delivers the worktree contract to an existing adopter."""
        workflow = self.framework / "templates/workflows/governed-sdd"
        relative_paths = (
            "PROJECT_WORKFLOW.md",
            "docs/AUDIT_PROMPT_READ_ONLY.md",
            "docs/CODE_REVIEW_PROMPT.md",
            "docs/COMPLETION_REPORT_TEMPLATE.md",
            "docs/LIFECYCLE_ORCHESTRATION.md",
            "docs/PULL_REQUEST_POLICY.md",
            "docs/workflows/IMPLEMENTATION.md",
            "docs/workflows/LIFECYCLE.md",
            "docs/workflows/REMEDIATION.md",
            "docs/workflows/REVIEW.md",
        )
        current = {
            relative: (workflow / relative).read_text(encoding="utf-8")
            for relative in relative_paths
        }
        new_capabilities = (
            "task-worktree-boundary",
            "task-worktree-remediation",
            "task-worktree-review",
            "task-worktree-integration",
            "task-worktree-review-procedure",
            "task-worktree-lifecycle",
        )

        for relative, text in current.items():
            previous = text
            for capability in new_capabilities:
                previous = re.sub(
                    rf"<!-- MERIDIAN:BEGIN capability={capability} v[123] -->.*?<!-- MERIDIAN:END -->\n?",
                    "",
                    previous,
                    flags=re.DOTALL,
                )
            previous = previous.replace("capability=roles v3", "capability=roles v1")
            previous = previous.replace("capability=git-workflow v5", "capability=git-workflow v1")
            previous = previous.replace("capability=audit-prompt v3", "capability=audit-prompt v1")
            previous = previous.replace(
                "capability=lifecycle-orchestration v6",
                "capability=lifecycle-orchestration v3",
            )
            previous = re.sub(
                r"<!-- MERIDIAN:BEGIN capability=task-worktree-handoff v3 -->.*?<!-- MERIDIAN:END -->",
                "- Branch: `<task-branch>`\n"
                "- Implementation commit: `<commit SHA>`\n"
                "- Base `main` commit: `<commit SHA>`",
                previous,
                flags=re.DOTALL,
            )
            for root in (workflow, self.project):
                (root / relative).write_text(previous, encoding="utf-8")

        (self.framework / "VERSION").write_text("1.1.41\n", encoding="utf-8")
        self.assertEqual(self.run_cli("lock", "--mode", "governed-sdd").returncode, 0)
        project_workflow = self.project / "PROJECT_WORKFLOW.md"
        project_workflow.write_text(
            project_workflow.read_text(encoding="utf-8") + "\nConsumer-owned note.\n",
            encoding="utf-8",
        )

        for relative, text in current.items():
            (workflow / relative).write_text(text, encoding="utf-8")
        (self.framework / "VERSION").write_text("1.1.48\n", encoding="utf-8")

        checked = self.run_cli("upgrade", "--check")
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertIn("MIGRATION 045-isolated-task-worktrees", checked.stdout)
        self.assertIn("MIGRATION 046-integration-validation-evidence-reuse", checked.stdout)
        self.assertIn("MIGRATION 047-codex-worktree-access", checked.stdout)
        applied = self.run_cli("upgrade", "--apply")
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        self.assertIn("capability=git-workflow v14", project_workflow.read_text(encoding="utf-8"))
        self.assertIn("Consumer-owned note.", project_workflow.read_text(encoding="utf-8"))
        self.assertIn(
            "capability=task-worktree-boundary v10",
            (self.project / "docs/workflows/IMPLEMENTATION.md").read_text(encoding="utf-8"),
        )
        report = (self.project / "docs/COMPLETION_REPORT_TEMPLATE.md").read_text(encoding="utf-8")
        self.assertIn("never an absolute path", report)
        manifest = json.loads((self.project / ".meridian/manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["frameworkVersion"], "1.1.48")
        self.assertEqual(manifest["appliedMigrations"][-1], "051-bounded-worktree-lifecycle")
        audited = self.run_cli("audit", "--mode", "governed-sdd")
        self.assertEqual(audited.returncode, 1, audited.stdout + audited.stderr)
        self.assertIn("declaration/legacy-compatibility", audited.stdout)

    def test_clean_upgrade_installs_integration_evidence_reuse_contract(self) -> None:
        """Migration 046 upgrades every changed integration capability."""
        workflow = self.framework / "templates/workflows/governed-sdd"
        changed_paths = (
            "PROJECT_WORKFLOW.md",
            "docs/CODE_REVIEW_PROMPT.md",
            "docs/COMPLETION_REPORT_TEMPLATE.md",
            "docs/LIFECYCLE_ORCHESTRATION.md",
            "docs/PULL_REQUEST_POLICY.md",
            "docs/workflows/REVIEW.md",
        )
        current = {
            relative: (workflow / relative).read_text(encoding="utf-8")
            for relative in changed_paths
        }
        previous_versions = {
            "git-workflow": (8, 2),
            "lifecycle-orchestration": (7, 4),
            "task-worktree-review": (4, 1),
            "task-worktree-integration": (3, 1),
            "task-worktree-review-procedure": (5, 1),
            "task-worktree-handoff": (3, 1),
        }
        for relative, text in current.items():
            previous = text
            previous = re.sub(
                r"<!-- MERIDIAN:BEGIN capability=codex-worktree-access v\d+ -->.*?<!-- MERIDIAN:END -->\n?",
                "",
                previous,
                flags=re.DOTALL,
            )
            for capability, (new, old) in previous_versions.items():
                previous = previous.replace(
                    f"capability={capability} v{new}",
                    f"capability={capability} v{old}",
                )
            for root in (workflow, self.project):
                (root / relative).write_text(previous, encoding="utf-8")

        (self.framework / "VERSION").write_text("1.1.42\n", encoding="utf-8")
        self.assertEqual(self.run_cli("lock", "--mode", "governed-sdd").returncode, 0)
        project_workflow = self.project / "PROJECT_WORKFLOW.md"
        project_workflow.write_text(
            project_workflow.read_text(encoding="utf-8") + "\nConsumer-owned note.\n",
            encoding="utf-8",
        )

        for relative, text in current.items():
            (workflow / relative).write_text(text, encoding="utf-8")
        (self.framework / "VERSION").write_text("1.1.48\n", encoding="utf-8")

        checked = self.run_cli("upgrade", "--check")
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertIn("MIGRATION 046-integration-validation-evidence-reuse", checked.stdout)
        self.assertIn("MIGRATION 047-codex-worktree-access", checked.stdout)
        applied = self.run_cli("upgrade", "--apply")
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        self.assertIn("capability=git-workflow v14", project_workflow.read_text(encoding="utf-8"))
        self.assertIn("Consumer-owned note.", project_workflow.read_text(encoding="utf-8"))
        self.assertIn(
            "capability=task-worktree-handoff v5",
            (self.project / "docs/COMPLETION_REPORT_TEMPLATE.md").read_text(encoding="utf-8"),
        )
        manifest = json.loads((self.project / ".meridian/manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["workflowBaselineVersion"], "1.1.48")
        self.assertEqual(manifest["appliedMigrations"][-1], "051-bounded-worktree-lifecycle")

    def test_upgrade_replaces_conflicting_review_blocks_and_preserves_consumer_text(self) -> None:
        """Migration 050 replaces the distributed checkout conflict in place."""
        workflow = self.framework / "templates/workflows/governed-sdd"
        paths = (
            "PROJECT_WORKFLOW.md",
            "docs/CODE_REVIEW_PROMPT.md",
            "docs/LIFECYCLE_ORCHESTRATION.md",
            "docs/workflows/REVIEW.md",
        )
        current = {
            relative: (workflow / relative).read_text(encoding="utf-8")
            for relative in paths
        }
        legacy_handoff = """<!-- MERIDIAN:BEGIN capability=implementer-reviewer-handoff v1 -->
## Implementer-to-reviewer handoff

After validation, create the task commit and push the task branch once for each
review attempt. The completion handoff must record the branch name,
implementation commit, and base `main` commit. Leave the primary checkout
clean and on the task branch; do not switch back to `main`.

The reviewer-integrator uses that same primary checkout in a fresh agent session that did not write the implementation. If the reviewer session starts on clean `main`, run `git switch <task-branch>`. If the branch is missing locally, or a dirty checkout prevents switching, return `BLOCKED` with the exact condition.

For `Review: REQUIRED`, the reviewer must never push the task branch. On
`CHANGES_REQUESTED`, it commits only the review record and matching task/queue
transition to `IN_PROGRESS`; the implementer then resolves and pushes the next
review attempt. Before accepting, run `git merge-base --is-ancestor main
<task-branch>`. If it fails, do not mark the task `ACCEPTED`; return `BLOCKED`
with no fetch, rebase, non-fast-forward merge, or force-push recovery. If it
passes, create the local review-and-status `ACCEPTED` commit, switch to `main`,
fast-forward merge the task branch, push `main` exactly once, and delete the
local task branch. For `Review: NOT_REQUIRED`, the implementer performs the
same acceptance commit and main integration after validation. Owner acceptance
is status-only and does not automatically integrate the branch.
<!-- MERIDIAN:END -->"""
        legacy_preflight = """<!-- MERIDIAN:BEGIN capability=task-worktree-review-procedure v2 -->
This block supersedes the checkout, ancestry, integration, and cleanup steps in
the legacy handoff block above. The completion handoff also records the
absolute task-worktree path and current task commit. Stop the implementer and
leave that worktree clean before a fresh reviewer session uses it. Verify its
registered path, branch, HEAD, cleanliness, and handoff commits. Never switch
the primary checkout to the task branch or review concurrently with an
implementer. After approval, commit the review and `ACCEPTED` state on the task
branch, then use the serialized integration transaction in
`PROJECT_WORKFLOW.md`. The validated task commit must be an ancestor of task
HEAD, with only permitted lifecycle records in the intervening diff, and the
validated base must be an ancestor of the validated commit. Current `main` may have advanced; reuse
evidence, run the bounded gate, select full validation, or return `BLOCKED`
only through that transaction's deterministic decision. Independent review,
acceptance evidence, and forge gates remain mandatory. Cleanup removes the
worktree before the branch only after validated integration succeeds.
<!-- MERIDIAN:END -->"""

        previous = current.copy()
        previous["docs/workflows/REVIEW.md"] = re.sub(
            r"<!-- MERIDIAN:BEGIN capability=task-worktree-review-procedure v9 -->.*?<!-- MERIDIAN:END -->",
            legacy_preflight,
            previous["docs/workflows/REVIEW.md"],
            count=1,
            flags=re.DOTALL,
        )
        previous["docs/workflows/REVIEW.md"] = re.sub(
            r"<!-- MERIDIAN:BEGIN capability=implementer-reviewer-handoff v2 -->.*?<!-- MERIDIAN:END -->",
            legacy_handoff,
            previous["docs/workflows/REVIEW.md"],
            count=1,
            flags=re.DOTALL,
        )
        previous["docs/CODE_REVIEW_PROMPT.md"] = previous["docs/CODE_REVIEW_PROMPT.md"].replace(
            "capability=task-worktree-review v4", "capability=task-worktree-review v2"
        )
        previous["PROJECT_WORKFLOW.md"] = previous["PROJECT_WORKFLOW.md"].replace(
            "capability=git-workflow v9", "capability=git-workflow v4"
        )
        previous["docs/LIFECYCLE_ORCHESTRATION.md"] = previous[
            "docs/LIFECYCLE_ORCHESTRATION.md"
        ].replace("capability=lifecycle-orchestration v10", "capability=lifecycle-orchestration v5")

        for relative, text in previous.items():
            (workflow / relative).write_text(text, encoding="utf-8")
            (self.project / relative).write_text(text, encoding="utf-8")
        (self.framework / "VERSION").write_text("1.1.46\n", encoding="utf-8")
        locked = self.run_cli("lock", "--mode", "governed-sdd")
        self.assertEqual(locked.returncode, 0, locked.stdout + locked.stderr)

        review = self.project / "docs/workflows/REVIEW.md"
        review.write_text(
            review.read_text(encoding="utf-8") + "\nConsumer-owned review note.\n",
            encoding="utf-8",
        )
        for relative, text in current.items():
            (workflow / relative).write_text(text, encoding="utf-8")
        (self.framework / "VERSION").write_text("1.1.48\n", encoding="utf-8")

        checked = self.run_cli("upgrade", "--check")
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertIn("MIGRATION 050-review-worktree-preflight", checked.stdout)
        applied = self.run_cli("upgrade", "--apply")
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)

        upgraded = review.read_text(encoding="utf-8")
        self.assertIn("capability=implementer-reviewer-handoff v5", upgraded)
        self.assertIn("capability=task-worktree-review-procedure v13", upgraded)
        self.assertIn("Consumer-owned review note.", upgraded)
        self.assertNotIn("uses that same primary checkout", upgraded)
        self.assertNotIn("git switch <task-branch>", upgraded)
        manifest = json.loads((self.project / ".meridian/manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["frameworkVersion"], "1.1.48")
        self.assertEqual(manifest["appliedMigrations"][-1], "051-bounded-worktree-lifecycle")

    def test_upgrade_installs_codex_profile_recovery_across_a_cli_only_release(self) -> None:
        """Migration 053 reaches a baseline-1.1.49 project locked under CLI-only release 1.1.50."""
        recovery = re.compile(
            r"\n\nIf `meridian codex configure --check` reports `repair-required`.*?(?=<!-- MERIDIAN:END -->)",
            re.DOTALL,
        )
        for mode in ("governed-sdd", "lean-delivery"):
            with self.subTest(mode):
                shutil.rmtree(self.project)
                self.project.mkdir()
                workflow = self.framework / "templates/workflows" / mode
                for path in workflow.rglob("*"):
                    if path.is_file():
                        destination = self.project / path.relative_to(workflow)
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(path, destination)
                template = workflow / "PROJECT_WORKFLOW.md"
                current = template.read_text(encoding="utf-8")
                previous = recovery.sub("\n", current, count=1).replace(
                    "capability=codex-worktree-access v2", "capability=codex-worktree-access v1"
                )
                self.assertNotEqual(previous, current)
                template.write_text(previous, encoding="utf-8")
                (self.project / "PROJECT_WORKFLOW.md").write_text(previous, encoding="utf-8")
                (self.framework / "VERSION").write_text("1.1.50\n", encoding="utf-8")
                locked = self.run_cli("lock", "--mode", mode)
                self.assertEqual(locked.returncode, 0, locked.stdout + locked.stderr)
                manifest_path = self.project / ".meridian/manifest.json"
                locked_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                self.assertEqual(locked_manifest["frameworkVersion"], "1.1.50")
                self.assertEqual(locked_manifest["workflowBaselineVersion"], "1.1.49")
                project_workflow = self.project / "PROJECT_WORKFLOW.md"
                project_workflow.write_text(
                    project_workflow.read_text(encoding="utf-8") + "\nConsumer-owned note.\n", encoding="utf-8"
                )

                template.write_text(current, encoding="utf-8")
                (self.framework / "VERSION").write_text("1.1.51\n", encoding="utf-8")
                checked = self.run_cli("upgrade", "--check")
                self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
                self.assertIn("MIGRATION 053-codex-profile-repair-guidance", checked.stdout)
                applied = self.run_cli("upgrade", "--apply")
                self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
                upgraded = project_workflow.read_text(encoding="utf-8")
                self.assertIn("capability=codex-worktree-access v4", upgraded)
                self.assertIn("reports `repair-required`", upgraded)
                self.assertIn("Consumer-owned note.", upgraded)
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                self.assertEqual(manifest["frameworkVersion"], "1.1.51")
                self.assertEqual(manifest["workflowBaselineVersion"], "1.1.51")
                self.assertEqual(manifest["appliedMigrations"][-1], "053-codex-profile-repair-guidance")

    def test_upgrade_installs_manual_proceed_worktree_rule_and_preserves_consumer_text(self) -> None:
        implementation, project_workflow = self.configure_1_1_53_to_1_1_54_manual_proceed_upgrade()
        project_workflow.write_text(
            project_workflow.read_text(encoding="utf-8") + "\nConsumer-owned worktree note.\n",
            encoding="utf-8",
        )

        checked = self.run_cli("upgrade", "--check")
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertIn("MIGRATION 056-manual-governed-proceed-worktree", checked.stdout)
        applied = self.run_cli("upgrade", "--apply")
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)

        self.assertIn("capability=task-worktree-boundary v10", implementation.read_text(encoding="utf-8"))
        self.assertIn("**Manually triggered.**", implementation.read_text(encoding="utf-8"))
        upgraded_workflow = project_workflow.read_text(encoding="utf-8")
        self.assertIn("capability=bounded-worktree-lifecycle v5", upgraded_workflow)
        self.assertIn("Consumer-owned worktree note.", upgraded_workflow)
        manifest = json.loads((self.project / ".meridian/manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["workflowBaselineVersion"], "1.1.54")
        self.assertEqual(manifest["appliedMigrations"][-1], "056-manual-governed-proceed-worktree")

    def test_upgrade_reports_bounded_conflict_for_custom_implementation_procedure(self) -> None:
        implementation, _ = self.configure_1_1_53_to_1_1_54_manual_proceed_upgrade()
        customized = implementation.read_text(encoding="utf-8").replace(
            "The coordinator runs `meridian worktree prepare`",
            "Our coordinator runs `meridian worktree prepare`",
            1,
        )
        implementation.write_text(customized, encoding="utf-8")

        applied = self.run_cli("upgrade", "--apply")
        self.assertEqual(applied.returncode, 2, applied.stdout + applied.stderr)
        self.assertIn("CONFLICT docs/workflows/IMPLEMENTATION.md", applied.stdout)
        self.assertEqual(implementation.read_text(encoding="utf-8"), customized)

    def test_upgrade_installs_self_referential_handoff_rules_and_preserves_consumer_text(self) -> None:
        workflow = self.framework / "templates/workflows/governed-sdd"
        paths = (
            "docs/COMPLETION_REPORT_TEMPLATE.md",
            "docs/workflows/REVIEW.md",
        )
        current = {relative: (workflow / relative).read_text(encoding="utf-8") for relative in paths}
        previous = {
            relative: text.replace("task-worktree-handoff v5", "task-worktree-handoff v3").replace(
                "task-worktree-review-procedure v9", "task-worktree-review-procedure v6"
            )
            for relative, text in current.items()
        }
        for relative, text in previous.items():
            (workflow / relative).write_text(text, encoding="utf-8")
            destination = self.project / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(text, encoding="utf-8")
        (self.framework / "VERSION").write_text("1.1.54\n", encoding="utf-8")
        self.assertEqual(self.run_cli("lock", "--mode", "governed-sdd").returncode, 0)
        report = self.project / "docs/COMPLETION_REPORT_TEMPLATE.md"
        report.write_text(report.read_text(encoding="utf-8") + "\nConsumer-owned handoff note.\n", encoding="utf-8")

        for relative, text in current.items():
            (workflow / relative).write_text(text, encoding="utf-8")
        (self.framework / "VERSION").write_text("1.2.3\n", encoding="utf-8")
        checked = self.run_cli("upgrade", "--check")
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertIn("MIGRATION 057-self-referential-handoff-commits", checked.stdout)
        applied = self.run_cli("upgrade", "--apply")
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)

        upgraded_report = report.read_text(encoding="utf-8")
        self.assertIn("capability=task-worktree-handoff v5", upgraded_report)
        self.assertIn("created after this report", upgraded_report)
        self.assertIn("Consumer-owned handoff note.", upgraded_report)
        upgraded_review = (self.project / "docs/workflows/REVIEW.md").read_text(encoding="utf-8")
        self.assertIn("capability=task-worktree-review-procedure v13", upgraded_review)
        self.assertIn("resolve it to the registered task branch `HEAD`", upgraded_review)
        manifest = json.loads((self.project / ".meridian/manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["workflowBaselineVersion"], "1.1.55")
        self.assertEqual(manifest["appliedMigrations"][-1], "057-self-referential-handoff-commits")

    def test_1_4_0_template_capabilities_are_required(self) -> None:
        requirements = meridian.capability_requirements(ROOT)
        for capability in ("worktree-command-locations", "worktree-budget-retirement", "handoff-correction-redelivery"):
            with self.subTest(capability=capability):
                self.assertEqual(requirements[capability], (1, "070-worktree-template-delivery"))

    def test_pristine_1_3_0_upgrades_all_1_4_0_managed_text(self) -> None:
        # Frozen git archive of v1.3.0; works in shallow CI checkouts too.
        archive = ROOT / "tests/fixtures/release-1.3.0-upgrade.tar.gz"
        self.assertEqual(meridian.read_version(ROOT), "1.4.0")
        with tarfile.open(archive) as source:
            for mode in ("lean-delivery", "governed-sdd"):
                with self.subTest(mode=mode):
                    self.project = self.framework.parent / mode
                    self.project.mkdir()
                    prefix = f"templates/workflows/{mode}/"
                    for member in source.getmembers():
                        if member.isfile() and member.name.startswith(prefix):
                            relative = Path(member.name.removeprefix(prefix))
                            target = self.project / relative
                            target.parent.mkdir(parents=True, exist_ok=True)
                            target.write_bytes(source.extractfile(member).read())
                    # Lock against the actual 1.3.0 release, then upgrade with
                    # this checkout's real VERSION, templates, and migrations.
                    old_framework = self.framework.parent / f"release-{mode}"
                    with tarfile.open(archive) as old:
                        old.extractall(old_framework, filter="data")
                    def cli(framework, *arguments):
                        return subprocess.run(
                            [sys.executable, str(CLI), "--framework-root", str(framework),
                             *arguments, "--project", str(self.project)],
                            text=True, capture_output=True,
                        )
                    locked = cli(old_framework, "lock", "--mode", mode)
                    self.assertEqual(locked.returncode, 0, locked.stdout + locked.stderr)
                    checked = cli(ROOT, "upgrade", "--check")
                    self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
                    self.assertIn("MIGRATION 070-worktree-template-delivery", checked.stdout)
                    applied = cli(ROOT, "upgrade", "--apply")
                    self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
                    self.assertNotIn("CONFLICT", applied.stdout)
                    paths = ["PROJECT_WORKFLOW.md", "docs/WORKTREE_LIFECYCLE.md"]
                    if mode == "governed-sdd":
                        paths.append("docs/COMPLETION_REPORT_TEMPLATE.md")
                    for relative in paths:
                        expected = ROOT / "templates/workflows" / mode / relative
                        self.assertEqual((self.project / relative).read_bytes(), expected.read_bytes())
                    manifest = json.loads((self.project / ".meridian/manifest.json").read_text())
                    self.assertEqual(manifest["workflowBaselineVersion"], "1.4.0")
                    self.assertEqual(manifest["appliedMigrations"][-1], "070-worktree-template-delivery")

    def test_pristine_1_2_15_lean_upgrade_installs_task_close(self) -> None:
        workflow = self.framework / "templates/workflows/lean-delivery"
        paths = ("AGENTS.md", "CLAUDE.md", "PROJECT_WORKFLOW.md")
        current = {name: (workflow / name).read_text() for name in paths}
        old_closure = "When closure requires machine task state, run `meridian task transition <TASK-ID> DONE` in the task worktree after validation and before archiving the record, then commit the state file with the completion records. Never edit status or verdict fields by hand."
        for name in paths:
            text = current[name].replace("capability=git-workflow v14", "capability=git-workflow v13")
            text = re.sub(r"After validation, commit the completed task record and handoff, then run.*?with the validation evidence\.", old_closure, text)
            text = text.replace("capability=bounded-worktree-lifecycle v7", "capability=bounded-worktree-lifecycle v6").replace(
                "writer confirmation, except when the record is archived and state is DONE:\nskip execution start, commit staged closure records, then run worktree advance.",
                "writer confirmation.")
            (workflow / name).write_text(text)
        for path in workflow.rglob("*"):
            if path.is_file():
                destination = self.project / path.relative_to(workflow)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, destination)
        (self.framework / "VERSION").write_text("1.2.15\n")
        locked = self.run_cli("lock", "--mode", "lean-delivery")
        self.assertEqual(locked.returncode, 0, locked.stdout + locked.stderr)
        for name, text in current.items():
            (workflow / name).write_text(text)
        (self.framework / "VERSION").write_text("1.3.0\n")
        checked = self.run_cli("upgrade", "--check")
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertIn("MIGRATION 069-lean-task-close", checked.stdout)
        applied = self.run_cli("upgrade", "--apply")
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        for name, text in current.items():
            self.assertEqual((self.project / name).read_text(), text)
            self.assertIn("meridian task close <TASK-ID>", text)
        manifest = json.loads((self.project / ".meridian/manifest.json").read_text())
        self.assertEqual(manifest["workflowBaselineVersion"], "1.3.0")
        self.assertEqual(manifest["appliedMigrations"][-1], "069-lean-task-close")

    def test_upgrade_installs_lean_closure_procedure_and_preserves_consumer_text(self) -> None:
        workflow = self.framework / "templates/workflows/lean-delivery"
        paths = ("PROJECT_WORKFLOW.md", "AGENTS.md", "CLAUDE.md")
        current = {relative: (workflow / relative).read_text(encoding="utf-8") for relative in paths}
        previous = {
            relative: re.sub(
                r"\n<!-- MERIDIAN:BEGIN capability=git-workflow v9 -->.*?<!-- MERIDIAN:END -->\n",
                "\n",
                text,
                flags=re.DOTALL,
            )
            for relative, text in current.items()
        }
        for relative, text in previous.items():
            (workflow / relative).write_text(text, encoding="utf-8")
        for path in workflow.rglob("*"):
            if path.is_file():
                destination = self.project / path.relative_to(workflow)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, destination)
        (self.framework / "VERSION").write_text("1.2.3\n", encoding="utf-8")
        self.assertEqual(self.run_cli("lock", "--mode", "lean-delivery").returncode, 0)

        for relative, text in previous.items():
            self.assertEqual((self.project / relative).read_text(encoding="utf-8"), text)
        agents = self.project / "AGENTS.md"
        agents.write_text(agents.read_text(encoding="utf-8") + "\nConsumer-owned closure note.\n", encoding="utf-8")

        for relative, text in current.items():
            (workflow / relative).write_text(text, encoding="utf-8")
        (self.framework / "VERSION").write_text("1.2.4\n", encoding="utf-8")
        checked = self.run_cli("upgrade", "--check")
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertIn("MIGRATION 058-lean-closure-procedure", checked.stdout)
        applied = self.run_cli("upgrade", "--apply")
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)

        for relative in paths:
            upgraded = (self.project / relative).read_text(encoding="utf-8")
            self.assertIn("MERIDIAN:BEGIN capability=git-workflow v14", upgraded)
            self.assertIn("Task branches do not edit `tasks/QUEUE.md`", upgraded)
        self.assertIn("Consumer-owned closure note.", agents.read_text(encoding="utf-8"))
        manifest = json.loads((self.project / ".meridian/manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["workflowBaselineVersion"], "1.2.4")
        self.assertEqual(manifest["appliedMigrations"][-1], "058-lean-closure-procedure")

    def test_upgrade_installs_governed_closure_procedure_and_preserves_consumer_text(self) -> None:
        workflow = self.framework / "templates/workflows/governed-sdd"
        paths = (
            "PROJECT_WORKFLOW.md",
            "docs/workflows/IMPLEMENTATION.md",
            "docs/workflows/REVIEW.md",
        )
        current = {relative: (workflow / relative).read_text(encoding="utf-8") for relative in paths}
        previous = {
            "PROJECT_WORKFLOW.md": re.sub(
                r"\n<!-- MERIDIAN:BEGIN capability=git-workflow v9 -->.*?<!-- MERIDIAN:END -->\n",
                "\n",
                current["PROJECT_WORKFLOW.md"],
                flags=re.DOTALL,
            ),
            "docs/workflows/IMPLEMENTATION.md": re.sub(
                r"\n<!-- MERIDIAN:BEGIN capability=task-worktree-boundary v10 -->.*?<!-- MERIDIAN:END -->\n",
                "\n",
                current["docs/workflows/IMPLEMENTATION.md"],
                flags=re.DOTALL,
            ),
            "docs/workflows/REVIEW.md": re.sub(
                r"\n<!-- MERIDIAN:BEGIN capability=task-worktree-review-procedure v9 -->.*?<!-- MERIDIAN:END -->\n",
                "\n",
                current["docs/workflows/REVIEW.md"],
                flags=re.DOTALL,
            ),
        }
        for relative, text in previous.items():
            (workflow / relative).write_text(text, encoding="utf-8")
        for path in workflow.rglob("*"):
            if path.is_file():
                destination = self.project / path.relative_to(workflow)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, destination)
        (self.framework / "VERSION").write_text("1.2.4\n", encoding="utf-8")
        self.assertEqual(self.run_cli("lock", "--mode", "governed-sdd").returncode, 0)

        implementation = self.project / "docs/workflows/IMPLEMENTATION.md"
        implementation.write_text(
            implementation.read_text(encoding="utf-8") + "\nConsumer-owned closure note.\n",
            encoding="utf-8",
        )

        for relative, text in current.items():
            (workflow / relative).write_text(text, encoding="utf-8")
        (self.framework / "VERSION").write_text("1.2.5\n", encoding="utf-8")
        checked = self.run_cli("upgrade", "--check")
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertIn("MIGRATION 059-governed-closure-procedure", checked.stdout)
        applied = self.run_cli("upgrade", "--apply")
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)

        upgraded_workflow = (self.project / "PROJECT_WORKFLOW.md").read_text(encoding="utf-8")
        upgraded_implementation = implementation.read_text(encoding="utf-8")
        upgraded_review = (self.project / "docs/workflows/REVIEW.md").read_text(encoding="utf-8")
        self.assertIn("capability=git-workflow v14", upgraded_workflow)
        self.assertIn("Review: REQUIRED` is a gate, not a request for authorization", upgraded_workflow)
        self.assertIn("capability=task-worktree-boundary v10", upgraded_implementation)
        self.assertIn("REVIEW_REQUIRED`; it is a gate", upgraded_implementation)
        self.assertIn("capability=task-worktree-review-procedure v13", upgraded_review)
        self.assertIn("reviewer-integrator performs C6 through C10", upgraded_review)
        self.assertIn("Consumer-owned closure note.", upgraded_implementation)
        manifest = json.loads((self.project / ".meridian/manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["workflowBaselineVersion"], "1.2.5")
        self.assertEqual(manifest["appliedMigrations"][-1], "059-governed-closure-procedure")

    def test_upgrade_installs_code_organization_v2_and_preserves_the_project_module_map(self) -> None:
        workflow = self.framework / "templates/workflows/governed-sdd"
        relative = "docs/CODE_ORGANIZATION.md"
        current = (workflow / relative).read_text(encoding="utf-8")
        new_sentence = re.search(r"^The project records its layered module map.*$", current, re.MULTILINE)
        self.assertNotIn("\n## Project module map", current)
        self.assertIsNotNone(new_sentence)
        previous = current.replace("capability=code-organization v2", "capability=code-organization v1").replace(
            new_sentence.group(0),
            "Record this project's actual layered module map in its own architecture documentation, not in this file.",
        )
        self.assertNotEqual(previous, current)
        (workflow / relative).write_text(previous, encoding="utf-8")
        for path in workflow.rglob("*"):
            if path.is_file():
                destination = self.project / path.relative_to(workflow)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, destination)
        (self.framework / "VERSION").write_text("1.2.6\n", encoding="utf-8")
        self.assertEqual(self.run_cli("lock", "--mode", "governed-sdd").returncode, 0)

        module_map = "\n## Project module map\n\nThe `core` module owns domain rules; `app` depends on `core`.\n"
        organization = self.project / relative
        organization.write_text(organization.read_text(encoding="utf-8") + module_map, encoding="utf-8")

        (workflow / relative).write_text(current, encoding="utf-8")
        (self.framework / "VERSION").write_text("1.2.7\n", encoding="utf-8")
        applied = self.run_cli("upgrade", "--apply")
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)

        upgraded = organization.read_text(encoding="utf-8")
        self.assertIn("capability=code-organization v2", upgraded)
        self.assertIn(new_sentence.group(0), upgraded)
        self.assertTrue(upgraded.endswith(module_map))
        self.assertEqual(len(re.findall(r"^## Project module map$", upgraded, re.MULTILINE)), 1)

    def test_upgrade_removes_an_untouched_smoke_line_and_never_drops_a_customized_one(self) -> None:
        workflow = self.framework / "templates/workflows/governed-sdd"
        relative = "PROJECT_WORKFLOW.md"
        current = (workflow / relative).read_text(encoding="utf-8")
        anchor = "<!-- MERIDIAN:BEGIN capability=execution-discipline v1 -->"
        self.assertIn(anchor, current)
        smoke = "Project integration smoke command: `none`.\n\n"
        (workflow / relative).write_text(current.replace(anchor, smoke + anchor, 1), encoding="utf-8")
        for path in workflow.rglob("*"):
            if path.is_file():
                destination = self.project / path.relative_to(workflow)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, destination)
        (self.framework / "VERSION").write_text("1.2.6\n", encoding="utf-8")
        self.assertEqual(self.run_cli("lock", "--mode", "governed-sdd").returncode, 0)
        project_workflow = self.project / relative
        locked = project_workflow.read_text(encoding="utf-8")

        (workflow / relative).write_text(current, encoding="utf-8")
        (self.framework / "VERSION").write_text("1.2.7\n", encoding="utf-8")
        applied = self.run_cli("upgrade", "--apply")
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        self.assertNotIn("Project integration smoke command", project_workflow.read_text(encoding="utf-8"))

        project_workflow.write_text(locked.replace("`none`", "`make smoke`"), encoding="utf-8")
        shutil.rmtree(self.project / ".meridian")
        (self.framework / "VERSION").write_text("1.2.6\n", encoding="utf-8")
        (workflow / relative).write_text(current.replace(anchor, smoke + anchor, 1), encoding="utf-8")
        self.assertEqual(self.run_cli("lock", "--mode", "governed-sdd").returncode, 0)
        project_workflow.write_text(locked.replace("`none`", "`make smoke`"), encoding="utf-8")
        (workflow / relative).write_text(current, encoding="utf-8")
        (self.framework / "VERSION").write_text("1.2.7\n", encoding="utf-8")
        applied = self.run_cli("upgrade", "--apply")
        self.assertIn(applied.returncode, (0, 2), applied.stdout + applied.stderr)
        self.assertIn("Project integration smoke command: `make smoke`", project_workflow.read_text(encoding="utf-8"))

    def _assert_upgrade_installs_closure_command_policy(self, mode: str) -> None:
        workflow = self.framework / f"templates/workflows/{mode}"
        relative = ".codex/rules/meridian.rules"
        current = (workflow / relative).read_text(encoding="utf-8")
        previous = re.sub(r"\n# Unattended-closure additions.*?\[\"ls\", [^\n]*\n", "\n", current, flags=re.DOTALL)
        self.assertNotEqual(previous, current)
        (workflow / relative).write_text(previous, encoding="utf-8")
        for path in workflow.rglob("*"):
            if path.is_file():
                destination = self.project / path.relative_to(workflow)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, destination)
        (self.framework / "VERSION").write_text("1.2.5\n", encoding="utf-8")
        self.assertEqual(self.run_cli("lock", "--mode", mode).returncode, 0)
        local = 'prefix_rule(pattern=["project-tool", "run"], decision="allow")\n'
        rules = self.project / relative
        rules.write_text(rules.read_text(encoding="utf-8") + "\n# Local rule\n" + local, encoding="utf-8")

        (workflow / relative).write_text(current, encoding="utf-8")
        (self.framework / "VERSION").write_text("1.2.6\n", encoding="utf-8")
        checked = self.run_cli("upgrade", "--check")
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertIn("MIGRATION 060-unattended-closure-command-policy", checked.stdout)
        if mode == "governed-sdd":
            lifecycle_plan = next(
                line
                for line in checked.stdout.splitlines()
                if "docs/WORKTREE_LIFECYCLE.md" in line
            )
            self.assertEqual(lifecycle_plan.split()[0], "KEEP")
            self.assertNotIn("ADOPT", lifecycle_plan)
        applied = self.run_cli("upgrade", "--apply")
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)

        upgraded = rules.read_text(encoding="utf-8")
        self.assertIn('["meridian", "worktree", ["evidence", "closure-status", "advance"]]', upgraded)
        self.assertIn('prefix_rule(pattern=["git", "mv"], decision="allow")', upgraded)
        self.assertIn(local, upgraded)
        manifest = json.loads((self.project / ".meridian/manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["workflowBaselineVersion"], "1.2.6")
        self.assertEqual(manifest["appliedMigrations"][-1], "060-unattended-closure-command-policy")

    def test_upgrade_installs_closure_command_policy_for_governed_and_keeps_local_rules(self) -> None:
        self._assert_upgrade_installs_closure_command_policy("governed-sdd")

    def test_upgrade_installs_resume_guidance_for_lean_from_1_2_6(self) -> None:
        workflow = self.framework / "templates/workflows/lean-delivery"
        paths = ("PROJECT_WORKFLOW.md", "docs/WORKTREE_LIFECYCLE.md")
        current = {relative: (workflow / relative).read_text(encoding="utf-8") for relative in paths}
        resume_paragraph = re.compile(r"\nA `Proceed with <TASK-ID>` directive that says to Resume.*?(?=<!-- MERIDIAN:END -->)", re.DOTALL)
        resume_bullet = re.compile(r" Only a Resume directive adds `--resume`.*?`dirty-worktree` and no other error\.", re.DOTALL)
        previous = {
            "PROJECT_WORKFLOW.md": resume_paragraph.sub(
                "\n", current["PROJECT_WORKFLOW.md"].replace(
                    "capability=bounded-worktree-lifecycle v7", "capability=bounded-worktree-lifecycle v3"
                ), count=1,
            ),
            "docs/WORKTREE_LIFECYCLE.md": resume_bullet.sub(
                "", re.sub(
                    r"## Commit-less fast-forward recovery.*?(?=## Candidate validation)",
                    "", current["docs/WORKTREE_LIFECYCLE.md"], flags=re.DOTALL,
                ).replace(
                    "capability=worktree-lifecycle v6", "capability=worktree-lifecycle v1"
                ), count=1,
            ),
        }
        for relative in paths:
            self.assertNotEqual(previous[relative], current[relative], relative)
            previous[relative] = previous[relative].replace(
                "Only explicit Resume passes `--resume` after status/diff inspection and sole\nwriter confirmation, except when the record is archived and state is DONE:\nskip execution start, commit staged closure records, then run worktree advance.", ""
            ).replace("Only explicit Resume adds `--resume` after\n  status/diff inspection.", "")
            previous[relative] = re.sub(r" On explicit Resume, if the record is already archived.*?with the validation evidence\.", "", previous[relative])
            self.assertNotIn("--resume", previous[relative])
            (workflow / relative).write_text(previous[relative], encoding="utf-8")
        for path in workflow.rglob("*"):
            if path.is_file():
                destination = self.project / path.relative_to(workflow)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, destination)
        (self.framework / "VERSION").write_text("1.2.6\n", encoding="utf-8")
        self.assertEqual(self.run_cli("lock", "--mode", "lean-delivery").returncode, 0)
        project_workflow = self.project / "PROJECT_WORKFLOW.md"
        project_workflow.write_text(
            project_workflow.read_text(encoding="utf-8") + "\nConsumer-owned resume note.\n", encoding="utf-8"
        )

        for relative in paths:
            (workflow / relative).write_text(current[relative], encoding="utf-8")
        (self.framework / "VERSION").write_text("1.2.7\n", encoding="utf-8")
        checked = self.run_cli("upgrade", "--check")
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertIn("MIGRATION 061-governed-phase-reads", checked.stdout)
        applied = self.run_cli("upgrade", "--apply")
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)

        upgraded = project_workflow.read_text(encoding="utf-8")
        self.assertIn("capability=bounded-worktree-lifecycle v7", upgraded)
        self.assertIn("`--resume` is allowed only for that directive", upgraded)
        self.assertIn("Consumer-owned resume note.", upgraded)
        lifecycle = (self.project / "docs/WORKTREE_LIFECYCLE.md").read_text(encoding="utf-8")
        self.assertIn("capability=worktree-lifecycle v6", lifecycle)
        self.assertIn("Only a Resume directive adds `--resume`", lifecycle)

    def test_upgrade_installs_closure_command_policy_for_lean_and_keeps_local_rules(self) -> None:
        self._assert_upgrade_installs_closure_command_policy("lean-delivery")

    def test_lean_lifecycle_document_is_managed_across_legacy_adoption(self) -> None:
        snapshot = self.framework / "release-baselines/1.0.0/templates/workflows/lean-delivery"
        shutil.copytree(self.framework / "templates/workflows/lean-delivery", snapshot)
        (snapshot / "docs/WORKTREE_LIFECYCLE.md").unlink()
        shutil.rmtree(self.project)
        self.project.mkdir()
        for path in snapshot.rglob("*"):
            if path.is_file():
                destination = self.project / path.relative_to(snapshot)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, destination)

        applied = self.run_cli("adopt", "--mode", "lean-delivery", "--from", "1.0.0", "--apply")

        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        lifecycle = self.project / "docs/WORKTREE_LIFECYCLE.md"
        current = self.framework / "templates/workflows/lean-delivery/docs/WORKTREE_LIFECYCLE.md"
        self.assertEqual(lifecycle.read_text(encoding="utf-8"), current.read_text(encoding="utf-8"))
        manifest = json.loads((self.project / ".meridian/manifest.json").read_text(encoding="utf-8"))
        self.assertIn("docs/WORKTREE_LIFECYCLE.md", manifest["managedFiles"])

    def test_upgrade_installs_lean_lifecycle_document_from_1_2_5(self) -> None:
        workflow = self.framework / "templates/workflows/lean-delivery"
        template = workflow / "docs/WORKTREE_LIFECYCLE.md"
        current = template.read_text(encoding="utf-8")
        previous = re.sub(
            r"\n## Candidate validation by integration outcome\n.*?(?=\n`meridian codex worktree-path`)",
            "\n",
            current,
            count=1,
            flags=re.DOTALL,
        )
        self.assertNotEqual(previous, current)

        for state in (
            "missing",
            "baseline",
            "local-edit",
            "adopt-identical",
            "adopt-different",
            "adopt-collision",
            "adopt-blocked",
        ):
            with self.subTest(state=state):
                shutil.rmtree(self.project)
                self.project.mkdir()
                template.write_text(previous, encoding="utf-8")
                for path in workflow.rglob("*"):
                    if path.is_file():
                        destination = self.project / path.relative_to(workflow)
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(path, destination)
                (self.framework / "VERSION").write_text("1.2.5\n", encoding="utf-8")
                locked = self.run_cli("lock", "--mode", "lean-delivery")
                self.assertEqual(locked.returncode, 0, locked.stdout + locked.stderr)

                lifecycle = self.project / "docs/WORKTREE_LIFECYCLE.md"
                if state == "missing":
                    lifecycle.unlink()
                    baseline_lifecycle = (
                        self.project / ".meridian/baselines/1.2.5/docs/WORKTREE_LIFECYCLE.md"
                    )
                    baseline_lifecycle.unlink()
                    manifest_path = self.project / ".meridian/manifest.json"
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    manifest["managedFiles"].pop("docs/WORKTREE_LIFECYCLE.md")
                    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
                elif state == "local-edit":
                    lifecycle.write_text(previous + "\nConsumer-owned lifecycle note.\n", encoding="utf-8")
                elif state.startswith("adopt-"):
                    baseline_lifecycle = (
                        self.project / ".meridian/baselines/1.2.5/docs/WORKTREE_LIFECYCLE.md"
                    )
                    baseline_lifecycle.unlink()
                    manifest_path = self.project / ".meridian/manifest.json"
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    manifest["managedFiles"].pop("docs/WORKTREE_LIFECYCLE.md")
                    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
                    if state == "adopt-identical":
                        lifecycle.write_text(current, encoding="utf-8")
                    else:
                        lifecycle.write_text(previous + "\nPre-adoption project copy.\n", encoding="utf-8")
                        if state == "adopt-collision":
                            lifecycle.with_name(
                                lifecycle.name + ".meridian-pre-adoption.bak"
                            ).write_text("earlier backup\n", encoding="utf-8")
                        elif state == "adopt-blocked":
                            agents = self.project / "AGENTS.md"
                            agents.write_text(
                                agents.read_text(encoding="utf-8") + "\nUndeclared local edit.\n",
                                encoding="utf-8",
                            )
                            (self.project / ".meridian/baselines/1.2.5/AGENTS.md").unlink()

                template.write_text(current, encoding="utf-8")
                (self.framework / "VERSION").write_text("1.2.6\n", encoding="utf-8")
                checked = self.run_cli("upgrade", "--check")
                if state == "adopt-blocked":
                    self.assertNotEqual(checked.returncode, 0)
                    self.assertIn("CONFLICT AGENTS.md — managed baseline is missing", checked.stdout)
                else:
                    self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
                expected_action = {
                    "missing": "ADD",
                    "baseline": "REPLACE",
                    "local-edit": "MERGE",
                    "adopt-identical": "ADOPT",
                    "adopt-different": "ADOPT-REPLACE",
                    "adopt-collision": "ADOPT-REPLACE",
                    "adopt-blocked": "ADOPT-REPLACE",
                }[state]
                lifecycle_plan = next(
                    line
                    for line in checked.stdout.splitlines()
                    if "docs/WORKTREE_LIFECYCLE.md" in line
                )
                self.assertEqual(lifecycle_plan.split()[0], expected_action)
                if state == "adopt-different":
                    self.assertIn(
                        "docs/WORKTREE_LIFECYCLE.md.meridian-pre-adoption.bak",
                        lifecycle_plan,
                    )
                elif state == "adopt-collision":
                    self.assertIn(
                        "docs/WORKTREE_LIFECYCLE.md.meridian-pre-adoption.bak.1",
                        lifecycle_plan,
                    )

                if state == "adopt-blocked":
                    before = lifecycle.read_text(encoding="utf-8")
                    applied = self.run_cli("upgrade", "--apply")
                    self.assertNotEqual(applied.returncode, 0)
                    self.assertEqual(lifecycle.read_text(encoding="utf-8"), before)
                    self.assertFalse(
                        lifecycle.with_name(
                            lifecycle.name + ".meridian-pre-adoption.bak"
                        ).exists()
                    )
                    continue

                applied = self.run_cli("upgrade", "--apply")
                self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
                self.assertIn(lifecycle_plan, applied.stdout)
                upgraded = lifecycle.read_text(encoding="utf-8")
                self.assertIn("## Candidate validation by integration outcome", upgraded)
                if state == "local-edit":
                    self.assertIn("Consumer-owned lifecycle note.", upgraded)
                else:
                    self.assertEqual(upgraded, current)
                if state in ("adopt-different", "adopt-collision"):
                    suffix = ".meridian-pre-adoption.bak.1" if state == "adopt-collision" else ".meridian-pre-adoption.bak"
                    backup = lifecycle.with_name(lifecycle.name + suffix)
                    self.assertEqual(
                        backup.read_text(encoding="utf-8"),
                        previous + "\nPre-adoption project copy.\n",
                    )
                    second = self.run_cli("upgrade", "--check")
                    self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
                    second_plan = next(
                        line
                        for line in second.stdout.splitlines()
                        if "docs/WORKTREE_LIFECYCLE.md" in line
                    )
                    self.assertEqual(second_plan.split()[0], "KEEP")

        template.write_text(current, encoding="utf-8")

    def test_owner_reconciled_upgrade_does_not_adopt_or_back_up_a_managed_file(self) -> None:
        workflow = self.framework / "templates/workflows/lean-delivery"
        template = workflow / "docs/WORKTREE_LIFECYCLE.md"
        current = template.read_text(encoding="utf-8")
        previous = current + "\nConsumer-owned lifecycle note.\n"
        self.assertNotEqual(previous, current)
        template.write_text(previous, encoding="utf-8")
        shutil.rmtree(self.project)
        self.project.mkdir()
        for path in workflow.rglob("*"):
            if path.is_file():
                destination = self.project / path.relative_to(workflow)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, destination)
        (self.framework / "VERSION").write_text("1.2.5\n", encoding="utf-8")
        self.assertEqual(self.run_cli("lock", "--mode", "lean-delivery").returncode, 0)
        lifecycle = self.project / "docs/WORKTREE_LIFECYCLE.md"
        (self.project / ".meridian/baselines/1.2.5/docs/WORKTREE_LIFECYCLE.md").unlink()
        template.write_text(current, encoding="utf-8")
        (self.framework / "VERSION").write_text("1.2.6\n", encoding="utf-8")

        applied = self.run_cli("upgrade", "--apply", "--owner-reconciled")

        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        self.assertEqual(lifecycle.read_text(encoding="utf-8"), previous)
        self.assertFalse(lifecycle.with_name(lifecycle.name + ".meridian-pre-adoption.bak").exists())
        template.write_text(current, encoding="utf-8")

    def test_upgrade_downgrades_cosmetic_conflict_to_verified(self) -> None:
        """Phase 3 of migrations/CAPABILITY_MARKERS.md: a conflict outside a
        satisfied capability marker is cosmetic and should be left untouched,
        not treated the same as a real, unverifiable conflict."""
        self.assertEqual(self.run_cli("lock", "--mode", "governed-sdd").returncode, 0)
        agents = self.framework / "templates/workflows/governed-sdd/docs/workflows/REMEDIATION.md"
        agents.write_text(
            agents.read_text(encoding="utf-8").replace("# Remediation Procedure", "# Remediation Procedure Rules"),
            encoding="utf-8",
        )
        local = self.project / "docs/workflows/REMEDIATION.md"
        local_text = local.read_text(encoding="utf-8")
        self.assertIn("MERIDIAN:BEGIN capability=review-remediation-record", local_text)
        local.write_text(
            local_text.replace("# Remediation Procedure", "# Our Remediation Procedure"), encoding="utf-8"
        )
        (self.framework / "VERSION").write_text("1.1.1\n", encoding="utf-8")

        checked = self.run_cli("upgrade", "--check")
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertIn("VERIFIED docs/workflows/REMEDIATION.md", checked.stdout)
        self.assertIn("capability marker(s)", checked.stdout)

        applied = self.run_cli("upgrade", "--apply")
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertIn(
            "# Our Remediation Procedure",
            (self.project / "docs/workflows/REMEDIATION.md").read_text(encoding="utf-8"),
            "a verified (cosmetic-only) conflict must leave the local file untouched",
        )

    def test_upgrade_appends_new_marker_when_existing_marker_was_moved(self) -> None:
        """A new protected capability must not conflict solely because a project
        relocated an unchanged older protected block."""
        policy = self.framework / "templates/workflows/governed-sdd/docs/CONTEXT_BUDGET_POLICY.md"
        profile = self.framework / "templates/workflows/governed-sdd/docs/EXECUTION_EVIDENCE_PROFILE.md"
        incoming_policy = policy.read_text(encoding="utf-8")
        marker = re.search(
            r"<!-- MERIDIAN:BEGIN capability=execution-evidence-profile v5 -->\n?.*?"
            r"<!-- MERIDIAN:END -->\n?",
            incoming_policy,
            re.DOTALL,
        )
        self.assertIsNotNone(marker)
        policy.write_text(incoming_policy[: marker.start()] + incoming_policy[marker.end() :], encoding="utf-8")
        profile.unlink()
        (self.framework / "VERSION").write_text("1.1.14\n", encoding="utf-8")
        shutil.rmtree(self.project)
        self.project.mkdir()
        self.copy_governed_templates()
        self.assertEqual(self.run_cli("lock", "--mode", "governed-sdd").returncode, 0)

        local_policy = self.project / "docs/CONTEXT_BUDGET_POLICY.md"
        local_text = local_policy.read_text(encoding="utf-8")
        validation = re.search(
            r"<!-- MERIDIAN:BEGIN capability=validation-scoping v2 -->\n?.*?"
            r"<!-- MERIDIAN:END -->\n?",
            local_text,
            re.DOTALL,
        )
        self.assertIsNotNone(validation)
        moved_validation = validation.group(0)
        local_text = (
            local_text[: validation.start()]
            + "Project-local validation procedure remains at this location.\n"
            + local_text[validation.end() :]
        )
        local_policy.write_text(
            local_text.rstrip() + "\n\n## Project validation baseline\n\n" + moved_validation,
            encoding="utf-8",
        )

        policy.write_text(incoming_policy, encoding="utf-8")
        profile.write_text("# Project Execution Evidence Profile\n", encoding="utf-8")
        (self.framework / "VERSION").write_text("1.1.15\n", encoding="utf-8")

        appended = meridian.append_only_new_markers(
            local_policy.read_text(encoding="utf-8"),
            (self.project / ".meridian/baselines/1.1.14/docs/CONTEXT_BUDGET_POLICY.md").read_text(
                encoding="utf-8"
            ),
            incoming_policy,
        )
        self.assertIsNotNone(appended)
        self.assertIn("## Project validation baseline", appended)
        self.assertIn("capability=execution-evidence-profile v5", appended)

        checked = self.run_cli("upgrade", "--check")
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertIn("MERGE    docs/CONTEXT_BUDGET_POLICY.md", checked.stdout)

        applied = self.run_cli("upgrade", "--apply")
        self.assertEqual(applied.returncode, 0, applied.stderr)
        upgraded = local_policy.read_text(encoding="utf-8")
        self.assertIn("## Project validation baseline", upgraded)
        self.assertIn("capability=validation-scoping v2", upgraded)
        self.assertIn("capability=execution-evidence-profile v5", upgraded)
        self.assertTrue((self.project / "docs/EXECUTION_EVIDENCE_PROFILE.md").is_file())

    def test_upgrade_preserves_a_verified_agents_pointer_claude_file(self) -> None:
        self.assertEqual(self.run_cli("lock", "--mode", "governed-sdd").returncode, 0)
        agent_template = self.framework / "templates/workflows/governed-sdd/AGENTS.md"
        claude_template = self.framework / "templates/workflows/governed-sdd/CLAUDE.md"
        marker = "<!-- MERIDIAN:BEGIN capability=pointer-test v1 -->\nShared gate.\n<!-- MERIDIAN:END -->\n"
        agent_template.write_text(agent_template.read_text(encoding="utf-8") + "\n" + marker, encoding="utf-8")
        claude_template.write_text(claude_template.read_text(encoding="utf-8") + "\n" + marker, encoding="utf-8")
        agent = self.project / "AGENTS.md"
        agent.write_text(agent.read_text(encoding="utf-8") + "\n" + marker, encoding="utf-8")
        pointer = self.project / "CLAUDE.md"
        pointer.write_text(
            "# Project instructions\n\nThis repository is governed by `AGENTS.md`, which is authoritative.\n\n"
            "Every Meridian capability marker lives in `AGENTS.md`, once.\n\nKeep this file a pointer.\n",
            encoding="utf-8",
        )
        (self.framework / "VERSION").write_text("1.1.1\n", encoding="utf-8")
        checked = self.run_cli("upgrade", "--check")
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertIn("POINTER-VERIFIED CLAUDE.md", checked.stdout)
        applied = self.run_cli("upgrade", "--apply")
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertEqual(pointer.read_text(encoding="utf-8"),
                         "# Project instructions\n\nThis repository is governed by `AGENTS.md`, which is authoritative.\n\nEvery Meridian capability marker lives in `AGENTS.md`, once.\n\nKeep this file a pointer.\n")

    def test_upgrade_preserves_an_explicit_agents_pointer_claude_file(self) -> None:
        self.assertEqual(self.run_cli("lock", "--mode", "governed-sdd").returncode, 0)
        agent_template = self.framework / "templates/workflows/governed-sdd/AGENTS.md"
        claude_template = self.framework / "templates/workflows/governed-sdd/CLAUDE.md"
        marker = "<!-- MERIDIAN:BEGIN capability=pointer-test v1 -->\nShared gate.\n<!-- MERIDIAN:END -->\n"
        agent_template.write_text(agent_template.read_text(encoding="utf-8") + "\n" + marker, encoding="utf-8")
        claude_template.write_text(claude_template.read_text(encoding="utf-8") + "\n" + marker, encoding="utf-8")
        agent = self.project / "AGENTS.md"
        agent.write_text(agent.read_text(encoding="utf-8") + "\n" + marker, encoding="utf-8")
        pointer = self.project / "CLAUDE.md"
        pointer.write_text(
            "<!-- MERIDIAN:CLAUDE-AGENTS-POINTER v1 -->\n\n"
            "# Project instructions\n\nRead AGENTS.md before task work.\n",
            encoding="utf-8",
        )
        (self.framework / "VERSION").write_text("1.1.1\n", encoding="utf-8")
        checked = self.run_cli("upgrade", "--check")
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertIn("POINTER-VERIFIED CLAUDE.md", checked.stdout)
        applied = self.run_cli("upgrade", "--apply")
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertEqual(
            pointer.read_text(encoding="utf-8"),
            "<!-- MERIDIAN:CLAUDE-AGENTS-POINTER v1 -->\n\n"
            "# Project instructions\n\nRead AGENTS.md before task work.\n",
        )

    def test_upgrade_converts_a_legacy_pointer_when_pointer_migration_is_pending(self) -> None:
        (self.framework / "VERSION").write_text("1.1.32\n", encoding="utf-8")
        self.assertEqual(self.run_cli("lock", "--mode", "governed-sdd").returncode, 0)
        pointer = self.project / "CLAUDE.md"
        pointer.write_text(
            "# Project instructions\n\nThis repository is governed by `AGENTS.md`, which is authoritative.\n\n"
            "Every Meridian capability marker lives in `AGENTS.md`, once.\n\nKeep this file a pointer.\n",
            encoding="utf-8",
        )
        (self.framework / "VERSION").write_text("1.1.33\n", encoding="utf-8")

        checked = self.run_cli("upgrade", "--check")
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertIn("POINTER-UPGRADE CLAUDE.md", checked.stdout)

        applied = self.run_cli("upgrade", "--apply")
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        upgraded = pointer.read_text(encoding="utf-8")
        self.assertEqual(upgraded.count("<!-- MERIDIAN:CLAUDE-AGENTS-POINTER v1 -->"), 1)
        self.assertEqual(meridian.marker_pairs(upgraded), [])

    def test_explicit_agents_pointer_rejects_duplicate_or_capability_markers(self) -> None:
        self.assertFalse(
            meridian.is_agents_pointer(
                "<!-- MERIDIAN:CLAUDE-AGENTS-POINTER v1 -->\n"
                "<!-- MERIDIAN:CLAUDE-AGENTS-POINTER v1 -->\n"
            )
        )
        self.assertFalse(
            meridian.is_agents_pointer(
                "<!-- MERIDIAN:CLAUDE-AGENTS-POINTER v1 -->\n"
                "<!-- MERIDIAN:BEGIN capability=test v1 -->\nRule.\n<!-- MERIDIAN:END -->\n"
            )
        )

    def test_marker_insertion_promotes_an_identical_unmarked_local_rule(self) -> None:
        template = (
            "# Profile\n\n<!-- MERIDIAN:BEGIN capability=investigation-scope v2 -->\n"
            "- Investigation scope: 2 per task.\n<!-- MERIDIAN:END -->\n"
        )
        content = meridian.extract_marker_block(template, "investigation-scope", 2)
        self.assertIsNotNone(content)
        local = "# Profile\n\n" + content
        upgraded = meridian.append_only_new_markers(local, "# Profile\n", template)
        self.assertIsNotNone(upgraded)
        self.assertEqual(upgraded.count("Investigation scope: 2 per task."), 1)
        self.assertIn("capability=investigation-scope v2", upgraded)

    def test_long_command_waits_block_is_added_once_to_a_customized_profile(self) -> None:
        for mode in ("lean-delivery", "governed-sdd"):
            with self.subTest(mode=mode):
                template = (
                    ROOT / "templates" / "workflows" / mode / "docs" / "EXECUTION_EVIDENCE_PROFILE.md"
                ).read_text(encoding="utf-8")
                self.assertIsNotNone(meridian.extract_marker_block(template, "long-command-waits", 1))
                local = "# Project profile\n\nProject-owned rule.\n"
                upgraded = meridian.append_only_new_markers(local, "# Project profile\n", template)
                self.assertIsNotNone(upgraded)
                self.assertEqual(upgraded.count("capability=long-command-waits v1"), 1)
                self.assertIn("Project-owned rule.", upgraded)

    def test_marker_normalization_accepts_prose_reflow_but_not_fenced_content(self) -> None:
        template = (
            "<!-- MERIDIAN:BEGIN capability=example v1 -->\n"
            "One long policy sentence wraps here.\n\n```text\nexact value\n```\n"
            "<!-- MERIDIAN:END -->\n"
        )
        reflowed = template.replace("One long policy sentence wraps here.", "One long policy\nsentence wraps here.")
        normalized = meridian.reflowed_marker_normalization(reflowed, template)
        self.assertEqual(normalized, template)
        changed_fence = reflowed.replace("exact value", "different value")
        self.assertIsNone(meridian.reflowed_marker_normalization(changed_fence, template))

    def test_marker_deduplication_removes_only_identical_template_copies(self) -> None:
        block = "<!-- MERIDIAN:BEGIN capability=example v1 -->\nRule.\n<!-- MERIDIAN:END -->\n"
        duplicated = "# Policy\n\n" + block + "\n" + block
        normalized = meridian.deduplicate_identical_template_markers(duplicated, block)
        self.assertIsNotNone(normalized)
        self.assertEqual(normalized.count("capability=example v1"), 1)
        divergent = duplicated.replace("Rule.\n<!-- MERIDIAN:END -->\n\n<!--", "Different.\n<!-- MERIDIAN:END -->\n\n<!--", 1)
        self.assertIsNone(meridian.deduplicate_identical_template_markers(divergent, block))

    def test_upgrade_does_not_require_a_capability_not_marked_in_this_file(self) -> None:
        """A migration's `managedPaths` lists every file its diff touches, which
        is not the same as every file that must carry its capability marker:
        migration 002 lists `docs/CONTEXT_BUDGET_POLICY.md` because it mentions
        lifecycle orchestration in prose, but only `validation-scoping` is
        actually marked in that file's template. The per-file cosmetic-conflict
        check must derive required capabilities from the template's own marker
        set, not from `managedPaths`, or this file can never be verified."""
        self.assertEqual(self.run_cli("lock", "--mode", "governed-sdd").returncode, 0)
        policy = self.framework / "templates/workflows/governed-sdd/docs/CONTEXT_BUDGET_POLICY.md"
        policy.write_text(
            policy.read_text(encoding="utf-8").replace("## Task-first loading", "## Task-First Loading Rules"),
            encoding="utf-8",
        )
        local = self.project / "docs/CONTEXT_BUDGET_POLICY.md"
        local_text = local.read_text(encoding="utf-8")
        self.assertIn("MERIDIAN:BEGIN capability=validation-scoping", local_text)
        local.write_text(
            local_text.replace("## Task-first loading", "## Our Task-First Loading"), encoding="utf-8"
        )
        (self.framework / "VERSION").write_text("1.1.1\n", encoding="utf-8")

        checked = self.run_cli("upgrade", "--check")
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertIn("VERIFIED docs/CONTEXT_BUDGET_POLICY.md", checked.stdout)

    def test_upgrade_retires_a_capability_from_a_conflicting_file(self) -> None:
        """Task 007: a migration's `removes` entry deletes a retired capability's
        block during `upgrade`, even when the file also has an unrelated local
        customization that blocks a clean three-way merge -- the retirement
        mirror of `test_upgrade_appends_new_marker_when_existing_marker_was_moved`.
        """
        self.assertEqual(self.run_cli("lock", "--mode", "governed-sdd").returncode, 0)

        policy = self.framework / "templates/workflows/governed-sdd/docs/CONTEXT_BUDGET_POLICY.md"
        incoming_policy = policy.read_text(encoding="utf-8")
        marker = re.search(
            r"<!-- MERIDIAN:BEGIN capability=minimal-read-only-status v3 -->\n?.*?"
            r"<!-- MERIDIAN:END -->\n?",
            incoming_policy,
            re.DOTALL,
        )
        self.assertIsNotNone(marker)
        incoming_policy = incoming_policy[: marker.start()] + incoming_policy[marker.end() :]
        # An unrelated framework-side edit, on the same line a local
        # customization below also touches, so the three-way merge cannot
        # auto-resolve and the file falls through to the retirement fallback.
        incoming_policy = incoming_policy.replace(
            "## Task-first loading", "## Task-First Loading (framework wording)"
        )
        policy.write_text(incoming_policy, encoding="utf-8")

        (self.framework / "migrations/999-retire-minimal-read-only-status.json").write_text(
            json.dumps(
                {
                    "id": "999-retire-minimal-read-only-status",
                    "from": "1.1.0",
                    "to": "1.1.1",
                    "description": "test-only retirement",
                    "removes": [
                        {
                            "capability": "minimal-read-only-status",
                            "capabilityVersion": 3,
                            "supersededBy": "role-scoped-agent-rules",
                        }
                    ],
                    "managedPaths": ["docs/CONTEXT_BUDGET_POLICY.md"],
                    "verification": ["test-only"],
                }
            ),
            encoding="utf-8",
        )
        (self.framework / "VERSION").write_text("1.1.1\n", encoding="utf-8")

        local_policy = self.project / "docs/CONTEXT_BUDGET_POLICY.md"
        local_text = local_policy.read_text(encoding="utf-8")
        self.assertIn("MERIDIAN:BEGIN capability=minimal-read-only-status v3", local_text)
        local_policy.write_text(
            local_text.replace("## Task-first loading", "## Task-First Loading (project wording)"),
            encoding="utf-8",
        )

        checked = self.run_cli("upgrade", "--check")
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertIn("RETIRE-MARKERS docs/CONTEXT_BUDGET_POLICY.md", checked.stdout)

        applied = self.run_cli("upgrade", "--apply")
        self.assertEqual(applied.returncode, 0, applied.stderr)
        upgraded = local_policy.read_text(encoding="utf-8")
        self.assertNotIn("capability=minimal-read-only-status", upgraded)
        self.assertNotIn("A status report is not a conformance audit.", upgraded)
        # The unrelated local customization survives untouched.
        self.assertIn("## Task-First Loading (project wording)", upgraded)
        # Every other still-required capability in this file is untouched.
        self.assertIn("capability=validation-scoping v2", upgraded)
        self.assertIn("capability=evidence-tiers v1", upgraded)

        audited = self.run_cli("audit", "--mode", "governed-sdd")
        self.assertNotIn("minimal-read-only-status", audited.stdout)

    def test_upgrade_refuses_to_retire_a_locally_modified_block(self) -> None:
        """The same retirement, but the local copy of the retired block itself
        was edited -- must fall through to a blocking conflict rather than
        silently discard the customization along with the block."""
        self.assertEqual(self.run_cli("lock", "--mode", "governed-sdd").returncode, 0)

        policy = self.framework / "templates/workflows/governed-sdd/docs/CONTEXT_BUDGET_POLICY.md"
        incoming_policy = policy.read_text(encoding="utf-8")
        marker = re.search(
            r"<!-- MERIDIAN:BEGIN capability=minimal-read-only-status v3 -->\n?.*?"
            r"<!-- MERIDIAN:END -->\n?",
            incoming_policy,
            re.DOTALL,
        )
        self.assertIsNotNone(marker)
        incoming_policy = incoming_policy[: marker.start()] + incoming_policy[marker.end() :]
        incoming_policy = incoming_policy.replace(
            "## Task-first loading", "## Task-First Loading (framework wording)"
        )
        policy.write_text(incoming_policy, encoding="utf-8")

        (self.framework / "migrations/999-retire-minimal-read-only-status.json").write_text(
            json.dumps(
                {
                    "id": "999-retire-minimal-read-only-status",
                    "from": "1.1.0",
                    "to": "1.1.1",
                    "description": "test-only retirement",
                    "removes": [{"capability": "minimal-read-only-status", "capabilityVersion": 3}],
                    "managedPaths": ["docs/CONTEXT_BUDGET_POLICY.md"],
                    "verification": ["test-only"],
                }
            ),
            encoding="utf-8",
        )
        (self.framework / "VERSION").write_text("1.1.1\n", encoding="utf-8")

        local_policy = self.project / "docs/CONTEXT_BUDGET_POLICY.md"
        local_text = local_policy.read_text(encoding="utf-8")
        local_text = local_text.replace("## Task-first loading", "## Task-First Loading (project wording)")
        # Edit inside the very block that is about to be retired.
        local_text = local_text.replace(
            "A status report is not a conformance audit.",
            "A status report is not a conformance audit, locally customized.",
        )
        local_policy.write_text(local_text, encoding="utf-8")

        checked = self.run_cli("upgrade", "--check")
        self.assertEqual(checked.returncode, 2, checked.stdout + checked.stderr)
        self.assertIn("CONFLICT docs/CONTEXT_BUDGET_POLICY.md", checked.stdout)
        self.assertIn("BLOCKED", checked.stdout)

    def test_retirement_move_preserves_project_text_outside_exact_source_marker(self) -> None:
        """A retirement move proves only its protected source marker.

        Project-owned material outside that marker must survive both the move
        and its follow-up audit; otherwise a consumer with a customized agent
        guide can never adopt compact routing safely.
        """
        self.assertEqual(self.run_cli("lock", "--mode", "governed-sdd").returncode, 0)

        source = self.framework / "templates/workflows/governed-sdd/docs/CONTEXT_BUDGET_POLICY.md"
        source_text = source.read_text(encoding="utf-8")
        marker = re.search(
            r"<!-- MERIDIAN:BEGIN capability=minimal-read-only-status v3 -->\n?.*?"
            r"<!-- MERIDIAN:END -->",
            source_text,
            re.DOTALL,
        )
        self.assertIsNotNone(marker)
        marker_text = marker.group(0)
        digest = meridian.marker_block_sha256(marker_text)
        incoming_source = source_text[: marker.start()] + source_text[marker.end() :]
        source.write_text(
            incoming_source.replace(
                "This policy reduces context and reasoning overhead while preserving governed-SDD authority and review quality.",
                "This framework policy reduces context and reasoning overhead while preserving governed-SDD authority and review quality.",
            ),
            encoding="utf-8",
        )

        target = self.framework / "templates/workflows/governed-sdd/docs/ROUTED_STATUS_RULE.md"
        target.write_text(marker_text + "\n", encoding="utf-8")
        (self.framework / "migrations/999-move-minimal-read-only-status.json").write_text(
            json.dumps(
                {
                    "id": "999-move-minimal-read-only-status",
                    "from": "1.1.0",
                    "to": "1.1.1",
                    "description": "test-only retirement move",
                    "capabilityMoves": [
                        {
                            "stage": "retirement",
                            "source": {
                                "path": "docs/CONTEXT_BUDGET_POLICY.md",
                                "capability": "minimal-read-only-status",
                                "capabilityVersion": 3,
                                "markerSha256": digest,
                            },
                            "target": {
                                "path": "docs/ROUTED_STATUS_RULE.md",
                                "capability": "minimal-read-only-status",
                                "capabilityVersion": 3,
                                "markerSha256": digest,
                            },
                        }
                    ],
                    "managedPaths": ["docs/CONTEXT_BUDGET_POLICY.md", "docs/ROUTED_STATUS_RULE.md"],
                    "verification": ["test-only"],
                }
            ),
            encoding="utf-8",
        )
        (self.framework / "VERSION").write_text("1.1.1\n", encoding="utf-8")

        local_source = self.project / "docs/CONTEXT_BUDGET_POLICY.md"
        local_source.write_text(
            local_source.read_text(encoding="utf-8").replace(
                "This policy reduces context and reasoning overhead while preserving governed-SDD authority and review quality.",
                "This project policy reduces context and reasoning overhead while preserving governed-SDD authority and review quality.",
            ),
            encoding="utf-8",
        )

        checked = self.run_cli("upgrade", "--check")
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertIn("RETIRE-MARKERS docs/CONTEXT_BUDGET_POLICY.md", checked.stdout)
        self.assertIn("ADD      docs/ROUTED_STATUS_RULE.md", checked.stdout)

        applied = self.run_cli("upgrade", "--apply")
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        upgraded_source = local_source.read_text(encoding="utf-8")
        self.assertIn("This project policy reduces context and reasoning overhead", upgraded_source)
        self.assertNotIn("capability=minimal-read-only-status", upgraded_source)
        self.assertEqual((self.project / "docs/ROUTED_STATUS_RULE.md").read_text(encoding="utf-8"), marker_text + "\n")

        audited = self.run_cli("audit", "--mode", "governed-sdd")
        self.assertEqual(audited.returncode, 1, audited.stdout + audited.stderr)
        self.assertIn("declaration/legacy-compatibility", audited.stdout)

    def _reinsert_role_scoped_agent_rules_block(self, text: str) -> str:
        block = (
            "<!-- MERIDIAN:BEGIN capability=role-scoped-agent-rules v1 -->\n"
            "## Role-scoped agent-rules reading\n\n"
            "`AGENTS.md`/`CLAUDE.md` states rules for every role in one file; reading all\n"
            "of it in every session is more than a given role needs. Read only the\n"
            "sections your current role requires, identified by heading text:\n\n"
            "- **Every role** reads the file's shared core: the introductory rules\n"
            "  through \"Command triggers\", plus \"Owner-acceptance workflow\".\n"
            "<!-- MERIDIAN:END -->\n\n"
        )
        anchor = "<!-- MERIDIAN:BEGIN capability=minimal-read-only-status v3 -->"
        self.assertIn(anchor, text)
        return text.replace(anchor, block + anchor, 1)

    def test_upgrade_removes_role_scoped_agent_rules_via_the_real_migration(self) -> None:
        """Task 008, using migration 025 itself (not a synthetic fixture): a
        project locked before the retirement has the block cleanly removed by
        `meridian upgrade` to 1.1.22."""
        policy = self.framework / "templates/workflows/governed-sdd/docs/CONTEXT_BUDGET_POLICY.md"
        policy.write_text(
            self._reinsert_role_scoped_agent_rules_block(policy.read_text(encoding="utf-8")),
            encoding="utf-8",
        )
        (self.framework / "VERSION").write_text("1.1.21\n", encoding="utf-8")
        shutil.rmtree(self.project)
        self.project.mkdir()
        self.copy_governed_templates()
        self.assertEqual(self.run_cli("lock", "--mode", "governed-sdd").returncode, 0)
        local_policy = self.project / "docs/CONTEXT_BUDGET_POLICY.md"
        self.assertIn("capability=role-scoped-agent-rules v1", local_policy.read_text(encoding="utf-8"))

        # Restore the framework to its real, current (post-025) state.
        policy.write_text(
            (ROOT / "templates/workflows/governed-sdd/docs/CONTEXT_BUDGET_POLICY.md").read_text(
                encoding="utf-8"
            ),
            encoding="utf-8",
        )
        (self.framework / "VERSION").write_text("1.1.22\n", encoding="utf-8")

        checked = self.run_cli("upgrade", "--check")
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)

        applied = self.run_cli("upgrade", "--apply")
        self.assertEqual(applied.returncode, 0, applied.stderr)
        upgraded = local_policy.read_text(encoding="utf-8")
        self.assertNotIn("role-scoped-agent-rules", upgraded)
        self.assertNotIn("Role-scoped agent-rules reading", upgraded)
        self.assertIn("capability=validation-scoping v2", upgraded)

        audited = self.run_cli("audit", "--mode", "governed-sdd")
        self.assertEqual(audited.returncode, 1, audited.stdout + audited.stderr)
        self.assertIn("declaration/legacy-compatibility", audited.stdout)

    REASONING_CONTRACT_BLOCK = (
        "<!-- MERIDIAN:BEGIN capability=reasoning-budget-contract v1 -->\n"
        "## Reasoning budget contract\n\n"
        "Select the lowest reliable reasoning effort while designing the task.\n"
        "<!-- MERIDIAN:END -->\n\n"
    )

    def _lock_project_with_reasoning_contract(self) -> tuple[Path, Path]:
        """Lock a governed project from templates that still carry the retired
        block and the superseded `execution-evidence-profile` v3 marker."""
        policy = self.framework / "templates/workflows/governed-sdd/docs/CONTEXT_BUDGET_POLICY.md"
        current = (ROOT / "templates/workflows/governed-sdd/docs/CONTEXT_BUDGET_POLICY.md").read_text(
            encoding="utf-8"
        )
        previous = current.replace(
            "capability=execution-evidence-profile v5", "capability=execution-evidence-profile v3"
        ).replace(
            "\n## Lifecycle orchestration", "\n" + self.REASONING_CONTRACT_BLOCK + "## Lifecycle orchestration", 1
        )
        self.assertIn("reasoning-budget-contract", previous)
        policy.write_text(previous, encoding="utf-8")
        (self.framework / "VERSION").write_text("1.2.8\n", encoding="utf-8")
        shutil.rmtree(self.project)
        self.project.mkdir()
        self.copy_governed_templates()
        self.assertEqual(self.run_cli("lock", "--mode", "governed-sdd").returncode, 0)
        policy.write_text(current, encoding="utf-8")
        (self.framework / "VERSION").write_text("1.2.9\n", encoding="utf-8")
        return policy, self.project / "docs/CONTEXT_BUDGET_POLICY.md"

    def test_upgrade_retires_reasoning_contract_alongside_a_marker_supersession(self) -> None:
        """Migration 063 both supersedes execution-evidence-profile v3 and
        retires reasoning-budget-contract in one file; when the three-way merge
        conflicts, the retirement must still apply, not be skipped."""
        policy, local_policy = self._lock_project_with_reasoning_contract()
        local_policy.write_text(
            local_policy.read_text(encoding="utf-8").replace(
                "## Task-first loading", "## Task-First Loading (project wording)"
            ),
            encoding="utf-8",
        )
        policy.write_text(
            policy.read_text(encoding="utf-8").replace(
                "## Task-first loading", "## Task-First Loading (framework wording)"
            ),
            encoding="utf-8",
        )

        checked = self.run_cli("upgrade", "--check")
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertIn("APPEND-RETIRE-MARKERS docs/CONTEXT_BUDGET_POLICY.md", checked.stdout)

        applied = self.run_cli("upgrade", "--apply")
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        upgraded = local_policy.read_text(encoding="utf-8")
        self.assertNotIn("reasoning-budget-contract", upgraded)
        self.assertIn("capability=execution-evidence-profile v5", upgraded)
        self.assertIn("Task-First Loading (project wording)", upgraded)

    def test_upgrade_refuses_to_retire_a_locally_edited_reasoning_contract(self) -> None:
        policy, local_policy = self._lock_project_with_reasoning_contract()
        local_policy.write_text(
            local_policy.read_text(encoding="utf-8")
            .replace("while designing the task.", "while designing the task, locally customized.")
            .replace("## Task-first loading", "## Task-First Loading (project wording)"),
            encoding="utf-8",
        )
        policy.write_text(
            policy.read_text(encoding="utf-8").replace(
                "## Task-first loading", "## Task-First Loading (framework wording)"
            ),
            encoding="utf-8",
        )

        checked = self.run_cli("upgrade", "--check")
        self.assertEqual(checked.returncode, 2, checked.stdout + checked.stderr)
        self.assertIn("CONFLICT docs/CONTEXT_BUDGET_POLICY.md", checked.stdout)
        self.assertIn("locally customized.", local_policy.read_text(encoding="utf-8"))

    def test_upgrade_refuses_role_scoped_agent_rules_removal_when_locally_modified(self) -> None:
        """Task 008's other half of AC3: the real migration 025 must refuse
        to discard a local edit inside the block it is retiring."""
        policy = self.framework / "templates/workflows/governed-sdd/docs/CONTEXT_BUDGET_POLICY.md"
        policy.write_text(
            self._reinsert_role_scoped_agent_rules_block(policy.read_text(encoding="utf-8")),
            encoding="utf-8",
        )
        (self.framework / "VERSION").write_text("1.1.21\n", encoding="utf-8")
        shutil.rmtree(self.project)
        self.project.mkdir()
        self.copy_governed_templates()
        self.assertEqual(self.run_cli("lock", "--mode", "governed-sdd").returncode, 0)

        local_policy = self.project / "docs/CONTEXT_BUDGET_POLICY.md"
        local_text = local_policy.read_text(encoding="utf-8")
        local_text = local_text.replace(
            "reading all\nof it in every session is more than a given role needs.",
            "reading all\nof it in every session is more than a given role needs, locally customized.",
        )
        # Also force a genuine three-way-merge conflict on an unrelated line
        # (both sides rename the same heading differently): migration 025's
        # real diff only deletes the retired block, so nothing else in it
        # would otherwise make `merge_clean` fail on its own, and this test's
        # actual target is `remove_retired_markers`'s own refusal once the
        # merge does fail for any reason.
        local_text = local_text.replace("## Task-first loading", "## Task-First Loading (project wording)")
        local_policy.write_text(local_text, encoding="utf-8")

        incoming_policy = (ROOT / "templates/workflows/governed-sdd/docs/CONTEXT_BUDGET_POLICY.md").read_text(
            encoding="utf-8"
        )
        incoming_policy = incoming_policy.replace(
            "## Task-first loading", "## Task-First Loading (framework wording)"
        )
        policy.write_text(incoming_policy, encoding="utf-8")
        (self.framework / "VERSION").write_text("1.1.22\n", encoding="utf-8")

        checked = self.run_cli("upgrade", "--check")
        self.assertEqual(checked.returncode, 2, checked.stdout + checked.stderr)
        self.assertIn("CONFLICT docs/CONTEXT_BUDGET_POLICY.md", checked.stdout)
        self.assertIn("BLOCKED", checked.stdout)
        # The local customization must still be on disk, untouched.
        self.assertIn("locally customized.", local_policy.read_text(encoding="utf-8"))

    def test_audit_passes_on_unmodified_markers(self) -> None:
        self.assertEqual(self.run_cli("lock", "--mode", "governed-sdd").returncode, 0)
        audited = self.run_cli("audit", "--mode", "governed-sdd")
        self.assertEqual(audited.returncode, 1, audited.stdout + audited.stderr)
        self.assertIn("PASS", audited.stdout)
        self.assertNotRegex(audited.stdout, r"(?m)^FAIL\s")
        self.assertIn("declaration/legacy-compatibility", audited.stdout)

    def test_audit_fails_on_edited_protected_region(self) -> None:
        self.assertEqual(self.run_cli("lock", "--mode", "governed-sdd").returncode, 0)
        agents = self.project / "docs/workflows/LIFECYCLE.md"
        text = agents.read_text(encoding="utf-8")
        self.assertIn("MERIDIAN:BEGIN capability=lifecycle-orchestration v3", text)
        edited = text.replace(
            "Act only as the coordinator", "Act only as the coordinator (edited without an upgrade)"
        )
        self.assertNotEqual(text, edited, "the replacement should have matched something inside the marker")
        agents.write_text(edited, encoding="utf-8")

        audited = self.run_cli("audit", "--mode", "governed-sdd")
        self.assertEqual(audited.returncode, 2)
        self.assertIn(
            "FAIL           marker-integrity — docs/workflows/LIFECYCLE.md: "
            "capability=lifecycle-orchestration v3",
            audited.stdout,
        )
        self.assertIn("SUMMARY worst=FAIL", audited.stdout)

    def test_audit_fails_when_a_file_carries_two_versions_of_one_capability(self) -> None:
        """Task 012: a version bump that was appended instead of replacing the
        version it supersedes leaves a contradictory pair behind — the audit
        must surface that, not just per-version drift."""
        self.assertEqual(self.run_cli("lock", "--mode", "governed-sdd").returncode, 0)
        agents = self.project / "AGENTS.md"
        text = agents.read_text(encoding="utf-8")
        self.assertIn("MERIDIAN:BEGIN capability=command-triggers v3", text)
        relabeled = text.replace(
            "MERIDIAN:BEGIN capability=command-triggers v3",
            "MERIDIAN:BEGIN capability=command-triggers v4",
            1,
        )
        duplicate_block = re.search(
            r"<!-- MERIDIAN:BEGIN capability=command-triggers v4 -->.*?<!-- MERIDIAN:END -->",
            relabeled,
            re.DOTALL,
        )
        self.assertIsNotNone(duplicate_block)
        agents.write_text(text.rstrip() + "\n\n" + duplicate_block.group(0) + "\n", encoding="utf-8")

        audited = self.run_cli("audit", "--mode", "governed-sdd")
        self.assertEqual(audited.returncode, 2)
        self.assertIn(
            "FAIL           marker-integrity — AGENTS.md: capability=command-triggers "
            "carries 2 versions (v3, v4)",
            audited.stdout,
        )

    def test_audit_skips_a_version_the_current_template_no_longer_carries(self) -> None:
        self.assertEqual(self.run_cli("lock", "--mode", "governed-sdd").returncode, 0)
        for name in ("docs/workflows/LIFECYCLE.md",):
            local = self.project / name
            local.write_text(
                local.read_text(encoding="utf-8").replace(
                    "MERIDIAN:BEGIN capability=lifecycle-orchestration v3",
                    "MERIDIAN:BEGIN capability=lifecycle-orchestration v99",
                ),
                encoding="utf-8",
            )

        audited = self.run_cli("audit", "--mode", "governed-sdd")
        self.assertEqual(audited.returncode, 1, audited.stdout + audited.stderr)
        self.assertIn("UNVERIFIED", audited.stdout)
        self.assertIn("lifecycle-orchestration v99", audited.stdout)
        self.assertNotRegex(audited.stdout, r"(?m)^FAIL\s")

    def test_audit_fails_a_retired_marker_still_present_outside_managed_paths(self) -> None:
        """Task 007: a marker whose exact (capability, version) some migration
        declared `removes` must be reported FAIL, not the generic stale SKIP —
        `meridian upgrade` only touches the files a retiring migration's
        `managedPaths` names, so a marker left in an unlisted file would
        otherwise sit as an invisible SKIP forever."""
        self.assertEqual(self.run_cli("lock", "--mode", "governed-sdd").returncode, 0)
        (self.framework / "migrations/999-retire-validation-scoping.json").write_text(
            json.dumps(
                {
                    "id": "999-retire-validation-scoping",
                    "from": "1.1.0",
                    "to": "1.1.1",
                    "description": "test-only retirement",
                    "removes": [{"capability": "validation-scoping", "capabilityVersion": 2}],
                    "managedPaths": ["docs/CONTEXT_BUDGET_POLICY.md"],
                    "verification": ["test-only"],
                }
            ),
            encoding="utf-8",
        )
        policy = self.framework / "templates/workflows/governed-sdd/docs/CONTEXT_BUDGET_POLICY.md"
        policy_text = policy.read_text(encoding="utf-8")
        marker = re.search(
            r"<!-- MERIDIAN:BEGIN capability=validation-scoping v2 -->\n?.*?"
            r"<!-- MERIDIAN:END -->\n?",
            policy_text,
            re.DOTALL,
        )
        self.assertIsNotNone(marker)
        policy.write_text(policy_text[: marker.start()] + policy_text[marker.end() :], encoding="utf-8")
        (self.framework / "VERSION").write_text("1.1.1\n", encoding="utf-8")

        # The project's local copy still carries the marker (upgrade has not
        # run yet), so the audit must catch it as retired-but-present, not
        # a generic "stale, run upgrade" SKIP.
        audited = self.run_cli("audit", "--mode", "governed-sdd")
        self.assertEqual(audited.returncode, 2, audited.stdout + audited.stderr)
        self.assertIn("FAIL", audited.stdout)
        self.assertIn("validation-scoping v2 is retired but still present", audited.stdout)

    def test_apply_refuses_conflicting_local_change(self) -> None:
        self.assertEqual(self.run_cli("lock", "--mode", "governed-sdd").returncode, 0)
        workflow = self.framework / "templates/workflows/governed-sdd/PROJECT_WORKFLOW.md"
        workflow.write_text(workflow.read_text(encoding="utf-8").replace("## Roles", "## Updated Roles"), encoding="utf-8")
        local = self.project / "PROJECT_WORKFLOW.md"
        local.write_text(local.read_text(encoding="utf-8").replace("## Roles", "## Local Roles"), encoding="utf-8")
        (self.framework / "VERSION").write_text("1.1.1\n", encoding="utf-8")

        applied = self.run_cli("upgrade", "--apply")
        self.assertEqual(applied.returncode, 2)
        self.assertIn("BLOCKED", applied.stderr)
        self.assertIn("## Local Roles", local.read_text(encoding="utf-8"))

    def test_router_project_upgrades_1_1_40_to_1_1_41_without_generated_drift(self) -> None:
        self.configure_1_1_40_to_1_1_41_upgrade()
        self.install_entry_router(include_restart=True)

        checked = self.run_cli("upgrade", "--check")
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertIn("ROUTER   AGENTS.md", checked.stdout)
        self.assertIn("ROUTER   CLAUDE.md", checked.stdout)
        self.assertNotIn("MERGE    AGENTS.md", checked.stdout)

        applied = self.run_cli("upgrade", "--apply")
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        outputs = meridian.entry_router_outputs(self.project)
        for target, expected in outputs.items():
            self.assertEqual((self.project / target).read_text(encoding="utf-8"), expected)
        self.assertEqual(meridian.audit_entry_router(self.project), [])
        manifest = json.loads((self.project / ".meridian/manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["managedFiles"]["AGENTS.md"], meridian.sha256(self.project / "AGENTS.md"))
        self.assertEqual(manifest["managedFiles"]["CLAUDE.md"], meridian.sha256(self.project / "CLAUDE.md"))

        noop = self.run_cli("upgrade", "--check")
        self.assertEqual(noop.returncode, 0, noop.stdout + noop.stderr)
        self.assertIn("ROUTER   AGENTS.md", noop.stdout)

    def test_router_project_missing_restart_trigger_blocks_before_writing(self) -> None:
        self.configure_1_1_40_to_1_1_41_upgrade()
        self.install_entry_router(include_restart=False)
        before = {
            path.relative_to(self.project): path.read_bytes()
            for path in self.project.rglob("*")
            if path.is_file()
        }

        checked = self.run_cli("upgrade", "--check")
        self.assertEqual(checked.returncode, 2, checked.stdout + checked.stderr)
        self.assertIn("ROUTER   AGENTS.md", checked.stdout)
        self.assertIn("missing trigger `Restart rejected <TASK-ID>`", checked.stdout)
        self.assertIn("for `docs/workflows/LIFECYCLE.md`", checked.stdout)
        self.assertIn("existing route line", checked.stdout)
        self.assertIn("exactly once", checked.stdout)

        applied = self.run_cli("upgrade", "--apply")
        self.assertEqual(applied.returncode, 2, applied.stdout + applied.stderr)
        after = {
            path.relative_to(self.project): path.read_bytes()
            for path in self.project.rglob("*")
            if path.is_file()
        }
        self.assertEqual(after, before)

    def test_project_without_entry_router_keeps_managed_entry_point_upgrade(self) -> None:
        self.configure_1_1_40_to_1_1_41_upgrade()

        checked = self.run_cli("upgrade", "--check")
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertIn("REPLACE  AGENTS.md", checked.stdout)
        self.assertIn("REPLACE  CLAUDE.md", checked.stdout)
        self.assertNotIn("ROUTER", checked.stdout)

        applied = self.run_cli("upgrade", "--apply")
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        self.assertIn(
            "`Restart rejected <TASK-ID>`",
            (self.project / "AGENTS.md").read_text(encoding="utf-8"),
        )

    def test_oldest_published_release_upgrades_to_current_in_one_apply(self) -> None:
        """Decision 6: the oldest published release reaches the current one in one step."""
        current_templates = self.framework / "templates/workflows/governed-sdd"
        shutil.rmtree(current_templates)
        # Verbatim templates/workflows/governed-sdd at tag v1.1.49; do not edit.
        with tarfile.open(ROOT / "tests/fixtures/release-1.1.49-governed-sdd.tar.gz") as archive:
            archive.extractall(current_templates.parent, filter="data")
        shutil.rmtree(self.project)
        self.project.mkdir()
        self.copy_governed_templates()
        (self.framework / "VERSION").write_text("1.1.49\n", encoding="utf-8")
        locked = self.run_cli("lock", "--mode", "governed-sdd")
        self.assertEqual(locked.returncode, 0, locked.stdout + locked.stderr)

        shutil.rmtree(current_templates)
        shutil.copytree(ROOT / "templates/workflows/governed-sdd", current_templates)
        current = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        (self.framework / "VERSION").write_text(current + "\n", encoding="utf-8")

        applied = self.run_cli("upgrade", "--apply")
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        manifest = json.loads((self.project / ".meridian/manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["frameworkVersion"], current)
        expected = [
            path.stem
            for path in sorted((self.framework / "migrations").glob("*.json"))
            if tuple(map(int, json.loads(path.read_text(encoding="utf-8"))["from"].split(".")))
            >= (1, 1, 49)
        ]
        self.assertTrue(expected, "the current release must apply at least one migration after 1.1.49")
        self.assertTrue(set(expected) <= set(manifest["appliedMigrations"]))
        noop = self.run_cli("upgrade", "--check")
        self.assertEqual(noop.returncode, 0, noop.stdout + noop.stderr)
        self.assertNotIn("CONFLICT", noop.stdout)

    def test_owner_reconciled_upgrade_registers_baseline_despite_conflicts(self) -> None:
        self.assertEqual(self.run_cli("lock", "--mode", "governed-sdd").returncode, 0)
        workflow = self.framework / "templates/workflows/governed-sdd/PROJECT_WORKFLOW.md"
        workflow.write_text(workflow.read_text(encoding="utf-8").replace("## Roles", "## Updated Roles"), encoding="utf-8")
        local = self.project / "PROJECT_WORKFLOW.md"
        local.write_text(local.read_text(encoding="utf-8").replace("## Roles", "## Local Roles"), encoding="utf-8")
        (self.framework / "VERSION").write_text("1.1.1\n", encoding="utf-8")

        rejected = self.run_cli("upgrade", "--check", "--owner-reconciled")
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("only applies to --apply", rejected.stderr)

        applied = self.run_cli("upgrade", "--apply", "--owner-reconciled")
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertIn("Owner-reconciled upgrade", applied.stdout)
        self.assertIn("## Local Roles", local.read_text(encoding="utf-8"))
        manifest = json.loads((self.project / ".meridian/manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["frameworkVersion"], "1.1.1")
        baselines = sorted(path.name for path in (self.project / ".meridian/baselines").iterdir())
        self.assertEqual(baselines, ["1.1.1"])
        baseline_workflow = self.project / ".meridian/baselines/1.1.1/PROJECT_WORKFLOW.md"
        self.assertIn("## Updated Roles", baseline_workflow.read_text(encoding="utf-8"))

    def test_check_reports_multiple_merge_conflicts(self) -> None:
        self.assertEqual(self.run_cli("lock", "--mode", "governed-sdd").returncode, 0)
        workflow = self.framework / "templates/workflows/governed-sdd/PROJECT_WORKFLOW.md"
        workflow.write_text(
            workflow.read_text(encoding="utf-8")
            .replace("## Roles", "## Updated Roles")
            .replace("## Git workflow", "## Updated Git workflow"),
            encoding="utf-8",
        )
        local = self.project / "PROJECT_WORKFLOW.md"
        local.write_text(
            local.read_text(encoding="utf-8")
            .replace("## Roles", "## Local Roles")
            .replace("## Git workflow", "## Local Git workflow"),
            encoding="utf-8",
        )
        (self.framework / "VERSION").write_text("1.1.1\n", encoding="utf-8")

        checked = self.run_cli("upgrade", "--check")
        self.assertEqual(checked.returncode, 2)
        self.assertIn("CONFLICT PROJECT_WORKFLOW.md", checked.stdout)
        self.assertIn(
            "BLOCKED UPGRADE_BLOCKED: 1 conflict(s); no files were changed; resume: resolve each conflict or router "
            "requirement that the plan lists, then rerun meridian upgrade --check",
            checked.stdout,
        )

    def test_adopt_applies_packaged_legacy_migrations(self) -> None:
        shutil.rmtree(self.project)
        self.project.mkdir()
        source = self.framework / "release-baselines/1.0.0/templates/workflows/governed-sdd"
        for path in source.rglob("*"):
            if path.is_file():
                destination = self.project / path.relative_to(source)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, destination)

        checked = self.run_cli("adopt", "--mode", "governed-sdd", "--from", "1.0.0", "--check")
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertIn("MIGRATION 001-review-remediation-record", checked.stdout)
        self.assertIn("MIGRATION 002-lifecycle-orchestration", checked.stdout)
        self.assertFalse((self.project / ".meridian").exists())

        applied = self.run_cli("adopt", "--mode", "governed-sdd", "--from", "1.0.0", "--apply")
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertTrue((self.project / "docs/REVIEW_RECORD_TEMPLATE.md").is_file())
        self.assertTrue((self.project / "docs/LIFECYCLE_ORCHESTRATION.md").is_file())
        manifest = json.loads((self.project / ".meridian/manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["frameworkVersion"], "1.1.0")
        self.assertEqual(manifest["workflowBaselineVersion"], "1.1.0")
        baselines = sorted(path.name for path in (self.project / ".meridian/baselines").iterdir())
        self.assertEqual(
            baselines,
            ["1.1.0"],
            "the intermediate 1.0.0 adoption baseline should be pruned once the target baseline lands",
        )

    def seed_unlocked_project_from_baseline(self) -> None:
        shutil.rmtree(self.project)
        self.project.mkdir()
        source = self.framework / "release-baselines/1.0.0/templates/workflows/governed-sdd"
        for path in source.rglob("*"):
            if path.is_file():
                destination = self.project / path.relative_to(source)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, destination)

    def test_adopt_writes_independent_framework_and_baseline_versions(self) -> None:
        self.seed_unlocked_project_from_baseline()
        for path in (self.framework / "migrations").glob("*.json"):
            path.unlink()
        (self.framework / "migrations/001-initial-baseline.json").write_text(
            json.dumps(
                {
                    "id": "001-initial-baseline",
                    "from": "1.0.0",
                    "to": "1.1.0",
                    "description": "test-only initial baseline",
                    "managedPaths": ["PROJECT_WORKFLOW.md"],
                    "verification": ["test-only"],
                }
            ),
            encoding="utf-8",
        )
        (self.framework / "VERSION").write_text("1.1.1\n", encoding="utf-8")

        applied = self.run_cli("adopt", "--mode", "governed-sdd", "--from", "1.0.0", "--apply")
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        manifest = json.loads((self.project / ".meridian/manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["frameworkVersion"], "1.1.1")
        self.assertEqual(manifest["workflowBaselineVersion"], "1.1.0")
        self.assertEqual(
            sorted(path.name for path in (self.project / ".meridian/baselines").iterdir()),
            ["1.1.0"],
        )

    def test_finalize_adoption_writes_independent_framework_and_baseline_versions(self) -> None:
        (self.framework / "VERSION").write_text("1.1.1\n", encoding="utf-8")
        for path in (self.framework / "migrations").glob("*.json"):
            if json.loads(path.read_text(encoding="utf-8"))["to"] != "1.1.0":
                path.unlink()
        shutil.rmtree(self.project)
        shutil.copytree(self.framework / "templates/workflows/governed-sdd", self.project)

        finalized = self.run_cli("finalize-adoption", "--mode", "governed-sdd", "--owner-accepted")
        self.assertEqual(finalized.returncode, 0, finalized.stdout + finalized.stderr)
        manifest = json.loads((self.project / ".meridian/manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["frameworkVersion"], "1.1.1")
        self.assertEqual(manifest["workflowBaselineVersion"], "1.1.0")

    def test_pre_marker_project_is_not_regressed_to_missing(self) -> None:
        """A project adopted before migration 006 has no MERIDIAN markers at
        all, only the old bare trigger phrases and template files. The legacy
        fallback correctly proves v1 for both capabilities — not the fully
        MISSING a naive marker-only check would report — but since 008/009
        bumped both to a required v2, v1-only evidence is now correctly
        insufficient rather than falsely treated as fully satisfied. The
        emitted delta must scope the fix to the v1->v2 change, not imply a
        from-scratch rewrite of a capability the project already has."""
        shutil.rmtree(self.project)
        self.project.mkdir()
        source = self.framework / "release-baselines/1.0.0/templates/workflows/governed-sdd"
        for path in source.rglob("*"):
            if path.is_file():
                destination = self.project / path.relative_to(source)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, destination)
        # Simulate a pre-006 adoption: bare trigger phrases and template files,
        # with no MERIDIAN:BEGIN marker anywhere (unlike the 1.0.0 baseline
        # itself, which has neither the phrases nor the files).
        (self.project / "docs/REVIEW_RECORD_TEMPLATE.md").write_text(
            "# Review Record\n\nNo marker here, just the pre-006 shape.\n", encoding="utf-8"
        )
        (self.project / "docs/LIFECYCLE_ORCHESTRATION.md").write_text(
            "# Autonomous Task Lifecycle Orchestration\n\nNo marker here either.\n", encoding="utf-8"
        )
        for name in ("AGENTS.md", "CLAUDE.md"):
            target = self.project / name
            target.write_text(
                target.read_text(encoding="utf-8") + "\nAddress review <TASK-ID>.\nRun lifecycle <TASK-ID>.\n",
                encoding="utf-8",
            )
        # Satisfy validation-scoping and ci-verified-validation too (both carry
        # markers in the current templates), so this test stays about the
        # 001/002 legacy fallback specifically rather than tripping on the two
        # newer, unrelated capabilities.
        current = self.framework / "templates/workflows/governed-sdd"
        for name in (
            "docs/CONTEXT_BUDGET_POLICY.md",
            "docs/PULL_REQUEST_POLICY.md",
            "docs/CODE_REVIEW_PROMPT.md",
            "docs/COMPLETION_REPORT_TEMPLATE.md",
        ):
            (self.project / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(current / name, self.project / name)

        planned = self.run_cli(
            "adopt", "--mode", "governed-sdd", "--from", "1.0.0", "--assisted", "--check"
        )
        self.assertEqual(planned.returncode, 3, planned.stdout)
        # The evidence text proves the legacy fallback did its job (v1 found),
        # distinct from "no marker found" — it's the v1->v2 gap that's real.
        self.assertIn(
            "CAPABILITY MISSING 067-execution-boundaries — no marker found; "
            "legacy pre-marker evidence only confirms v1, but v6 is required",
            planned.stdout,
        )
        self.assertIn(
            "CAPABILITY MISSING 067-execution-boundaries — no marker found; "
            "legacy pre-marker evidence only confirms v1, but v12 is required",
            planned.stdout,
        )
        self.assertIn("\nNEXT_ACTION IMPLEMENT_MIGRATION\n", planned.stdout)
        # The implementer is pointed at the delta, not a from-scratch rewrite:
        # the capability is already there, only its newest version is missing.
        self.assertIn("apply only this", planned.stdout)
        self.assertIn("061-governed-phase-reads: Each routed implementation", planned.stdout)
        self.assertIn("045-isolated-task-worktrees", planned.stdout)

    def test_assisted_adoption_detects_only_missing_lifecycle(self) -> None:
        shutil.rmtree(self.project)
        self.project.mkdir()
        source = self.framework / "release-baselines/1.0.0/templates/workflows/governed-sdd"
        for path in source.rglob("*"):
            if path.is_file():
                destination = self.project / path.relative_to(source)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, destination)
        current = self.framework / "templates/workflows/governed-sdd"
        shutil.copyfile(current / "docs/REVIEW_RECORD_TEMPLATE.md", self.project / "docs/REVIEW_RECORD_TEMPLATE.md")
        # Satisfy validation-scoping, ci-verified-validation, and
        # PROJECT_WORKFLOW.md's eight baseline capabilities (all carry markers
        # in the current templates) so this test can focus purely on the
        # 001/002 legacy-fallback progression it's actually about; a marker
        # only needs to be found somewhere among managed files, not
        # specifically in AGENTS.md/CLAUDE.md.
        for name in (
            "docs/CONTEXT_BUDGET_POLICY.md",
            "docs/PULL_REQUEST_POLICY.md",
            "docs/CODE_REVIEW_PROMPT.md",
            "docs/COMPLETION_REPORT_TEMPLATE.md",
            "PROJECT_WORKFLOW.md",
            "LANGUAGE_POLICY.md",
            "tasks/TASK_BLUEPRINT.md",
            "docs/CODE_ORGANIZATION.md",
            "docs/AUDIT_PROMPT_READ_ONLY.md",
        ):
            shutil.copyfile(current / name, self.project / name)
        for name in ("AGENTS.md", "CLAUDE.md"):
            target = self.project / name
            target.write_text(target.read_text(encoding="utf-8") + "\nAddress review <TASK-ID>.\n", encoding="utf-8")

        planned = self.run_cli(
            "adopt", "--mode", "governed-sdd", "--from", "1.0.0", "--assisted", "--check"
        )
        self.assertEqual(planned.returncode, 3)
        # detect_capabilities() names the migration that introduced the
        # highest required version, not necessarily the original one — 061
        # carries the v3 delta a project stuck below it actually needs to apply.
        self.assertIn(
            "CAPABILITY PRESENT 061-governed-phase-reads — marker present at v3 (>= required v3)",
            planned.stdout,
        )
        self.assertIn("CAPABILITY MISSING 045-isolated-task-worktrees", planned.stdout)
        self.assertIn("AGENT_REQUIRED", planned.stdout)
        self.assertIn("\nNEXT_ACTION IMPLEMENT_MIGRATION\n", planned.stdout)
        self.assertIn("IMPLEMENTER_PROMPT_BEGIN", planned.stdout)
        self.assertIn("REVIEWER_PROMPT_BEGIN", planned.stdout)
        self.assertIn("This reviewer session must be fresh", planned.stdout)
        self.assertIn("ORCHESTRATOR_PROMPT_BEGIN", planned.stdout)
        self.assertIn("adoption-review.md", planned.stdout)
        self.assertIn("045-isolated-task-worktrees", planned.stdout)
        self.assertIn("migrations/045-isolated-task-worktrees.json", planned.stdout)
        self.assertIn("/bin/meridian finalize-adoption", planned.stdout)
        self.assertFalse((self.project / ".meridian").exists())

        shutil.copyfile(current / "docs/LIFECYCLE_ORCHESTRATION.md", self.project / "docs/LIFECYCLE_ORCHESTRATION.md")
        for name in (
            "docs/workflows/IMPLEMENTATION.md",
            "docs/workflows/REVIEW.md",
            "docs/workflows/REMEDIATION.md",
            "docs/workflows/LIFECYCLE.md",
            "docs/WORKTREE_LIFECYCLE.md",
            ".codex/rules/meridian.rules",
            ".codex/hooks.json",
        ):
            (self.project / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(current / name, self.project / name)
        # Replace AGENTS.md/CLAUDE.md wholesale with the current, fully marked
        # templates rather than appending one more bare phrase: this test's
        # legacy-fallback evidence was already captured above, and the five
        # AGENTS.md/CLAUDE.md-only baseline capabilities from migration 012
        # have no legacy fallback of their own to satisfy any other way.
        for name in ("AGENTS.md", "CLAUDE.md"):
            shutil.copyfile(current / name, self.project / name)
        shutil.copyfile(
            current / "docs/EXECUTION_EVIDENCE_PROFILE.md",
            self.project / "docs/EXECUTION_EVIDENCE_PROFILE.md",
        )

        # All capabilities are now present, but nothing has been reviewed yet:
        # finalize must refuse, and the plan must ask for an independent review.
        refused = self.run_cli("finalize-adoption", "--mode", "governed-sdd")
        self.assertEqual(refused.returncode, 2)
        self.assertIn("no independent review record found", refused.stderr)

        reviewing = self.run_cli(
            "adopt", "--mode", "governed-sdd", "--from", "1.0.0", "--assisted", "--check"
        )
        self.assertEqual(reviewing.returncode, 3)
        self.assertIn("\nNEXT_ACTION REVIEW_MIGRATION\n", reviewing.stdout)
        self.assertNotIn("Perform the capability-aware Meridian adoption migration", reviewing.stdout)
        self.assertIn("REVIEWER_PROMPT_BEGIN", reviewing.stdout)

        review_path = self.project / ".meridian/adoption-review.md"
        review_path.parent.mkdir(parents=True, exist_ok=True)
        review_path.write_text(
            "# Adoption Review\n\nVerdict: APPROVE\nAttempt: 1\n\n## Findings\n",
            encoding="utf-8",
        )

        ready = self.run_cli(
            "adopt", "--mode", "governed-sdd", "--from", "1.0.0", "--assisted", "--check"
        )
        self.assertEqual(ready.returncode, 0)
        self.assertIn("\nNEXT_ACTION FINALIZE\n", ready.stdout)

        finalized = self.run_cli("finalize-adoption", "--mode", "governed-sdd")
        self.assertEqual(finalized.returncode, 0, finalized.stderr)
        self.assertTrue((self.project / ".meridian/manifest.json").is_file())

    def test_address_review_and_retry_limit(self) -> None:
        shutil.rmtree(self.project)
        self.project.mkdir()
        source = self.framework / "release-baselines/1.0.0/templates/workflows/governed-sdd"
        for path in source.rglob("*"):
            if path.is_file():
                destination = self.project / path.relative_to(source)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, destination)

        review_path = self.project / ".meridian/adoption-review.md"
        review_path.parent.mkdir(parents=True, exist_ok=True)
        review_path.write_text(
            "Verdict: CHANGES_REQUESTED\nAttempt: 1\n\n- [ ] add lifecycle orchestration\n",
            encoding="utf-8",
        )

        planned = self.run_cli(
            "adopt", "--mode", "governed-sdd", "--from", "1.0.0", "--assisted", "--check"
        )
        self.assertEqual(planned.returncode, 3)
        self.assertIn("\nNEXT_ACTION ADDRESS_REVIEW\n", planned.stdout)
        self.assertIn("ATTEMPT 1", planned.stdout)

        review_path.write_text(
            "Verdict: CHANGES_REQUESTED\nAttempt: 2\n\n- [ ] still missing lifecycle orchestration\n",
            encoding="utf-8",
        )
        blocked = self.run_cli(
            "adopt", "--mode", "governed-sdd", "--from", "1.0.0", "--assisted", "--check"
        )
        self.assertEqual(blocked.returncode, 2)
        line = next(line for line in blocked.stderr.splitlines() if line.startswith("BLOCKED "))
        self.assertTrue(
            line.startswith("BLOCKED ADOPTION_BLOCKED: two consecutive CHANGES_REQUESTED verdicts (attempt 2); resolve "),
            line,
        )
        self.assertTrue(
            line.endswith(
                "manually before retrying; resume: resolve the adoption review record that the detail names manually, "
                "then restart the assisted adoption loop"
            ),
            line,
        )

    def test_emit_returns_single_prompt_block(self) -> None:
        shutil.rmtree(self.project)
        self.project.mkdir()
        source = self.framework / "release-baselines/1.0.0/templates/workflows/governed-sdd"
        for path in source.rglob("*"):
            if path.is_file():
                destination = self.project / path.relative_to(source)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, destination)

        emitted = self.run_cli(
            "adopt", "--mode", "governed-sdd", "--from", "1.0.0", "--assisted", "--check",
            "--emit", "implementer",
        )
        self.assertEqual(emitted.returncode, 3)
        self.assertNotIn("IMPLEMENTER_PROMPT_BEGIN", emitted.stdout)
        self.assertIn("Perform the capability-aware Meridian adoption migration", emitted.stdout)

        rejected = self.run_cli(
            "adopt", "--mode", "governed-sdd", "--from", "1.0.0", "--assisted", "--check",
            "--emit", "reviewer",
        )
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("no reviewer prompt applies", rejected.stderr)

    def test_assisted_adoption_refuses_lean_delivery(self) -> None:
        shutil.rmtree(self.project)
        self.project.mkdir()
        planned = self.run_cli(
            "adopt", "--mode", "lean-delivery", "--from", "1.0.0", "--assisted", "--check"
        )
        self.assertEqual(planned.returncode, 2)
        self.assertIn("tracks capabilities only for governed-sdd", planned.stderr)

    def test_finalize_owner_accepted_bypasses_review_gate(self) -> None:
        shutil.rmtree(self.project)
        self.project.mkdir()
        source = self.framework / "release-baselines/1.0.0/templates/workflows/governed-sdd"
        for path in source.rglob("*"):
            if path.is_file():
                destination = self.project / path.relative_to(source)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, destination)
        current = self.framework / "templates" / "workflows" / "governed-sdd"
        for name in (
            "AGENTS.md",
            "CLAUDE.md",
            "PROJECT_WORKFLOW.md",
            "LANGUAGE_POLICY.md",
            "tasks/TASK_BLUEPRINT.md",
            "docs/CODE_ORGANIZATION.md",
            "docs/AUDIT_PROMPT_READ_ONLY.md",
            "docs/REVIEW_RECORD_TEMPLATE.md",
            "docs/LIFECYCLE_ORCHESTRATION.md",
            "docs/CONTEXT_BUDGET_POLICY.md",
            "docs/EXECUTION_EVIDENCE_PROFILE.md",
            "docs/PULL_REQUEST_POLICY.md",
            "docs/CODE_REVIEW_PROMPT.md",
            "docs/COMPLETION_REPORT_TEMPLATE.md",
            "docs/workflows/IMPLEMENTATION.md",
            "docs/workflows/REVIEW.md",
            "docs/workflows/REMEDIATION.md",
            "docs/workflows/LIFECYCLE.md",
            "docs/WORKTREE_LIFECYCLE.md",
            ".codex/rules/meridian.rules",
            ".codex/hooks.json",
        ):
            (self.project / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(current / name, self.project / name)

        refused = self.run_cli("finalize-adoption", "--mode", "governed-sdd")
        self.assertEqual(refused.returncode, 2)

        accepted = self.run_cli("finalize-adoption", "--mode", "governed-sdd", "--owner-accepted")
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.assertIn("Owner-accepted finalize", accepted.stdout)
        self.assertTrue((self.project / ".meridian/manifest.json").is_file())

    def test_mode_and_version_autodetect(self) -> None:
        shutil.rmtree(self.project)
        self.project.mkdir()
        source = self.framework / "release-baselines/1.0.0/templates/workflows/governed-sdd"
        for path in source.rglob("*"):
            if path.is_file():
                destination = self.project / path.relative_to(source)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, destination)

        result = subprocess.run(
            [
                sys.executable,
                str(CLI),
                "--framework-root",
                str(self.framework),
                "adopt",
                "--assisted",
                "--check",
                "--project",
                str(self.project),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertIn("Assisted adoption 1.0.0 ->", result.stdout)


class MarkerSupersessionTest(unittest.TestCase):
    """`append_only_new_markers` must distinguish an added capability from a
    superseded one by name, not by `(name, version)` pair — task 012 of
    docs/PLAN_TOKEN_EFFICIENCY.md. Under pair comparison, a version bump is
    indistinguishable from an unrelated new capability: the bumped pair is
    absent from both the local and base pair sets exactly like a genuinely
    new one, so the old block gets left in place while the new one is
    appended at the end, where nothing reads it.
    """

    BASE = (
        "intro\n\n"
        "<!-- MERIDIAN:BEGIN capability=mvp v1 -->\n"
        "old rule text.\n"
        "<!-- MERIDIAN:END -->\n\n"
        "tail\n"
    )
    OLD_BLOCK = "<!-- MERIDIAN:BEGIN capability=mvp v1 -->\nold rule text.\n<!-- MERIDIAN:END -->"
    NEW_BLOCK = "<!-- MERIDIAN:BEGIN capability=mvp v2 -->\nnew rule text.\n<!-- MERIDIAN:END -->"

    def test_added_capability_still_appends(self) -> None:
        template = self.BASE + (
            "\n<!-- MERIDIAN:BEGIN capability=other v1 -->\n"
            "new capability.\n"
            "<!-- MERIDIAN:END -->\n"
        )
        result = meridian.append_only_new_markers(self.BASE, self.BASE, template)
        self.assertIsNotNone(result)
        self.assertIn("old rule text.", result)
        self.assertIn("new capability.", result)

    def test_bumped_capability_with_unmodified_block_replaces_in_place(self) -> None:
        template = self.BASE.replace(self.OLD_BLOCK, self.NEW_BLOCK)
        result = meridian.append_only_new_markers(self.BASE, self.BASE, template)
        self.assertIsNotNone(result)
        self.assertIn("capability=mvp v2", result)
        self.assertIn("new rule text.", result)
        self.assertNotIn("capability=mvp v1", result)
        self.assertNotIn("old rule text.", result)
        # Surrounding project-owned text is preserved untouched, in place.
        self.assertIn("intro", result)
        self.assertIn("tail", result)
        self.assertEqual(result.index("intro"), self.BASE.index("intro"))

    def test_bumped_capability_with_modified_block_returns_none(self) -> None:
        local = self.BASE.replace("old rule text.", "old rule text, locally customized.")
        template = self.BASE.replace(self.OLD_BLOCK, self.NEW_BLOCK)
        result = meridian.append_only_new_markers(local, self.BASE, template)
        self.assertIsNone(result)

    def test_local_file_with_two_existing_versions_is_left_untouched(self) -> None:
        local = self.BASE + "\n" + self.NEW_BLOCK + "\n"
        template = self.BASE.replace(self.OLD_BLOCK, self.NEW_BLOCK)
        result = meridian.append_only_new_markers(local, self.BASE, template)
        self.assertIsNone(result)

    def test_edited_unchanged_version_block_blocks_an_otherwise_safe_append(self) -> None:
        """A capability whose version does not change must still be checked
        against the base: an unrelated new capability elsewhere in the same
        template must not cause the function to silently accept a project's
        edit to a different, already-current protected block."""
        local = self.BASE.replace("old rule text.", "old rule text, locally edited.")
        template = self.BASE + (
            "\n<!-- MERIDIAN:BEGIN capability=other v1 -->\n"
            "new capability.\n"
            "<!-- MERIDIAN:END -->\n"
        )
        result = meridian.append_only_new_markers(local, self.BASE, template)
        self.assertIsNone(result)


class RetiredTextAdvisoryTest(unittest.TestCase):
    def test_scanner_limits_version_paths_and_managed_regions(self) -> None:
        entry = meridian.load_retired_text_registry(ROOT)[0]
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            for relative_path in entry["files"]:
                path = project / relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    "intro\n<!-- MERIDIAN:BEGIN capability=example v1 -->\n"
                    + "\n".join(entry["phrases"])
                    + "\n<!-- MERIDIAN:END -->\n"
                    + "\n".join(phrase.upper() for phrase in entry["phrases"]) + "\n",
                    encoding="utf-8",
                )
            for relative_path in ("tasks/001.md", "tasks/handoffs/001.md", "tasks/reviews/001.md", "tasks/done/001.md", "tasks/QUEUE_ARCHIVE.md"):
                path = project / relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("\n".join(entry["phrases"]), encoding="utf-8")
            self.assertEqual(meridian.retired_text_advisories(project, ROOT, {"frameworkVersion": "1.2.8"}), [])
            for version in ("1.2.9", "1.2.12"):
                rows = meridian.retired_text_advisories(project, ROOT, {"frameworkVersion": version})
                self.assertEqual(len(rows), len(entry["files"]) * len(entry["phrases"]))
                for row in rows:
                    self.assertEqual(row.status, "ADVISORY")
                    self.assertIn("retired capability=reasoning-budget-contract", row.detail)
                    self.assertIn(entry["remedy"], row.detail)
                    self.assertRegex(row.detail, r"docs/[^:]+:(?:9|10|11|12|13):")
            for relative_path in entry["files"]:
                (project / relative_path).write_text("clean project text\n", encoding="utf-8")
            self.assertEqual(meridian.retired_text_advisories(project, ROOT, {"frameworkVersion": "1.2.9"}), [])

    def test_phrase_matching_is_literal_and_preserves_inline_line_numbers(self) -> None:
        entry = {"capability": "example", "retiredIn": "1.2.9", "phrases": ["cap [a-z].*"], "files": ["docs/example.md"], "remedy": "Remove by hand."}
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(meridian, "load_retired_text_registry", return_value=[entry]):
            project = Path(directory)
            path = project / "docs/example.md"
            path.parent.mkdir()
            path.write_text("cap abc\n<!-- MERIDIAN:BEGIN capability=example v1 -->cap [a-z].*<!-- MERIDIAN:END --> CAP [A-Z].*\n", encoding="utf-8")
            rows = meridian.retired_text_advisories(project, ROOT, {"frameworkVersion": "1.2.9"})
            self.assertEqual(len(rows), 1)
            self.assertIn("docs/example.md:2:", rows[0].detail)

    def test_registry_matches_published_schema(self) -> None:
        schema = json.loads((ROOT / "schemas/retired-text-v1.schema.json").read_text(encoding="utf-8"))
        data = json.loads((ROOT / "capabilities/retired-text-v1.json").read_text(encoding="utf-8"))
        self.assertEqual(set(data), set(schema["required"]))
        self.assertEqual(data["version"], schema["properties"]["version"]["const"])
        item = schema["properties"]["retirements"]["items"]
        for entry in meridian.load_retired_text_registry(ROOT):
            self.assertEqual(set(entry), set(item["required"]))
            for key, value in entry.items():
                rule = item["properties"][key]
                if rule["type"] == "string":
                    self.assertIsInstance(value, str)
                    if "pattern" in rule:
                        self.assertRegex(value, rule["pattern"])
                else:
                    self.assertIsInstance(value, list)
                    self.assertGreaterEqual(len(value), rule["minItems"])
                    self.assertEqual(len(value), len(set(value)))
                    for text in value:
                        self.assertIsInstance(text, str)
                        self.assertGreaterEqual(len(text), rule["items"]["minLength"])
                        if "pattern" in rule["items"]:
                            self.assertRegex(text, rule["items"]["pattern"])


class CapabilityRetirementTest(unittest.TestCase):
    """`remove_retired_markers` (task 007 of docs/PLAN_TOKEN_EFFICIENCY.md):
    the retirement mirror of `append_only_new_markers`'s supersession case.
    Safe to delete a capability's block only when the local copy still
    matches the project's own locked baseline byte-for-byte; refuse
    otherwise so a local edit under a marker about to be deleted is never
    silently discarded along with it.
    """

    BASE = (
        "intro\n\n"
        "<!-- MERIDIAN:BEGIN capability=old-rule v1 -->\n"
        "retired rule text.\n"
        "<!-- MERIDIAN:END -->\n\n"
        "tail\n"
    )

    def test_retires_an_unmodified_block(self) -> None:
        result = meridian.remove_retired_markers(self.BASE, self.BASE, [("old-rule", 1)])
        self.assertIsNotNone(result)
        self.assertNotIn("capability=old-rule", result)
        self.assertNotIn("retired rule text.", result)
        # Surrounding project-owned text survives untouched.
        self.assertIn("intro", result)
        self.assertIn("tail", result)

    def test_retiring_an_already_absent_block_is_idempotent(self) -> None:
        local = self.BASE.replace(
            "<!-- MERIDIAN:BEGIN capability=old-rule v1 -->\n"
            "retired rule text.\n"
            "<!-- MERIDIAN:END -->\n\n",
            "",
        )
        result = meridian.remove_retired_markers(local, self.BASE, [("old-rule", 1)])
        self.assertEqual(result, local)

    def test_refuses_to_retire_a_locally_modified_block(self) -> None:
        local = self.BASE.replace("retired rule text.", "retired rule text, locally customized.")
        result = meridian.remove_retired_markers(local, self.BASE, [("old-rule", 1)])
        self.assertIsNone(result)

    def test_returns_input_unchanged_when_nothing_in_the_list_applies(self) -> None:
        result = meridian.remove_retired_markers(self.BASE, self.BASE, [("unrelated-capability", 1)])
        self.assertEqual(result, self.BASE)

    def test_refuses_when_the_same_block_appears_twice_in_one_file(self) -> None:
        """`str.replace` is content-addressed: deleting only the first of two
        byte-identical occurrences would be a silent partial mutation. Must
        refuse instead, the same duplicate-paste case `audit_duplicate_headings`
        exists to catch."""
        duplicated = self.BASE + (
            "\n<!-- MERIDIAN:BEGIN capability=old-rule v1 -->\n"
            "retired rule text.\n"
            "<!-- MERIDIAN:END -->\n"
        )
        result = meridian.remove_retired_markers(duplicated, duplicated, [("old-rule", 1)])
        self.assertIsNone(result)

    def test_removal_collapses_only_the_local_blank_line_gap(self) -> None:
        """The blank-line cleanup after a deletion must be scoped to the
        splice point, never touching an unrelated run of blank lines
        elsewhere in the same file."""
        text = (
            "intro\n\n"
            "<!-- MERIDIAN:BEGIN capability=old-rule v1 -->\n"
            "retired rule text.\n"
            "<!-- MERIDIAN:END -->\n\n"
            "middle\n\n\n\n"
            "tail\n"
        )
        result = meridian.remove_retired_markers(text, text, [("old-rule", 1)])
        self.assertIsNotNone(result)
        self.assertEqual(result, "intro\n\nmiddle\n\n\n\ntail\n")

    def test_capability_requirements_drops_a_retired_capability(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        framework = Path(temporary.name)
        migrations = framework / "migrations"
        migrations.mkdir()
        (migrations / "001-add.json").write_text(
            json.dumps(
                {
                    "id": "001-add",
                    "from": "1.0.0",
                    "to": "1.1.0",
                    "capability": "old-rule",
                    "capabilityVersion": 1,
                    "managedPaths": ["AGENTS.md"],
                }
            ),
            encoding="utf-8",
        )
        (migrations / "002-retire.json").write_text(
            json.dumps(
                {
                    "id": "002-retire",
                    "from": "1.1.0",
                    "to": "1.2.0",
                    "removes": [{"capability": "old-rule", "capabilityVersion": 1}],
                    "managedPaths": ["AGENTS.md"],
                }
            ),
            encoding="utf-8",
        )
        requirements = meridian.capability_requirements(framework)
        self.assertNotIn("old-rule", requirements)
        self.assertIn("old-rule", meridian.retired_capability_ids(framework))

    def test_capability_requirements_honors_a_later_reintroduction(self) -> None:
        """A capability retired by one migration and reintroduced by a later
        one must end up required again — removal and addition are applied in
        migration sequence order, not as an unordered set operation."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        framework = Path(temporary.name)
        migrations = framework / "migrations"
        migrations.mkdir()
        (migrations / "001-add.json").write_text(
            json.dumps(
                {
                    "id": "001-add",
                    "from": "1.0.0",
                    "to": "1.1.0",
                    "capability": "reused-rule",
                    "capabilityVersion": 1,
                    "managedPaths": ["AGENTS.md"],
                }
            ),
            encoding="utf-8",
        )
        (migrations / "002-retire.json").write_text(
            json.dumps(
                {
                    "id": "002-retire",
                    "from": "1.1.0",
                    "to": "1.2.0",
                    "removes": [{"capability": "reused-rule", "capabilityVersion": 1}],
                    "managedPaths": ["AGENTS.md"],
                }
            ),
            encoding="utf-8",
        )
        (migrations / "003-reintroduce.json").write_text(
            json.dumps(
                {
                    "id": "003-reintroduce",
                    "from": "1.2.0",
                    "to": "1.3.0",
                    "capability": "reused-rule",
                    "capabilityVersion": 1,
                    "managedPaths": ["AGENTS.md"],
                }
            ),
            encoding="utf-8",
        )
        requirements = meridian.capability_requirements(framework)
        self.assertIn("reused-rule", requirements)
        self.assertEqual(requirements["reused-rule"], (1, "003-reintroduce"))

    def test_removals_for_managed_file_scopes_by_managed_paths(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        framework = Path(temporary.name)
        migrations = framework / "migrations"
        migrations.mkdir()
        (migrations / "001-retire.json").write_text(
            json.dumps(
                {
                    "id": "001-retire",
                    "from": "1.0.0",
                    "to": "1.1.0",
                    "removes": [{"capability": "old-rule", "capabilityVersion": 1, "supersededBy": "new-rule"}],
                    "managedPaths": ["AGENTS.md", "CLAUDE.md"],
                }
            ),
            encoding="utf-8",
        )
        for_agents = meridian.removals_for_managed_file(framework, ["001-retire"], Path("AGENTS.md"))
        self.assertEqual(for_agents, [("old-rule", 1, "new-rule")])
        for_unrelated = meridian.removals_for_managed_file(
            framework, ["001-retire"], Path("docs/UNRELATED.md")
        )
        self.assertEqual(for_unrelated, [])


class GenerateClaudeMdTest(unittest.TestCase):
    """`CLAUDE.md` is generated from `AGENTS.md` (task 004 of
    docs/PLAN_TOKEN_EFFICIENCY.md): from `meridian.CLAUDE_MD_SHARED_ANCHOR`'s
    heading onward, the committed `CLAUDE.md` must be byte-identical to what
    `generate_claude_md` derives from the committed `AGENTS.md`, so the two
    files cannot independently drift on content meant to be shared. Everything
    above the anchor is each file's own hand-authored preamble and is exempt.
    """

    def test_committed_claude_md_matches_the_generator_for_every_mode(self) -> None:
        for mode in meridian.CLAUDE_MD_SHARED_ANCHOR:
            workflow = ROOT / "templates" / "workflows" / mode
            agents_text = (workflow / "AGENTS.md").read_text(encoding="utf-8")
            claude_text = (workflow / "CLAUDE.md").read_text(encoding="utf-8")
            generated = meridian.generate_claude_md(mode, agents_text, claude_text)
            self.assertEqual(
                generated,
                claude_text,
                f"{mode}: CLAUDE.md has drifted from AGENTS.md past the shared anchor "
                f"{meridian.CLAUDE_MD_SHARED_ANCHOR[mode]!r}",
            )

    def test_generator_reports_drift_when_claude_md_diverges(self) -> None:
        agents_text = (
            "# [Project Name] — Agent Rules\n\npreamble\n\n"
            "## Code organization\n\nshared body.\n"
        )
        stale_claude_text = (
            "# [Project Name]\n\nown preamble\n\n"
            "## Code organization\n\nSTALE shared body.\n"
        )
        generated = meridian.generate_claude_md("governed-sdd", agents_text, stale_claude_text)
        self.assertNotEqual(generated, stale_claude_text)
        self.assertIn("own preamble", generated)
        self.assertIn("shared body.\n", generated)
        self.assertNotIn("STALE", generated)

    def test_generator_preserves_marker_content_verbatim_even_when_agents_md_disagrees(self) -> None:
        """The regression guard for task 014: task 004's generator copied a
        marker's content from AGENTS.md, silently changing what a released
        capability version means for every adopted project. The self-
        consistency test above can never catch that, because it compares the
        generator's output to a `CLAUDE.md` that was itself regenerated by the
        same generator. This test instead gives AGENTS.md and CLAUDE.md
        genuinely different text for the same capability+version marker and
        asserts the output keeps CLAUDE.md's own text, byte for byte — a
        marker's content may only change via a version bump and a migration,
        never via this generator.
        """
        agents_text = (
            "# [Project Name] — Agent Rules\n\npreamble\n\n"
            "## Code organization\n\n"
            "<!-- MERIDIAN:BEGIN capability=example-capability v1 -->\n"
            "NEW WORDING the generator must not introduce.\n"
            "<!-- MERIDIAN:END -->\n"
        )
        claude_text = (
            "# [Project Name]\n\nown preamble\n\n"
            "## Code organization\n\n"
            "<!-- MERIDIAN:BEGIN capability=example-capability v1 -->\n"
            "ORIGINAL RELEASED WORDING.\n"
            "<!-- MERIDIAN:END -->\n"
        )
        generated = meridian.generate_claude_md("governed-sdd", agents_text, claude_text)
        self.assertIn("ORIGINAL RELEASED WORDING.", generated)
        self.assertNotIn("NEW WORDING", generated)
        for capability, version in meridian.marker_pairs(claude_text):
            self.assertEqual(
                meridian.extract_marked_block(generated, capability, version),
                meridian.extract_marked_block(claude_text, capability, version),
                f"capability={capability} v{version} was altered by the generator",
            )

    def test_generator_copies_a_brand_new_marker_claude_md_does_not_have_yet(self) -> None:
        """A capability with no existing block in CLAUDE.md has nothing to
        preserve; the generator's only source for its first appearance is
        AGENTS.md, same as any other shared-body text."""
        agents_text = (
            "# [Project Name] — Agent Rules\n\npreamble\n\n"
            "## Code organization\n\n"
            "<!-- MERIDIAN:BEGIN capability=brand-new-capability v1 -->\n"
            "First-ever wording.\n"
            "<!-- MERIDIAN:END -->\n"
        )
        claude_text = "# [Project Name]\n\nown preamble\n\n## Code organization\n\nno markers here.\n"
        generated = meridian.generate_claude_md("governed-sdd", agents_text, claude_text)
        self.assertIn("First-ever wording.", generated)

    def test_generator_raises_when_the_anchor_heading_is_missing(self) -> None:
        with self.assertRaises(meridian.MeridianError):
            meridian.generate_claude_md("governed-sdd", "no anchor here", "## Code organization\nbody")
        with self.assertRaises(meridian.MeridianError):
            meridian.generate_claude_md("governed-sdd", "## Code organization\nbody", "no anchor here")

    def test_cli_check_and_write_round_trip_on_a_stale_copy(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        framework = Path(temporary.name) / "framework"
        workflow = framework / "templates" / "workflows" / "governed-sdd"
        workflow.mkdir(parents=True)
        source = ROOT / "templates" / "workflows" / "governed-sdd"
        agents_text = (source / "AGENTS.md").read_text(encoding="utf-8")
        claude_text = (source / "CLAUDE.md").read_text(encoding="utf-8")
        (workflow / "AGENTS.md").write_text(
            agents_text.replace("## Command triggers", "## Command triggers\n\nstale.", 1),
            encoding="utf-8",
        )
        (workflow / "CLAUDE.md").write_text(claude_text, encoding="utf-8")

        def run(*extra: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [
                    sys.executable,
                    str(CLI),
                    "--framework-root",
                    str(framework),
                    "generate-claude-md",
                    "--mode",
                    "governed-sdd",
                    *extra,
                ],
                text=True,
                capture_output=True,
                check=False,
            )

        checked_before = run("--check")
        self.assertEqual(checked_before.returncode, 2)
        self.assertIn("STALE", checked_before.stderr)

        written = run("--write")
        self.assertEqual(written.returncode, 0, written.stderr)

        checked_after = run("--check")
        self.assertEqual(checked_after.returncode, 0, checked_after.stderr)
        self.assertIn(
            "stale.", (workflow / "CLAUDE.md").read_text(encoding="utf-8")
        )


class GeneratedEntryRouterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.project = Path(self.temporary.name)
        workflows = self.project / "docs/workflows"
        workflows.mkdir(parents=True)
        self.router = workflows / "ENTRY_ROUTER.md"
        self.router.write_text(
            "# Project Router\n\n"
            "- Status: `docs/workflows/STATUS_DESIGN.md`\n"
            "- Proceed: `docs/workflows/IMPLEMENTATION.md`\n"
            "- Review: `docs/workflows/REVIEW.md`\n"
            "- Address review: `docs/workflows/REMEDIATION.md`\n"
            "- Lifecycle or Accept: `docs/workflows/LIFECYCLE.md`\n"
            "- Audit: `docs/AUDIT_PROMPT_READ_ONLY.md`\n",
            encoding="utf-8",
        )
        (workflows / "ENTRY_ROUTER_MAP.json").write_text(
            json.dumps(meridian.ENTRY_ROUTER_ROUTES, indent=2) + "\n", encoding="utf-8"
        )
        for route, path in meridian.ENTRY_ROUTER_ROUTES.items():
            target = self.project / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                "# Routed procedure\n\n" + " ".join(meridian.ENTRY_ROUTER_SAFEGUARDS[route]) + "\n",
                encoding="utf-8",
            )

    def test_renders_identical_entry_points_and_audits_routes(self) -> None:
        outputs = meridian.entry_router_outputs(self.project)
        self.assertEqual(outputs[Path("AGENTS.md")], outputs[Path("CLAUDE.md")])
        for target, content in outputs.items():
            (self.project / target).write_text(content, encoding="utf-8")
        self.assertEqual(meridian.audit_entry_router(self.project), [])

    def test_allows_a_comment_only_host_overlay_but_rejects_instruction_text(self) -> None:
        overlay = self.project / "docs/workflows/ENTRY_ROUTER.CLAUDE.overlay.md"
        overlay.write_text("<!-- Claude host metadata -->\n", encoding="utf-8")
        outputs = meridian.entry_router_outputs(self.project)
        self.assertIn("<!-- Claude host metadata -->", outputs[Path("CLAUDE.md")])
        self.assertNotIn("<!-- Claude host metadata -->", outputs[Path("AGENTS.md")])
        overlay.write_text("Read this extra instruction.\n", encoding="utf-8")
        with self.assertRaises(meridian.MeridianError):
            meridian.entry_router_outputs(self.project)

    def test_audit_reports_generated_drift_missing_route_and_budget_failure(self) -> None:
        outputs = meridian.entry_router_outputs(self.project)
        for target, content in outputs.items():
            (self.project / target).write_text(content, encoding="utf-8")
        (self.project / "AGENTS.md").write_text("stale\n", encoding="utf-8")
        self.assertTrue(any("generated entry router drift" in detail for _status, detail in meridian.audit_entry_router(self.project)))
        (self.project / "AGENTS.md").write_text(outputs[Path("AGENTS.md")], encoding="utf-8")
        (self.project / "docs/workflows/ENTRY_ROUTER_MAP.json").write_text("{}\n", encoding="utf-8")
        self.assertTrue(any("route map must declare exactly" in detail for _status, detail in meridian.audit_entry_router(self.project)))
        self.router.write_text("x" * (meridian.ENTRY_ROUTER_BUDGET_BYTES + 1), encoding="utf-8")
        with self.assertRaises(meridian.MeridianError):
            meridian.entry_router_outputs(self.project)

    def test_generator_refuses_to_emit_a_pointer(self) -> None:
        self.router.write_text(
            "<!-- MERIDIAN:CLAUDE-AGENTS-POINTER v1 -->\n\nRead `AGENTS.md`.\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(meridian.MeridianError, "must not emit a Claude-to-AGENTS pointer"):
            meridian.entry_router_outputs(self.project)

    def test_cli_checks_and_writes_both_entry_points(self) -> None:
        command = [sys.executable, str(CLI), "--framework-root", str(ROOT), "generate-entry-routers", "--project", str(self.project)]
        stale = subprocess.run(command + ["--check"], text=True, capture_output=True, check=False)
        self.assertEqual(stale.returncode, 2, stale.stdout + stale.stderr)
        written = subprocess.run(command + ["--write"], text=True, capture_output=True, check=False)
        self.assertEqual(written.returncode, 0, written.stdout + written.stderr)
        checked = subprocess.run(command + ["--check"], text=True, capture_output=True, check=False)
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)


class BudgetCliTest(unittest.TestCase):
    """`meridian budget`: durable per-task-per-attempt diagnostic/evidence/
    context-expansion counters (task 006 of docs/PLAN_TOKEN_EFFICIENCY.md)."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.project = Path(self.temporary.name) / "project"
        (self.project / "tasks").mkdir(parents=True)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_task(self, task_id: str, status: str, **overrides: str) -> None:
        lines = [f"Status: {status}"]
        for field, value in overrides.items():
            lines.append(f"{field}: {value}")
        (self.project / "tasks" / f"{task_id}.md").write_text(
            "\n".join(lines) + "\n", encoding="utf-8"
        )

    def budget_state(self) -> dict:
        return json.loads((self.project / ".meridian/budget.json").read_text(encoding="utf-8"))

    def append_contract(self, task_id: str) -> None:
        path = self.project / "tasks" / f"{task_id}.md"
        path.write_text(path.read_text(encoding="utf-8") + "\n" + meridian.execution_contract(self.project, task_id) + "\n", encoding="utf-8")

    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CLI), *arguments, "--project", str(self.project)],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_show_defaults_with_no_state(self) -> None:
        self.write_task("TASK-001", "IN_PROGRESS")
        result = self.run_cli("budget", "show", "TASK-001")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.strip(),
            "Attempt 1 · Diagnostics 0/3 · Captures 0/2 · Expansions 0/2 · Investigations 0/2",
        )

    def test_show_resolves_nested_project_tasks_and_profile_defaults(self) -> None:
        (self.project / "tasks/TASK-007.md").unlink(missing_ok=True)
        nested = self.project / "docs/tasks/M19"
        nested.mkdir(parents=True)
        (nested / "TASK-007.md").write_text("Status: IN_PROGRESS\n", encoding="utf-8")
        (self.project / "PROJECT_WORKFLOW.md").write_text(
            "<!-- MERIDIAN:BEGIN capability=execution-assets v1 -->\n"
            "<!-- MERIDIAN:END -->\n"
            "Task files live under `docs/tasks/<milestone>/`; queue is `docs/TASK_QUEUE.md`.\n\n## Roles\n",
            encoding="utf-8",
        )
        profile = self.project / "docs/EXECUTION_EVIDENCE_PROFILE.md"
        profile.parent.mkdir(exist_ok=True)
        profile.write_text(
            "`Diagnostic attempts`: 4 per failure.\n"
            "`Evidence captures`: 5 per acceptance criterion.\n"
            "`Context expansions`: 6 per task.\n"
            "`Investigation scope`: 7 per task.\n",
            encoding="utf-8",
        )
        result = self.run_cli("budget", "show", "TASK-007")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.strip(),
            "Attempt 1 · Diagnostics 0/4 · Captures 0/5 · Expansions 0/6 · Investigations 0/7",
        )

    def test_show_ignores_nested_review_record_with_the_same_task_id(self) -> None:
        nested = self.project / "docs/tasks/M19"
        review = self.project / "docs/tasks/reviews"
        nested.mkdir(parents=True)
        review.mkdir(parents=True)
        (nested / "M19-HUD-010.md").write_text(
            "Status: IN_PROGRESS\n", encoding="utf-8"
        )
        (review / "M19-HUD-010.md").write_text(
            "Verdict: CHANGES_REQUESTED\n", encoding="utf-8"
        )
        (self.project / "PROJECT_WORKFLOW.md").write_text(
            "<!-- MERIDIAN:BEGIN capability=execution-assets v1 -->\n"
            "<!-- MERIDIAN:END -->\n"
            "Task files live under `docs/tasks/<milestone>/`; queue is `docs/TASK_QUEUE.md`.\n\n## Roles\n",
            encoding="utf-8",
        )

        result = self.run_cli("budget", "show", "M19-HUD-010")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Diagnostics 0/3", result.stdout)

    def test_show_ignores_nested_completion_handoff_with_the_same_task_id(self) -> None:
        nested = self.project / "docs/tasks/M19"
        handoffs = self.project / "tasks/handoffs"
        nested.mkdir(parents=True)
        handoffs.mkdir(parents=True)
        (nested / "M19-HUD-010.md").write_text(
            "Status: IN_PROGRESS\n", encoding="utf-8"
        )
        (handoffs / "M19-HUD-010.md").write_text(
            "## Completion Report — M19-HUD-010\n", encoding="utf-8"
        )
        (self.project / "PROJECT_WORKFLOW.md").write_text(
            "<!-- MERIDIAN:BEGIN capability=execution-assets v1 -->\n"
            "<!-- MERIDIAN:END -->\n"
            "Task files live under `docs/tasks/<milestone>/`; queue is `docs/TASK_QUEUE.md`.\n\n## Roles\n",
            encoding="utf-8",
        )

        result = self.run_cli("budget", "show", "M19-HUD-010")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Diagnostics 0/3", result.stdout)

    def test_locations_and_preflight_use_the_declared_queue(self) -> None:
        (self.project / "docs/tasks/M19").mkdir(parents=True)
        (self.project / "docs/tasks/M19/TASK-007.md").write_text(
            "Status: IN_PROGRESS\n\n## Authority\n\n## Expected code surface\n\n## Validation\n",
            encoding="utf-8",
        )
        (self.project / "docs/TASK_QUEUE.md").write_text(
            "| Order | ID | Priority | Status | Dependencies |\n|---:|---|---|---|---|\n"
            "| 1 | TASK-007 | P0 | QUEUED | — |\n",
            encoding="utf-8",
        )
        (self.project / "docs/EXECUTION_EVIDENCE_PROFILE.md").write_text("profile\n", encoding="utf-8")
        (self.project / "PROJECT_WORKFLOW.md").write_text(
            "<!-- MERIDIAN:BEGIN capability=execution-assets v1 -->\n<!-- MERIDIAN:END -->\n"
            "Task files live under `docs/tasks/<milestone>/`; queue is `docs/TASK_QUEUE.md`.\n\n## Roles\n",
            encoding="utf-8",
        )
        nested_task = self.project / "docs/tasks/M19/TASK-007.md"
        nested_task.write_text(
            nested_task.read_text(encoding="utf-8") + "\n" + meridian.execution_contract(self.project, "TASK-007") + "\n",
            encoding="utf-8",
        )
        locations = self.run_cli("locations", "--field", "queue")
        self.assertEqual(locations.stdout.strip(), "docs/TASK_QUEUE.md")
        preflight = self.run_cli("execution", "preflight", "TASK-007")
        self.assertNotEqual(preflight.returncode, 0)
        self.assertIn(
            "BLOCKED QUEUE_STATUS_MISMATCH: rule: the task record and its queue row must agree; sources checked: "
            "Status in docs/tasks/M19/TASK-007.md and the Status column of row TASK-007 in docs/TASK_QUEUE.md; "
            "accepted: equal values; found: task IN_PROGRESS, queue QUEUED; the actor may change "
            "docs/tasks/M19/TASK-007.md and docs/TASK_QUEUE.md together through the lifecycle; resume: change only "
            "the document the message says this actor may change so the statuses are accepted, then rerun meridian "
            "execution preflight TASK-007 --project .",
            preflight.stderr,
        )

    def remediation_project(self, branch: str, record_status: str, queue_status: str = "QUEUED") -> Path:
        """A Git project on `branch` whose queue row is `queue_status` and whose record is `record_status`."""
        subprocess.run(["git", "init", "-q", "-b", branch, str(self.project)], check=True)
        (self.project / "docs").mkdir(exist_ok=True)
        (self.project / "docs/EXECUTION_EVIDENCE_PROFILE.md").write_text("profile\n", encoding="utf-8")
        task = self.project / "tasks/TASK-007.md"
        task.write_text(
            f"Status: {record_status}\n\n## Authority\n\n## Expected code surface\n\n## Validation\n\n"
            "- `check`: `python3 -c pass`\n",
            encoding="utf-8",
        )
        self.append_contract("TASK-007")
        (self.project / "tasks/QUEUE.md").write_text(
            "| Order | ID | Priority | Status | Dependencies |\n|---:|---|---|---|---|\n"
            f"| 1 | TASK-007 | P0 | {queue_status} | — |\n",
            encoding="utf-8",
        )
        return task

    def test_task_branch_preflight_accepts_every_state_the_workflow_produces(self) -> None:
        # Issue #6: a task branch cannot edit the queue, and a review returns the record to IN_PROGRESS.
        task = self.remediation_project("task-007", "IN_PROGRESS")
        for status in ("QUEUED", "IN_PROGRESS", "CHANGES_REQUESTED", "READY_FOR_REVIEW"):
            with self.subTest(status=status):
                text = task.read_text(encoding="utf-8")
                task.write_text(f"Status: {status}\n" + text.split("\n", 1)[1], encoding="utf-8")
                result = self.run_cli("execution", "preflight", "TASK-007")
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_remediation_commands_share_the_preflight_on_a_task_branch(self) -> None:
        self.remediation_project("task-007", "IN_PROGRESS")
        validated = self.run_cli("execution", "validate", "TASK-007", "check")
        self.assertEqual(validated.returncode, 0, validated.stderr)
        investigated = self.run_cli(
            "execution", "investigate", "TASK-007", "--question", "q", "--source", "tasks/TASK-007.md",
            "--finding", "f",
        )
        self.assertNotIn("QUEUE_STATUS_MISMATCH", investigated.stderr)
        self.assertNotIn("TASK_STATUS_REJECTED", investigated.stderr)
        report = self.project / "ready.md"
        report.write_text("## Completion Report — TASK-007\n", encoding="utf-8")
        ready = self.run_cli("execution", "ready-check", "TASK-007", str(report))
        self.assertNotIn("QUEUE_STATUS_MISMATCH", ready.stderr)
        self.assertNotIn("TASK_STATUS_REJECTED", ready.stderr)

    def test_task_branch_preflight_still_rejects_states_the_workflow_cannot_produce(self) -> None:
        self.remediation_project("task-007", "IN_PROGRESS", queue_status="DONE")
        mismatch = self.run_cli("execution", "preflight", "TASK-007")
        self.assertNotEqual(mismatch.returncode, 0)
        self.assertIn(
            "BLOCKED QUEUE_STATUS_MISMATCH: rule: the task record and its queue row must agree; sources checked: "
            "Status in tasks/TASK-007.md and the Status column of row TASK-007 in tasks/QUEUE.md; accepted: equal "
            "values, or queue QUEUED with task QUEUED, IN_PROGRESS, CHANGES_REQUESTED, READY_FOR_REVIEW; "
            "found: task IN_PROGRESS, queue DONE; on task branch task-007 the actor may change only "
            "tasks/TASK-007.md, and the queue row stays QUEUED; resume: ",
            mismatch.stderr,
        )
        task = self.project / "tasks/TASK-007.md"
        task.write_text(task.read_text(encoding="utf-8").replace("Status: IN_PROGRESS", "Status: ACCEPTED"), encoding="utf-8")
        rejected = self.run_cli("execution", "preflight", "TASK-007")
        self.assertIn(
            "BLOCKED TASK_STATUS_REJECTED: rule: preflight runs only on an open task; field checked: Status in "
            "tasks/TASK-007.md; accepted: QUEUED, IN_PROGRESS, CHANGES_REQUESTED, READY_FOR_REVIEW; found: ACCEPTED",
            rejected.stderr,
        )

    def test_outside_the_task_branch_the_record_and_queue_must_still_agree(self) -> None:
        self.remediation_project("main", "IN_PROGRESS")
        result = self.run_cli("execution", "preflight", "TASK-007")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("accepted: equal values; found: task IN_PROGRESS, queue QUEUED", result.stderr)
        self.assertIn("together through the lifecycle", result.stderr)
        task = self.project / "tasks/TASK-007.md"
        task.write_text(task.read_text(encoding="utf-8").replace("Status: IN_PROGRESS", "Status: CHANGES_REQUESTED"), encoding="utf-8")
        self.assertIn("accepted: QUEUED, IN_PROGRESS; found: CHANGES_REQUESTED", self.run_cli("execution", "preflight", "TASK-007").stderr)

    def test_execution_preflight_requires_profile_and_task_contract(self) -> None:
        self.write_task("TASK-008", "QUEUED")
        missing = self.run_cli("execution", "preflight", "TASK-008")
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("BLOCKED EXECUTION_PROFILE_MISSING:", missing.stderr)
        (self.project / "docs").mkdir()
        (self.project / "docs/EXECUTION_EVIDENCE_PROFILE.md").write_text("profile\n", encoding="utf-8")
        (self.project / "tasks/TASK-008.md").write_text(
            "Status: QUEUED\n\n## Authority\n\n## Expected code surface\n\n## Validation\n",
            encoding="utf-8",
        )
        self.append_contract("TASK-008")
        passed = self.run_cli("execution", "preflight", "TASK-008")
        self.assertEqual(passed.returncode, 0, passed.stderr)
        self.assertIn("Execution contract:", passed.stdout)

    def test_execution_preflight_uses_spike_shape(self) -> None:
        (self.project / "docs").mkdir(exist_ok=True)
        (self.project / "docs/EXECUTION_EVIDENCE_PROFILE.md").write_text("profile\n", encoding="utf-8")
        task = self.project / "tasks/TASK-018.md"
        task.write_text(
            "Status: QUEUED\nClass: SPIKE\nQuestion: What behavior is correct?\n"
            "Budget: 2 iterations\nDeliverable: An ADR\n\n## Authority\n\n## Validation\n",
            encoding="utf-8",
        )
        self.append_contract("TASK-018")

        passed = self.run_cli("execution", "preflight", "TASK-018")
        self.assertEqual(passed.returncode, 0, passed.stderr)

        for field in ("Question", "Budget", "Deliverable"):
            with self.subTest(field=field):
                text = task.read_text(encoding="utf-8")
                task.write_text(
                    re.sub(rf"^{field}:.*\n", "", text, flags=re.MULTILINE), encoding="utf-8"
                )
                blocked = self.run_cli("execution", "preflight", "TASK-018")
                self.assertNotEqual(blocked.returncode, 0)
                self.assertIn("BLOCKED TASK_RECORD_INCOMPLETE:", blocked.stderr)
                self.assertIn(f"missing: {field}", blocked.stderr)
                task.write_text(text, encoding="utf-8")

    def test_execution_preflight_validates_host_impact_declarations(self) -> None:
        (self.project / "docs").mkdir(exist_ok=True)
        (self.project / "docs/EXECUTION_EVIDENCE_PROFILE.md").write_text("profile\n", encoding="utf-8")
        task = self.project / "tasks/TASK-019.md"
        base = "Status: QUEUED\n\n## Authority\n\n## Expected code surface\n\n## Validation\n"
        not_applicable = "\n## Host impact\n\nClassification: NOT_APPLICABLE\nRationale: This task changes only application behavior.\n"
        task.write_text(base + not_applicable, encoding="utf-8")
        self.append_contract("TASK-019")
        self.assertEqual(self.run_cli("execution", "preflight", "TASK-019").returncode, 0)

        task.write_text(task.read_text(encoding="utf-8").replace("Rationale: This task changes only application behavior.\n", ""), encoding="utf-8")
        missing_rationale = self.run_cli("execution", "preflight", "TASK-019")
        self.assertNotEqual(missing_rationale.returncode, 0)
        self.assertEqual(
            self.blocked_line(missing_rationale),
            "BLOCKED HOST_IMPACT_DECLARATION_INVALID: NOT_APPLICABLE declaration is missing Rationale; resume: correct "
            "the task's Host impact declaration as the detail names, then rerun the blocked meridian execution command",
        )

        required = """Classification: REQUIRED
Policy outcome: The lifecycle gate validates host-impact evidence.

| Profile | Before | Intended after | Activation preconditions | Fallback |
|---|---|---|---|---|
| Meridian CLI / direct invocation / project | advisory | enforced | Run through execution. | Block missing evidence. |

Evidence plan:
- Static: parser test
- Host execution: fixture command
- Manual activation: run from a project subdirectory
"""
        task.write_text(base + "\n## Host impact\n\n" + required, encoding="utf-8")
        self.append_contract("TASK-019")
        self.assertEqual(self.run_cli("execution", "preflight", "TASK-019").returncode, 0)

        task.write_text(task.read_text(encoding="utf-8").replace("- Host execution: fixture command\n", ""), encoding="utf-8")
        missing_evidence = self.run_cli("execution", "preflight", "TASK-019")
        self.assertNotEqual(missing_evidence.returncode, 0)
        self.assertEqual(
            self.blocked_line(missing_evidence),
            "BLOCKED HOST_IMPACT_DECLARATION_INVALID: REQUIRED declaration is missing Host execution evidence plan; "
            "resume: correct the task's Host impact declaration as the detail names, then rerun the blocked meridian "
            "execution command",
        )

    def test_ready_check_requires_evidence_only_for_enforced_host_profiles(self) -> None:
        (self.project / "docs").mkdir(exist_ok=True)
        (self.project / "docs/EXECUTION_EVIDENCE_PROFILE.md").write_text("profile\n", encoding="utf-8")
        task = self.project / "tasks/TASK-020.md"
        task.write_text(
            "Status: IN_PROGRESS\n\n## Authority\n\n## Expected code surface\n\n## Validation\n\n"
            "## Host impact\n\nClassification: REQUIRED\nPolicy outcome: Accurate host claims.\n\n"
            "| Profile | Before | Intended after | Activation preconditions | Fallback |\n"
            "|---|---|---|---|---|\n"
            "| Meridian CLI / direct / project | advisory | enforced | Run execution. | Block claim. |\n"
            "| Codex / project / trusted rules | advisory | unverified | Probe unavailable. | Retain unverified. |\n\n"
            "Evidence plan:\n- Static: parser test\n- Host execution: fixture command\n- Manual activation: project subdirectory\n",
            encoding="utf-8",
        )
        self.append_contract("TASK-020")
        report = self.project / "ready.md"
        report.write_text(
            "## Completion Report — TASK-020\n\n- Files changed: none\n- Validation: exit 0\n"
            "- Validation skips: none\n"
            "- Manual verification: none\n- Acceptance criteria: all met\n- Budget usage: 0/3\n"
            "- Isolated exploration: none\n- Blockers/deviations: none\n",
            encoding="utf-8",
        )
        missing = self.run_cli("execution", "ready-check", "TASK-020", str(report))
        self.assertNotEqual(missing.returncode, 0)
        self.assertEqual(
            self.blocked_line(missing),
            "BLOCKED HOST_IMPACT_EVIDENCE_MISSING: enforced profile is missing Completion evidence: Meridian CLI / "
            "direct / project; resume: add a Completion evidence entry for each listed profile to the task's Host "
            "impact section, then rerun the blocked meridian execution command",
        )

        task.write_text(
            task.read_text(encoding="utf-8").replace(
                "\n## Execution contract — resolved",
                "\nCompletion evidence:\n- [Meridian CLI / direct / project]: fixture observed the gate.\n"
                "\n## Execution contract — resolved",
            ),
            encoding="utf-8",
        )
        passed = self.run_cli("execution", "ready-check", "TASK-020", str(report))
        self.assertEqual(passed.returncode, 0, passed.stderr)

    def test_reconcile_upgrades_a_nonterminal_legacy_contract_before_preflight(self) -> None:
        (self.project / "docs").mkdir()
        (self.project / "docs/EXECUTION_EVIDENCE_PROFILE.md").write_text("profile\n", encoding="utf-8")
        task = self.project / "tasks/TASK-014.md"
        task.write_text(
            "Status: QUEUED\n\n## Authority\n\n## Expected code surface\n\n## Validation\n\n## Completion\n",
            encoding="utf-8",
        )
        legacy_contract = meridian.execution_contract(self.project, "TASK-014").replace(
            "- Execution commands: `required via meridian execution`", ""
        )
        task.write_text(task.read_text(encoding="utf-8").replace("## Completion", legacy_contract + "\n\n## Completion"), encoding="utf-8")
        blocked = self.run_cli("execution", "preflight", "TASK-014")
        self.assertNotEqual(blocked.returncode, 0)
        self.assertIn("BLOCKED EXECUTION_CONTRACT_UNRESOLVED:", blocked.stderr)
        self.assertIn("`required via meridian execution`", blocked.stderr)
        preview = self.run_cli("execution", "reconcile", "TASK-014")
        self.assertEqual(preview.returncode, 0, preview.stderr)
        self.assertIn("rerun with --apply", preview.stdout)
        applied = self.run_cli("execution", "reconcile", "TASK-014", "--apply")
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertEqual(self.run_cli("execution", "preflight", "TASK-014").returncode, 0)

    def test_reconcile_is_idempotent_when_contract_is_the_final_section(self) -> None:
        (self.project / "docs").mkdir()
        (self.project / "docs/EXECUTION_EVIDENCE_PROFILE.md").write_text("profile\n", encoding="utf-8")
        task = self.project / "tasks/TASK-016.md"
        task.write_text(
            "Status: QUEUED\n\n## Authority\n\n## Expected code surface\n\n## Validation\n",
            encoding="utf-8",
        )

        preview = self.run_cli("execution", "reconcile", "TASK-016")
        self.assertIn("rerun with --apply", preview.stdout)
        applied = self.run_cli("execution", "reconcile", "TASK-016", "--apply")
        self.assertEqual(applied.returncode, 0, applied.stderr)
        reconciled = task.read_text(encoding="utf-8")

        current = self.run_cli("execution", "reconcile", "TASK-016")
        self.assertEqual(current.returncode, 0, current.stderr)
        self.assertIn("already current", current.stdout)
        self.assertEqual(task.read_text(encoding="utf-8"), reconciled)

    def test_execution_contract_blocks_unnamed_validation_entries(self) -> None:
        (self.project / "docs").mkdir()
        (self.project / "docs/EXECUTION_EVIDENCE_PROFILE.md").write_text("profile\n", encoding="utf-8")
        task = self.project / "tasks/TASK-017.md"
        task.write_text(
            "Status: QUEUED\n\n## Authority\n\n## Expected code surface\n\n"
            "## Validation\n\n- `cargo fmt --check`\n",
            encoding="utf-8",
        )

        reconcile = self.run_cli("execution", "reconcile", "TASK-017")
        self.assertNotEqual(reconcile.returncode, 0)
        self.assertIn("BLOCKED VALIDATION_ENTRY_FORMAT:", reconcile.stderr)
        preflight = self.run_cli("execution", "preflight", "TASK-017")
        self.assertNotEqual(preflight.returncode, 0)
        self.assertIn("BLOCKED VALIDATION_ENTRY_FORMAT:", preflight.stderr)

    def test_reconcile_preserves_terminal_task_history(self) -> None:
        (self.project / "docs").mkdir()
        (self.project / "docs/EXECUTION_EVIDENCE_PROFILE.md").write_text("profile\n", encoding="utf-8")
        task = self.project / "tasks/TASK-015.md"
        task.write_text("Status: ACCEPTED\n\n## Completion\n- historical record\n", encoding="utf-8")
        original = task.read_text(encoding="utf-8")
        result = self.run_cli("execution", "reconcile", "TASK-015", "--apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("skipped for terminal task", result.stdout)
        self.assertEqual(task.read_text(encoding="utf-8"), original)

    def test_handoff_check_rejects_missing_budget_usage(self) -> None:
        report = self.project / "handoff.md"
        report.write_text(
            "## Completion Report — TASK-009\n\n"
            "- Files changed: `a.rs`\n- Validation: `cargo test` exit 0\n"
            "- Validation skips: none\n"
            "- Manual verification: none\n- Acceptance criteria: all met\n"
            "- Blockers/deviations: none\n",
            encoding="utf-8",
        )
        result = self.run_cli("execution", "handoff-check", "TASK-009", str(report))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Budget usage", result.stderr)

    def test_ready_check_combines_preflight_and_handoff(self) -> None:
        (self.project / "docs").mkdir()
        (self.project / "docs/EXECUTION_EVIDENCE_PROFILE.md").write_text("profile\n", encoding="utf-8")
        (self.project / "tasks/TASK-012.md").write_text(
            "Status: IN_PROGRESS\n\n## Authority\n\n## Expected code surface\n\n## Validation\n",
            encoding="utf-8",
        )
        self.append_contract("TASK-012")
        report = self.project / "ready.md"
        report.write_text(
            "## Completion Report — TASK-012\n\n- Files changed: none\n- Validation: exit 0\n"
            "- Validation skips: none\n"
            "- Manual verification: none\n- Acceptance criteria: all met\n- Budget usage: 0/3\n"
            "- Isolated exploration: none\n"
            "- Blockers/deviations: none\n",
            encoding="utf-8",
        )
        handoff = self.project / "tasks/handoffs/TASK-012.md"
        handoff.parent.mkdir(parents=True, exist_ok=True)
        handoff.write_text("## Completion Report — TASK-012\n", encoding="utf-8")
        result = self.run_cli("execution", "ready-check", "TASK-012", str(report))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("READY_FOR_REVIEW gate passed", result.stdout)

    def test_handoff_rejects_fabricated_validation_and_requires_recorded_investigation(self) -> None:
        (self.project / "docs").mkdir()
        (self.project / "docs/EXECUTION_EVIDENCE_PROFILE.md").write_text("profile\n", encoding="utf-8")
        (self.project / "tasks/TASK-013.md").write_text(
            "Status: IN_PROGRESS\n\n## Authority\n\n## Expected code surface\n\n"
            "## Validation\n\n- `probe`: `printf validation-ok`\n",
            encoding="utf-8",
        )
        self.append_contract("TASK-013")
        report = self.project / "evidence.md"
        report.write_text(
            "## Completion Report — TASK-013\n\n- Files changed: none\n"
            "- Validation: `printf validation-ok` exit 0\n- Manual verification: none\n"
            "- Validation skips: none\n"
            "- Acceptance criteria: all met\n- Budget usage: 0/3\n"
            "- Isolated exploration: none\n- Blockers/deviations: none\n",
            encoding="utf-8",
        )
        fabricated = self.run_cli("execution", "handoff-check", "TASK-013", str(report))
        self.assertNotEqual(fabricated.returncode, 0)
        self.assertIn("BLOCKED HANDOFF_VALIDATION_EVIDENCE_MISSING:", fabricated.stderr)

        self.assertEqual(self.run_cli("execution", "validate", "TASK-013", "probe").returncode, 0)
        investigated = self.run_cli(
            "execution", "investigate", "TASK-013", "--question", "Which API owns the value?",
            "--scope", "2", "--source", "vendor/api.rs", "--finding", "Window owns the value.",
        )
        # The default `Investigation scope: 2` admits exactly one scope-2 use.
        self.assertEqual(investigated.returncode, 0, investigated.stderr)
        self.assertIn("2/2 recorded", investigated.stdout)
        missing_question = self.run_cli("execution", "handoff-check", "TASK-013", str(report))
        self.assertNotEqual(missing_question.returncode, 0)
        self.assertIn("BLOCKED HANDOFF_EXPLORATION_MISMATCH:", missing_question.stderr)
        self.assertIn("found: `none` with 1 recorded", missing_question.stderr)
        report.write_text(
            report.read_text(encoding="utf-8").replace(
                "- Isolated exploration: none",
                "- Isolated exploration: Which API owns the value? — Window owns the value.",
            ),
            encoding="utf-8",
        )
        self.assertEqual(self.run_cli("execution", "handoff-check", "TASK-013", str(report)).returncode, 0)

    def test_handoff_accepts_report_with_or_without_rule_discrepancies(self) -> None:
        self.write_task("TASK-009", "IN_PROGRESS")
        report = self.project / "rule-discrepancies.md"
        body = (
            "## Completion Report — TASK-009\n\n- Files changed: none\n"
            "- Validation: `python3 -m unittest discover -s tests -v` exit 0\n"
            "- Validation skips: none\n"
            "- Manual verification: none\n- Acceptance criteria: all met\n"
            "- Budget usage: 0/3\n- Isolated exploration: none\n"
            "%s- Blockers/deviations: none\n"
        )
        for extra in (
            "",
            "- Rule discrepancies: none\n",
            "- Rule discrepancies: `main` ahead of origin; integrate stage accepted it; followed the command\n",
        ):
            report.write_text(body % extra, encoding="utf-8")
            result = self.run_cli("execution", "handoff-check", "TASK-009", str(report))
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_handoff_accepts_non_project_specific_skips_and_rejects_failures(self) -> None:
        self.write_task("TASK-009", "IN_PROGRESS")
        report = self.project / "validation-skips.md"
        report.write_text(
            "## Completion Report — TASK-009\n\n- Files changed: none\n"
            "- Validation: `python3 -m unittest discover -s tests -v` exit 0\n"
            "- Validation skips: none\n"
            "- Manual verification: none\n- Acceptance criteria: all met\n"
            "- Budget usage: 0/3\n- Isolated exploration: none\n"
            "- Blockers/deviations: none\n",
            encoding="utf-8",
        )
        self.assertEqual(self.run_cli("execution", "handoff-check", "TASK-009", str(report)).returncode, 0)

        report.write_text(
            report.read_text(encoding="utf-8").replace(
                "- Validation skips: none\n",
                "- Validation skips: ConsumerSuite.test_unavailable_service — service unavailable; "
                "reported by `consumer-test --network`\n",
            ),
            encoding="utf-8",
        )
        documented_form = self.run_cli("execution", "handoff-check", "TASK-009", str(report))
        self.assertEqual(documented_form.returncode, 0, documented_form.stderr)

        report.write_text(
            report.read_text(encoding="utf-8").replace(
                "- Validation skips: ConsumerSuite.test_unavailable_service — service unavailable; "
                "reported by `consumer-test --network`\n",
                "- Validation skips: network fixture unavailable\n",
            ),
            encoding="utf-8",
        )
        free_text = self.run_cli("execution", "handoff-check", "TASK-009", str(report))
        self.assertEqual(free_text.returncode, 0, free_text.stderr)

        report.write_text(
            report.read_text(encoding="utf-8").replace(
                "- Validation: `python3 -m unittest discover -s tests -v` exit 0\n"
                "- Validation skips: network fixture unavailable\n",
                "- Validation: `python3 -m unittest discover -s tests -v` exit 1\n"
                "- Validation skips: none\n",
            ),
            encoding="utf-8",
        )
        rejected = self.run_cli("execution", "handoff-check", "TASK-009", str(report))
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("BLOCKED HANDOFF_VALIDATION_FAILING:", rejected.stderr)
        self.assertIn("a failing validation needs a named skip", rejected.stderr)

        report.write_text(
            report.read_text(encoding="utf-8").replace(
                "- Validation skips: none\n",
                "- Validation skips: network fixture unavailable\n",
            ),
            encoding="utf-8",
        )
        named_skip_failure = self.run_cli("execution", "handoff-check", "TASK-009", str(report))
        self.assertNotEqual(named_skip_failure.returncode, 0)
        self.assertIn("a named skip does not make a failing validation pass", named_skip_failure.stderr)

        report.write_text(
            report.read_text(encoding="utf-8").replace("- Validation skips: network fixture unavailable\n", ""),
            encoding="utf-8",
        )
        absent = self.run_cli("execution", "handoff-check", "TASK-009", str(report))
        self.assertNotEqual(absent.returncode, 0)
        self.assertIn("Validation skips", absent.stderr)

    def blocked_line(self, result: subprocess.CompletedProcess[str]) -> str:
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        return next(line for line in result.stderr.splitlines() if line.startswith("BLOCKED "))

    def test_execution_gates_report_coded_actionable_stops(self) -> None:
        self.write_task("TASK-020", "QUEUED")
        self.assertEqual(
            self.blocked_line(self.run_cli("execution", "preflight", "TASK-020")),
            "BLOCKED EXECUTION_PROFILE_MISSING: rule: the execution contract derives from the project profile; "
            "source checked: docs/EXECUTION_EVIDENCE_PROFILE.md; expected: the file exists; found: no such file; "
            "resume: add docs/EXECUTION_EVIDENCE_PROFILE.md to the project, then rerun the blocked meridian "
            "execution command",
        )
        (self.project / "docs").mkdir()
        profile = self.project / "docs/EXECUTION_EVIDENCE_PROFILE.md"
        profile.write_text("profile\n", encoding="utf-8")
        task = self.project / "tasks/TASK-020.md"
        body = "Status: QUEUED\n\n## Authority\n\n## Expected code surface\n\n## Validation\n"
        task.write_text(body, encoding="utf-8")
        digest = meridian.profile_digest(self.project)
        resume = "resume: meridian execution reconcile TASK-020 --apply --project ."
        self.assertEqual(
            self.blocked_line(self.run_cli("execution", "preflight", "TASK-020")),
            "BLOCKED EXECUTION_CONTRACT_UNRESOLVED: rule: a task needs a resolved execution contract; field "
            f"checked: `- Profile revision` in tasks/TASK-020.md; expected: sha256:{digest}; found: no such line; "
            + resume,
        )
        self.append_contract("TASK-020")
        profile.write_text("changed profile\n", encoding="utf-8")
        changed = meridian.profile_digest(self.project)
        self.assertEqual(
            self.blocked_line(self.run_cli("execution", "preflight", "TASK-020")),
            "BLOCKED EXECUTION_CONTRACT_UNRESOLVED: rule: the resolved contract must match the current profile; "
            "field checked: `- Profile revision` in tasks/TASK-020.md against docs/EXECUTION_EVIDENCE_PROFILE.md; "
            f"expected: sha256:{changed}; found: sha256:{digest}; " + resume,
        )
        task.write_text(body.replace("## Expected code surface\n\n", ""), encoding="utf-8")
        self.append_contract("TASK-020")
        self.assertEqual(
            self.blocked_line(self.run_cli("execution", "preflight", "TASK-020")),
            "BLOCKED TASK_RECORD_INCOMPLETE: rule: a normal task record must contain its required headings; source "
            "checked: tasks/TASK-020.md; accepted: ## Authority, ## Validation, ## Expected code surface; missing: "
            "## Expected code surface; resume: add the listed sections or fields to the task record, then rerun "
            "meridian execution preflight TASK-020 --project .",
        )
        task.write_text(body.replace("QUEUED", "ACCEPTED"), encoding="utf-8")
        self.append_contract("TASK-020")
        accepted = (
            "resume: bring the task to QUEUED or IN_PROGRESS through its lifecycle, then rerun the blocked "
            "meridian execution command"
        )
        self.assertEqual(
            self.blocked_line(self.run_cli("execution", "preflight", "TASK-020")),
            "BLOCKED TASK_STATUS_REJECTED: rule: preflight runs only on an open task; field checked: Status in "
            "tasks/TASK-020.md; accepted: QUEUED, IN_PROGRESS; found: ACCEPTED; " + accepted,
        )
        task.write_text(body.replace("QUEUED", "DRAFT"), encoding="utf-8")
        self.assertEqual(
            self.blocked_line(self.run_cli("execution", "reconcile", "TASK-020")),
            "BLOCKED TASK_STATUS_REJECTED: rule: reconcile refreshes only an open task; field checked: Status in "
            "tasks/TASK-020.md; accepted: QUEUED, IN_PROGRESS (terminal tasks are skipped); found: DRAFT; " + accepted,
        )
        task.write_text(body + "\n- `cargo fmt --check`\n", encoding="utf-8")
        self.assertEqual(
            self.blocked_line(self.run_cli("execution", "reconcile", "TASK-020")),
            "BLOCKED VALIDATION_ENTRY_FORMAT: rule: every entry in the task's ## Validation section must be a named "
            "literal command; accepted form: - `validation-id`: `literal command`; found: '- `cargo fmt --check`'; "
            "resume: rewrite each listed Validation entry as - `validation-id`: `literal command`, then rerun the "
            "blocked meridian execution command",
        )
        self.assertEqual(
            self.blocked_line(self.run_cli("execution", "evidence", "TASK-020", "diagnostic", "--gap", " ")),
            "BLOCKED EXECUTION_EVIDENCE_ARGUMENTS: rule: evidence is recorded with the gap that justifies it; option "
            "checked: --gap; accepted: a non-empty string; found: ' '; resume: rerun the meridian execution evidence "
            "command with the missing options",
        )
        self.assertIn(
            "missing: --artifact",
            self.blocked_line(self.run_cli(
                "execution", "evidence", "TASK-020", "captures", "--gap", "g", "--criterion", "AC-1",
            )),
        )

    def test_handoff_gates_report_coded_actionable_stops(self) -> None:
        self.write_task("TASK-021", "IN_PROGRESS")
        report = self.project / "report.md"
        fields = {
            "Files changed": "none", "Validation": "`x` exit 0", "Validation skips": "none",
            "Manual verification": "none", "Acceptance criteria": "all met", "Budget usage": "0/3",
            "Isolated exploration": "none", "Blockers/deviations": "none",
        }

        def write(heading: str = "TASK-021", **overrides: str | None) -> None:
            lines = [f"## Completion Report — {heading}", ""]
            for field, value in {**fields, **overrides}.items():
                if value is not None:
                    lines.append(f"- {field}: {value}")
            report.write_text("\n".join(lines) + "\n", encoding="utf-8")

        def check() -> subprocess.CompletedProcess[str]:
            return self.run_cli("execution", "handoff-check", "TASK-021", str(report))

        resume = "then rerun meridian execution handoff-check TASK-021 <report> --project ."
        self.assertEqual(
            self.blocked_line(check()),
            f"BLOCKED HANDOFF_REPORT_MISSING: rule: the handoff check reads a completion report; source checked: "
            f"{report}; expected: an existing file; found: no such file; resume: write the completion report, "
            "then run meridian execution handoff-check TASK-021 <report> --project .",
        )
        required = ", ".join(fields)
        write(Validation=None)
        self.assertEqual(
            self.blocked_line(check()),
            "BLOCKED HANDOFF_FIELDS_MISSING: rule: every required field needs a non-empty value; source checked: "
            "report.md; accepted form: `- <Field>: <value>`; required: " + required + "; missing: Validation; "
            "resume: add each missing field as `- <Field>: <value>`, " + resume,
        )
        report.write_text(report.read_text(encoding="utf-8") + "- Validation (commands): `x` exit 0\n", encoding="utf-8")
        self.assertEqual(
            self.blocked_line(check()),
            "BLOCKED HANDOFF_FIELD_FORMAT: rule: a required field's name must be followed directly by the colon; "
            "source checked: report.md; accepted form: `- <Field>: <value>`; found: `- Validation (commands):` "
            "(expected `- Validation: <value>`); resume: rewrite each listed field as `- <Field>: <value>`, " + resume,
        )
        write("TASK-099")
        self.assertEqual(
            self.blocked_line(check()),
            "BLOCKED HANDOFF_TASK_MISMATCH: rule: the report must identify its task; source checked: report.md; "
            "accepted: `Completion Report — TASK-021`; found: `Completion Report — TASK-099`; resume: correct "
            "the report heading to name this task, " + resume,
        )
        write(Validation="`x` exit 1")
        self.assertEqual(
            self.blocked_line(check()),
            "BLOCKED HANDOFF_VALIDATION_FAILING: rule: a failing validation needs a named skip; field checked: "
            "Validation; accepted: no `exit <non-zero>`; found: `exit 1` with Validation skips: none; resume: fix "
            "the failing validation and report its passing result, " + resume,
        )
        write(Validation="`x` exit 1", **{"Validation skips": "network down"})
        self.assertIn(
            "rule: a named skip does not make a failing validation pass; field checked: Validation; accepted: no "
            "`exit <non-zero>`; found: `exit 1` with Validation skips: network down;",
            self.blocked_line(check()),
        )

    def test_handoff_isolated_exploration_and_durable_evidence_gates(self) -> None:
        (self.project / "docs").mkdir()
        (self.project / "docs/EXECUTION_EVIDENCE_PROFILE.md").write_text("profile\n", encoding="utf-8")
        (self.project / "tasks/TASK-022.md").write_text(
            "Status: IN_PROGRESS\n\n## Authority\n\n## Expected code surface\n\n"
            "## Validation\n\n- `probe`: `printf ok`\n",
            encoding="utf-8",
        )
        self.append_contract("TASK-022")
        report = self.project / "report.md"

        def write(exploration: str) -> None:
            report.write_text(
                "## Completion Report — TASK-022\n\n- Files changed: none\n- Validation: `printf ok` exit 0\n"
                "- Validation skips: none\n- Manual verification: none\n- Acceptance criteria: all met\n"
                f"- Budget usage: 0/3\n- Isolated exploration: {exploration}\n- Blockers/deviations: none\n",
                encoding="utf-8",
            )

        def check() -> subprocess.CompletedProcess[str]:
            return self.run_cli("execution", "handoff-check", "TASK-022", str(report))

        write("none")
        self.assertEqual(
            self.blocked_line(check()),
            "BLOCKED HANDOFF_VALIDATION_EVIDENCE_MISSING: rule: every declared validation needs a successful durable "
            "record; source checked: .meridian/execution-evidence.json for TASK-022; accepted: an entry with the "
            "declared id and command and exitStatus 0; missing for: probe; resume: run meridian execution validate "
            "TASK-022 <validation-id> --project . for each listed ID, then rerun the handoff check",
        )
        self.assertEqual(self.run_cli("execution", "validate", "TASK-022", "probe").returncode, 0)
        for accepted in ("none", "None", "none needed", "No isolated exploration was needed", "no"):
            with self.subTest(accepted=accepted):
                write(accepted)
                self.assertEqual(check().returncode, 0, accepted)
        write("explored the API")
        self.assertEqual(
            self.blocked_line(check()),
            "BLOCKED HANDOFF_EXPLORATION_MISMATCH: rule: with no recorded investigation the report must say there was "
            "none; field checked: Isolated exploration against .meridian/execution-evidence.json; accepted: `none`, "
            "or text starting with `none` or `no`; found: 'explored the API'; expected `none` (or record the "
            "investigation); resume: correct the Isolated exploration field or record the investigation with meridian "
            "execution investigate TASK-022, then rerun the handoff check",
        )
        write("nothing")
        self.assertIn("found: 'nothing'", self.blocked_line(check()))
        self.assertEqual(
            self.run_cli(
                "execution", "investigate", "TASK-022", "--question", "Which API?", "--scope", "2",
                "--source", "a.rs", "--finding", "The window API.",
            ).returncode,
            0,
        )
        write("none")
        self.assertEqual(
            self.blocked_line(check()),
            "BLOCKED HANDOFF_EXPLORATION_MISMATCH: rule: recorded investigations must be reported; field checked: "
            "Isolated exploration against .meridian/execution-evidence.json; accepted: a summary of each recorded "
            "investigation; found: `none` with 1 recorded; resume: correct the Isolated exploration field or record "
            "the investigation with meridian execution investigate TASK-022, then rerun the handoff check",
        )
        write("Which API?")
        self.assertEqual(
            self.blocked_line(check()),
            "BLOCKED HANDOFF_EXPLORATION_SUMMARY_MISSING: rule: the report must contain each recorded question and "
            "finding; source checked: .meridian/execution-evidence.json; accepted: the exact question and finding "
            "text; missing the question or finding of: Which API?; resume: add each listed question and finding to "
            "the report, then rerun meridian execution handoff-check TASK-022 <report> --project .",
        )

    def test_validation_runs_only_a_declared_literal_command_and_records_status(self) -> None:
        (self.project / "docs").mkdir()
        (self.project / "docs/EXECUTION_EVIDENCE_PROFILE.md").write_text("profile\n", encoding="utf-8")
        (self.project / "tasks/TASK-010.md").write_text(
            "Status: IN_PROGRESS\n\n## Authority\n\n## Expected code surface\n\n"
            "## Validation\n\n- `probe`: `printf validation-ok`\n",
            encoding="utf-8",
        )
        self.append_contract("TASK-010")
        result = self.run_cli("execution", "validate", "TASK-010", "probe")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("validation-ok", result.stdout)
        evidence = json.loads((self.project / ".meridian/execution-evidence.json").read_text(encoding="utf-8"))
        self.assertEqual(evidence["TASK-010"][0]["id"], "probe")
        missing = self.run_cli("execution", "validate", "TASK-010", "not-declared")
        self.assertNotEqual(missing.returncode, 0)
        self.assertEqual(
            self.blocked_line(missing),
            "BLOCKED VALIDATION_ID_UNDECLARED: rule: only a task-declared validation ID runs; field checked: "
            "Validation in the TASK-010 record; accepted: probe; found: 'not-declared'; resume: rerun meridian "
            "execution validate with a validation ID listed in the task's Validation section, or declare the command "
            "there first",
        )

    def test_evidence_requires_a_gap_and_capture_provenance(self) -> None:
        self.write_task("TASK-011", "IN_PROGRESS")
        missing = self.run_cli("execution", "evidence", "TASK-011", "captures", "--gap", "text is perceptual")
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("BLOCKED EXECUTION_EVIDENCE_ARGUMENTS:", missing.stderr)
        self.assertIn("missing: --criterion, --artifact", missing.stderr)
        recorded = self.run_cli(
            "execution", "evidence", "TASK-011", "captures", "--gap", "text is perceptual",
            "--criterion", "AC-4", "--artifact", "/tmp/capture.png",
        )
        self.assertEqual(recorded.returncode, 0, recorded.stderr)
        evidence = json.loads((self.project / ".meridian/execution-evidence.json").read_text(encoding="utf-8"))
        self.assertEqual(evidence["TASK-011"][0]["criterion"], "AC-4")
        self.assertEqual(evidence["TASK-011"][0]["artifact"], "/tmp/capture.png")
        other = self.run_cli(
            "execution", "evidence", "TASK-011", "captures", "--gap", "second criterion",
            "--criterion", "AC-5", "--artifact", "/tmp/second.png",
        )
        self.assertEqual(other.returncode, 0, other.stderr)
        shown = self.run_cli("budget", "show", "TASK-011")
        self.assertIn("AC-4 1/2, AC-5 1/2", shown.stdout)

    def test_spend_increments_and_reports(self) -> None:
        self.write_task("TASK-002", "IN_PROGRESS")
        first = self.run_cli("budget", "spend", "TASK-002", "diagnostic")
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(first.stdout.strip(), "TASK-002: diagnostic 1/3")
        second = self.run_cli("budget", "spend", "TASK-002", "diagnostic")
        self.assertEqual(second.stdout.strip(), "TASK-002: diagnostic 2/3")
        third = self.run_cli("budget", "spend", "TASK-002", "diagnostic")
        self.assertEqual(third.returncode, 0, third.stderr)
        self.assertEqual(third.stdout.strip(), "TASK-002: diagnostic 3/3")
        self.assertIn("Diagnostics 3/3", self.run_cli("budget", "show", "TASK-002").stdout)

    def test_spend_returns_non_zero_and_names_blocked_once_cap_is_used(self) -> None:
        self.write_task("TASK-003", "IN_PROGRESS")
        # Default cap is 2 captures; both uses are admitted.
        for used in (1, 2):
            accepted = self.run_cli("budget", "spend", "TASK-003", "captures")
            self.assertEqual(accepted.returncode, 0, accepted.stderr)
            self.assertEqual(accepted.stdout.strip(), f"TASK-003: captures {used}/2")
        exhausted = self.run_cli("budget", "spend", "TASK-003", "captures")
        self.assertNotEqual(exhausted.returncode, 0)
        self.assertEqual(
            self.blocked_line(exhausted),
            "BLOCKED BUDGET_EXHAUSTED: Evidence captures exhausted for TASK-003: 2 of 2 allowed uses already "
            "recorded, 1 more requested; do not raise the cap; resume: report this stop and ask the developer to "
            "raise the cap or re-scope the task; never raise the cap yourself",
        )
        with self.assertRaises(meridian.MeridianStop) as invalid:
            meridian.budget_spend(self.project, "TASK-003", "captures", amount=0)
        self.assertEqual(
            str(invalid.exception),
            "BLOCKED EXECUTION_EVIDENCE_ARGUMENTS: rule: a budget use is at least one; option checked: --scope; "
            "accepted: an integer of 1 or more; found: 0; resume: rerun meridian execution investigate with --scope "
            "of 1 or more",
        )

    def test_investigation_arguments_name_the_missing_options(self) -> None:
        self.write_task("TASK-406", "IN_PROGRESS")
        result = self.run_cli("execution", "investigate", "TASK-406", "--question", " ", "--scope", "1", "--source", "x", "--finding", "")
        self.assertEqual(
            self.blocked_line(result),
            "BLOCKED EXECUTION_EVIDENCE_ARGUMENTS: rule: an investigation records its question, sources, and finding; "
            "options checked: --question, --source, --finding; accepted: a non-empty value for each; found: missing or "
            "empty --question, --finding; resume: rerun meridian execution investigate with --question, --source, and "
            "--finding",
        )

    def test_uncoded_command_refusal_reports_command_refused(self) -> None:
        refused = self.run_cli("budget", "show", "TASK-404")
        line = self.blocked_line(refused)
        self.assertTrue(line.startswith("BLOCKED COMMAND_REFUSED: "), line)
        self.assertTrue(
            line.endswith("; resume: correct the condition that the detail names, then rerun the same meridian command"),
            line,
        )
        self.assertNotIn("BLOCKED:", refused.stderr)

    def test_operating_system_failure_reports_os_access_failed(self) -> None:
        self.write_task("TASK-405", "IN_PROGRESS")
        (self.project / ".meridian").mkdir()
        (self.project / ".meridian/budget.json").mkdir()
        failed = self.run_cli("budget", "spend", "TASK-405", "diagnostic")
        line = self.blocked_line(failed)
        self.assertTrue(line.startswith("BLOCKED OS_ACCESS_FAILED: "), line)
        self.assertTrue(
            line.endswith("; resume: fix the access problem that the detail names, then rerun the same meridian command"),
            line,
        )

    def test_spend_respects_task_override_cap(self) -> None:
        self.write_task("TASK-004", "IN_PROGRESS", **{"Diagnostic attempts": "1"})
        first = self.run_cli("budget", "spend", "TASK-004", "diagnostic")
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(first.stdout.strip(), "TASK-004: diagnostic 1/1")
        second = self.run_cli("budget", "spend", "TASK-004", "diagnostic")
        self.assertNotEqual(second.returncode, 0)
        self.assertIn("1 of 1 allowed uses already recorded", second.stderr)

    def test_spend_rejected_by_cap_leaves_state_unchanged(self) -> None:
        self.write_task("TASK-010", "IN_PROGRESS")
        for used in (1, 2):
            accepted = self.run_cli("budget", "spend", "TASK-010", "captures")
            self.assertEqual(accepted.returncode, 0, accepted.stderr)
            self.assertEqual(accepted.stdout.strip(), f"TASK-010: captures {used}/2")

        # A spend beyond the cap must be rejected without durably consuming
        # the unit it could not deliver: the persisted counter stays at the
        # last accepted value, not the rejected one.
        first_rejection = self.run_cli("budget", "spend", "TASK-010", "captures")
        self.assertNotEqual(first_rejection.returncode, 0)
        self.assertIn("2 of 2 allowed uses already recorded", first_rejection.stderr)
        self.assertEqual(self.budget_state()["TASK-010:1"]["captures"], 2)

        # Retrying after a rejection must see the same unchanged state, not
        # a counter that keeps climbing past the cap with every attempt.
        second_rejection = self.run_cli("budget", "spend", "TASK-010", "captures")
        self.assertNotEqual(second_rejection.returncode, 0)
        self.assertIn("2 of 2 allowed uses already recorded", second_rejection.stderr)
        self.assertEqual(self.budget_state()["TASK-010:1"]["captures"], 2)

    def test_multi_unit_spend_crossing_the_cap_is_rejected_without_writing(self) -> None:
        self.write_task("TASK-014", "IN_PROGRESS")
        # Default investigation scope is 2, so a single scope-2 use is admitted.
        count, cap = meridian.budget_spend(self.project, "TASK-014", "investigations", amount=2)
        self.assertEqual((count, cap), (2, 2))
        self.assertEqual(self.budget_state()["TASK-014:1"]["investigations"], 2)

        self.write_task("TASK-015", "IN_PROGRESS", **{"Investigation scope": "3"})
        meridian.budget_spend(self.project, "TASK-015", "investigations", amount=2)
        with self.assertRaises(meridian.MeridianError) as raised:
            meridian.budget_spend(self.project, "TASK-015", "investigations", amount=2)
        message = str(raised.exception)
        self.assertIn("BLOCKED", message)
        self.assertIn("2 of 3 allowed uses already recorded, 2 more requested", message)
        self.assertEqual(self.budget_state()["TASK-015:1"]["investigations"], 2)
        # The one remaining unit is still spendable after the rejection.
        self.assertEqual(
            meridian.budget_spend(self.project, "TASK-015", "investigations", amount=1), (3, 3)
        )

    def test_unknown_task_is_blocked_without_writing_state(self) -> None:
        result = self.run_cli("budget", "show", "TASK-NOPE")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unknown task", result.stderr)
        self.assertFalse((self.project / ".meridian/budget.json").exists())

    def test_missing_budget_file_is_treated_as_a_fresh_project(self) -> None:
        self.write_task("TASK-005", "IN_PROGRESS")
        self.assertFalse((self.project / ".meridian/budget.json").exists())
        result = self.run_cli("budget", "show", "TASK-005")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("0/3", result.stdout)

    def test_git_budget_state_uses_common_metadata_and_migrates_legacy_file(self) -> None:
        self.write_task("TASK-016", "IN_PROGRESS")
        subprocess.run(("git", "init", str(self.project)), check=True, capture_output=True, text=True)
        legacy = self.project / ".meridian/budget.json"
        legacy.parent.mkdir(exist_ok=True)
        legacy.write_text(json.dumps({"TASK-016:1": {"diagnostic": 1}}), encoding="utf-8")
        subprocess.run(("git", "-C", str(self.project), "add", "."), check=True, capture_output=True, text=True)
        subprocess.run(("git", "-C", str(self.project), "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "legacy state"), check=True, capture_output=True, text=True)
        shown = self.run_cli("budget", "show", "TASK-016")
        self.assertEqual(shown.returncode, 0, shown.stderr)
        self.assertIn("Diagnostics 1/3", shown.stdout)
        self.assertEqual(subprocess.run(
            ("git", "-C", str(self.project), "status", "--porcelain"),
            check=True, capture_output=True, text=True,
        ).stdout, "")

        result = self.run_cli("budget", "spend", "TASK-016", "diagnostic")
        self.assertEqual(result.stdout.strip(), "TASK-016: diagnostic 2/3")
        self.assertIn("commit its deletion", result.stderr)
        self.assertFalse(legacy.exists())
        self.assertEqual(json.loads(meridian.budget_state_path(self.project).read_text(encoding="utf-8"))["TASK-016:1"]["diagnostic"], 2)
        self.assertNotEqual(subprocess.run(("git", "-C", str(self.project), "ls-files", "--error-unmatch", ".meridian/budget.json"), capture_output=True, text=True, check=False).returncode, 0)
        second = self.run_cli("budget", "spend", "TASK-016", "diagnostic")
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertNotIn("commit its deletion", second.stderr)

    def test_budget_command_from_a_task_worktree_leaves_its_index_unchanged(self) -> None:
        self.write_task("TASK-017", "IN_PROGRESS")
        subprocess.run(("git", "init", str(self.project)), check=True, capture_output=True, text=True)
        legacy = self.project / ".meridian/budget.json"
        legacy.parent.mkdir(exist_ok=True)
        legacy.write_text('{"TASK-017:1": {"diagnostic": 1}}\n', encoding="utf-8")
        subprocess.run(("git", "-C", str(self.project), "add", "."), check=True, capture_output=True, text=True)
        subprocess.run(
            ("git", "-C", str(self.project), "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
             "commit", "-m", "legacy state"), check=True, capture_output=True, text=True,
        )
        worktree = Path(self.temporary.name) / "task-worktree"
        subprocess.run(("git", "-C", str(self.project), "worktree", "add", "-b", "task-017", str(worktree)),
                       check=True, capture_output=True, text=True)

        count, cap = meridian.budget_spend(worktree, "TASK-017", "diagnostic")
        self.assertEqual((count, cap), (2, 3))
        self.assertEqual(subprocess.run(
            ("git", "-C", str(worktree), "status", "--porcelain"),
            check=True, capture_output=True, text=True,
        ).stdout, "")
        self.assertIn("D  .meridian/budget.json", subprocess.run(
            ("git", "-C", str(self.project), "status", "--porcelain"),
            check=True, capture_output=True, text=True,
        ).stdout)

    def test_new_review_attempt_gets_a_fresh_allocation(self) -> None:
        self.write_task("TASK-006", "IN_PROGRESS")
        self.run_cli("budget", "spend", "TASK-006", "diagnostic")
        self.run_cli("budget", "spend", "TASK-006", "diagnostic")

        # Reviewer's handoff commit moves the task to READY_FOR_REVIEW...
        self.write_task("TASK-006", "READY_FOR_REVIEW")
        # A mutation at that status records the transition; `budget show` is
        # deliberately read-only and must not do so.
        self.run_cli("budget", "spend", "TASK-006", "diagnostic")
        # ...then `Address review TASK-006` moves it back to IN_PROGRESS: a
        # new remediation attempt, which must not inherit the old counters.
        self.write_task("TASK-006", "IN_PROGRESS")

        after = self.run_cli("budget", "spend", "TASK-006", "diagnostic")
        self.assertEqual(after.returncode, 0, after.stderr)
        self.assertEqual(after.stdout.strip(), "TASK-006: diagnostic 1/3")

        state = self.budget_state()
        self.assertIn("Attempt 2", self.run_cli("budget", "show", "TASK-006").stdout)
        self.assertEqual(state["TASK-006"]["attempt"], 2)
        self.assertEqual(state["TASK-006:1"]["diagnostic"], 3)
        self.assertEqual(state["TASK-006:2"]["diagnostic"], 1)


class CapabilityMarkerTest(unittest.TestCase):
    """Phase 1 of migrations/CAPABILITY_MARKERS.md: markers exist and are well-formed.

    No detection or verification code reads these yet (that's phase 2+); this
    only guards the markers themselves against silent drift or malformed
    nesting as the templates keep changing.
    """

    WORKFLOW = ROOT / "templates" / "workflows" / "governed-sdd"

    def marker_pairs(self, text: str) -> list[tuple[str, str]]:
        begins = MARKER_BEGIN.findall(text)
        end_count = text.count(MARKER_END)
        self.assertEqual(
            len(begins), end_count, "mismatched MERIDIAN:BEGIN/END marker count"
        )
        return begins

    def test_agents_and_claude_carry_expected_marker_versions(self) -> None:
        for name in ("AGENTS.md", "CLAUDE.md"):
            self.assertEqual(self.marker_pairs((self.WORKFLOW / name).read_text(encoding="utf-8")), [("command-triggers", "3")])
        self.assertIn(("review-remediation-record", "6"), self.marker_pairs((self.WORKFLOW / "docs/workflows/REMEDIATION.md").read_text(encoding="utf-8")))
        self.assertIn(("lifecycle-orchestration", "3"), self.marker_pairs((self.WORKFLOW / "docs/workflows/LIFECYCLE.md").read_text(encoding="utf-8")))
        implementation = self.marker_pairs((self.WORKFLOW / "docs/workflows/IMPLEMENTATION.md").read_text(encoding="utf-8"))
        for pair in (("execution-command-gate", "4"), ("validation-scoping", "2"), ("spike-routing", "2"), ("host-impact-routing", "2")):
            self.assertIn(pair, implementation)

    def test_manual_proceed_migration_does_not_declare_remediation_changes(self) -> None:
        migration = json.loads((ROOT / "migrations/056-manual-governed-proceed-worktree.json").read_text())
        self.assertNotIn("docs/workflows/REMEDIATION.md", migration["managedPaths"])
        adoption = json.loads((ROOT / "migrations/066-machine-task-state-adoption.json").read_text())
        self.assertIn("docs/workflows/REMEDIATION.md", adoption["managedPaths"])

    def test_host_impact_declaration_has_both_governed_shapes_and_evidence_routing(self) -> None:
        blueprint = (self.WORKFLOW / "tasks/TASK_BLUEPRINT.md").read_text(encoding="utf-8")
        implementation = (self.WORKFLOW / "docs/workflows/IMPLEMENTATION.md").read_text(encoding="utf-8")
        self.assertIn(("task-blueprint", "18"), self.marker_pairs(blueprint))
        self.assertIn("Classification: NOT_APPLICABLE", blueprint)
        self.assertIn("Rationale:", blueprint)
        self.assertIn("Classification: REQUIRED", blueprint)
        self.assertIn("| Profile | Before | Intended after | Activation preconditions | Fallback |", blueprint)
        self.assertIn("- Static:", blueprint)
        self.assertIn("- Host execution:", blueprint)
        self.assertIn("- Manual activation:", blueprint)
        self.assertIn("Completion evidence:", blueprint)
        self.assertIn(("host-impact-routing", "2"), self.marker_pairs(implementation))
        self.assertIn("return `BLOCKED HOST_IMPACT_DECLARATION_INVALID`", implementation)
        self.assertIn("not host enforcement", implementation)

    def test_review_record_template_carries_its_own_marker(self) -> None:
        text = (self.WORKFLOW / "docs/REVIEW_RECORD_TEMPLATE.md").read_text(encoding="utf-8")
        self.assertEqual(
            self.marker_pairs(text),
            [("review-remediation-record", "6"), ("manual-verification-record", "1")],
        )

    def test_lifecycle_orchestration_carries_its_own_marker(self) -> None:
        text = (self.WORKFLOW / "docs/LIFECYCLE_ORCHESTRATION.md").read_text(encoding="utf-8")
        self.assertEqual(
            self.marker_pairs(text),
            [("lifecycle-orchestration", "12"), ("rejected-attempt-restart", "5")],
        )

    def test_context_budget_policy_carries_its_capability_markers(self) -> None:
        text = (self.WORKFLOW / "docs/CONTEXT_BUDGET_POLICY.md").read_text(encoding="utf-8")
        self.assertEqual(
            self.marker_pairs(text),
            [
                ("queue-briefing", "1"),
                ("authority-excerpt", "1"),
                ("read-guard", "2"),
                ("isolated-exploration", "1"),
                ("minimal-read-only-status", "3"),
                ("validation-scoping", "2"),
                ("evidence-tiers", "1"),
                ("execution-evidence-profile", "5"),
                ("phase-reads", "1"),
            ],
        )

    def test_execution_evidence_profile_is_stack_agnostic_and_configurable(self) -> None:
        policy = (self.WORKFLOW / "docs/CONTEXT_BUDGET_POLICY.md").read_text(encoding="utf-8")
        profile = (self.WORKFLOW / "docs/EXECUTION_EVIDENCE_PROFILE.md").read_text(
            encoding="utf-8"
        )
        self.assertIn(("execution-evidence-profile", "5"), self.marker_pairs(policy))
        self.assertIn("Successful validation output", profile)
        self.assertIn("Failure diagnostics", profile)
        self.assertIn("Manual evidence", profile)
        self.assertNotIn("cargo", profile.lower())

    def test_reasoning_budget_contract_was_retired_from_governed_templates(self) -> None:
        """Migration 063 retires `reasoning-budget-contract` through `removes`;
        no managed Governed SDD text may require choosing, recording, matching,
        confirming, or escalating a reasoning level."""
        paths = [
            "tasks/TASK_BLUEPRINT.md",
            "docs/CONTEXT_BUDGET_POLICY.md",
            "docs/LIFECYCLE_ORCHESTRATION.md",
            "docs/OPERATOR_PROMPTS.md",
            "docs/PULL_REQUEST_POLICY.md",
            "docs/EXECUTION_EVIDENCE_PROFILE.md",
        ]
        texts = {path: (self.WORKFLOW / path).read_text(encoding="utf-8") for path in paths}

        self.assertIn(("task-blueprint", "18"), self.marker_pairs(texts["tasks/TASK_BLUEPRINT.md"]))
        self.assertIn(
            ("lifecycle-orchestration", "12"), self.marker_pairs(texts["docs/LIFECYCLE_ORCHESTRATION.md"])
        )
        self.assertNotIn(
            "reasoning-budget-contract", dict(self.marker_pairs(texts["docs/CONTEXT_BUDGET_POLICY.md"]))
        )
        for path, text in texts.items():
            self.assertNotIn("reasoning-budget-contract", text, path)
            self.assertNotIn("`Reasoning`", text, path)
            self.assertNotIn("Reasoning justification", text, path)
            self.assertNotIn("reasoning level", text, path)
            self.assertNotIn("reasoning cap", text, path)
        migration = json.loads(
            (ROOT / "migrations/063-retire-reasoning-budget-contract.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            migration["removes"], [{"capability": "reasoning-budget-contract", "capabilityVersion": 1}]
        )
        self.assertIn("reasoning-budget-contract", meridian.retired_capability_ids(ROOT))
        self.assertNotIn("reasoning-budget-contract", meridian.capability_requirements(ROOT))

    def test_role_scoped_agent_rules_was_retired_not_merely_deleted_by_hand(self) -> None:
        """Task 008 retired `role-scoped-agent-rules` (docs/AUDIT_TOKEN_EFFICIENCY.md
        F5) through migration 025's `removes` field, task 007's retirement
        path — not a direct template edit. This is the regression guard for
        that decision: the capability, and the section it named, must stay
        gone, and `capability_requirements()` must no longer require it."""
        policy = (self.WORKFLOW / "docs/CONTEXT_BUDGET_POLICY.md").read_text(encoding="utf-8")
        self.assertNotIn("role-scoped-agent-rules", policy)
        self.assertNotIn("Role-scoped agent-rules reading", policy)
        self.assertIn("role-scoped-agent-rules", meridian.retired_capability_ids(ROOT))
        self.assertNotIn("role-scoped-agent-rules", meridian.capability_requirements(ROOT))

    def test_minimal_read_only_status_profile_limits_context_expansion(self) -> None:
        policy = (self.WORKFLOW / "docs/CONTEXT_BUDGET_POLICY.md").read_text(encoding="utf-8")
        prompts = (self.WORKFLOW / "docs/OPERATOR_PROMPTS.md").read_text(encoding="utf-8")
        self.assertIn("A status report is not a conformance audit.", policy)
        self.assertIn("Before every expanded read", policy)
        self.assertIn("Use the minimal read-only status profile", prompts)
        self.assertIn("Do not load completed milestones", prompts)

    def test_operator_prompts_resolve_locations_and_bound_framework_maintenance(self) -> None:
        prompts = (self.WORKFLOW / "docs/OPERATOR_PROMPTS.md").read_text(encoding="utf-8")
        self.assertIn("Resolve the canonical queue, task, and review-record locations", prompts)
        self.assertIn("meridian locations --project .", prompts)
        self.assertIn("Do not substitute a template path", prompts)
        self.assertIn("Class:\nSPIKE", prompts)
        self.assertIn("meridian upgrade --project . --check", prompts)
        self.assertIn("Do not run\n`meridian upgrade --apply`, `meridian adopt`, or `finalize-adoption`", prompts)
        self.assertNotIn("## 3. Design the next milestone or phase", prompts)
        self.assertIn("## 1a. Align tech design for questions and future work (read-only)", prompts)
        self.assertIn("Return a concise readiness brief", prompts)
        self.assertIn("Do not modify files, create ADRs or tasks", prompts)

    def test_ci_verified_validation_marker_in_each_of_its_three_docs(self) -> None:
        pull_request_policy = (self.WORKFLOW / "docs/PULL_REQUEST_POLICY.md").read_text(encoding="utf-8")
        self.assertEqual(
            self.marker_pairs(pull_request_policy),
            [
                ("task-worktree-integration", "7"),
                ("ci-verified-validation", "1"),
                ("remote-branch-cleanup", "1"),
            ],
        )

        code_review_prompt = (self.WORKFLOW / "docs/CODE_REVIEW_PROMPT.md").read_text(encoding="utf-8")
        self.assertEqual(
            self.marker_pairs(code_review_prompt),
            [("code-review-prompt", "3")],
        )

        completion_report = (self.WORKFLOW / "docs/COMPLETION_REPORT_TEMPLATE.md").read_text(encoding="utf-8")
        self.assertEqual(
            self.marker_pairs(completion_report),
            [
                ("task-worktree-handoff", "5"),
                ("handoff-correction-redelivery", "1"),
                ("manual-verification-record", "1"),
                ("ci-verified-validation", "1"),
            ],
        )

    def test_manual_verification_precondition_gates_implementation_start(self) -> None:
        agents = (self.WORKFLOW / "docs/workflows/IMPLEMENTATION.md").read_text(encoding="utf-8")
        self.assertIn(("manual-verification-precondition", "4"), self.marker_pairs(agents))
        self.assertIn("Manual verification: required", agents)
        self.assertIn("return `BLOCKED SCOPE_CHANGE_REQUIRED` immediately", agents)
        self.assertIn("deterministic test", agents)
        self.assertIn("probe that actually succeeds", agents)
        self.assertIn(
            "never respond to a failed probe by exploring the local environment for an alternative",
            agents,
        )
        self.assertIn(
            "it never suspends the requirement to stop on a probe that has already been "
            "attempted and failed",
            agents,
        )
        self.assertIn("check its `Manual verification rationale` first, before any probe", agents)
        self.assertIn("do not run the probe", agents)

    def test_manual_verification_record_fields_in_completion_and_review_records(self) -> None:
        completion_report = (self.WORKFLOW / "docs/COMPLETION_REPORT_TEMPLATE.md").read_text(encoding="utf-8")
        self.assertIn("Manual verification: `<none | screenshot path", completion_report)
        review_record = (self.WORKFLOW / "docs/REVIEW_RECORD_TEMPLATE.md").read_text(encoding="utf-8")
        self.assertIn(("manual-verification-record", "1"), self.marker_pairs(review_record))
        self.assertIn("Manual verification observed:", review_record)
        self.assertIn("independently confirms", review_record)

    def test_project_workflow_carries_all_declared_baseline_capabilities(self) -> None:
        text = (self.WORKFLOW / "PROJECT_WORKFLOW.md").read_text(encoding="utf-8")
        pairs = self.marker_pairs(text)
        expected = {
            capability: "1"
            for capability in (
                "workflow-mode-lock",
                "document-precedence",
                "execution-assets",
                "roles",
                "git-workflow",
                "execution-discipline",
            )
        }
        expected["workflow-mode-lock"] = "2"
        expected["document-precedence"] = "2"
        expected["execution-assets"] = "4"
        expected["roles"] = "4"
        expected["git-workflow"] = "14"
        expected["bounded-worktree-lifecycle"] = "5"
        expected["codex-worktree-access"] = "4"
        expected["task-identity-policy"] = "1"
        expected["task-lifecycle"] = "4"
        expected["review-policy"] = "3"
        expected["worktree-command-locations"] = "1"
        expected["worktree-budget-retirement"] = "1"
        self.assertEqual(sorted(pairs), sorted(expected.items()))

    def test_git_workflow_block_drives_closure_through_advance(self) -> None:
        for path in (
            self.WORKFLOW / "PROJECT_WORKFLOW.md",
            ROOT / "templates" / "workflows" / "lean-delivery" / "PROJECT_WORKFLOW.md",
        ):
            text = path.read_text(encoding="utf-8")
            start = text.index("capability=git-workflow")
            block = " ".join(text[start : text.index("<!-- MERIDIAN:END -->", start)].split())
            self.assertIn("meridian worktree advance", block, path)
            self.assertIn("`action_required`", block, path)
            self.assertIn("`BLOCKED <CODE>`", block, path)
            self.assertNotIn("Close a validated task in order", block, path)
            self.assertNotIn("closure-status", block, path)
            self.assertIn("`Validation skips:`", block, path)

    def test_whole_file_baseline_capabilities_each_carry_one_marker(self) -> None:
        expectations = {
            "LANGUAGE_POLICY.md": ("language-policy", "2"),
            "tasks/TASK_BLUEPRINT.md": ("task-blueprint", "18"),
            "docs/CODE_ORGANIZATION.md": ("code-organization", "2"),
            "docs/AUDIT_PROMPT_READ_ONLY.md": ("audit-prompt", "4"),
        }
        for name, pair in expectations.items():
            text = (self.WORKFLOW / name).read_text(encoding="utf-8")
            self.assertEqual(self.marker_pairs(text), [pair], name)

    def test_language_policy_marker_excludes_the_per_project_language_line(self) -> None:
        """Corrective migration 013: meridian-init.md replaces
        [Conversation language] with the project's actual choice, so that
        line must sit outside the protected region or every correctly
        initialized project would fail meridian audit on day one."""
        text = (self.WORKFLOW / "LANGUAGE_POLICY.md").read_text(encoding="utf-8")
        match = re.search(
            r"<!-- MERIDIAN:BEGIN capability=language-policy v2 -->\n?(.*?)"
            r"<!-- MERIDIAN:END -->",
            text,
            re.DOTALL,
        )
        self.assertIsNotNone(match)
        self.assertNotIn("[Conversation language]", match.group(1))

    def test_agents_and_claude_carry_the_five_residual_capabilities(self) -> None:
        self.assertIn(("command-triggers", "3"), self.marker_pairs((self.WORKFLOW / "AGENTS.md").read_text(encoding="utf-8")))
        review = self.marker_pairs((self.WORKFLOW / "docs/workflows/REVIEW.md").read_text(encoding="utf-8"))
        self.assertIn(("review-mode-boundary", "3"), review)
        self.assertIn(("implementer-reviewer-handoff", "5"), review)
        self.assertIn(("reviewer-integrator-identity", "3"), review)
        self.assertIn(("task-worktree-review-procedure", "13"), review)

    def test_review_preflight_fails_closed_before_substantive_inspection(self) -> None:
        review = (self.WORKFLOW / "docs/workflows/REVIEW.md").read_text(encoding="utf-8")
        preflight = review.index("## Mandatory task-worktree preflight")
        substantive = review.index("Only after every preflight check passes")
        boundary = review.index("### Review-mode boundary")
        normalized = " ".join(review.split())
        self.assertLess(preflight, substantive)
        self.assertLess(preflight, boundary)
        for condition in (
            "session started in the primary checkout",
            "locate exactly one registered entry",
            "path is absent",
            "mismatched branch",
            "mismatched `HEAD`",
            "dirty worktree",
            "disagrees with the handoff",
            "active or unconfirmed implementer",
            "validated task and base commits exist",
            "resolve it to the registered task branch `HEAD`",
            "mismatched subject",
        ):
            with self.subTest(condition=condition):
                self.assertIn(condition, normalized)
        self.assertIn("every such read uses the verified absolute", review)
        self.assertIn("every Git command uses `git -C", review)
        self.assertNotIn("uses that same primary checkout", review)
        self.assertNotIn("git switch <task-branch>", review)
        self.assertNotRegex(
            review,
            r"(?is)leave the primary checkout.{0,80}on the task branch",
        )

    def test_review_mode_boundary_has_no_hardcoded_review_record_path(self) -> None:
        text = (self.WORKFLOW / "docs/workflows/REVIEW.md").read_text(encoding="utf-8")
        match = re.search(
            r"<!-- MERIDIAN:BEGIN capability=review-mode-boundary v3 -->\n?(.*?)"
            r"<!-- MERIDIAN:END -->",
            text,
            re.DOTALL,
        )
        self.assertIsNotNone(match)
        self.assertNotIn("tasks/reviews/<TASK-ID>.md", match.group(1))


class DuplicateHeadingAuditTest(unittest.TestCase):
    """`audit_duplicate_headings` (task 007's duplication-detection half):
    flags a capability whose marker sits under more than one distinct
    heading within the same managed file -- the mechanical signature of an
    accidental duplicate paste. Scoped to one file at a time: the same
    capability legitimately appears under different heading names across
    different consuming documents by design.
    """

    def test_real_templates_have_no_within_file_duplicate_headings(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        project = Path(temporary.name) / "project"
        source = ROOT / "templates" / "workflows" / "governed-sdd"
        for path in source.rglob("*"):
            if path.is_file():
                destination = project / path.relative_to(source)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, destination)
        results = meridian.audit_duplicate_headings(project, ROOT, "governed-sdd")
        self.assertEqual(results, [])

    def test_flags_a_capability_duplicated_under_two_headings_in_one_file(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        project = Path(temporary.name) / "project"
        project.mkdir(parents=True)
        (project / "PROJECT_WORKFLOW.md").write_text(
            "## First section\n\n"
            "<!-- MERIDIAN:BEGIN capability=dup-rule v1 -->\ntext.\n<!-- MERIDIAN:END -->\n\n"
            "## Second section\n\n"
            "<!-- MERIDIAN:BEGIN capability=dup-rule v1 -->\ntext.\n<!-- MERIDIAN:END -->\n",
            encoding="utf-8",
        )

        class FakeManagedFile:
            def __init__(self, target: Path) -> None:
                self.target = target
                self.source = project / target

        original = meridian.managed_files
        meridian.managed_files = lambda framework_root, mode: [FakeManagedFile(Path("PROJECT_WORKFLOW.md"))]
        try:
            results = meridian.audit_duplicate_headings(project, ROOT, "governed-sdd")
        finally:
            meridian.managed_files = original
        self.assertEqual(len(results), 1)
        status, message = results[0]
        self.assertEqual(status, "FAIL")
        self.assertIn("dup-rule", message)
        self.assertIn("First section", message)
        self.assertIn("Second section", message)

    def test_does_not_flag_the_same_capability_under_the_same_heading_name_across_files(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        project = Path(temporary.name) / "project"
        project.mkdir(parents=True)
        for name in ("AGENTS.md", "CLAUDE.md"):
            (project / name).write_text(
                "## Command triggers\n\n"
                "<!-- MERIDIAN:BEGIN capability=command-triggers v1 -->\ntext.\n<!-- MERIDIAN:END -->\n",
                encoding="utf-8",
            )

        class FakeManagedFile:
            def __init__(self, target: Path) -> None:
                self.target = target
                self.source = project / target

        original = meridian.managed_files
        meridian.managed_files = lambda framework_root, mode: [
            FakeManagedFile(Path("AGENTS.md")),
            FakeManagedFile(Path("CLAUDE.md")),
        ]
        try:
            results = meridian.audit_duplicate_headings(project, ROOT, "governed-sdd")
        finally:
            meridian.managed_files = original
        self.assertEqual(results, [])


class CodexRulesUpgradeTest(unittest.TestCase):
    """Regression coverage for task 040's newly managed Codex rules file."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.framework = root / "framework"
        self.project = root / "project"
        shutil.copytree(ROOT / "templates", self.framework / "templates")
        shutil.copytree(ROOT / "migrations", self.framework / "migrations")
        shutil.copytree(ROOT / "capabilities", self.framework / "capabilities")
        self.project.mkdir()
        source = self.framework / "templates/workflows/governed-sdd"
        for path in source.rglob("*"):
            if path.is_file():
                destination = self.project / path.relative_to(source)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, destination)
        self.rules = source / ".codex/rules/meridian.rules"
        self.rules_text = self.rules.read_text(encoding="utf-8")
        (self.framework / "VERSION").write_text("1.1.37\n", encoding="utf-8")
        self.assertEqual(self.run_cli("lock", "--mode", "governed-sdd").returncode, 0)
        # A 1.1.37 consumer predates task 040. Remove the new file from both
        # its live tree and recorded baseline while keeping the current
        # framework template intact as the incoming 1.1.38 source.
        (self.project / ".codex/rules/meridian.rules").unlink()
        (
            self.project
            / ".meridian/baselines/1.1.37/.codex/rules/meridian.rules"
        ).unlink()
        (self.project / ".codex/rules").rmdir()
        (self.project / ".codex/hooks.json").unlink()
        (self.project / ".codex").rmdir()
        (self.framework / "VERSION").write_text("1.1.38\n", encoding="utf-8")
        # This fixture models 1.1.38 immediately after task 040, before task 041.
        (self.framework / "templates/workflows/governed-sdd/.codex/hooks.json").unlink()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(CLI),
                "--framework-root",
                str(self.framework),
                *arguments,
                "--project",
                str(self.project),
            ],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_upgrade_adds_rules_when_consumer_has_no_codex_directory(self) -> None:
        self.assertFalse((self.project / ".codex").exists())
        checked = self.run_cli("upgrade", "--check")
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertIn("ADD      .codex/rules/meridian.rules — new managed file", checked.stdout)

        applied = self.run_cli("upgrade", "--apply")
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        self.assertEqual(
            (self.project / ".codex/rules/meridian.rules").read_text(encoding="utf-8"),
            self.rules_text,
        )

    def test_upgrade_conflicts_without_overwriting_locally_precreated_rules(self) -> None:
        local = self.project / ".codex/rules/meridian.rules"
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_text("prefix_rule(pattern=[\"echo\"], decision=\"allow\")\n", encoding="utf-8")

        checked = self.run_cli("upgrade", "--check")
        self.assertNotEqual(checked.returncode, 0)
        self.assertIn("CONFLICT .codex/rules/meridian.rules — managed baseline is missing", checked.stdout)
        self.assertEqual(local.read_text(encoding="utf-8"), "prefix_rule(pattern=[\"echo\"], decision=\"allow\")\n")


class CodexWorktreeAccessTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def repository(self, name: str, remote: str | None = None) -> Path:
        path = self.root / name
        path.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Meridian Test"], cwd=path, check=True)
        subprocess.run(["git", "config", "user.email", "meridian@example.invalid"], cwd=path, check=True)
        (path / "README.md").write_text(f"# {name}\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=path, check=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=path, check=True, capture_output=True)
        if remote:
            subprocess.run(["git", "remote", "add", "origin", remote], cwd=path, check=True)
        return path

    def test_repository_namespaces_prevent_equal_task_id_collisions(self) -> None:
        first = self.repository("first", "git@github.com:acme/one.git")
        second = self.repository("second", "https://gitlab.example/acme/two.git")
        worktrees = (self.root / "worktrees").resolve()
        first_path = meridian.task_worktree_path(first, worktrees, "TASK-054")
        second_path = meridian.task_worktree_path(second, worktrees, "task-054")
        self.assertEqual(first_path.relative_to(worktrees).parts, ("github.com", "acme", "one", "task-054"))
        self.assertEqual(second_path.relative_to(worktrees).parts, ("gitlab.example", "acme", "two", "task-054"))
        self.assertNotEqual(first_path, second_path)

    def test_local_identity_contains_name_and_common_directory_hash(self) -> None:
        project = self.repository("local-project")
        identity = meridian.repository_identity(project)
        self.assertEqual((identity.remote_host, identity.owner), ("local", "repositories"))
        self.assertRegex(identity.repository, r"^local-project-[0-9a-f]{12}$")
        self.assertEqual(identity, meridian.repository_identity(project))

    def test_unsafe_identity_task_and_root_are_rejected(self) -> None:
        project = self.repository("safe", "git@example.com:../repo.git")
        with self.assertRaises(meridian.MeridianError):
            meridian.repository_identity(project)
        with self.assertRaises(meridian.MeridianError):
            meridian.canonical_task_id("../054")
        with self.assertRaises(meridian.MeridianError):
            meridian.task_worktree_path(self.repository("other"), Path.home(), "054")

    def test_existing_path_for_another_repository_is_a_collision(self) -> None:
        first = self.repository("one", "git@github.com:acme/shared.git")
        second = self.repository("two", "git@github.com:acme/shared.git")
        path = self.root / "existing"
        subprocess.run(["git", "-C", str(first), "worktree", "add", "-b", "task-054", str(path), "main"], check=True, capture_output=True)
        with self.assertRaisesRegex(meridian.MeridianError, "collision"):
            meridian.validate_worktree_collision(second, path, "054")

    def test_namespaced_symlink_escape_is_rejected(self) -> None:
        project = self.repository("safe", "git@github.com:acme/repo.git")
        worktrees = self.root / "worktrees"
        worktrees.mkdir()
        outside = self.root / "outside"
        outside.mkdir()
        (worktrees / "github.com").symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(meridian.MeridianError, "symlink"):
            meridian.task_worktree_path(project, worktrees, "054")

    def test_config_apply_preserves_text_backs_up_and_is_idempotent(self) -> None:
        config = self.root / "config.toml"
        original = (
            '# keep this comment\n'
            'notify = ["/usr/bin/example", "turn-ended"]\n'
            'model = "gpt-test"\n'
            'model_reasoning_effort = "medium"\n\n'
            '[features]\n'
            'network_proxy = false\n'
        )
        config.write_text(original, encoding="utf-8")
        root = self.root / "worktrees"
        plan = meridian.plan_codex_configuration(config, root)
        self.assertEqual(plan.status, "approval-required")
        self.assertTrue(meridian.apply_codex_configuration(plan))
        changed = config.read_text(encoding="utf-8")
        self.assertIn("# keep this comment", changed)
        self.assertIn(str(root.resolve()), changed)
        parsed = tomllib.loads(changed)
        self.assertEqual(parsed["default_permissions"], "meridian-worktrees")
        self.assertEqual(parsed["notify"], ["/usr/bin/example", "turn-ended"])
        self.assertEqual(parsed["model"], "gpt-test")
        self.assertEqual(parsed["model_reasoning_effort"], "medium")
        self.assertEqual(
            parsed["permissions"]["meridian-worktrees"]["workspace_roots"],
            {str(root.resolve()): True},
        )
        self.assertLess(changed.index('model = "gpt-test"'), changed.index(meridian.CODEX_MANAGED_BEGIN))
        self.assertLess(changed.index(meridian.CODEX_MANAGED_END), changed.index("[features]"))
        self.assertEqual(config.with_name("config.toml.meridian.bak").read_text(encoding="utf-8"), original)
        second = meridian.plan_codex_configuration(config, root)
        self.assertEqual(second.status, "ready")
        self.assertFalse(meridian.apply_codex_configuration(second))

    def test_config_plan_repairs_managed_block_inserted_before_root_keys(self) -> None:
        config = self.root / "config.toml"
        root = (self.root / "worktrees").resolve()
        broken = (
            meridian._codex_managed_block(root)
            + '\n\nnotify = ["/usr/bin/example", "turn-ended"]\n'
            + 'model = "gpt-test"\n\n'
            + '[features]\nnetwork_proxy = false\n'
        )
        config.write_text(broken, encoding="utf-8")

        plan = meridian.plan_codex_configuration(config, root)

        self.assertEqual(plan.status, "approval-required")
        repaired = plan.proposed_text or ""
        parsed = tomllib.loads(repaired)
        self.assertEqual(parsed["notify"], ["/usr/bin/example", "turn-ended"])
        self.assertEqual(parsed["model"], "gpt-test")
        self.assertEqual(
            parsed["permissions"]["meridian-worktrees"]["workspace_roots"],
            {str(root): True},
        )
        self.assertLess(repaired.index('model = "gpt-test"'), repaired.index(meridian.CODEX_MANAGED_BEGIN))

    def test_atomic_replace_failure_keeps_original(self) -> None:
        config = self.root / "config.toml"
        original = 'model = "gpt-test"\n'
        config.write_text(original, encoding="utf-8")
        plan = meridian.plan_codex_configuration(config, self.root / "worktrees")
        with mock.patch.object(meridian.os, "replace", side_effect=OSError("simulated")):
            with self.assertRaises(OSError):
                meridian.apply_codex_configuration(plan)
        self.assertEqual(config.read_text(encoding="utf-8"), original)

    def test_conflicting_and_malformed_configuration_is_blocked(self) -> None:
        config = self.root / "config.toml"
        config.write_text('sandbox_mode = "workspace-write"\n', encoding="utf-8")
        with self.assertRaisesRegex(meridian.MeridianError, "legacy"):
            meridian.plan_codex_configuration(config, self.root / "worktrees")
        config.write_text("broken = [\n", encoding="utf-8")
        with self.assertRaisesRegex(meridian.MeridianError, "malformed"):
            meridian.plan_codex_configuration(config, self.root / "worktrees")

    def test_managed_requirements_must_allow_the_profile(self) -> None:
        config = self.root / "config.toml"
        requirements = self.root / "requirements.toml"
        requirements.write_text('[allowed_permission_profiles]\nother = true\n', encoding="utf-8")
        with self.assertRaisesRegex(meridian.MeridianError, "managed"):
            meridian.plan_codex_configuration(config, self.root / "worktrees", requirements)
        requirements.write_text('[allowed_permission_profiles]\nmeridian-worktrees = true\n', encoding="utf-8")
        self.assertEqual(
            meridian.plan_codex_configuration(config, self.root / "worktrees", requirements).status,
            "approval-required",
        )

    def test_existing_permission_profile_selection_is_replaced_without_losing_profiles(self) -> None:
        config = self.root / "config.toml"
        config.write_text(
            'default_permissions = ":workspace"\n\n[permissions.other]\nextends = ":read-only"\n',
            encoding="utf-8",
        )
        plan = meridian.plan_codex_configuration(config, self.root / "worktrees")
        self.assertIsNotNone(plan.proposed_text)
        parsed = tomllib.loads(plan.proposed_text or "")
        self.assertEqual(parsed["default_permissions"], "meridian-worktrees")
        self.assertEqual(parsed["permissions"]["other"]["extends"], ":read-only")

    def test_initializer_only_offers_explicit_check_and_apply(self) -> None:
        instructions = (ROOT / "commands/meridian-init.md").read_text(encoding="utf-8")
        self.assertIn("meridian setup --check", instructions)
        self.assertIn("meridian setup --apply` only after explicit confirmation", instructions)
        self.assertIn("not invalidate initialization", instructions)


class WorktreeRootSetupTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary.name).resolve()
        self.cwd_patch = mock.patch.object(meridian.Path, "cwd", return_value=self.home)
        self.cwd_patch.start()
        self.xdg = self.home / "xdg"
        self.user_config = self.xdg / "meridian/config.json"
        self.codex_config = self.home / "codex/config.toml"
        self.environment = {"HOME": str(self.home), "XDG_CONFIG_HOME": str(self.xdg)}

    def tearDown(self) -> None:
        self.cwd_patch.stop()
        self.temporary.cleanup()

    def resolve(self, explicit: Path | None = None, **environment: str) -> meridian.ResolvedWorktreeRoot:
        return meridian.resolve_worktree_root(
            explicit,
            environment={**self.environment, **environment},
            home=self.home,
        )

    def test_resolution_precedence_and_source_reporting(self) -> None:
        default = self.resolve()
        self.assertEqual(default.path, self.home / ".meridian/worktrees")
        self.assertEqual(default.source, "default")

        configured = self.home / "configured"
        self.user_config.parent.mkdir(parents=True)
        self.user_config.write_text(
            json.dumps({"version": 1, "worktreeRoot": str(configured)}), encoding="utf-8"
        )
        self.assertEqual(self.resolve(), meridian.ResolvedWorktreeRoot(configured, "user-config", self.user_config))

        from_environment = self.home / "environment"
        resolved_environment = self.resolve(MERIDIAN_WORKTREE_ROOT=str(from_environment))
        self.assertEqual((resolved_environment.path, resolved_environment.source), (from_environment, "MERIDIAN_WORKTREE_ROOT"))

        explicit = self.home / "explicit"
        resolved_explicit = self.resolve(explicit, MERIDIAN_WORKTREE_ROOT=str(explicit))
        self.assertEqual((resolved_explicit.path, resolved_explicit.source), (explicit, "--worktree-root"))

    def test_conflicting_explicit_and_environment_values_name_both_sources(self) -> None:
        with self.assertRaisesRegex(
            meridian.MeridianError, r"--worktree-root supplied .*MERIDIAN_WORKTREE_ROOT supplied"
        ):
            self.resolve(self.home / "explicit", MERIDIAN_WORKTREE_ROOT=str(self.home / "environment"))

    def test_configuration_schema_and_unsafe_roots_are_rejected(self) -> None:
        self.user_config.parent.mkdir(parents=True)
        for value in (
            {"worktreeRoot": str(self.home / "missing-version")},
            {"version": 2, "worktreeRoot": str(self.home / "future")},
            {"version": 1, "worktreeRoot": "", "extra": True},
        ):
            with self.subTest(value=value):
                self.user_config.write_text(json.dumps(value), encoding="utf-8")
                with self.assertRaises(meridian.MeridianError):
                    self.resolve()
        self.user_config.unlink()
        with self.assertRaisesRegex(meridian.MeridianError, "filesystem root"):
            self.resolve(Path("/"))
        with self.assertRaisesRegex(meridian.MeridianError, "home"):
            self.resolve(self.home)

    def test_check_is_read_only_and_reports_unconfigured_state(self) -> None:
        root = self.home / "custom"
        plan = meridian.plan_setup(
            root,
            self.codex_config,
            environment=self.environment,
            home=self.home,
        )
        output = io.StringIO()
        with redirect_stdout(output):
            meridian.print_setup_plan(plan)
        self.assertEqual(plan.directory_state, "missing")
        self.assertEqual(plan.codex_state, "unconfigured")
        self.assertIn("worktree-root-source: --worktree-root", output.getvalue())
        self.assertIn("create", output.getvalue())
        self.assertFalse(root.exists())
        self.assertFalse(self.user_config.exists())
        self.assertFalse(self.codex_config.exists())

    def test_cli_check_writes_nothing(self) -> None:
        root = self.home / "cli-root"
        environment = {
            **os.environ,
            "HOME": str(self.home),
            "XDG_CONFIG_HOME": str(self.xdg),
        }
        checked = subprocess.run(
            [
                sys.executable,
                str(CLI),
                "setup",
                "--check",
                "--worktree-root",
                str(root),
                "--config",
                str(self.codex_config),
            ],
            cwd=self.home,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertIn("codex-profile: unconfigured", checked.stdout)
        self.assertIn("worktree-root-source: --worktree-root", checked.stdout)
        self.assertFalse(root.exists())
        self.assertFalse(self.xdg.exists())
        self.assertFalse(self.codex_config.exists())

    def test_apply_creates_private_default_root_without_user_config_and_is_idempotent(self) -> None:
        first = meridian.plan_setup(
            None, self.codex_config, environment=self.environment, home=self.home
        )
        self.assertTrue(meridian.apply_setup(first))
        root = self.home / ".meridian/worktrees"
        self.assertTrue(root.is_dir())
        self.assertEqual(stat.S_IMODE(root.stat().st_mode), 0o700)
        self.assertFalse(self.user_config.exists())
        self.assertEqual(
            tomllib.loads(self.codex_config.read_text(encoding="utf-8"))["permissions"]
            ["meridian-worktrees"]["workspace_roots"],
            {str(root): True},
        )
        second = meridian.plan_setup(
            None, self.codex_config, environment=self.environment, home=self.home
        )
        self.assertEqual((second.directory_state, second.codex_state, second.changes), ("ready", "ready", ("none",)))
        self.assertFalse(meridian.apply_setup(second))

    def test_custom_root_is_persisted_and_private_permissions_are_repaired(self) -> None:
        root = self.home / "custom"
        root.mkdir(mode=0o755)
        plan = meridian.plan_setup(
            root, self.codex_config, environment=self.environment, home=self.home
        )
        self.assertEqual(plan.directory_state, "repair-required")
        self.assertTrue(meridian.apply_setup(plan))
        self.assertEqual(stat.S_IMODE(root.stat().st_mode), 0o700)
        self.assertEqual(
            json.loads(self.user_config.read_text(encoding="utf-8")),
            {"version": 1, "worktreeRoot": str(root)},
        )
        self.assertEqual(stat.S_IMODE(self.user_config.stat().st_mode), 0o600)

    def test_apply_refuses_a_non_directory_root_before_any_write(self) -> None:
        root = self.home / "not-a-directory"
        root.write_text("keep\n", encoding="utf-8")
        plan = meridian.plan_setup(
            root, self.codex_config, environment=self.environment, home=self.home
        )
        self.assertEqual(plan.directory_state, "blocked")
        self.assertEqual(plan.changes, ("none; setup is blocked before mutation",))
        with self.assertRaisesRegex(meridian.MeridianError, "not a directory"):
            meridian.apply_setup(plan)
        self.assertEqual(root.read_text(encoding="utf-8"), "keep\n")
        self.assertFalse(self.user_config.exists())
        self.assertFalse(self.codex_config.exists())

    def test_every_codex_setup_state_including_damaged_profile_root_replacement(self) -> None:
        root = self.home / "root"
        root.mkdir(mode=0o700)
        unconfigured = meridian.plan_setup(root, self.codex_config, environment=self.environment, home=self.home)
        self.assertEqual(unconfigured.codex_state, "unconfigured")
        meridian.apply_setup(unconfigured)
        self.assertEqual(
            meridian.plan_setup(root, self.codex_config, environment=self.environment, home=self.home).codex_state,
            "ready",
        )

        text = self.codex_config.read_text(encoding="utf-8")
        self.codex_config.write_text(text.replace(meridian.CODEX_MANAGED_END + "\n", ""), encoding="utf-8")
        self.assertEqual(
            meridian.plan_setup(root, self.codex_config, environment=self.environment, home=self.home).codex_state,
            "repair-required",
        )

        other = self.home / "other"
        self.codex_config.write_text(meridian._codex_managed_block(other) + "\n", encoding="utf-8")
        different = meridian.plan_setup(root, self.codex_config, environment=self.environment, home=self.home)
        self.assertEqual(different.codex_state, "different-root")
        self.assertIn("profile=", meridian.codex_profile_root_mismatch(self.codex_config, root) or "")

        damaged = self.codex_config.read_text(encoding="utf-8").replace(meridian.CODEX_MANAGED_END + "\n", "")
        self.codex_config.write_text(damaged, encoding="utf-8")
        combined = meridian.plan_setup(root, self.codex_config, environment=self.environment, home=self.home)
        self.assertEqual(combined.codex_state, "repair-and-replace-required")
        self.assertIn("replaces the one configured worktree root", combined.codex_detail)
        self.assertTrue(meridian.apply_setup(combined))
        self.assertEqual(
            tomllib.loads(self.codex_config.read_text(encoding="utf-8"))["permissions"]
            ["meridian-worktrees"]["workspace_roots"],
            {str(root): True},
        )

    def test_setup_plans_and_applies_codex_skill_links_idempotently(self) -> None:
        root = self.home / "root"
        environment = {**self.environment, "MERIDIAN_ROOT": str(ROOT)}
        plan = meridian.plan_setup(
            root, self.codex_config, environment=environment, home=self.home, framework_root=ROOT
        )
        self.assertEqual(plan.skill_links_state, "missing")
        self.assertEqual(plan.meridian_root_state, "ready")
        self.assertFalse((self.home / ".agents").exists())
        self.assertTrue(meridian.apply_setup(plan))
        for name in meridian.CODEX_SKILL_NAMES:
            link = self.home / ".agents/skills" / name
            self.assertTrue(link.is_symlink())
            self.assertEqual(link.resolve(), (ROOT / "skills" / name).resolve())
        again = meridian.plan_setup(
            root, self.codex_config, environment=environment, home=self.home, framework_root=ROOT
        )
        self.assertEqual(again.skill_links_state, "ready")
        self.assertFalse(meridian.apply_setup(again))

    def test_setup_refuses_conflicting_or_blocked_skill_links(self) -> None:
        skills = self.home / ".agents/skills"
        skills.mkdir(parents=True)
        (skills / "meridian-lean-delivery").symlink_to(self.home / "elsewhere")
        (skills / "meridian-governed-sdd").mkdir()
        plan = meridian.plan_setup(
            self.home / "root", self.codex_config, environment=self.environment, home=self.home, framework_root=ROOT
        )
        self.assertEqual(plan.skill_links_state, "blocked")
        self.assertEqual(plan.changes, ("none; setup is blocked before mutation",))
        with self.assertRaisesRegex(meridian.MeridianError, "setup is blocked"):
            meridian.apply_setup(plan)
        self.assertFalse((self.home / "root").exists())
        self.assertFalse(self.codex_config.exists())

    def test_setup_skips_skill_links_outside_a_git_checkout_and_warns_about_stale_copy(self) -> None:
        framework = self.home / "plugin-cache"
        for name in meridian.CODEX_SKILL_NAMES:
            (framework / "skills" / name).mkdir(parents=True)
            (framework / "skills" / name / "SKILL.md").write_text("skill\n", encoding="utf-8")
        stale = self.home / ".codex/skills/meridian-lean-delivery"
        stale.parent.mkdir(parents=True)
        stale.write_text("stale\n", encoding="utf-8")
        plan = meridian.plan_setup(
            self.home / "root", self.codex_config, environment=self.environment, home=self.home, framework_root=framework
        )
        self.assertEqual(plan.skill_links_state, "skipped")
        self.assertTrue(any(str(stale) in warning for warning in plan.warnings))
        self.assertFalse(meridian.apply_setup(plan) and (self.home / ".agents").exists())

    def test_setup_reports_meridian_root_environment_states(self) -> None:
        root = self.home / "root"
        for environment, expected in (
            (self.environment, "unset"),
            ({**self.environment, "MERIDIAN_ROOT": str(ROOT)}, "ready"),
            ({**self.environment, "MERIDIAN_ROOT": str(self.home / "other")}, "mismatch"),
        ):
            with self.subTest(expected=expected):
                plan = meridian.plan_setup(
                    root,
                    self.codex_config,
                    environment=environment,
                    home=self.home,
                    framework_root=ROOT,
                )
                self.assertEqual(plan.meridian_root_state, expected)

    def test_setup_task_identity_is_opt_in_and_supports_both_workflows(self) -> None:
        for workflow_mode in meridian.WORKFLOW_MODES:
            with self.subTest(workflow_mode=workflow_mode):
                project = self.home / workflow_mode
                project.mkdir()
                (project / "PROJECT_WORKFLOW.md").write_text(
                    (ROOT / "templates/workflows" / workflow_mode / "PROJECT_WORKFLOW.md").read_text(encoding="utf-8"),
                    encoding="utf-8",
                )
                root = self.home / f"{workflow_mode}-root"
                unchecked = meridian.plan_setup(
                    root,
                    self.codex_config,
                    environment=self.environment,
                    home=self.home,
                    project_root=project,
                )
                self.assertEqual(unchecked.task_identity_state, "not-requested")
                self.assertFalse(meridian.apply_setup(unchecked) and (project / meridian.TASK_IDENTITY_PATH).exists())
                self.assertFalse((project / meridian.TASK_IDENTITY_PATH).exists())

                for choice in ("opaque", "milestone"):
                    choice_project = self.home / f"{workflow_mode}-{choice}"
                    choice_project.mkdir()
                    (choice_project / "PROJECT_WORKFLOW.md").write_text(
                        (ROOT / "templates/workflows" / workflow_mode / "PROJECT_WORKFLOW.md").read_text(encoding="utf-8"),
                        encoding="utf-8",
                    )
                    plan = meridian.plan_setup(
                        self.home / f"{workflow_mode}-{choice}-root",
                        self.home / f"{workflow_mode}-{choice}.toml",
                        task_identity=choice,
                        environment=self.environment,
                        home=self.home,
                        project_root=choice_project,
                    )
                    output = io.StringIO()
                    with redirect_stdout(output):
                        meridian.print_setup_plan(plan)
                    self.assertEqual(plan.task_identity_state, "planned")
                    self.assertIn(f"task identity mode {choice}", output.getvalue())
                    self.assertTrue(meridian.apply_setup(plan))
                    self.assertEqual(
                        json.loads((choice_project / meridian.TASK_IDENTITY_PATH).read_text(encoding="utf-8")),
                        {"version": 1, "mode": choice},
                    )

    def test_setup_proposes_runnable_candidate_commands_without_rewriting_declared_entries(self) -> None:
        project = self.home / "project"
        (project / "scripts").mkdir(parents=True)
        (project / "scripts/check_repository.py").write_text("pass\n", encoding="utf-8")
        (project / "tests").mkdir()
        command = [sys.executable, str(CLI), "setup", "--project", str(project),
                   "--worktree-root", str(self.home / "root"), "--config", str(self.codex_config)]
        environment = {**os.environ, **self.environment}
        checked = subprocess.run(command + ["--check"], text=True, capture_output=True, env=environment)
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        line = next(line for line in checked.stdout.splitlines() if line.startswith("candidate-validation-proposal: "))
        proposal = json.loads(line.split(": ", 1)[1])
        self.assertEqual(proposal["outcomes"]["FULL"],
                         ["python3 scripts/check_repository.py", "python3 -m unittest discover -s tests"])
        declaration = project / meridian.CANDIDATE_VALIDATION_PATH
        self.assertFalse(declaration.exists())
        applied = subprocess.run(command + ["--apply"], text=True, capture_output=True, env=environment)
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        self.assertEqual(json.loads(declaration.read_text()), proposal)
        proposal["outcomes"] = {outcome: ["scripts/check_repository.py"] for outcome in proposal["outcomes"]}
        legacy = json.dumps(proposal) + "\n"
        declaration.write_text(legacy, encoding="utf-8")
        for mode in ("--check", "--apply"):
            result = subprocess.run(command + [mode], text=True, capture_output=True, env=environment)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertNotIn("candidate-validation-proposal:", result.stdout)
            self.assertEqual(declaration.read_text(), legacy)

    def test_candidate_command_discovery_uses_primary_paths_and_never_executes(self) -> None:
        project = self.home / "project"
        (project / "bin").mkdir(parents=True)
        executable = project / "bin/check"
        executable.write_text("#!/bin/sh\ntouch executed\n", encoding="utf-8")
        executable.chmod(0o755)
        with mock.patch.dict(os.environ, {"PATH": "bin"}):
            for entry in ("check --flag", "bin/check", "./bin/check", str(executable)):
                self.assertTrue(meridian.runnable_candidate_validation_command(entry, project), entry)
            for entry in ("", "'unterminated", "unittest discover", "missing/check"):
                self.assertFalse(meridian.runnable_candidate_validation_command(entry, project), entry)
            executable.chmod(0o644)
            self.assertFalse(meridian.runnable_candidate_validation_command("bin/check", project))
        self.assertFalse((project / "executed").exists())

    def test_setup_cli_plans_then_applies_the_requested_task_identity(self) -> None:
        project = self.home / "project"
        project.mkdir()
        root = self.home / "root"
        command = [
            sys.executable,
            str(CLI),
            "setup",
            "--project", str(project),
            "--worktree-root", str(root),
            "--config", str(self.codex_config),
            "--task-identity", "milestone",
        ]
        environment = {**os.environ, **self.environment}
        checked = subprocess.run(
            command + ["--check"], text=True, capture_output=True, check=False, env=environment
        )
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertIn("task-identity: planned", checked.stdout)
        self.assertIn('task-identity-proposal: {"mode": "milestone", "version": 1}', checked.stdout)
        identity_path = project / meridian.TASK_IDENTITY_PATH
        self.assertFalse(identity_path.exists())

        applied = subprocess.run(
            command + ["--apply"], text=True, capture_output=True, check=False, env=environment
        )
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        self.assertEqual(
            identity_path.read_text(encoding="utf-8"),
            '{\n  "mode": "milestone",\n  "version": 1\n}\n',
        )

    def test_setup_cli_ignores_conflicting_skill_links_in_an_unrelated_home(self) -> None:
        unrelated_home = self.home / "unrelated-home"
        skills = unrelated_home / ".agents/skills"
        skills.mkdir(parents=True)
        for name in meridian.CODEX_SKILL_NAMES:
            (skills / name).symlink_to(unrelated_home / "elsewhere")

        checked = subprocess.run(
            [
                sys.executable,
                str(CLI),
                "setup",
                "--check",
                "--worktree-root",
                str(self.home / "root"),
                "--config",
                str(self.codex_config),
            ],
            text=True,
            capture_output=True,
            check=False,
            env={**os.environ, "HOME": str(unrelated_home), **self.environment},
        )

        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertIn("codex-skill-links: missing", checked.stdout)

    def test_setup_task_identity_refuses_invalid_and_preserves_existing_declarations(self) -> None:
        project = self.home / "project"
        project.mkdir()
        root = self.home / "root"
        with self.assertRaisesRegex(meridian.MeridianError, "unsupported task identity mode"):
            meridian.plan_setup(
                root,
                self.codex_config,
                task_identity="invalid",
                environment=self.environment,
                home=self.home,
                project_root=project,
            )
        self.assertFalse((project / meridian.TASK_IDENTITY_PATH).exists())

        identity_path = project / meridian.TASK_IDENTITY_PATH
        identity_path.parent.mkdir()
        identity_path.write_text('{"version": 1, "mode": "opaque"}\n', encoding="utf-8")
        before = identity_path.read_bytes()
        identical = meridian.plan_setup(
            root,
            self.codex_config,
            task_identity="opaque",
            environment=self.environment,
            home=self.home,
            project_root=project,
        )
        self.assertEqual(identical.task_identity_state, "already-set")
        self.assertIn("already set to opaque", identical.task_identity_detail)
        self.assertIsNone(identical.task_identity_proposal)

        different = meridian.plan_setup(
            root,
            self.codex_config,
            task_identity="milestone",
            environment=self.environment,
            home=self.home,
            project_root=project,
        )
        self.assertEqual(different.task_identity_state, "different")
        self.assertIn("requested milestone", different.task_identity_detail)
        self.assertIsNone(different.task_identity_proposal)
        self.assertTrue(meridian.apply_setup(different))
        self.assertEqual(identity_path.read_bytes(), before)

    def test_setup_task_identity_blocks_malformed_existing_declaration(self) -> None:
        project = self.home / "project"
        identity_path = project / meridian.TASK_IDENTITY_PATH
        identity_path.parent.mkdir(parents=True)
        identity_path.write_text("not json\n", encoding="utf-8")
        plan = meridian.plan_setup(
            self.home / "root",
            self.codex_config,
            task_identity="milestone",
            environment=self.environment,
            home=self.home,
            project_root=project,
        )
        self.assertEqual(plan.task_identity_state, "blocked")
        with self.assertRaisesRegex(meridian.MeridianError, "invalid task identity declaration"):
            meridian.apply_setup(plan)
        self.assertEqual(identity_path.read_text(encoding="utf-8"), "not json\n")

    def test_setup_milestone_identity_is_reported_by_the_resolver(self) -> None:
        project = self.home / "project"
        (project / "tasks").mkdir(parents=True)
        (project / "tasks/M2-API-001.md").write_text("ID: M2-API-001\n", encoding="utf-8")
        (project / "tasks/QUEUE.md").write_text(
            "| ID | Status | Task file |\n|---|---|---|\n| M2-API-001 | TODO | [M2-API-001](M2-API-001.md) |\n",
            encoding="utf-8",
        )
        plan = meridian.plan_setup(
            self.home / "root",
            self.codex_config,
            task_identity="milestone",
            environment=self.environment,
            home=self.home,
            project_root=project,
        )
        self.assertTrue(meridian.apply_setup(plan))
        checked = subprocess.run(
            [sys.executable, str(CLI), "task", "identity", "check", "M2-API-001", "--project", str(project), "--format", "json"],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertEqual(json.loads(checked.stdout)["mode"], "milestone")

    def test_setup_adds_the_project_claude_allowlist_only_after_apply(self) -> None:
        project = self.home / "project"
        settings = project / ".claude/settings.local.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(
            json.dumps({"permissions": {"allow": ["Bash(existing command)"]}, "preserve": True}),
            encoding="utf-8",
        )
        root = self.home / "root"

        plan = meridian.plan_setup(
            root,
            self.codex_config,
            environment=self.environment,
            home=self.home,
            project_root=project,
        )

        self.assertEqual(plan.claude_state, "approval-required")
        self.assertIn("project Claude Code command allowlist and deny rules", "\n".join(plan.changes))
        self.assertIn("Bash(git push --force:*)", plan.claude_detail)
        self.assertIn("defense in depth", plan.claude_detail)
        self.assertEqual(json.loads(settings.read_text(encoding="utf-8"))["permissions"]["allow"], ["Bash(existing command)"])
        self.assertNotIn("deny", json.loads(settings.read_text(encoding="utf-8"))["permissions"])
        self.assertTrue(meridian.apply_setup(plan))
        configured = json.loads(settings.read_text(encoding="utf-8"))
        self.assertTrue(configured["preserve"])
        self.assertEqual(
            configured["permissions"]["allow"],
            ["Bash(existing command)", *meridian.CLAUDE_PROJECT_ALLOWLIST],
        )
        self.assertEqual(configured["permissions"]["deny"], list(meridian.CLAUDE_PROJECT_DENYLIST))
        repeated = meridian.plan_setup(
            root,
            self.codex_config,
            environment=self.environment,
            home=self.home,
            project_root=project,
        )
        self.assertEqual(repeated.claude_state, "ready")
        self.assertFalse(meridian.apply_setup(repeated))

    def test_setup_keeps_user_deny_entries_and_adds_each_missing_rule_once(self) -> None:
        project = self.home / "project"
        settings = project / ".claude/settings.local.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(
            json.dumps({"permissions": {
                "allow": list(meridian.CLAUDE_PROJECT_ALLOWLIST),
                "deny": ["Bash(rm:*)", "Bash(git tag:*)"],
            }}),
            encoding="utf-8",
        )
        plan = meridian.plan_claude_project_allowlist(project)
        self.assertEqual(plan.status, "approval-required")
        self.assertNotIn("Bash(git tag:*)", plan.detail)
        self.assertIn("Bash(git rebase:*)", plan.detail)
        self.assertTrue(meridian.apply_claude_project_allowlist(plan))
        deny = json.loads(settings.read_text(encoding="utf-8"))["permissions"]["deny"]
        self.assertEqual(deny[:2], ["Bash(rm:*)", "Bash(git tag:*)"])
        self.assertEqual(len(deny), len(set(deny)))
        self.assertEqual(set(deny), {"Bash(rm:*)", *meridian.CLAUDE_PROJECT_DENYLIST})
        again = meridian.plan_claude_project_allowlist(project)
        self.assertEqual(again.status, "ready")
        self.assertFalse(meridian.apply_claude_project_allowlist(again))

    def test_setup_blocks_a_malformed_deny_list(self) -> None:
        project = self.home / "project"
        settings = project / ".claude/settings.local.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(json.dumps({"permissions": {"deny": "Bash(rm:*)"}}), encoding="utf-8")
        self.assertEqual(meridian.plan_claude_project_allowlist(project).status, "blocked")

    def test_claude_deny_rules_cover_the_denied_actions_and_spare_the_lifecycle(self) -> None:
        def matches(rule: str, command: str) -> bool:
            prefix = rule.removeprefix("Bash(").removesuffix(":*)")
            return command == prefix or command.startswith(prefix + " ")

        deny = meridian.CLAUDE_PROJECT_DENYLIST
        for denied in (
            "git push --force origin main",
            "git push -f origin main",
            "git push --force-with-lease origin main",
            "git push --mirror origin",
            "git push --delete origin task-165",
            "git tag v1.2.9",
            "git rebase main",
            "git reset --hard HEAD~1",
            "git cherry-pick abc123",
            "git branch -D task-165",
            "git worktree remove --force /tmp/worktree",
        ):
            self.assertTrue(any(matches(rule, denied) for rule in deny), denied)
        for needed in (
            "git push origin main",
            "git push origin task-165",
            "git branch -d task-165",
            "git branch --show-current",
            "git worktree remove /tmp/worktree",
            "git worktree list",
            "git reset HEAD file",
            "git merge --ff-only task-165",
            "git commit -m message",
        ):
            self.assertFalse(any(matches(rule, needed) for rule in deny), needed)
        for rule in meridian.CLAUDE_PROJECT_ALLOWLIST:
            self.assertNotIn(rule, deny)

    def test_setup_advises_about_direct_hook_registration_with_plugin_enabled(self) -> None:
        project = self.home / "project"
        settings = project / ".claude/settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(json.dumps({
            "enabledPlugins": {"meridian@local": True},
            "hooks": {"UserPromptSubmit": [{"command": "/tmp/queue-briefing.sh"}]},
        }), encoding="utf-8")

        plan = meridian.plan_setup(
            self.home / "root", self.codex_config, environment=self.environment,
            home=self.home, project_root=project,
        )

        self.assertEqual(len(plan.claude_hook_duplicates), 1)
        self.assertIn(str(settings), plan.claude_hook_duplicates[0])
        self.assertIn("queue-briefing.sh", plan.claude_hook_duplicates[0])

    def test_malformed_claude_settings_block_setup_before_mutation(self) -> None:
        project = self.home / "project"
        settings = project / ".claude/settings.local.json"
        settings.parent.mkdir(parents=True)
        settings.write_text("not json\n", encoding="utf-8")
        root = self.home / "root"

        plan = meridian.plan_setup(
            root,
            self.codex_config,
            environment=self.environment,
            home=self.home,
            project_root=project,
        )

        self.assertEqual(plan.claude_state, "blocked")
        self.assertEqual(plan.changes, ("none; setup is blocked before mutation",))
        with self.assertRaisesRegex(meridian.MeridianError, "malformed Claude settings"):
            meridian.apply_setup(plan)
        self.assertFalse(root.exists())
        self.assertFalse(self.codex_config.exists())
        self.assertEqual(settings.read_text(encoding="utf-8"), "not json\n")

    def test_codex_doctor_reports_the_claude_project_allowlist_gap(self) -> None:
        project = self.home / "project"
        project.mkdir()
        root = self.home / "root"
        root.mkdir()

        missing = meridian.codex_doctor(project, self.codex_config, root, home=self.home)
        self.assertEqual(missing["claude-project-allowlist"], "approval-required")
        claude_plan = meridian.plan_claude_project_allowlist(project)
        self.assertTrue(meridian.apply_claude_project_allowlist(claude_plan))
        ready = meridian.codex_doctor(project, self.codex_config, root, home=self.home)
        self.assertEqual(ready["claude-project-allowlist"], "ready")

    def _trusted_project_with_rules(self, rules_text: str) -> tuple[Path, Path]:
        project = self.home / "project"
        (project / ".codex/rules").mkdir(parents=True)
        (project / ".codex/rules/meridian.rules").write_text(rules_text, encoding="utf-8")
        root = self.home / "root"
        root.mkdir()
        self.codex_config.parent.mkdir(parents=True, exist_ok=True)
        self.codex_config.write_text(
            f'[projects."{project.resolve()}"]\ntrust_level = "trusted"\n', encoding="utf-8"
        )
        return project, root

    @unittest.skipUnless(shutil.which("codex"), "codex is not on PATH; cannot evaluate execpolicy decisions")
    def test_codex_doctor_probes_every_closure_policy_group(self) -> None:
        rules = (ROOT / "templates/workflows/lean-delivery/.codex/rules/meridian.rules").read_text(encoding="utf-8")
        project, root = self._trusted_project_with_rules(rules)
        ready = meridian.codex_doctor(project, self.codex_config, root, home=self.home)
        self.assertEqual(ready["lifecycle-command-policy"], "ready")
        for key in ("archive-rename-policy", "inspection-command-policy", "validation-command-policy"):
            self.assertEqual(ready[key], "ready", key)

    @unittest.skipUnless(shutil.which("codex"), "codex is not on PATH; cannot evaluate execpolicy decisions")
    def test_codex_doctor_names_the_gap_for_rules_without_the_closure_block(self) -> None:
        rules = (ROOT / "templates/workflows/lean-delivery/.codex/rules/meridian.rules").read_text(encoding="utf-8")
        legacy = re.sub(r"\n# Unattended-closure additions.*?\[\"ls\", [^\n]*\n", "\n", rules, flags=re.DOTALL)
        self.assertNotEqual(legacy, rules)
        project, root = self._trusted_project_with_rules(legacy)
        gaps = meridian.codex_doctor(project, self.codex_config, root, home=self.home)
        self.assertEqual(gaps["lifecycle-command-policy"], "blocked")
        self.assertEqual(gaps["archive-rename-policy"], "gap: git mv")
        self.assertTrue(gaps["inspection-command-policy"].startswith("gap: "))
        self.assertTrue(gaps["validation-command-policy"].startswith("gap: "))

    def test_claude_allowlist_covers_only_the_declared_command_surface(self) -> None:
        allowlist = set(meridian.CLAUDE_PROJECT_ALLOWLIST)
        for command in (
            "Bash(git push origin main)",
            "Bash(meridian worktree evidence:*)",
            "Bash(meridian worktree closure-status:*)",
            "Bash(meridian worktree integrate stage:*)",
            "Bash(python3 scripts/meridian.py worktree integrate finalize:*)",
            "Bash(python3 scripts/check_repository.py)",
            "Bash(python3 -m unittest discover -s tests)",
            "Bash(git mv tasks/:*)",
            "Bash(ls:*)",
            "Bash(grep:*)",
        ):
            self.assertIn(command, allowlist)
        for subcommand in (
            "validate",
            "ready-check",
            "handoff-check",
            "preflight",
            "evidence",
            "contract",
            "investigate",
        ):
            self.assertIn(f"Bash(meridian execution {subcommand}:*)", allowlist)
            self.assertIn(f"Bash(python3 scripts/meridian.py execution {subcommand}:*)", allowlist)
        for unrelated in ("Bash(git mv:*)", "Bash(mv:*)", "Bash(sed:*)", "Bash(rg:*)", "Bash(find:*)"):
            self.assertNotIn(unrelated, allowlist)
        self.assertNotIn("Bash(meridian execution reconcile:*)", allowlist)
        self.assertNotIn("Bash(python3 scripts/meridian.py execution reconcile:*)", allowlist)
        self.assertNotIn("Bash(meridian:*)", allowlist)
        for forbidden in ("--tags", "--force", "rebase", "reset", "branch -D", "worktree add", "worktree remove", "worktree prune"):
            self.assertFalse(any(forbidden in command for command in allowlist), forbidden)

    def test_claude_allowlist_execution_commands_match_the_codex_rule(self) -> None:
        rules = (ROOT / "templates/workflows/governed-sdd/.codex/rules/meridian.rules").read_text(encoding="utf-8")
        match = re.search(
            r'prefix_rule\(pattern=\["meridian", "execution", \[(.*?)\]\], decision="allow"\)',
            rules,
        )
        self.assertIsNotNone(match)
        codex_subcommands = set(re.findall(r'"([^"]+)"', match.group(1)))
        allowlist = set(meridian.CLAUDE_PROJECT_ALLOWLIST)
        claude_subcommands = {
            command.removeprefix("Bash(meridian execution ").removesuffix(":*)")
            for command in allowlist
            if command.startswith("Bash(meridian execution ")
        }
        python_subcommands = {
            command.removeprefix("Bash(python3 scripts/meridian.py execution ").removesuffix(":*)")
            for command in allowlist
            if command.startswith("Bash(python3 scripts/meridian.py execution ")
        }
        self.assertEqual(claude_subcommands, codex_subcommands)
        self.assertEqual(python_subcommands, codex_subcommands)


class CodexProfileRepairTest(unittest.TestCase):
    """Semantic recovery of the Codex permission profile when ownership comments are lost."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.worktrees = self.root / "worktrees"
        self.worktrees.mkdir()
        self.config = self.root / "config.toml"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def profile_tables(self, root: Path | None = None, **overrides: str) -> str:
        values = {
            "description": '"Workspace access plus Meridian-managed task worktrees."',
            "extends": '":workspace"',
        }
        values.update(overrides)
        body = "".join(f"{key} = {value}\n" for key, value in values.items())
        return (
            f"[permissions.meridian-worktrees]\n{body}\n"
            f"[permissions.meridian-worktrees.workspace_roots]\n"
            f'"{root or self.worktrees}" = true\n'
        )

    def rewritten(self, *, selection: str = 'default_permissions = "meridian-worktrees"\n', tables: str | None = None) -> str:
        """Model the observed app rewrite: keys moved, app settings changed, trailing marker gone."""
        return (
            '# app-managed header\n'
            'model = "gpt-next"\n'
            f"{selection}"
            'notify = ["/usr/bin/example", "turn-ended"]\n\n'
            "[plugins.example]\nenabled = true\n\n"
            "[features]\nnetwork_proxy = false\n\n"
            f"{meridian.CODEX_MANAGED_BEGIN}\n"
            + (tables if tables is not None else self.profile_tables())
            + "\n[projects.example]\ntrust_level = \"trusted\"\n"
        )

    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CLI), "codex", "configure", *arguments,
             "--worktree-root", str(self.worktrees), "--config", str(self.config)],
            text=True,
            capture_output=True,
            check=False,
        )

    def assert_blocked_unchanged(self, text: str, pattern: str) -> None:
        self.config.write_text(text, encoding="utf-8")
        with self.assertRaisesRegex(meridian.MeridianError, pattern):
            meridian.plan_codex_configuration(self.config, self.worktrees)
        self.assertEqual(self.config.read_text(encoding="utf-8"), text)

    def test_observed_rewrite_is_a_named_repairable_state(self) -> None:
        text = self.rewritten()
        self.config.write_text(text, encoding="utf-8")

        plan = meridian.plan_codex_configuration(self.config, self.worktrees)

        self.assertEqual(plan.status, "repair-required")
        self.assertIn("ownership-metadata-repair", plan.detail)
        self.assertEqual(tomllib.loads(plan.proposed_text or ""), tomllib.loads(text))
        self.assertEqual(self.config.read_text(encoding="utf-8"), text)

    def test_damaged_exact_profile_with_an_old_root_is_repaired_and_replaced(self) -> None:
        old_root = self.root / "old-worktrees"
        original = self.rewritten(tables=self.profile_tables(old_root))
        self.config.write_text(original, encoding="utf-8")

        plan = meridian.plan_codex_configuration(self.config, self.worktrees)

        self.assertEqual(plan.status, "repair-and-replace-required")
        self.assertIn("restores Meridian's ownership metadata and replaces the one configured worktree root", plan.detail)
        self.assertEqual(self.config.read_text(encoding="utf-8"), original)
        expected = tomllib.loads(original)
        expected["permissions"]["meridian-worktrees"]["workspace_roots"] = {str(self.worktrees): True}
        self.assertEqual(tomllib.loads(plan.proposed_text or ""), expected)

        checked = self.run_cli("--check")
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertIn("status: repair-and-replace-required", checked.stdout)
        self.assertIn("repairs ownership metadata and replaces the worktree root", checked.stdout)
        self.assertIn(f'-"{old_root}" = true', checked.stdout)
        self.assertIn(f'+"{self.worktrees}" = true', checked.stdout)
        self.assertEqual(self.config.read_text(encoding="utf-8"), original)
        report = meridian.codex_doctor(self.root, self.config, self.worktrees)
        self.assertEqual(report["permission-model"], "repair-and-replace-required")
        self.assertEqual(report["profile-ownership"], "repair-and-replace-required")

        applied = self.run_cli("--apply")
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertIn("ownership metadata repaired and root replaced", applied.stdout)
        backup = self.config.with_name("config.toml.meridian-repair.bak")
        self.assertEqual(backup.read_text(encoding="utf-8"), original)
        self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
        ready = meridian.plan_codex_configuration(self.config, self.worktrees)
        self.assertEqual(ready.status, "ready")
        self.assertFalse(meridian.apply_codex_configuration(ready))

    def test_moved_and_normalized_markers_with_an_old_root_use_the_combined_state(self) -> None:
        old_root = self.root / "old-worktrees"
        base = self.rewritten(tables=self.profile_tables(old_root))
        shapes = {
            "moved": meridian.CODEX_MANAGED_END + "\n" + base,
            "normalized": base.replace("# MERIDIAN:BEGIN", "# MERIDIAN:BEGIN  "),
        }
        for name, text in shapes.items():
            with self.subTest(name):
                self.config.write_text(text, encoding="utf-8")
                plan = meridian.plan_codex_configuration(self.config, self.worktrees)
                self.assertEqual(plan.status, "repair-and-replace-required")
                self.assertEqual(
                    tomllib.loads(plan.proposed_text or "")["permissions"]["meridian-worktrees"]["workspace_roots"],
                    {str(self.worktrees): True},
                )

    def test_every_damaged_marker_shape_is_repaired_to_a_fixed_point(self) -> None:
        begin, end = meridian.CODEX_MANAGED_BEGIN, meridian.CODEX_MANAGED_END
        tables = self.profile_tables()
        shapes = {
            "end-missing": self.rewritten(),
            "both-missing": self.rewritten().replace(begin + "\n", ""),
            "end-only": self.rewritten().replace(begin + "\n", "") + end + "\n",
            "reversed": end + "\n" + self.rewritten() + begin + "\n",
            "not-enclosing": self.rewritten().replace(tables, "") + f"{end}\n\n{tables}",
            # The trailing marker survived or was restored by hand, but the selection moved above the span.
            "selection-outside-span": self.rewritten().replace(
                "\n[projects.example]", f"{end}\n\n[projects.example]", 1
            ),
            # Markers wrap only the parent table; the workspace_roots table sits outside.
            "roots-outside-span": self.rewritten().replace(
                "\n[permissions.meridian-worktrees.workspace_roots]",
                f"{end}\n\n[permissions.meridian-worktrees.workspace_roots]",
                1,
            ),
        }
        for name, text in shapes.items():
            with self.subTest(name):
                self.config.write_text(text, encoding="utf-8")
                plan = meridian.plan_codex_configuration(self.config, self.worktrees)
                self.assertEqual(plan.status, "repair-required")
                self.assertEqual(tomllib.loads(plan.proposed_text or ""), tomllib.loads(text))
                self.config.write_text(plan.proposed_text or "", encoding="utf-8")
                again = meridian.plan_codex_configuration(self.config, self.worktrees)
                self.assertEqual(again.status, "ready")
                self.assertFalse(meridian.apply_codex_configuration(again))

    def test_apply_repairs_with_exclusive_private_backup_and_preserves_unrelated_text(self) -> None:
        original = self.rewritten()
        self.config.write_text(original, encoding="utf-8")
        stale = self.config.with_name("config.toml.meridian.bak")
        stale.write_text("stale first-apply backup\n", encoding="utf-8")

        plan = meridian.plan_codex_configuration(self.config, self.worktrees)
        self.assertTrue(meridian.apply_codex_configuration(plan))

        repaired = self.config.read_text(encoding="utf-8")
        self.assertIn("# app-managed header", repaired)
        self.assertIn("[plugins.example]", repaired)
        self.assertEqual(repaired.count(meridian.CODEX_MANAGED_BEGIN), 1)
        self.assertEqual(repaired.count(meridian.CODEX_MANAGED_END), 1)
        self.assertEqual(stale.read_text(encoding="utf-8"), "stale first-apply backup\n")
        backup = self.config.with_name("config.toml.meridian-repair.bak")
        self.assertEqual(backup.read_text(encoding="utf-8"), original)
        self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.config.stat().st_mode & 0o777, 0o600)
        self.assertEqual(meridian.plan_codex_configuration(self.config, self.worktrees).status, "ready")

        # A later app rewrite gets its own backup instead of overwriting the earlier one.
        later = repaired.replace(meridian.CODEX_MANAGED_END + "\n", "")
        self.config.write_text(later, encoding="utf-8")
        self.assertTrue(meridian.apply_codex_configuration(meridian.plan_codex_configuration(self.config, self.worktrees)))
        self.assertEqual(backup.read_text(encoding="utf-8"), original)
        self.assertEqual(self.config.with_name("config.toml.meridian-repair.1.bak").read_text(encoding="utf-8"), later)

    def test_apply_refuses_when_the_file_changed_after_planning(self) -> None:
        self.config.write_text(self.rewritten(), encoding="utf-8")
        plan = meridian.plan_codex_configuration(self.config, self.worktrees)
        changed = self.rewritten() + "# edited after planning\n"
        self.config.write_text(changed, encoding="utf-8")
        with self.assertRaisesRegex(meridian.MeridianError, "changed since"):
            meridian.apply_codex_configuration(plan)
        self.assertEqual(self.config.read_text(encoding="utf-8"), changed)

    def test_divergent_profiles_are_never_adopted_and_name_the_field(self) -> None:
        other_root = self.root / "elsewhere"
        cases = {
            "parent": (self.rewritten(tables=self.profile_tables(extends='":read-only"')), "extends"),
            "description": (self.rewritten(tables=self.profile_tables(description='"mine"')), "description"),
            "default-selection": (self.rewritten(selection='default_permissions = ":workspace"\n'), "default_permissions"),
            "no-selection": (self.rewritten(selection=""), "default_permissions"),
            "extra-grant": (self.rewritten(tables=self.profile_tables(network="true")), "network"),
            "partial": (
                self.rewritten(tables='[permissions.meridian-worktrees]\nextends = ":workspace"\n'),
                "description",
            ),
            "extra-root": (
                self.rewritten(tables=self.profile_tables() + f'"{other_root}" = true\n'),
                "workspace_roots",
            ),
            "foreign-unmarked": (
                self.rewritten(tables=self.profile_tables(extends='":read-only"')).replace(
                    meridian.CODEX_MANAGED_BEGIN + "\n", ""
                ),
                "extends",
            ),
        }
        for name, (text, field) in cases.items():
            with self.subTest(name):
                self.assert_blocked_unchanged(text, f"differs from the expected profile in: .*{field}")

    def test_ambiguous_or_unusual_serializations_are_blocked(self) -> None:
        inline = (
            '[permissions.meridian-worktrees]\n'
            'description = "Workspace access plus Meridian-managed task worktrees."\n'
            'extends = ":workspace"\n'
            f'workspace_roots = {{ "{self.worktrees}" = true }}\n'
        )
        self.assert_blocked_unchanged(self.rewritten(tables=inline), "exactly one plain")
        dotted = (
            '[permissions.meridian-worktrees]\n'
            'description = "Workspace access plus Meridian-managed task worktrees."\n'
            'extends = ":workspace"\n'
            f'workspace_roots."{self.worktrees}" = true\n'
        )
        self.assert_blocked_unchanged(self.rewritten(tables=dotted), "exactly one plain")
        self.assert_blocked_unchanged(self.rewritten() + self.profile_tables(), "malformed")
        self.config.write_text(f'sandbox_mode = "workspace-write"\n{self.rewritten()}', encoding="utf-8")
        with self.assertRaisesRegex(meridian.MeridianError, "legacy"):
            meridian.plan_codex_configuration(self.config, self.worktrees)

    def test_stray_markers_without_a_profile_remain_blocked(self) -> None:
        for text in (
            f"{meridian.CODEX_MANAGED_BEGIN}\nmodel = \"x\"\n",
            f"model = \"x\"\n{meridian.CODEX_MANAGED_END}\n",
            f"{meridian.CODEX_MANAGED_END}\n{meridian.CODEX_MANAGED_BEGIN}\n",
        ):
            with self.subTest(text=text):
                self.assert_blocked_unchanged(text, "incomplete or damaged")

    def test_intact_markers_with_another_root_keep_the_managed_replace_path(self) -> None:
        old_root = self.root / "old-root"
        self.config.write_text(meridian._codex_managed_block(old_root) + "\n", encoding="utf-8")
        plan = meridian.plan_codex_configuration(self.config, self.worktrees)
        self.assertEqual(plan.status, "approval-required")
        self.assertEqual(
            tomllib.loads(plan.proposed_text or "")["permissions"]["meridian-worktrees"]["workspace_roots"],
            {str(self.worktrees): True},
        )

    def test_cli_check_reports_diff_without_writing_and_apply_repairs(self) -> None:
        text = self.rewritten()
        self.config.write_text(text, encoding="utf-8")

        checked = self.run_cli("--check")
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertIn("status: repair-required", checked.stdout)
        self.assertIn("ownership-metadata-repair", checked.stdout)
        self.assertIn(f"+{meridian.CODEX_MANAGED_END}", checked.stdout)
        self.assertEqual(self.config.read_text(encoding="utf-8"), text)
        self.assertFalse(list(self.root.glob("*.bak")))

        applied = self.run_cli("--apply")
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertIn("does not prove", applied.stdout)
        self.assertIn(meridian.CODEX_MANAGED_END, self.config.read_text(encoding="utf-8"))
        repeated = self.run_cli("--apply")
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        self.assertIn("status: ready", repeated.stdout)
        self.assertIn("result: no-op", repeated.stdout)

    def test_cli_blocks_divergent_profile_with_field_names(self) -> None:
        text = self.rewritten(tables=self.profile_tables(extends='":read-only"'))
        self.config.write_text(text, encoding="utf-8")
        blocked = self.run_cli("--apply")
        self.assertEqual(blocked.returncode, 2)
        self.assertIn("BLOCKED", blocked.stderr)
        self.assertIn("extends", blocked.stderr)
        self.assertEqual(self.config.read_text(encoding="utf-8"), text)

    def test_contract_and_both_workflows_document_the_bounded_recovery(self) -> None:
        contract = (ROOT / "docs/HOST_CAPABILITY_CONTRACT.md").read_text(encoding="utf-8")
        for fragment in ("repair-required", "Explicit `--apply`", "does not prove", "profile-ownership"):
            self.assertIn(fragment, contract)
        for mode in ("lean-delivery", "governed-sdd"):
            workflow = (ROOT / f"templates/workflows/{mode}/PROJECT_WORKFLOW.md").read_text(encoding="utf-8")
            region = workflow.split("capability=codex-worktree-access v4 -->", 1)[1].split("<!-- MERIDIAN:END -->", 1)[0]
            for fragment in ("repair-required", "`--apply` only", "`blocked` status", "fresh session"):
                self.assertIn(fragment, region, mode)

    def test_doctor_reports_ownership_separately_from_root_access(self) -> None:
        self.config.write_text(self.rewritten(), encoding="utf-8")
        report = meridian.codex_doctor(self.root, self.config, self.worktrees)
        self.assertEqual(report["permission-model"], "repair-required")
        self.assertEqual(report["profile-ownership"], "repair-required")
        self.assertEqual(report["worktree-root-write"], "ready")
        self.assertIn("git-metadata", report)

        other_root = self.root / "other-root"
        self.config.write_text(meridian._codex_managed_block(other_root) + "\n", encoding="utf-8")
        different = meridian.codex_doctor(self.root, self.config, self.worktrees)
        self.assertEqual(
            different["codex-root-mismatch"],
            f"profile={other_root} resolved={self.worktrees}",
        )

        self.config.write_text(self.rewritten(tables=self.profile_tables(extends='":read-only"')), encoding="utf-8")
        blocked = meridian.codex_doctor(self.root, self.config, self.worktrees)
        self.assertEqual(blocked["permission-model"], "blocked")
        self.assertEqual(blocked["profile-ownership"], "blocked")
        self.assertEqual(blocked["worktree-root-write"], "approval-required")

    def test_doctor_reports_skill_links_and_meridian_root_without_writing(self) -> None:
        before = sorted(path.relative_to(self.root) for path in self.root.rglob("*"))
        report = meridian.codex_doctor(
            self.root,
            self.config,
            self.worktrees,
            framework_root=ROOT,
            home=self.root,
            environment={"MERIDIAN_ROOT": str(ROOT)},
        )
        self.assertEqual(report["skill-links"], "missing")
        self.assertEqual(report["MERIDIAN_ROOT"], "ready")
        after = sorted(path.relative_to(self.root) for path in self.root.rglob("*"))
        self.assertEqual(before, after)


class TaskIdentityResolverTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.project = Path(self.temporary.name) / "project"
        (self.project / "tasks").mkdir(parents=True)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def declare(self, mode: str = "milestone", **extra: object) -> None:
        declaration: dict[str, object] = {"version": 1, "mode": mode, **extra}
        identity = self.project / ".meridian/task-identity.json"
        identity.parent.mkdir(parents=True, exist_ok=True)
        identity.write_text(json.dumps(declaration), encoding="utf-8")

    def add_task(self, task_id: str, relative: str | None = None) -> Path:
        path = self.project / (relative or f"tasks/{task_id}.md")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"ID: {task_id}\nStatus: IN_PROGRESS\n", encoding="utf-8")
        return path

    def write_queue(self, rows: list[tuple[str, str]], path: str = "tasks/QUEUE.md") -> None:
        queue = self.project / path
        queue.parent.mkdir(parents=True, exist_ok=True)
        body = "| ID | Status | Task file |\n|---|---|---|\n"
        body += "".join(f"| {task_id} | IN_PROGRESS | [{task_id}]({link}) |\n" for task_id, link in rows)
        queue.write_text(body, encoding="utf-8")

    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CLI), *arguments],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_absent_and_explicit_opaque_policies_preserve_numeric_aliases(self) -> None:
        task = self.add_task("TASK-023")
        self.write_queue([("TASK-023", "TASK-023.md")])
        absent = meridian.resolve_task_identity(self.project, "023", "existing")
        self.declare("opaque")
        explicit = meridian.resolve_task_identity(self.project, "task-023", "existing")
        self.assertEqual(absent, explicit)
        self.assertEqual(explicit.kind, "opaque")
        self.assertEqual(explicit.canonical_id, "TASK-023")
        self.assertEqual(explicit.branch_name, "task-023")
        self.assertEqual(explicit.task_path, task.resolve())

    def test_milestone_normalizes_command_input_and_derives_every_surface(self) -> None:
        self.declare()
        task = self.add_task("M30-INSPECT_UI-001")
        self.write_queue([("M30-INSPECT_UI-001", "M30-INSPECT_UI-001.md")])
        resolved = meridian.resolve_task_identity(self.project, "m30-inspect_ui-001", "existing")
        self.assertEqual(resolved.kind, "structured")
        self.assertEqual(resolved.canonical_id, "M30-INSPECT_UI-001")
        self.assertEqual(resolved.branch_name, "m30-inspect_ui-001")
        self.assertEqual(resolved.artifact_stem, "M30-INSPECT_UI-001")
        self.assertEqual(resolved.semantic_tuple, {"milestone": 30, "workstream": "INSPECT_UI", "ordinal": 1})
        self.assertEqual(resolved.task_path, task.resolve())
        self.assertEqual(resolved.handoff_path, (self.project / "tasks/handoffs/M30-INSPECT_UI-001.md").resolve())
        self.assertEqual(resolved.review_path, (self.project / "tasks/reviews/M30-INSPECT_UI-001.md").resolve())
        self.assertEqual(resolved.budget_key(2), "M30-INSPECT_UI-001:2")

    def test_milestone_retains_known_legacy_and_restricts_new_identities(self) -> None:
        self.declare()
        self.add_task("LEGACY-7")
        self.write_queue([("LEGACY-7", "LEGACY-7.md")])
        legacy = meridian.resolve_task_identity(self.project, "LEGACY-7", "existing")
        self.assertEqual(legacy.kind, "legacy-opaque")
        with self.assertRaisesRegex(meridian.MeridianError, "unknown"):
            meridian.resolve_task_identity(self.project, "OTHER-7", "existing")
        with self.assertRaisesRegex(meridian.MeridianError, "must use"):
            meridian.resolve_task_identity(self.project, "OTHER-7", "new")
        created = meridian.resolve_task_identity(self.project, "m31-build-999", "new")
        self.assertEqual((created.canonical_id, created.kind), ("M31-BUILD-999", "structured"))

    def test_custom_nested_locations_are_resolved_once(self) -> None:
        self.declare()
        workflow = self.project / "PROJECT_WORKFLOW.md"
        workflow.write_text(
            "<!-- MERIDIAN:BEGIN capability=execution-assets v2 -->\n"
            "**Canonical locations.** Task files live at `docs/tasks/<milestone>/<TASK-ID>.md`, "
            "the queue at `docs/TASK_QUEUE.md`, completion handoffs live at "
            "`artifacts/handoffs/<TASK-ID>.md`, and durable review records at "
            "`artifacts/reviews/<TASK-ID>.md`.\n<!-- MERIDIAN:END -->\n",
            encoding="utf-8",
        )
        task = self.add_task("M8-API-011", "docs/tasks/M8/M8-API-011.md")
        self.write_queue([("M8-API-011", "tasks/M8/M8-API-011.md")], "docs/TASK_QUEUE.md")
        resolved = meridian.resolve_task_identity(self.project, "M8-API-011", "existing")
        self.assertEqual(resolved.task_path, task.resolve())
        self.assertEqual(resolved.queue_path, (self.project / "docs/TASK_QUEUE.md").resolve())
        self.assertEqual(resolved.handoff_path, (self.project / "artifacts/handoffs/M8-API-011.md").resolve())
        self.assertEqual(resolved.review_path, (self.project / "artifacts/reviews/M8-API-011.md").resolve())

    def test_policy_and_authority_fail_closed(self) -> None:
        identity = self.project / ".meridian/task-identity.json"
        identity.parent.mkdir(parents=True)
        malformed = (
            "{",
            json.dumps({"version": True, "mode": "opaque"}),
            json.dumps({"version": 2, "mode": "opaque"}),
            json.dumps({"version": 1, "mode": "other"}),
            json.dumps({"version": 1, "mode": "opaque", "regex": ".*"}),
        )
        for declaration in malformed:
            with self.subTest(declaration=declaration):
                identity.write_text(declaration, encoding="utf-8")
                with self.assertRaises(meridian.MeridianError):
                    meridian.resolve_task_identity(self.project, "TASK-001", "new")

    def test_ambiguity_collisions_mixed_case_and_traversal_are_rejected(self) -> None:
        self.declare()
        self.add_task("M2-API-001")
        self.add_task("M2-Api-002")
        self.write_queue([("M2-API-001", "M2-API-001.md"), ("M2-Api-002", "M2-Api-002.md")])
        with self.assertRaisesRegex(meridian.MeridianError, "canonical uppercase"):
            meridian.resolve_task_identity(self.project, "M2-Api-002", "existing")
        with self.assertRaises(meridian.MeridianError):
            meridian.resolve_task_identity(self.project, "../M2-API-001", "existing")

        self.declare("opaque")
        self.add_task("TASK-007")
        self.add_task("007")
        self.write_queue([("TASK-007", "TASK-007.md"), ("007", "007.md")])
        with self.assertRaisesRegex(meridian.MeridianError, "collision"):
            meridian.resolve_task_identity(self.project, "TASK-007", "existing")

    def test_mismatched_duplicate_and_unsafe_authorities_are_rejected(self) -> None:
        self.declare()
        self.add_task("M4-API-001")
        self.add_task("M4-API-002")
        self.write_queue([("M4-API-001", "M4-API-002.md")])
        with self.assertRaisesRegex(meridian.MeridianError, "disagree"):
            meridian.resolve_task_identity(self.project, "M4-API-001", "existing")

        duplicate = self.project / "tasks/nested/M4-API-001.md"
        duplicate.parent.mkdir()
        duplicate.write_text("ID: M4-API-001\n", encoding="utf-8")
        with self.assertRaisesRegex(meridian.MeridianError, "ambiguous"):
            meridian.resolve_task_identity(self.project, "M4-API-001", "existing")

        self.declare("opaque")
        with self.assertRaises(meridian.MeridianError):
            meridian.resolve_task_identity(self.project, "foo..bar", "new")

    def test_structured_grammar_rejects_noncanonical_new_ids(self) -> None:
        self.declare()
        invalid = (
            "M0-API-001", "M01-API-001", "M1--001", "M1-_API-001",
            "M1-API_-001", "M1-API-000", "M1-API-1000", "M1-API-01",
        )
        for task_id in invalid:
            with self.subTest(task_id=task_id), self.assertRaises(meridian.MeridianError):
                meridian.resolve_task_identity(self.project, task_id, "new")

    def test_cli_json_exit_codes_and_read_only_behavior(self) -> None:
        self.declare()
        self.add_task("M9-CLI-003")
        self.write_queue([("M9-CLI-003", "M9-CLI-003.md")])
        before = {path.relative_to(self.project): path.read_bytes() for path in self.project.rglob("*") if path.is_file()}
        checked = self.run_cli(
            "task", "identity", "check", "m9-cli-003",
            "--project", str(self.project), "--format", "json",
        )
        self.assertEqual(checked.returncode, 0, checked.stderr)
        payload = json.loads(checked.stdout)
        direct = meridian.resolve_task_identity(self.project, "m9-cli-003", "existing")
        self.assertEqual(payload, meridian.task_identity_json(self.project, direct))
        runtime_state: dict[str, object] = {}
        runtime_key, _text = meridian.resolve_budget_key(self.project, runtime_state, "m9-cli-003")
        self.assertEqual(payload["budget_key"], runtime_key)
        after = {path.relative_to(self.project): path.read_bytes() for path in self.project.rglob("*") if path.is_file()}
        self.assertEqual(before, after)

        unknown = self.run_cli(
            "task", "identity", "check", "M9-CLI-004",
            "--project", str(self.project), "--format", "json",
        )
        self.assertEqual(unknown.returncode, 2)
        self.assertEqual(unknown.stdout, "")
        usage = self.run_cli(
            "task", "identity", "check", "M9-CLI-003", "--project", str(self.project)
        )
        self.assertEqual(usage.returncode, 64)
        self.assertEqual(usage.stdout, "")

    def test_cli_budget_key_matches_the_runtime_attempt_without_writing(self) -> None:
        self.add_task("TASK-009")
        self.write_queue([("TASK-009", "TASK-009.md")])
        state = {"TASK-009": {"attempt": 2, "lastStatus": "READY_FOR_REVIEW"}}
        budget = self.project / ".meridian/budget.json"
        budget.parent.mkdir(parents=True)
        budget.write_text(json.dumps(state), encoding="utf-8")
        checked = self.run_cli(
            "task", "identity", "check", "009",
            "--project", str(self.project), "--format", "json",
        )
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertEqual(json.loads(checked.stdout)["budget_key"], "TASK-009:3")
        self.assertEqual(json.loads(budget.read_text(encoding="utf-8")), state)
        runtime_state = json.loads(budget.read_text(encoding="utf-8"))
        key, _text = meridian.resolve_budget_key(self.project, runtime_state, "009")
        self.assertEqual(key, "TASK-009:3")

    def test_next_identity_uses_matching_authorities_and_is_read_only(self) -> None:
        self.declare()
        empty = self.run_cli(
            "task", "identity", "next", "--milestone", "9", "--workstream", "CLI",
            "--project", str(self.project), "--format", "json",
        )
        self.assertEqual(empty.returncode, 0, empty.stderr)
        self.assertEqual(json.loads(empty.stdout)["canonical_id"], "M9-CLI-001")
        self.add_task("M9-CLI-003")
        self.add_task("M9-CLI-007")
        self.add_task("M9-OTHER-999")
        self.add_task("M10-CLI-999")
        self.add_task("TASK-999")
        self.write_queue([
            ("M9-CLI-003", "M9-CLI-003.md"), ("M9-CLI-007", "M9-CLI-007.md"),
            ("M9-OTHER-999", "M9-OTHER-999.md"), ("M10-CLI-999", "M10-CLI-999.md"),
            ("TASK-999", "TASK-999.md"),
        ])
        before = {path.relative_to(self.project): path.read_bytes() for path in self.project.rglob("*") if path.is_file()}
        checked = self.run_cli(
            "task", "identity", "next", "--milestone", "9", "--workstream", "CLI",
            "--project", str(self.project), "--format", "json",
        )
        self.assertEqual(checked.returncode, 0, checked.stderr)
        payload = json.loads(checked.stdout)
        self.assertEqual(payload["canonical_id"], "M9-CLI-008")
        self.assertEqual(payload["task_path"], "tasks/M9-CLI-008.md")
        self.assertEqual(payload, meridian.resolve_task_identity(self.project, "M9-CLI-008", "new").as_json(self.project))
        after = {path.relative_to(self.project): path.read_bytes() for path in self.project.rglob("*") if path.is_file()}
        self.assertEqual(before, after)

    def test_next_identity_rejects_invalid_policy_grammar_overflow_and_ambiguity(self) -> None:
        self.declare("opaque")
        for milestone, workstream in (("1", "API"), ("01", "API"), ("1", "api")):
            with self.subTest(milestone=milestone, workstream=workstream):
                checked = self.run_cli(
                    "task", "identity", "next", "--milestone", milestone, "--workstream", workstream,
                    "--project", str(self.project), "--format", "json",
                )
                self.assertEqual(checked.returncode, 2)
                self.assertEqual(checked.stdout, "")

        self.declare()
        self.add_task("M1-API-999")
        self.write_queue([("M1-API-999", "M1-API-999.md")])
        overflow = self.run_cli(
            "task", "identity", "next", "--milestone", "1", "--workstream", "API",
            "--project", str(self.project), "--format", "json",
        )
        self.assertEqual(overflow.returncode, 2)
        self.assertIn("exceeds 999", overflow.stderr)

        self.add_task("M2-API-001")
        self.add_task("M2-API-001", "tasks/nested/M2-API-001.md")
        ambiguous = self.run_cli(
            "task", "identity", "next", "--milestone", "2", "--workstream", "API",
            "--project", str(self.project), "--format", "json",
        )
        self.assertEqual(ambiguous.returncode, 2)
        self.assertIn("ambiguous", ambiguous.stderr)

    def test_migration_delivers_only_managed_guidance_and_never_opts_in(self) -> None:
        for mode in meridian.WORKFLOW_MODES:
            template = ROOT / "templates/workflows" / mode / "PROJECT_WORKFLOW.md"
            self.assertIn("capability=task-identity-policy v1", template.read_text(encoding="utf-8"))

        root = Path(self.temporary.name)
        framework = root / "framework"
        consumer = root / "consumer"
        for source in ("templates", "migrations", "release-baselines", "capabilities"):
            shutil.copytree(ROOT / source, framework / source)
        current = (framework / "templates/workflows/lean-delivery/PROJECT_WORKFLOW.md").read_text(encoding="utf-8")
        previous = re.sub(
            r"\n<!-- MERIDIAN:BEGIN capability=task-identity-policy v1 -->.*?<!-- MERIDIAN:END -->\n",
            "\n",
            current,
            flags=re.DOTALL,
        )
        source = framework / "templates/workflows/lean-delivery"
        for path in source.rglob("*"):
            if path.is_file():
                destination = consumer / path.relative_to(source)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, destination)
        (source / "PROJECT_WORKFLOW.md").write_text(previous, encoding="utf-8")
        (consumer / "PROJECT_WORKFLOW.md").write_text(previous + "\nConsumer-owned note.\n", encoding="utf-8")
        (framework / "VERSION").write_text("1.1.45\n", encoding="utf-8")
        command = [sys.executable, str(CLI), "--framework-root", str(framework)]
        locked = subprocess.run(
            command + ["lock", "--mode", "lean-delivery", "--project", str(consumer)],
            text=True, capture_output=True, check=False,
        )
        self.assertEqual(locked.returncode, 0, locked.stdout + locked.stderr)
        (source / "PROJECT_WORKFLOW.md").write_text(current, encoding="utf-8")
        (framework / "VERSION").write_text("1.1.46\n", encoding="utf-8")
        upgraded = subprocess.run(
            command + ["upgrade", "--apply", "--project", str(consumer)],
            text=True, capture_output=True, check=False,
        )
        self.assertEqual(upgraded.returncode, 0, upgraded.stdout + upgraded.stderr)
        workflow = (consumer / "PROJECT_WORKFLOW.md").read_text(encoding="utf-8")
        self.assertIn("capability=task-identity-policy v1", workflow)
        self.assertIn("Consumer-owned note.", workflow)
        self.assertFalse((consumer / meridian.TASK_IDENTITY_PATH).exists())


class ProjectDeclarationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.project = Path(self.temporary.name) / "project"
        self.project.mkdir()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write(self, declaration: object) -> None:
        path = self.project / ".meridian/project.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(declaration), encoding="utf-8")

    def test_defaults_partial_full_and_invalid_declarations(self) -> None:
        defaults = meridian.resolve_project_locations(self.project)
        self.assertEqual(defaults.queue, Path("tasks/QUEUE.md"))
        self.write({"version": 1, "locations": {"queue": "docs/QUEUE.md"}})
        self.assertEqual(meridian.resolve_project_locations(self.project).queue, Path("docs/QUEUE.md"))
        self.write({"version": 1, "locations": {"queue": "docs/QUEUE.md", "taskRoots": ["work/tasks"], "reviewRoot": "reviews", "handoffRoot": "handoffs", "adrLog": "docs/ADR.md", "plan": "docs/PLAN.md"}})
        locations = meridian.resolve_project_locations(self.project)
        self.assertEqual((locations.queue, locations.task_roots, locations.plan), (Path("docs/QUEUE.md"), (Path("work/tasks"),), Path("docs/PLAN.md")))
        for declaration in ({"version": 2}, {"version": 1, "unknown": True}, {"version": 1, "locations": {"queue": "/tmp/QUEUE.md"}}, {"version": 1, "locations": {"queue": "../QUEUE.md"}}):
            self.write(declaration)
            with self.subTest(declaration=declaration), self.assertRaises(meridian.MeridianError):
                meridian.read_project_declaration(self.project)

    def test_declaration_overrides_legacy_and_cli_fields(self) -> None:
        (self.project / "PROJECT_WORKFLOW.md").write_text("<!-- MERIDIAN:BEGIN capability=execution-assets v2 -->\n<!-- MERIDIAN:END -->\nTask files live at `legacy/tasks/<TASK-ID>.md`; queue is `legacy/QUEUE.md`.\n", encoding="utf-8")
        self.write({"version": 1, "project": {"name": "Example", "slug": "example"}, "locations": {"queue": "docs/QUEUE.md"}})
        result = subprocess.run([sys.executable, str(CLI), "locations", "--field", "queue", "--project", str(self.project)], text=True, capture_output=True, check=False)
        self.assertEqual((result.returncode, result.stdout.strip(), result.stderr), (0, "docs/QUEUE.md", ""))
        author = subprocess.run([sys.executable, str(CLI), "project", "show", "--field", "reviewer-author", "--project", str(self.project)], text=True, capture_output=True, check=False)
        self.assertEqual(author.stdout.strip(), "Example Reviewer-Integrator <reviewer-integrator@example.local>")
        self.assertEqual(meridian.resolve_project_locations(self.project).queue.with_name("QUEUE_ARCHIVE.md"), Path("docs/QUEUE_ARCHIVE.md"))

    def test_declaration_overrides_an_invalid_legacy_location(self) -> None:
        (self.project / "PROJECT_WORKFLOW.md").write_text(
            "<!-- MERIDIAN:BEGIN capability=execution-assets v2 -->\n<!-- MERIDIAN:END -->\n"
            "queue is `/tmp/QUEUE.md`.\n",
            encoding="utf-8",
        )
        self.write({"version": 1, "locations": {"queue": "docs/QUEUE.md"}})
        self.assertEqual(meridian.resolve_project_locations(self.project).queue, Path("docs/QUEUE.md"))

    def test_legacy_location_warning_is_emitted_once_per_process(self) -> None:
        (self.project / "PROJECT_WORKFLOW.md").write_text(
            "<!-- MERIDIAN:BEGIN capability=execution-assets v2 -->\n<!-- MERIDIAN:END -->\n"
            "Task files live at `legacy/tasks/<TASK-ID>.md`; queue is `legacy/QUEUE.md`.\n",
            encoding="utf-8",
        )
        output = io.StringIO()
        with redirect_stderr(output):
            meridian.resolve_project_locations(self.project)
            meridian.resolve_project_locations(self.project)
        self.assertEqual(output.getvalue().count("DEPRECATED: resolve canonical locations"), 1)

    def test_linked_worktree_reads_primary_declaration(self) -> None:
        subprocess.run(("git", "init", str(self.project)), check=True, capture_output=True, text=True)
        self.write({"version": 1, "project": {"name": "Before", "slug": "before"}})
        subprocess.run(("git", "-C", str(self.project), "add", "."), check=True, capture_output=True, text=True)
        subprocess.run(("git", "-C", str(self.project), "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "initial"), check=True, capture_output=True, text=True)
        linked = Path(self.temporary.name) / "linked"
        subprocess.run(("git", "-C", str(self.project), "worktree", "add", "-b", "task-stale", str(linked)), check=True, capture_output=True, text=True)
        self.write({"version": 1, "project": {"name": "After", "slug": "after"}, "locations": {"queue": "current/QUEUE.md"}})
        author = subprocess.run([sys.executable, str(CLI), "project", "show", "--field", "reviewer-author", "--project", str(linked)], text=True, capture_output=True, check=False)
        locations = subprocess.run([sys.executable, str(CLI), "locations", "--field", "queue", "--project", str(linked)], text=True, capture_output=True, check=False)
        self.assertEqual((author.returncode, author.stdout.strip()), (0, "After Reviewer-Integrator <reviewer-integrator@after.local>"))
        self.assertEqual((locations.returncode, locations.stdout.strip()), (0, "current/QUEUE.md"))

    def test_setup_marks_missing_identity_incomplete_and_proposes_it(self) -> None:
        self.write({"version": 1, "locations": {"queue": "docs/QUEUE.md"}})
        plan = meridian.plan_setup(None, self.project / "config.toml", home=self.project, framework_root=ROOT, project_root=self.project)
        self.assertEqual(plan.project_declaration_state, "advisory-incomplete")
        self.assertEqual(plan.project_declaration_proposal["project"]["slug"], "project")


class CapabilityVersionDetectionTest(unittest.TestCase):
    """Phase 2 of migrations/CAPABILITY_MARKERS.md: version-aware detection.

    No real migration requires v2 of anything yet, so this builds a synthetic
    framework with one to exercise the case Meridian's own shipped migrations
    can't: a marker present but below the version now required.
    """

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.framework = root / "framework"
        self.project = root / "project"
        (self.framework / "migrations").mkdir(parents=True)
        self.project.mkdir(parents=True)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_migration(self, filename: str, capability: str, version: int) -> None:
        migration_id = filename.removesuffix(".json")
        (self.framework / "migrations" / filename).write_text(
            json.dumps({"id": migration_id, "capability": capability, "capabilityVersion": version}),
            encoding="utf-8",
        )

    def test_requirement_is_the_highest_declared_version(self) -> None:
        self.write_migration("001-widget.json", "widget", 1)
        self.write_migration("002-widget-v2.json", "widget", 2)
        requirements = meridian.capability_requirements(self.framework)
        self.assertEqual(requirements["widget"], (2, "002-widget-v2"))

    def test_marker_absent_is_distinct_from_marker_stale(self) -> None:
        self.write_migration("001-widget.json", "widget", 2)

        absent = meridian.find_capability_marker_version("no marker here", "widget")
        self.assertIsNone(absent)

        stale_text = "<!-- MERIDIAN:BEGIN capability=widget v1 -->text<!-- MERIDIAN:END -->"
        self.assertEqual(meridian.find_capability_marker_version(stale_text, "widget"), 1)

    def test_detect_capabilities_distinguishes_absent_stale_and_satisfied(self) -> None:
        self.write_migration("001-widget.json", "widget", 2)
        agents = self.project / "AGENTS.md"
        claude = self.project / "CLAUDE.md"
        for path in (agents, claude):
            path.write_text("", encoding="utf-8")

        import meridian as m

        managed = [m.ManagedFile(source=Path("unused"), target=Path("AGENTS.md"))]
        original_managed_files = m.managed_files
        m.managed_files = lambda framework_root, mode: managed
        try:
            absent = m.detect_capabilities(self.project, "governed-sdd", self.framework)
            self.assertEqual(len(absent), 1)
            self.assertFalse(absent[0].present)
            self.assertIn("no MERIDIAN:BEGIN", absent[0].evidence)

            agents.write_text(
                "<!-- MERIDIAN:BEGIN capability=widget v1 -->text<!-- MERIDIAN:END -->",
                encoding="utf-8",
            )
            stale = m.detect_capabilities(self.project, "governed-sdd", self.framework)
            self.assertFalse(stale[0].present)
            self.assertEqual(stale[0].evidence, "marker present at v1, but v2 is required")

            agents.write_text(
                "<!-- MERIDIAN:BEGIN capability=widget v2 -->text<!-- MERIDIAN:END -->",
                encoding="utf-8",
            )
            satisfied = m.detect_capabilities(self.project, "governed-sdd", self.framework)
            self.assertTrue(satisfied[0].present)
        finally:
            m.managed_files = original_managed_files


class CapabilityProfileManifestTest(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = meridian.load_capability_catalog(ROOT)

    def manifest(self, mode: str = "lean-delivery") -> dict[str, object]:
        profile = self.catalog.profile("meridian-self-hosting")
        self.assertIsNotNone(profile)
        capabilities: dict[str, object] = {}
        for capability_id, version in profile.capabilities:
            capability = self.catalog.capability(capability_id)
            self.assertIsNotNone(capability)
            capabilities[capability_id] = {
                "requiredVersion": version,
                "managedSurface": [
                    {"path": surface.path, "form": surface.forms[0]}
                    for surface in capability.managed_surfaces
                ],
                "installation": {
                    "state": "MISSING",
                    "evidence": [],
                    "notApplicableRationale": None,
                },
                "hostActivation": {
                    host_id: {
                        "state": "UNVERIFIED",
                        "evidence": [],
                        "notApplicableRationale": None,
                    }
                    for host_id, _evidence_kind in capability.host_profiles
                },
                "verification": {
                    "state": "UNVERIFIED",
                    "evidence": [],
                    "verifiedAt": None,
                    "verifierVersion": None,
                    "notApplicableRationale": None,
                },
            }
        return {
            "protocolVersion": meridian.PROTOCOL_VERSION,
            "frameworkVersion": "1.1.0",
            "workflowMode": mode,
            "managedFiles": {},
            "appliedMigrations": ["014-minimal-read-only-status", "040-pretooluse-read-guard"],
            "capabilityProfiles": {
                "meridian-self-hosting": {
                    "profileVersion": profile.version,
                    "capabilities": capabilities,
                }
            },
        }

    def installed_project(
        self, project: Path, mode: str = "lean-delivery"
    ) -> dict[str, object]:
        manifest = self.manifest(mode)
        managed_files: dict[str, str] = {}
        for capability_id, declaration in manifest["capabilityProfiles"][
            "meridian-self-hosting"
        ]["capabilities"].items():
            surface_digests = []
            for surface in declaration["managedSurface"]:
                path = project / surface["path"]
                if not path.exists():
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(f"surface: {surface['path']}\n", encoding="utf-8")
                digest = meridian.sha256(path)
                surface_digests.append(f"sha256:{digest}")
                if surface["form"] == "managed-copy":
                    managed_files[surface["path"]] = digest
            declaration["installation"] = {
                "state": "INSTALLED",
                "evidence": surface_digests,
                "notApplicableRationale": None,
            }
            host_activation = {}
            for host_id in declaration["hostActivation"]:
                probe_path = f".meridian/evidence/{capability_id}-{host_id}.json"
                probe = project / probe_path
                probe.parent.mkdir(parents=True, exist_ok=True)
                probe.write_text("{}\n", encoding="utf-8")
                host_activation[host_id] = {
                    "state": "ENFORCED",
                    "evidence": [f"probe:{probe_path}"],
                    "notApplicableRationale": None,
                }
            declaration["hostActivation"] = host_activation
            verification_path = f".meridian/evidence/{capability_id}-verification.json"
            verification_probe = project / verification_path
            verification_probe.parent.mkdir(parents=True, exist_ok=True)
            verification_probe.write_text("{}\n", encoding="utf-8")
            declaration["verification"] = {
                "state": "PASS",
                "evidence": [f"probe:{verification_path}"],
                "verifiedAt": "2026-09-28T00:00:00Z",
                "verifierVersion": meridian.read_version(ROOT),
                "notApplicableRationale": None,
            }
        manifest["managedFiles"] = managed_files
        meridian.write_manifest(project, manifest, ROOT)
        return manifest

    def audit(self, project: Path, mode: str = "lean-delivery") -> tuple[int, str]:
        output = io.StringIO()
        with redirect_stdout(output):
            return_code = meridian.run_audit(project, ROOT, mode)
        return return_code, output.getvalue()

    def test_catalog_exposes_versioned_profile_metadata_and_dependencies(self) -> None:
        self.assertEqual(self.catalog.catalog_version, 1)
        self.assertEqual(len(self.catalog.capabilities), 8)
        read_guard = self.catalog.capability("read-guard")
        self.assertEqual(read_guard.version, 1)
        self.assertEqual(read_guard.workflow_modes, ("lean-delivery", "governed-sdd"))
        self.assertTrue(read_guard.self_hosting_eligible)
        self.assertIn(("codex-project", "hook-invocation-observation"), read_guard.host_profiles)
        self.assertIn("shared-source", read_guard.installation_forms)
        self.assertTrue(read_guard.managed_surfaces)
        self.assertEqual(read_guard.dependencies, (("context-budgeting", 1),))
        profile = self.catalog.profile("meridian-self-hosting")
        self.assertEqual(
            profile.verification_probe,
            ".meridian/probes/meridian-self-hosting/host-neutral-ci-v1.json",
        )
        self.assertEqual(
            set(dict(profile.host_probes)), {"claude-project", "codex-project"}
        )

    def test_profile_doctor_is_read_only_and_resolves_required_probes(self) -> None:
        before = {
            path.relative_to(ROOT): path.read_bytes()
            for path in ROOT.rglob("*")
            if path.is_file() and ".git" not in path.parts
        }
        output = io.StringIO()
        with redirect_stdout(output):
            return_code = meridian.profile_doctor(
                ROOT, ROOT, "meridian-self-hosting"
            )
        after = {
            path.relative_to(ROOT): path.read_bytes()
            for path in ROOT.rglob("*")
            if path.is_file() and ".git" not in path.parts
        }
        self.assertEqual(return_code, 0, output.getvalue())
        self.assertEqual(after, before)
        self.assertIn("probe/claude-project", output.getvalue())
        self.assertIn("probe/codex-project", output.getvalue())
        self.assertIn("host state=UNVERIFIED", output.getvalue())

    def test_profile_doctor_fails_missing_or_incomplete_probe(self) -> None:
        for mutation, diagnostic in (("missing", "required probe is missing"), ("incomplete", "missing capability checks")):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                project = Path(directory)
                shutil.copytree(ROOT / ".meridian/probes", project / ".meridian/probes")
                self.installed_project(project)
                probe = project / ".meridian/probes/meridian-self-hosting/codex-project-v1.json"
                if mutation == "missing":
                    probe.unlink()
                else:
                    data = json.loads(probe.read_text(encoding="utf-8"))
                    data["checks"] = data["checks"][:-1]
                    probe.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
                output = io.StringIO()
                with redirect_stdout(output):
                    return_code = meridian.profile_doctor(
                        project, ROOT, "meridian-self-hosting"
                    )
                self.assertEqual(return_code, 2, output.getvalue())
                self.assertIn(diagnostic, output.getvalue())

    def test_ci_profile_gate_accepts_host_unverified_but_rejects_static_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            manifest = self.installed_project(project)
            capabilities = manifest["capabilityProfiles"]["meridian-self-hosting"]["capabilities"]
            for declaration in capabilities.values():
                for activation in declaration["hostActivation"].values():
                    activation.update(state="UNVERIFIED", evidence=[])
                declaration["verification"] = {
                    "state": "UNVERIFIED",
                    "evidence": [],
                    "verifiedAt": None,
                    "verifierVersion": None,
                    "notApplicableRationale": None,
                }
            meridian.write_manifest(project, manifest, ROOT)
            output = io.StringIO()
            with redirect_stdout(output):
                return_code = meridian.run_audit(
                    project, ROOT, "lean-delivery", "meridian-self-hosting"
                )
            self.assertEqual(return_code, 0, output.getvalue())
            self.assertIn("SUMMARY worst=UNVERIFIED", output.getvalue())
            self.assertIn("CI_GATE profile=meridian-self-hosting worst=PASS", output.getvalue())

            (project / ".codex/hooks.json").unlink()
            output = io.StringIO()
            with redirect_stdout(output):
                return_code = meridian.run_audit(
                    project, ROOT, "lean-delivery", "meridian-self-hosting"
                )
            self.assertEqual(return_code, 2, output.getvalue())
            self.assertIn("missing managed-copy surface .codex/hooks.json", output.getvalue())

    def test_ci_profile_gate_rejects_missing_managed_policy_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self.installed_project(project)
            (project / "docs/CONTEXT_BUDGET_POLICY.md").unlink()
            output = io.StringIO()
            with redirect_stdout(output):
                return_code = meridian.run_audit(
                    project, ROOT, "lean-delivery", "meridian-self-hosting"
                )
            self.assertEqual(return_code, 2, output.getvalue())
            self.assertIn(
                "missing managed-copy surface docs/CONTEXT_BUDGET_POLICY.md",
                output.getvalue(),
            )

    def test_ci_profile_gate_rejects_missing_shared_hook_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self.installed_project(project)
            (project / "hooks/queue-briefing.sh").unlink()
            output = io.StringIO()
            with redirect_stdout(output):
                return_code = meridian.run_audit(
                    project, ROOT, "lean-delivery", "meridian-self-hosting"
                )
            self.assertEqual(return_code, 2, output.getvalue())
            self.assertIn(
                "missing shared-source surface hooks/queue-briefing.sh",
                output.getvalue(),
            )

    def test_ci_profile_gate_rejects_an_unknown_profile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self.installed_project(project)
            output = io.StringIO()
            with redirect_stdout(output):
                return_code = meridian.run_audit(
                    project, ROOT, "lean-delivery", "unknown-profile"
                )
            self.assertEqual(return_code, 2, output.getvalue())
            self.assertIn("CI_GATE profile=unknown-profile worst=FAIL", output.getvalue())

    def test_live_manifest_has_no_host_claim_or_machine_specific_path(self) -> None:
        manifest_text = (ROOT / meridian.MANIFEST_PATH).read_text(encoding="utf-8")
        manifest = json.loads(manifest_text)
        capabilities = manifest["capabilityProfiles"]["meridian-self-hosting"]["capabilities"]
        self.assertNotIn(str(Path.home()), manifest_text)
        for declaration in capabilities.values():
            for activation in declaration["hostActivation"].values():
                self.assertEqual(activation["state"], "UNVERIFIED")
                self.assertEqual(activation["evidence"], [])

    def test_published_schemas_track_protocol_and_state_vocabularies(self) -> None:
        manifest_schema = json.loads(
            (ROOT / "schemas/manifest-v2.schema.json").read_text(encoding="utf-8")
        )
        catalog_schema = json.loads(
            (ROOT / "schemas/capability-catalog-v1.schema.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest_schema["properties"]["protocolVersion"]["const"], 2)
        self.assertEqual(
            tuple(manifest_schema["properties"]["workflowMode"]["enum"]),
            meridian.WORKFLOW_MODES,
        )
        self.assertEqual(
            tuple(
                manifest_schema["$defs"]["installationSnapshot"]["properties"]["state"]["enum"]
            ),
            meridian.INSTALLATION_STATES,
        )
        self.assertEqual(catalog_schema["properties"]["catalogVersion"]["const"], 1)

    def test_lean_and_governed_profiles_round_trip_through_the_current_writer(self) -> None:
        for mode in meridian.WORKFLOW_MODES:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                project = Path(directory)
                manifest = self.manifest(mode)
                meridian.write_manifest(project, manifest, ROOT)
                written = json.loads((project / meridian.MANIFEST_PATH).read_text(encoding="utf-8"))
                self.assertEqual(written["protocolVersion"], 2)
                self.assertEqual(written["workflowMode"], mode)
                self.assertNotIn("mode", written)
                loaded = meridian.load_manifest(project, ROOT)
                self.assertEqual(meridian.manifest_workflow_mode(loaded), mode)
                self.assertEqual(len(meridian.parse_capability_profiles(loaded, self.catalog)), 1)

    def test_legacy_mode_and_migration_history_do_not_fabricate_capabilities(self) -> None:
        legacy = {
            "protocolVersion": 1,
            "mode": "lean-delivery",
            "managedFiles": {},
            "appliedMigrations": [
                "014-minimal-read-only-status",
                "018-execution-evidence-profile",
                "040-pretooluse-read-guard",
            ],
        }
        self.assertEqual(meridian.validate_manifest(legacy, self.catalog), ())
        projected = meridian.canonical_manifest(legacy)
        self.assertEqual(projected["workflowMode"], "lean-delivery")
        self.assertNotIn("mode", projected)
        self.assertNotIn("capabilityProfiles", projected)
        self.assertEqual(projected, meridian.canonical_manifest(legacy))

    def test_conflicting_mode_aliases_are_rejected(self) -> None:
        manifest = self.manifest()
        manifest["mode"] = "governed-sdd"
        with self.assertRaisesRegex(meridian.MeridianError, "mode and workflowMode conflict"):
            meridian.validate_manifest(manifest, self.catalog)

    def test_invalid_state_empty_surface_and_missing_positive_evidence_are_rejected(self) -> None:
        cases = []
        unsupported = self.manifest()
        unsupported["capabilityProfiles"]["meridian-self-hosting"]["capabilities"]["language-policy"]["installation"]["state"] = "UNKNOWN"
        cases.append((unsupported, "state is unsupported"))
        empty_surface = self.manifest()
        empty_surface["capabilityProfiles"]["meridian-self-hosting"]["capabilities"]["language-policy"]["managedSurface"] = []
        cases.append((empty_surface, "managedSurface must be a non-empty list"))
        no_evidence = self.manifest()
        no_evidence["capabilityProfiles"]["meridian-self-hosting"]["capabilities"]["language-policy"]["installation"]["state"] = "INSTALLED"
        cases.append((no_evidence, "INSTALLED requires evidence"))
        for manifest, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(meridian.MeridianError, message):
                meridian.validate_manifest(manifest, self.catalog)

    def test_not_applicable_requires_a_catalog_backed_rationale(self) -> None:
        manifest = self.manifest()
        hosts = manifest["capabilityProfiles"]["meridian-self-hosting"]["capabilities"]["queue-briefing"]["hostActivation"]
        hosts["codex-project"] = {
            "state": "NOT_APPLICABLE",
            "evidence": [],
            "notApplicableRationale": "host-profile-unsupported",
        }
        meridian.validate_manifest(manifest, self.catalog)
        hosts["codex-project"]["notApplicableRationale"] = None
        with self.assertRaisesRegex(meridian.MeridianError, "catalog-backed rationale"):
            meridian.validate_manifest(manifest, self.catalog)

    def test_upgrade_check_reads_profile_without_writing_or_promoting_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            framework = root / "framework"
            project = root / "project"
            for source in ("templates", "migrations", "release-baselines", "capabilities"):
                shutil.copytree(ROOT / source, framework / source)
            (framework / "VERSION").write_text("1.1.0\n", encoding="utf-8")
            source = framework / "templates/workflows/governed-sdd"
            for path in source.rglob("*"):
                if path.is_file():
                    destination = project / path.relative_to(source)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(path, destination)
            command = [
                sys.executable,
                str(CLI),
                "--framework-root",
                str(framework),
                "lock",
                "--mode",
                "governed-sdd",
                "--project",
                str(project),
            ]
            locked = subprocess.run(command, text=True, capture_output=True, check=False)
            self.assertEqual(locked.returncode, 0, locked.stdout + locked.stderr)
            manifest_path = project / meridian.MANIFEST_PATH
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["capabilityProfiles"] = self.manifest("governed-sdd")["capabilityProfiles"]
            manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            before = {
                path.relative_to(project): path.read_bytes()
                for path in project.rglob("*")
                if path.is_file()
            }
            checked = subprocess.run(
                [
                    sys.executable,
                    str(CLI),
                    "--framework-root",
                    str(framework),
                    "upgrade",
                    "--check",
                    "--project",
                    str(project),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
            after = {
                path.relative_to(project): path.read_bytes()
                for path in project.rglob("*")
                if path.is_file()
            }
            self.assertEqual(after, before)
            persisted = json.loads(manifest_path.read_text(encoding="utf-8"))
            installation = persisted["capabilityProfiles"]["meridian-self-hosting"]["capabilities"]["language-policy"]["installation"]
            self.assertEqual(installation["state"], "MISSING")

    def test_retired_text_audit_advisories_preserve_exit_status_and_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self.installed_project(project)
            (project / ".meridian/candidate-validation.json").write_text('{"version": 1, "state": "none"}\n', encoding="utf-8")
            baseline_code, _ = self.audit(project)
            self.assertEqual(baseline_code, 0)
            for relative_path in meridian.load_retired_text_registry(ROOT)[0]["files"]:
                path = project / relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(relative_path + "\n## Reasoning profile\n", encoding="utf-8")
            manifest = self.installed_project(project)
            manifest["frameworkVersion"] = meridian.read_version(ROOT)
            meridian.write_manifest(project, manifest, ROOT)
            with mock.patch.object(meridian, "retired_text_advisories", return_value=[]):
                baseline_code, _ = self.audit(project)
            self.assertEqual(baseline_code, 0)
            before = {path.relative_to(project): path.read_bytes() for path in project.rglob("*") if path.is_file()}
            code, output = self.audit(project)
            self.assertEqual(code, baseline_code, output)
            self.assertIn("SUMMARY worst=ADVISORY", output)
            self.assertEqual(output.count("ADVISORY       retired-text"), 2)
            self.assertIn("docs/CONTEXT_BUDGET_POLICY.md:2:", output)
            after = {path.relative_to(project): path.read_bytes() for path in project.rglob("*") if path.is_file()}
            self.assertEqual(after, before)

    def test_cross_mode_audit_accepts_complete_declarations_and_reports_counts(self) -> None:
        for mode in meridian.WORKFLOW_MODES:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                project = Path(directory)
                self.installed_project(project, mode)
                (project / ".meridian/candidate-validation.json").write_text(
                    '{"version": 1, "state": "none"}\n', encoding="utf-8"
                )

                return_code, output = self.audit(project, mode)

                self.assertEqual(return_code, 0, output)
                self.assertIn("PASS", output)
                self.assertIn("SUMMARY worst=PASS", output)
                for state in meridian.AUDIT_STATES:
                    self.assertRegex(output, rf"\b{state}=\d+")
                self.assertNotIn("No capability markers found", output)

    def test_audit_fails_missing_and_drifted_managed_surfaces(self) -> None:
        missing_surfaces = (
            ("LANGUAGE_POLICY.md", "missing managed-copy surface LANGUAGE_POLICY.md"),
            (".codex/hooks.json", "missing managed-copy surface .codex/hooks.json"),
            ("hooks/read-guard.sh", "missing shared-source surface hooks/read-guard.sh"),
        )
        for relative_path, diagnostic in missing_surfaces:
            with self.subTest(surface=relative_path), tempfile.TemporaryDirectory() as directory:
                project = Path(directory)
                self.installed_project(project)
                (project / relative_path).unlink()

                return_code, output = self.audit(project)

                self.assertEqual(return_code, 2, output)
                self.assertIn(diagnostic, output)
                self.assertIn("SUMMARY worst=FAIL", output)

        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self.installed_project(project)
            hook = project / "hooks/read-guard.sh"
            hook.write_text("drifted\n", encoding="utf-8")

            return_code, output = self.audit(project)

            self.assertEqual(return_code, 2, output)
            self.assertIn("stale digest evidence", output)
            self.assertIn("shared-source:hooks/read-guard.sh", output)

    def test_audit_rejects_empty_surfaces_and_invalid_positive_claims(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            manifest = self.installed_project(project)
            declaration = manifest["capabilityProfiles"]["meridian-self-hosting"][
                "capabilities"
            ]["language-policy"]
            declaration["managedSurface"] = []
            (project / meridian.MANIFEST_PATH).write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )

            return_code, output = self.audit(project)

            self.assertEqual(return_code, 2, output)
            self.assertIn("managedSurface must be a non-empty list", output)

        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            manifest = self.installed_project(project)
            activation = manifest["capabilityProfiles"]["meridian-self-hosting"][
                "capabilities"
            ]["language-policy"]["hostActivation"]["codex-project"]
            activation["evidence"] = ["positive-claim-without-an-artifact"]
            (project / meridian.MANIFEST_PATH).write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )

            return_code, output = self.audit(project)

            self.assertEqual(return_code, 2, output)
            self.assertIn("invalid positive evidence", output)
            self.assertIn("expected probe:<path>", output)

    def test_audit_reports_stale_evidence_and_mixed_aggregate_results(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            manifest = self.installed_project(project)
            capabilities = manifest["capabilityProfiles"]["meridian-self-hosting"][
                "capabilities"
            ]
            capabilities["language-policy"]["hostActivation"]["codex-project"] = {
                "state": "UNVERIFIED",
                "evidence": [],
                "notApplicableRationale": None,
            }
            capabilities["read-guard"]["verification"]["verifierVersion"] = "0.0.0"
            (project / meridian.MANIFEST_PATH).write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )

            return_code, output = self.audit(project)

            self.assertEqual(return_code, 2, output)
            self.assertIn("UNVERIFIED", output)
            self.assertIn("stale verifierVersion", output)
            self.assertIn("SUMMARY worst=FAIL", output)

        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            manifest = self.installed_project(project)
            capabilities = manifest["capabilityProfiles"]["meridian-self-hosting"][
                "capabilities"
            ]
            advisory = capabilities["language-policy"]["hostActivation"]["codex-project"]
            advisory["state"] = "ADVISORY"
            capabilities["read-guard"]["hostActivation"]["codex-project"] = {
                "state": "UNVERIFIED",
                "evidence": [],
                "notApplicableRationale": None,
            }
            (project / meridian.MANIFEST_PATH).write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )

            return_code, output = self.audit(project)

            self.assertEqual(return_code, 1, output)
            self.assertRegex(output, r"ADVISORY=[1-9]\d*")
            self.assertRegex(output, r"UNVERIFIED=[1-9]\d*")
            self.assertIn("SUMMARY worst=UNVERIFIED", output)

    def test_audit_accepts_only_catalog_backed_exclusions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            framework = root / "framework"
            project = root / "project"
            shutil.copytree(ROOT, framework)
            catalog_path = framework / meridian.CAPABILITY_CATALOG_PATH
            catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
            catalog["capabilities"]["language-policy"]["workflowModes"] = ["governed-sdd"]
            catalog_path.write_text(
                json.dumps(catalog, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            custom_catalog = meridian.load_capability_catalog(framework)
            self.catalog = custom_catalog
            manifest = self.installed_project(project)
            declaration = manifest["capabilityProfiles"]["meridian-self-hosting"][
                "capabilities"
            ]["language-policy"]
            declaration["installation"] = {
                "state": "NOT_APPLICABLE",
                "evidence": [],
                "notApplicableRationale": "workflow-mode-excluded",
            }
            for activation in declaration["hostActivation"].values():
                activation.update(
                    state="NOT_APPLICABLE",
                    evidence=[],
                    notApplicableRationale="workflow-mode-excluded",
                )
            declaration["verification"] = {
                "state": "NOT_APPLICABLE",
                "evidence": [],
                "verifiedAt": None,
                "verifierVersion": None,
                "notApplicableRationale": "workflow-mode-excluded",
            }
            manifest["capabilityProfiles"]["meridian-self-hosting"]["capabilities"][
                "queue-briefing"
            ]["hostActivation"]["codex-project"] = {
                "state": "NOT_APPLICABLE",
                "evidence": [],
                "notApplicableRationale": "host-profile-unsupported",
            }
            meridian.write_manifest(project, manifest, framework)
            (project / ".meridian/candidate-validation.json").write_text(
                '{"version": 1, "state": "none"}\n', encoding="utf-8"
            )
            output = io.StringIO()

            with redirect_stdout(output):
                return_code = meridian.run_audit(project, framework, "lean-delivery")

            self.assertEqual(return_code, 0, output.getvalue())
            self.assertIn("NOT_APPLICABLE", output.getvalue())
            self.assertIn("catalog exclusion: workflow-mode-excluded", output.getvalue())
            self.assertIn(
                "meridian-self-hosting/queue-briefing/host/codex-project",
                output.getvalue(),
            )
            self.assertIn("catalog exclusion: host-profile-unsupported", output.getvalue())

    def test_legacy_lean_manifest_is_named_and_migration_history_is_not_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            meridian.write_manifest(
                project,
                {
                    "protocolVersion": 1,
                    "mode": "lean-delivery",
                    "frameworkVersion": meridian.read_version(ROOT),
                    "managedFiles": {},
                    "appliedMigrations": ["040-pretooluse-read-guard"],
                },
                ROOT,
            )

            return_code, output = self.audit(project)

            self.assertEqual(return_code, 1, output)
            self.assertIn("declaration/legacy-compatibility", output)
            self.assertIn("migration history is provenance only", output)
            self.assertIn("SUMMARY worst=UNVERIFIED", output)

    def test_lean_managed_files_deliver_only_neutral_profile_surfaces(self) -> None:
        lean_paths = {
            item.target.as_posix()
            for item in meridian.managed_files(ROOT, "lean-delivery")
        }
        self.assertTrue(
            {
                "LANGUAGE_POLICY.md",
                "docs/CONTEXT_BUDGET_POLICY.md",
                "docs/EXECUTION_EVIDENCE_PROFILE.md",
                ".codex/hooks.json",
                ".codex/rules/meridian.rules",
            }
            <= lean_paths
        )
        policy = (
            ROOT / "templates/workflows/lean-delivery/docs/CONTEXT_BUDGET_POLICY.md"
        ).read_text(encoding="utf-8")
        for governed_only in (
            "READY_FOR_REVIEW",
            "ACCEPTED",
            "owner acceptance",
            "reviewer-integrator",
            "Authority entries",
        ):
            self.assertNotIn(governed_only, policy)

    def test_bootstrap_observes_installation_without_promoting_host_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            manifest = {
                "protocolVersion": meridian.PROTOCOL_VERSION,
                "frameworkVersion": meridian.read_version(ROOT),
                "workflowMode": "lean-delivery",
                "managedFiles": {},
                "appliedMigrations": [],
            }
            meridian.write_manifest(project, manifest, ROOT)
            profile = self.catalog.profile("meridian-self-hosting")
            self.assertIsNotNone(profile)
            for capability_id, _version in profile.capabilities:
                capability = self.catalog.capability(capability_id)
                self.assertIsNotNone(capability)
                for surface in capability.managed_surfaces:
                    source = ROOT / surface.path
                    destination = project / surface.path
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, destination)

            observed = meridian.bootstrap_capability_profile(
                project, ROOT, "meridian-self-hosting", apply=True
            )
            declarations = observed["capabilityProfiles"]["meridian-self-hosting"][
                "capabilities"
            ]
            self.assertTrue(declarations)
            for declaration in declarations.values():
                self.assertEqual(declaration["installation"]["state"], "INSTALLED")
                self.assertEqual(declaration["verification"]["state"], "UNVERIFIED")
                self.assertTrue(
                    all(
                        host["state"] == "UNVERIFIED"
                        for host in declaration["hostActivation"].values()
                    )
                )

            return_code, output = self.audit(project)
            self.assertEqual(return_code, 1, output)
            self.assertNotRegex(output, r"(?m)^FAIL\s")
            self.assertIn("SUMMARY worst=UNVERIFIED", output)

    def test_live_execution_profile_has_no_unresolved_configuration_placeholder(self) -> None:
        profile = (ROOT / "docs/EXECUTION_EVIDENCE_PROFILE.md").read_text(
            encoding="utf-8"
        )
        self.assertNotRegex(profile, r"\[[^]]*(?:describe|command|method|bound|policy|tool)[^]]*\]")
        self.assertIn("python3 scripts/check_repository.py", profile)
        self.assertIn("python3 -m unittest discover -s tests -q 2>&1 | tail -n 40", profile)


class ProfileSurfaceUpgradeTest(unittest.TestCase):
    """`meridian upgrade` completes a profile declaration the catalog has outgrown."""

    PROFILE = "governed-sdd-consumer"
    CAPABILITY = "execution-evidence"
    ADDED = "docs/COMPLETION_REPORT_TEMPLATE.md"

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.framework = root / "framework"
        self.project = root / "project"
        for name in ("templates", "migrations", "capabilities", "release-baselines"):
            shutil.copytree(ROOT / name, self.framework / name)
        shutil.copyfile(ROOT / "VERSION", self.framework / "VERSION")
        self.project.mkdir()
        source = self.framework / "templates/workflows/governed-sdd"
        for path in source.rglob("*"):
            if path.is_file():
                destination = self.project / path.relative_to(source)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, destination)
        self.assertEqual(self.run_cli("lock", "--mode", "governed-sdd").returncode, 0)
        meridian.bootstrap_capability_profile(self.project, self.framework, self.PROFILE, apply=True)
        self.expected = self.read_manifest()
        self.catalog = meridian.load_capability_catalog(self.framework)
        # A manifest written before the catalog gained the completion report template.
        old = json.loads(json.dumps(self.expected))
        declaration = old["capabilityProfiles"][self.PROFILE]["capabilities"][self.CAPABILITY]
        declaration["managedSurface"] = [
            surface for surface in declaration["managedSurface"] if surface["path"] != self.ADDED
        ]
        declaration["installation"]["evidence"] = [
            item for item in declaration["installation"]["evidence"] if self.ADDED not in item
        ]
        self.old = old
        self.write_manifest(old)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CLI), "--framework-root", str(self.framework), *arguments,
             "--project", str(self.project)],
            text=True, capture_output=True, check=False,
        )

    def read_manifest(self) -> dict[str, object]:
        return json.loads((self.project / ".meridian/manifest.json").read_text(encoding="utf-8"))

    def write_manifest(self, manifest: dict[str, object]) -> None:
        (self.project / ".meridian/manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    def tree(self) -> dict[str, str]:
        return {
            str(path.relative_to(self.project)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(self.project.rglob("*")) if path.is_file()
        }

    def declaration(self, manifest: dict[str, object]) -> dict[str, object]:
        return manifest["capabilityProfiles"][self.PROFILE]["capabilities"][self.CAPABILITY]

    def test_strict_validation_still_rejects_the_older_surface(self) -> None:
        with self.assertRaisesRegex(meridian.MeridianError, "must completely match the catalog surface"):
            meridian.validate_manifest(self.old, self.catalog)

        gaps: list[tuple[str, str, tuple[str, ...]]] = []
        meridian.validate_manifest(self.old, self.catalog, gaps)
        self.assertEqual(gaps, [(self.PROFILE, self.CAPABILITY, (self.ADDED,))])

    def test_check_prints_the_row_and_writes_nothing(self) -> None:
        before = self.tree()

        checked = self.run_cli("upgrade", "--check")

        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertNotIn("BLOCKED", checked.stdout + checked.stderr)
        self.assertIn(
            f"PROFILE-SURFACE {self.PROFILE}/{self.CAPABILITY}: add {self.ADDED}", checked.stdout
        )
        self.assertEqual(self.tree(), before)

    def test_apply_matches_a_fresh_bootstrap(self) -> None:
        applied = self.run_cli("upgrade", "--apply")

        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        after = self.read_manifest()
        self.assertEqual(
            after["capabilityProfiles"], self.expected["capabilityProfiles"]
        )
        meridian.validate_manifest(after, self.catalog)
        again = self.run_cli("upgrade", "--check")
        self.assertNotIn("PROFILE-SURFACE", again.stdout)

    def test_apply_keeps_the_verification_snapshot(self) -> None:
        old = json.loads(json.dumps(self.old))
        declaration = self.declaration(old)
        declaration["verification"] = {
            "state": "ADVISORY", "evidence": ["probe:kept"], "verifiedAt": "2026-01-01T00:00:00Z",
            "verifierVersion": "1", "notApplicableRationale": None,
        }
        self.write_manifest(old)

        self.assertEqual(self.run_cli("upgrade", "--apply").returncode, 0)

        rebuilt = self.declaration(self.read_manifest())
        self.assertEqual(rebuilt["hostActivation"], declaration["hostActivation"])
        self.assertEqual(rebuilt["verification"], declaration["verification"])
        self.assertIn(self.ADDED, [surface["path"] for surface in rebuilt["managedSurface"]])

    def test_drifted_managed_copy_blocks_before_any_write(self) -> None:
        (self.project / self.ADDED).write_text("locally edited\n", encoding="utf-8")
        before = self.tree()
        manifest_before = self.read_manifest()

        checked = self.run_cli("upgrade", "--check")
        applied = self.run_cli("upgrade", "--apply")

        self.assertEqual(checked.returncode, 2, checked.stdout + checked.stderr)
        self.assertIn("differs from the digest recorded at install", checked.stdout)
        self.assertNotEqual(applied.returncode, 0)
        self.assertEqual(self.tree(), before)
        self.assertEqual(self.read_manifest(), manifest_before)

    def test_every_other_surface_mismatch_still_fails(self) -> None:
        def mutated(change) -> dict[str, object]:
            manifest = json.loads(json.dumps(self.old))
            change(manifest["capabilityProfiles"][self.PROFILE], self.declaration(manifest))
            return manifest

        def unknown_path(_profile, declaration) -> None:
            declaration["managedSurface"].append({"path": "docs/NOT_IN_CATALOG.md", "form": "managed-copy"})

        def unsupported_form(_profile, declaration) -> None:
            declaration["managedSurface"][0]["form"] = "declaration-only"

        def duplicate_path(_profile, declaration) -> None:
            declaration["managedSurface"].append(dict(declaration["managedSurface"][0]))

        def swapped_path(_profile, declaration) -> None:
            declaration["managedSurface"][0]["path"] = "docs/NOT_IN_CATALOG.md"

        def wrong_profile_version(profile, _declaration) -> None:
            profile["profileVersion"] += 1

        def wrong_capability_version(_profile, declaration) -> None:
            declaration["requiredVersion"] += 1

        def missing_capability(profile, _declaration) -> None:
            del profile["capabilities"][self.CAPABILITY]

        for change in (
            unknown_path, unsupported_form, duplicate_path, swapped_path,
            wrong_profile_version, wrong_capability_version, missing_capability,
        ):
            with self.subTest(change=change.__name__), self.assertRaises(meridian.MeridianError):
                meridian.validate_manifest(mutated(change), self.catalog, [])


class WorktreeLifecycleCliTest(unittest.TestCase):
    def setUp(self, *, seed: bool = True) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.project = self.root / "project"
        self.project.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=self.project, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Meridian Test"], cwd=self.project, check=True)
        subprocess.run(["git", "config", "user.email", "meridian@example.invalid"], cwd=self.project, check=True)
        # Fixture commits must not leave detached Git maintenance running during snapshots.
        subprocess.run(["git", "config", "maintenance.auto", "false"], cwd=self.project, check=True)
        self.worktree_root = self.root / "worktrees"
        self.worktree_root.mkdir()
        if not seed:
            return
        (self.project / "tasks").mkdir()
        (self.project / "tasks/056-lifecycle.md").write_text(
            "# Task 056\n\n> **ID**: `056`\n", encoding="utf-8"
        )
        (self.project / "tasks/QUEUE.md").write_text(
            "| Status | ID | Title |\n|---|---|---|\n| `[ ]` | 056 | Lifecycle |\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "add", "."], cwd=self.project, check=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=self.project, check=True, capture_output=True)

    def create_bare_origin(self) -> Path:
        remote = self.root / "origin.git"
        subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
        subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=self.project, check=True)
        return remote

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_cli(self, *arguments: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CLI), "--framework-root", str(ROOT), *arguments],
            cwd=cwd or self.project,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_path_alias_is_equivalent_and_deprecated(self) -> None:
        current = self.run_cli(
            "worktree", "path", "056", "--project", str(self.project),
            "--worktree-root", str(self.worktree_root),
        )
        alias = self.run_cli(
            "codex", "worktree-path", "056", "--project", str(self.project),
            "--worktree-root", str(self.worktree_root),
        )
        self.assertEqual(current.returncode, 0, current.stderr)
        self.assertEqual(alias.returncode, 0, alias.stderr)
        self.assertEqual(current.stdout, alias.stdout)
        self.assertIn("DEPRECATED", alias.stderr)

    def test_worktree_and_codex_commands_accept_the_resolved_root_without_an_option(self) -> None:
        environment = {**os.environ, "MERIDIAN_WORKTREE_ROOT": str(self.worktree_root)}
        worktree = subprocess.run(
            [sys.executable, str(CLI), "worktree", "path", "056", "--project", str(self.project)],
            cwd=self.project,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        codex = subprocess.run(
            [sys.executable, str(CLI), "codex", "worktree-path", "056", "--project", str(self.project)],
            cwd=self.project,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(worktree.returncode, 0, worktree.stderr)
        self.assertEqual(codex.returncode, 0, codex.stderr)
        self.assertEqual(worktree.stdout, codex.stdout)

    def test_prepare_and_worker_check_json_exit_codes(self) -> None:
        prepared = self.run_cli(
            "worktree", "prepare", "056", "--project", str(self.project),
            "--worktree-root", str(self.worktree_root), "--format", "json",
        )
        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        contract = json.loads(prepared.stdout)
        wrong = self.run_cli(
            "worktree", "check", "056", "--project", str(self.project),
            "--worktree-root", str(self.worktree_root), "--format", "json",
        )
        self.assertEqual(wrong.returncode, 2)
        self.assertIn("wrong-worktree", json.loads(wrong.stdout)["errors"])
        errors = ", ".join(json.loads(wrong.stdout)["errors"])
        self.assertEqual(
            wrong.stderr.strip(),
            f"BLOCKED WRONG_WORKTREE: worktree check reported: {errors}; resume: meridian worktree prepare 056 "
            f"--project {self.project.resolve()} --format json",
        )
        correct = self.run_cli(
            "worktree", "check", "056", "--project", str(self.project),
            "--worktree-root", str(self.worktree_root), "--format", "json",
            cwd=Path(contract["worktree"]),
        )
        self.assertEqual(correct.returncode, 0, correct.stderr)
        self.assertEqual(json.loads(correct.stdout)["status"], "ready")

    def test_prepare_records_and_preserves_started_at_without_fabricating_legacy_timing(self) -> None:
        prepared = self.run_cli(
            "worktree", "prepare", "056", "--project", str(self.project),
            "--worktree-root", str(self.worktree_root), "--format", "json",
        )
        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        first = json.loads(prepared.stdout)
        self.assertTrue(first["created"])
        self.assertRegex(first["started_at"], r"^\d{4}-\d\d-\d\dT.*Z$")
        repeated = self.run_cli(
            "worktree", "prepare", "056", "--project", str(self.project),
            "--worktree-root", str(self.worktree_root), "--format", "json",
        )
        repeated_contract = json.loads(repeated.stdout)
        self.assertFalse(repeated_contract["created"])
        self.assertEqual(repeated_contract["worktree"], first["worktree"])
        self.assertEqual(repeated_contract["started_at"], first["started_at"])
        worktrees = subprocess.run(
            ("git", "worktree", "list", "--porcelain"), cwd=self.project,
            text=True, capture_output=True, check=True,
        ).stdout
        self.assertEqual(worktrees.count("\nworktree ") + worktrees.startswith("worktree "), 2)

        identity = meridian.resolve_task_identity(self.project, "056", "existing")
        state_path, _lease, _integration = meridian._lifecycle_paths(self.project, identity)
        legacy = json.loads(state_path.read_text(encoding="utf-8"))
        legacy.pop("started_at")
        state_path.write_text(json.dumps(legacy), encoding="utf-8")
        preserved = self.run_cli(
            "worktree", "prepare", "056", "--project", str(self.project),
            "--worktree-root", str(self.worktree_root), "--format", "json",
        )
        self.assertNotIn("started_at", json.loads(preserved.stdout))

    def test_handoff_worktree_value_is_root_relative_and_legacy_absolute_is_accepted(self) -> None:
        prepared = self.run_cli(
            "worktree", "prepare", "056", "--project", str(self.project),
            "--worktree-root", str(self.worktree_root), "--format", "json",
        )
        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        contract = json.loads(prepared.stdout)
        relative = contract["handoff_worktree"]
        self.assertFalse(Path(relative).is_absolute())
        self.assertEqual(self.worktree_root.resolve() / relative, Path(contract["worktree"]))
        printed = self.run_cli(
            "worktree", "path", "056", "--project", str(self.project),
            "--worktree-root", str(self.worktree_root), "--format", "json",
        )
        self.assertEqual(json.loads(printed.stdout)["handoff_worktree"], relative)
        handoff = Path(contract["handoff"])
        handoff.parent.mkdir(parents=True, exist_ok=True)

        for value, expected in (
            (relative, True),
            (contract["worktree"], True),
            ("elsewhere/task-056", False),
        ):
            with self.subTest(value=value):
                handoff.write_text(f"- Worktree: `{value}`\n", encoding="utf-8")
                result = self.run_cli(
                    "worktree", "check", "056", "--project", str(self.project),
                    "--worktree-root", str(self.worktree_root), "--format", "json",
                    cwd=Path(contract["worktree"]),
                )
                report = json.loads(result.stdout)
                self.assertEqual(report["handoff_worktree"], relative)
                self.assertEqual(report["handoff_consistent"], expected)
                if expected:
                    self.assertEqual(result.returncode, 0, result.stdout)
                else:
                    self.assertEqual(result.returncode, 2)
                    self.assertIn("handoff-mismatch", report["errors"])

    def test_usage_errors_exit_64(self) -> None:
        result = self.run_cli("worktree", "prepare", "056")
        self.assertEqual(result.returncode, 64)

    def test_closure_status_covers_lifecycle_states_without_mutation(self) -> None:
        def snapshot(*roots: Path) -> dict[str, str]:
            return {
                f"{root.name}/{path.relative_to(root)}": hashlib.sha256(path.read_bytes()).hexdigest()
                for root in roots
                for path in root.rglob("*")
                if path.is_file()
            }

        def status(
            expected_step: str, expected_reason: str | None, *, text: bool = False,
            resume_contains: str | None = None,
        ) -> None:
            before = snapshot(self.project, worktree)
            result = self.run_cli(
                "worktree", "closure-status", "056", "--project", str(self.project),
                "--worktree-root", str(self.worktree_root),
                *( () if text else ("--format", "json") ),
            )
            self.assertEqual(snapshot(self.project, worktree), before)
            self.assertEqual(result.returncode, 2 if expected_reason else 0, result.stderr)
            if text:
                self.assertEqual(
                    result.stdout.strip(),
                    f"BLOCKED {expected_reason}: the task worktree, branch, or lifecycle state is missing or does not "
                    f"match; resume: meridian worktree prepare 056 --project {self.project.resolve()} --format json",
                )
                return
            report = json.loads(result.stdout)
            self.assertEqual(report["step"], expected_step)
            self.assertEqual(report["stop_reason"], expected_reason)
            self.assertIn("resume", report)
            if resume_contains is not None:
                self.assertIn(resume_contains, report["resume"])

        worktree = self.worktree_root / "unused"
        status("C4", "WRONG_WORKTREE", text=True)

        remote = self.root / "origin.git"
        subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
        (self.project / "tasks/handoffs").mkdir()
        (self.project / "tasks/handoffs/056.md").write_text("# Completion Report — 056\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=self.project, check=True)
        subprocess.run(["git", "commit", "-m", "handoff"], cwd=self.project, check=True, capture_output=True)
        subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=self.project, check=True)
        subprocess.run(["git", "push", "-u", "origin", "main"], cwd=self.project, check=True, capture_output=True)

        prepared = self.run_cli(
            "worktree", "prepare", "056", "--project", str(self.project),
            "--worktree-root", str(self.worktree_root), "--format", "json",
        )
        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        worktree = Path(json.loads(prepared.stdout)["worktree"])
        status("C1", "ACCEPTANCE_UNMET")

        (worktree / "implementation.txt").write_text("done\n", encoding="utf-8")
        subprocess.run(["git", "add", "implementation.txt"], cwd=worktree, check=True)
        subprocess.run(["git", "commit", "-m", "complete task"], cwd=worktree, check=True, capture_output=True)
        status("C5", "EVIDENCE_INCOMPLETE")

        identity = meridian.resolve_task_identity(self.project, "056", "existing")
        state, lease, integration = meridian._lifecycle_paths(self.project, identity)
        task_commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=worktree, check=True, capture_output=True, text=True
        ).stdout.strip()
        evidence = {
            "accepted": True,
            "validation_passed": True,
            "validated_task_commit": task_commit,
            "validated_base_commit": json.loads(prepared.stdout)["base_commit"],
            "full_validation_required": False,
            "interaction_assessment_complete": True,
            "task_paths": [],
            "task_dependencies": [],
            "task_behavioral_surfaces": [],
            "main_advanced_dependencies": [],
            "main_advanced_behavioral_surfaces": [],
        }
        evidence_path = state.with_suffix(".evidence.json")
        evidence_path.write_text(json.dumps({**evidence, "validated_task_commit": "0" * 40}), encoding="utf-8")
        status("C5", "EVIDENCE_INCOMPLETE")
        evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
        status("C6", None)
        legacy = self.project / ".meridian/budget.json"
        legacy.parent.mkdir(exist_ok=True)
        legacy.write_text("{}\n", encoding="utf-8")
        subprocess.run(["git", "add", ".meridian/budget.json"], cwd=self.project, check=True)
        status("C6", "PRIMARY_DIRTY", resume_contains="legacy budget file; commit its deletion")
        subprocess.run(["git", "reset", "HEAD", "--", ".meridian/budget.json"], cwd=self.project, check=True)
        legacy.unlink()
        evidence_path.unlink()
        lease.write_text(json.dumps({"task_id": identity.canonical_id}), encoding="utf-8")
        integration.write_text(json.dumps({"task_id": identity.canonical_id}), encoding="utf-8")
        status("C7", None)
        integration.unlink()
        status("C6", "LEASE_HELD")
        lease.unlink()

        subprocess.run(["git", "merge", "--no-ff", "task-056", "-m", "integrate"], cwd=self.project, check=True)
        status("C9", "PUSH_PENDING")
        subprocess.run(["git", "push", "origin", "main"], cwd=self.project, check=True, capture_output=True)
        status("C10", None)

        cleaned = self.run_cli(
            "worktree", "cleanup", "056", "--project", str(self.project),
            "--worktree-root", str(self.worktree_root), "--format", "json",
        )
        self.assertEqual(cleaned.returncode, 0, cleaned.stderr)
        worktree = self.worktree_root / "removed"
        status("C10", None)

    def _stage_ready_task_with_origin(self, local_ahead: bool = False) -> Path:
        self.create_bare_origin()
        subprocess.run(["git", "push", "-u", "origin", "main"], cwd=self.project, check=True, capture_output=True)
        if local_ahead:
            (self.project / "unpushed.txt").write_text("unpushed\n", encoding="utf-8")
            (self.project / ".meridian").mkdir(exist_ok=True)
            (self.project / ".meridian/candidate-validation.json").write_text(
                '{"version": 1, "state": "none"}\n', encoding="utf-8"
            )
            (self.project / "PROJECT_WORKFLOW.md").write_text("LEAN_DELIVERY\n", encoding="utf-8")
            (self.project / "tasks").mkdir(exist_ok=True)
            (self.project / "tasks/QUEUE.md").write_text(
                "| Status | ID | Title | Priority | Depends | Task |\n"
                "|---|---|---|---|---|---|\n"
                "| `[ ]` | 056 | Fixture task | P2 | — | [056](056-fixture.md) |\n",
                encoding="utf-8",
            )
            (self.project / "PROJECT_PLAN.md").write_text("- `[ ]` 056 — Fixture task.\n", encoding="utf-8")
            subprocess.run(
                ["git", "add", "unpushed.txt", ".meridian/candidate-validation.json", "PROJECT_WORKFLOW.md",
                 "tasks/QUEUE.md", "PROJECT_PLAN.md"],
                cwd=self.project, check=True,
            )
            subprocess.run(["git", "commit", "-m", "unpushed governance commit"], cwd=self.project, check=True, capture_output=True)
        prepared = self.run_cli(
            "worktree", "prepare", "056", "--project", str(self.project),
            "--worktree-root", str(self.worktree_root), "--format", "json",
        )
        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        worktree = Path(json.loads(prepared.stdout)["worktree"])
        (worktree / "implementation.txt").write_text("done\n", encoding="utf-8")
        subprocess.run(["git", "add", "implementation.txt"], cwd=worktree, check=True)
        subprocess.run(["git", "commit", "-m", "complete task"], cwd=worktree, check=True, capture_output=True)
        identity = meridian.resolve_task_identity(self.project, "056", "existing")
        state, _lease, _integration = meridian._lifecycle_paths(self.project, identity)
        task_commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=worktree, check=True, capture_output=True, text=True
        ).stdout.strip()
        validated_base = subprocess.run(
            ["git", "rev-parse", "main"], cwd=self.project, check=True, capture_output=True, text=True
        ).stdout.strip()
        state.with_suffix(".evidence.json").write_text(json.dumps({
            "accepted": True,
            "validation_passed": True,
            "validated_task_commit": task_commit,
            "validated_base_commit": validated_base,
            "full_validation_required": False,
            "interaction_assessment_complete": True,
            "task_paths": [],
            "task_dependencies": [],
            "task_behavioral_surfaces": [],
            "main_advanced_dependencies": [],
            "main_advanced_behavioral_surfaces": [],
        }), encoding="utf-8")
        return state.with_suffix(".evidence.json")

    def test_integrate_stage_blocks_when_fetched_origin_main_is_ahead(self) -> None:
        evidence_path = self._stage_ready_task_with_origin()
        remote = self.root / "origin.git"
        clone = self.root / "origin-writer"
        subprocess.run(["git", "clone", "--branch", "main", str(remote), str(clone)], check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Meridian Test"], cwd=clone, check=True)
        subprocess.run(["git", "config", "user.email", "meridian@example.invalid"], cwd=clone, check=True)
        (clone / "upstream.txt").write_text("upstream\n", encoding="utf-8")
        subprocess.run(["git", "add", "upstream.txt"], cwd=clone, check=True)
        subprocess.run(["git", "commit", "-m", "upstream advance"], cwd=clone, check=True, capture_output=True)
        subprocess.run(["git", "push", "origin", "main"], cwd=clone, check=True, capture_output=True)
        subprocess.run(["git", "fetch", "origin"], cwd=self.project, check=True, capture_output=True)

        result = self.run_cli(
            "worktree", "integrate", "stage", "056", "--project", str(self.project),
            "--worktree-root", str(self.worktree_root), "--evidence", str(evidence_path),
            "--format", "json",
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("local main is behind the already fetched origin/main", result.stderr)
        local = subprocess.run(
            ["git", "rev-parse", "--short=12", "main"], cwd=self.project, check=True, capture_output=True, text=True
        ).stdout.strip()
        fetched = subprocess.run(
            ["git", "rev-parse", "--short=12", "refs/remotes/origin/main"],
            cwd=self.project, check=True, capture_output=True, text=True,
        ).stdout.strip()
        self.assertEqual(
            result.stderr.strip(),
            "BLOCKED MAIN_BEHIND_ORIGIN: local main is behind the already fetched origin/main "
            f"(local main {local}, origin/main {fetched}); resume: bring local main up to the fetched origin/main "
            "without rewriting history, then rerun meridian worktree integrate stage 056 "
            f"--project {self.project.resolve()} --evidence {evidence_path} --format json",
        )

    def _stage_args(self, evidence_path: Path) -> tuple[str, ...]:
        return (
            "worktree", "integrate", "stage", "056", "--project", str(self.project),
            "--worktree-root", str(self.worktree_root), "--evidence", str(evidence_path), "--format", "json",
        )

    def test_stop_helper_formats_registered_codes_and_rejects_others(self) -> None:
        self.assertEqual(
            meridian.format_stop("PUSH_PENDING", "main is ahead"),
            "BLOCKED PUSH_PENDING: main is ahead; resume: git push origin main",
        )
        with self.assertRaises(meridian.InternalStopError):
            meridian.format_stop("NOT_A_REGISTERED_CODE", "detail", resume="x")
        with self.assertRaises(meridian.InternalStopError):
            meridian.stop_resume("WRONG_WORKTREE", task_id="056")

    def test_stop_registry_covers_closure_codes_and_names_real_tests(self) -> None:
        registry = meridian.load_stop_registry()
        closure = (
            "ACCEPTANCE_UNMET", "VALIDATION_FAILED", "REVIEW_REQUIRED", "WRONG_WORKTREE", "EVIDENCE_INCOMPLETE",
            "PRIMARY_DIRTY", "MAIN_BEHIND_ORIGIN", "LEASE_HELD", "INTEGRATION_CONFLICT",
            "CANDIDATE_VALIDATION_FAILED", "EVIDENCE_MISMATCH", "PUSH_PENDING", "PUSH_REJECTED", "CLEANUP_BLOCKED",
            "UNDECLARED_VALIDATION_COMMANDS", "STALE_WORKTREE_BASE", "REVIEW_NOT_APPROVED", "REVIEW_STALE",
        )
        gates = (
            "EXECUTION_CONTRACT_UNRESOLVED", "EXECUTION_PROFILE_MISSING", "VALIDATION_ENTRY_FORMAT",
            "TASK_RECORD_INCOMPLETE", "TASK_STATUS_REJECTED", "QUEUE_STATUS_MISMATCH",
            "EXECUTION_EVIDENCE_ARGUMENTS", "HANDOFF_REPORT_MISSING", "HANDOFF_FIELDS_MISSING",
            "HANDOFF_FIELD_FORMAT", "HANDOFF_TASK_MISMATCH", "HANDOFF_VALIDATION_FAILING",
            "HANDOFF_VALIDATION_EVIDENCE_MISSING", "HANDOFF_EXPLORATION_MISMATCH",
            "HANDOFF_EXPLORATION_SUMMARY_MISSING", "TASK_STATE_MISSING", "TASK_STATE_INVALID",
        )
        remaining = (
            "COMMAND_REFUSED", "OS_ACCESS_FAILED", "VALIDATION_ID_UNDECLARED", "BUDGET_EXHAUSTED",
            "BUDGET_ATTEMPT_REQUIRES_AUTHORIZATION",
            "HOST_IMPACT_DECLARATION_INVALID", "HOST_IMPACT_EVIDENCE_MISSING", "UPGRADE_BLOCKED", "ADOPTION_BLOCKED",
            "WORKFLOW_UNREADABLE", "RULE_CONFLICT", "CONTRACT_EXHAUSTED", "SCOPE_CHANGE_REQUIRED",
            "REVIEW_LOOP_EXHAUSTED", "SELF_UPDATE_PLUGIN_CACHE", "SELF_UPDATE_DIRTY",
            "SELF_UPDATE_BRANCH", "SELF_UPDATE_TARGET", "SELF_UPDATE_NON_FF", "SELF_UPDATE_VERIFY",
        )
        self.assertEqual(set(registry), set(closure) | set(gates) | set(remaining))
        self.assertEqual(
            {code for code, entry in registry.items() if entry["class"] == "judgment"},
            {
                "ACCEPTANCE_UNMET", "REVIEW_REQUIRED", "WORKFLOW_UNREADABLE", "RULE_CONFLICT", "CONTRACT_EXHAUSTED",
                "SCOPE_CHANGE_REQUIRED", "REVIEW_LOOP_EXHAUSTED",
            },
        )
        self.assertEqual(registry["PUSH_PENDING"]["kind"], "status")
        for code, entry in registry.items():
            with self.subTest(code=code):
                if entry["class"] == "tool" and entry["kind"] == "stop":
                    module_name, class_name, method = str(entry["test"]).rsplit(".", 2)
                    owner = getattr(importlib.import_module(module_name), class_name)
                    self.assertTrue(callable(getattr(owner, method, None)), entry["test"])

    def test_stop_registry_matches_its_schema_shape(self) -> None:
        schema = json.loads((ROOT / "schemas/stop-codes-v1.schema.json").read_text(encoding="utf-8"))
        item = schema["properties"]["stops"]["items"]
        for code, entry in meridian.load_stop_registry().items():
            with self.subTest(code=code):
                self.assertLessEqual(set(entry), set(item["properties"]))
                self.assertTrue(set(item["required"]) <= set(entry))
                self.assertIn(entry["class"], item["properties"]["class"]["enum"])
                self.assertIn(entry["kind"], item["properties"]["kind"]["enum"])
                self.assertTrue(set(entry["workflows"]) <= set(item["properties"]["workflows"]["items"]["enum"]))

    def test_closure_status_text_reports_incomplete_evidence_through_the_registry(self) -> None:
        prepared = self.run_cli(
            "worktree", "prepare", "056", "--project", str(self.project),
            "--worktree-root", str(self.worktree_root), "--format", "json",
        )
        worktree = Path(json.loads(prepared.stdout)["worktree"])
        (worktree / "implementation.txt").write_text("done\n", encoding="utf-8")
        subprocess.run(["git", "add", "implementation.txt"], cwd=worktree, check=True)
        subprocess.run(["git", "commit", "-m", "complete task"], cwd=worktree, check=True, capture_output=True)
        result = self.run_cli(
            "worktree", "closure-status", "056", "--project", str(self.project),
            "--worktree-root", str(self.worktree_root),
        )
        self.assertEqual(result.returncode, 2)
        self.assertEqual(
            result.stdout.strip(),
            "BLOCKED EVIDENCE_INCOMPLETE: machine evidence for the validated task commit is missing or "
            "incomplete; resume: record machine evidence",
        )

    def test_integrate_stage_reports_primary_dirty_through_the_registry(self) -> None:
        evidence_path = self._stage_ready_task_with_origin(local_ahead=True)
        (self.project / "stray.txt").write_text("stray\n", encoding="utf-8")
        result = self.run_cli(*self._stage_args(evidence_path))
        self.assertEqual(result.returncode, 2)
        self.assertEqual(
            result.stderr.strip(),
            "BLOCKED PRIMARY_DIRTY: primary checkout must be clean; resume: clean the primary checkout and run "
            "integration stage",
        )

    def test_integrate_stage_reports_a_held_lease_through_the_registry(self) -> None:
        evidence_path = self._stage_ready_task_with_origin(local_ahead=True)
        identity = meridian.resolve_task_identity(self.project, "056", "existing")
        _state, lease, _integration = meridian._lifecycle_paths(self.project, identity)
        lease.write_text(json.dumps({"task_id": "056"}), encoding="utf-8")
        result = self.run_cli(*self._stage_args(evidence_path))
        self.assertEqual(result.returncode, 2)
        self.assertEqual(
            result.stderr.strip(),
            f"BLOCKED LEASE_HELD: an interrupted integration lease is retained at {lease}; use "
            "`meridian worktree integrate abort`; resume: meridian worktree integrate abort 056 "
            f"--project {self.project.resolve()} --format json",
        )

    def test_integrate_stage_reports_undeclared_validation_commands_through_the_registry(self) -> None:
        evidence_path = self._stage_ready_task_with_origin(local_ahead=True)
        (self.project / ".meridian/candidate-validation.json").write_text(
            '{"version": 1, "state": "undeclared"}\n', encoding="utf-8"
        )
        subprocess.run(["git", "add", ".meridian/candidate-validation.json"], cwd=self.project, check=True)
        subprocess.run(["git", "commit", "-m", "undeclare"], cwd=self.project, check=True, capture_output=True)
        result = self.run_cli(*self._stage_args(evidence_path))
        self.assertEqual(result.returncode, 2)
        self.assertEqual(
            result.stderr.strip(),
            "BLOCKED UNDECLARED_VALIDATION_COMMANDS: no project choice is recorded at "
            ".meridian/candidate-validation.json. Task validation commands: none recorded. Proposed declaration: "
            '{"state": "undeclared", "version": 1}; resume: write declared candidate validation fragments or '
            "state none in .meridian/candidate-validation.json, then rerun the interrupted meridian worktree "
            "integrate step",
        )

    def test_integrate_stage_reports_an_integration_conflict_through_the_registry(self) -> None:
        evidence_path = self._stage_ready_task_with_origin(local_ahead=True)
        (self.project / "implementation.txt").write_text("main side\n", encoding="utf-8")
        subprocess.run(["git", "add", "implementation.txt"], cwd=self.project, check=True)
        subprocess.run(["git", "commit", "-m", "conflicting main change"], cwd=self.project, check=True, capture_output=True)
        result = self.run_cli(*self._stage_args(evidence_path))
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(
            result.stderr.strip(),
            "BLOCKED INTEGRATION_CONFLICT: integration conflict was aborted; task branch and worktree were "
            "retained; resume: the developer resolves the conflict on the task branch, then rerun meridian "
            f"worktree integrate stage 056 --project {self.project.resolve()} --evidence {evidence_path} "
            "--format json",
        )

    def test_integrate_finalize_reports_an_evidence_mismatch_through_the_registry(self) -> None:
        evidence_path = self._stage_ready_task_with_origin(local_ahead=True)
        staged = self.run_cli(*self._stage_args(evidence_path))
        self.assertEqual(staged.returncode, 0, staged.stderr)
        validation = self.root / "candidate-validation-evidence.json"
        validation.write_text(json.dumps({"passed": False}), encoding="utf-8")
        result = self.run_cli(
            "worktree", "integrate", "finalize", "056", "--project", str(self.project),
            "--evidence", str(validation), "--format", "json",
        )
        self.assertEqual(result.returncode, 2)
        self.assertEqual(
            result.stderr.strip(),
            "BLOCKED EVIDENCE_MISMATCH: candidate validation evidence is stale, mismatched, or failed; resume: "
            f"meridian worktree integrate abort 056 --project {self.project.resolve()} --format json",
        )

    def test_cleanup_reports_blocked_cleanup_through_the_registry(self) -> None:
        prepared = self.run_cli(
            "worktree", "prepare", "056", "--project", str(self.project),
            "--worktree-root", str(self.worktree_root), "--format", "json",
        )
        worktree = Path(json.loads(prepared.stdout)["worktree"])
        (worktree / "implementation.txt").write_text("done\n", encoding="utf-8")
        subprocess.run(["git", "add", "implementation.txt"], cwd=worktree, check=True)
        subprocess.run(["git", "commit", "-m", "complete task"], cwd=worktree, check=True, capture_output=True)
        result = self.run_cli(
            "worktree", "cleanup", "056", "--project", str(self.project),
            "--worktree-root", str(self.worktree_root), "--format", "json",
        )
        self.assertEqual(result.returncode, 2)
        self.assertEqual(
            result.stderr.strip(),
            "BLOCKED CLEANUP_BLOCKED: task commit is not integrated into main; resume: rerun meridian worktree "
            f"cleanup 056 --project {self.project.resolve()} --format json after the named condition clears",
        )

    def test_integrate_stage_accepts_local_main_ahead_of_fetched_origin_main(self) -> None:
        evidence_path = self._stage_ready_task_with_origin(local_ahead=True)
        result = self.run_cli(
            "worktree", "integrate", "stage", "056", "--project", str(self.project),
            "--worktree-root", str(self.worktree_root), "--evidence", str(evidence_path),
            "--format", "json",
        )
        self.assertNotIn("MAIN_BEHIND_ORIGIN", result.stderr + result.stdout)
        self.assertEqual(result.returncode, 0, result.stderr)

    def _advance_ready_task(self) -> Path:
        """A completed task branch with origin and a handoff but no recorded evidence."""
        (self.project / "tasks/handoffs").mkdir()
        (self.project / "tasks/handoffs/056.md").write_text("# Completion Report — 056\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=self.project, check=True)
        subprocess.run(["git", "commit", "-m", "handoff"], cwd=self.project, check=True, capture_output=True)
        evidence_path = self._stage_ready_task_with_origin(local_ahead=True)
        evidence_path.unlink()
        worktree = Path(json.loads(self.run_cli(
            "worktree", "path", "056", "--project", str(self.project),
            "--worktree-root", str(self.worktree_root), "--format", "json",
        ).stdout)["path"])
        meridian.transition_task_state(worktree, "056", "DONE")
        subprocess.run(["git", "add", "."], cwd=worktree, check=True)
        subprocess.run(["git", "commit", "-m", "record terminal state"], cwd=worktree, check=True, capture_output=True)
        (self.project / ".meridian/candidate-validation.json").write_text(
            json.dumps({"version": 1, "state": "declared", "outcomes": {
                "REUSE": ["scripts/check_repository.py"],
                "BOUNDED": ["scripts/check_repository.py"],
                "FULL": ["scripts/check_repository.py", "unittest discover"],
            }}), encoding="utf-8",
        )
        subprocess.run(["git", "add", ".meridian/candidate-validation.json"], cwd=self.project, check=True)
        subprocess.run(["git", "commit", "-m", "declare"], cwd=self.project, check=True, capture_output=True)
        return evidence_path

    def _advance(self, *extra: str) -> subprocess.CompletedProcess[str]:
        return self.run_cli(
            "worktree", "advance", "056", "--project", str(self.project),
            "--worktree-root", str(self.worktree_root), *extra, "--format", "json",
        )

    def _passing(self) -> tuple[str, ...]:
        return ("--accepted", "--validation-command", "check", "--validation-exit-code", "0")

    def _journal(self) -> list[dict[str, object]]:
        journal = self.project / ".git/meridian-journal.jsonl"
        return [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()]

    def test_advance_runs_to_candidate_validation_and_reruns_without_repeating(self) -> None:
        evidence_path = self._advance_ready_task()
        waiting = self._advance()
        self.assertEqual(waiting.returncode, 0, waiting.stderr)
        report = json.loads(waiting.stdout)
        self.assertEqual(
            (report["step"], report["action_required"], report["stop_code"], report["performed"]),
            ("C5", "run-validation", "EVIDENCE_INCOMPLETE", []),
        )
        self.assertFalse(evidence_path.exists())

        result = self._advance(*self._passing())
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(set(report), {
            "version", "task_id", "step", "action_required", "commands", "required_fragments", "stop_code", "resume", "performed",
        })
        self.assertEqual((report["step"], report["action_required"]), ("C7", "run-candidate-validation"))
        self.assertEqual(report["performed"], ["C5", "C6"])
        self.assertIsNone(report["stop_code"])
        self.assertEqual(report["commands"][0], "git diff --check")
        self.assertEqual(report["commands"], ["git diff --check"])
        self.assertIn("scripts/check_repository.py", report["required_fragments"])
        self.assertIn("project command containing that exact fragment", report["resume"])
        recorded = json.loads(evidence_path.read_text(encoding="utf-8"))
        self.assertEqual(recorded["validation_commands"], ["check"])
        commands = [(line["command"], line["result"]) for line in self._journal()]
        self.assertEqual(
            [item for item in commands if item[0] not in ("advance", "prepare")],
            [("evidence", "ok"), ("integrate stage", "ok")],
        )

        before = evidence_path.read_text(encoding="utf-8")
        rerun = json.loads(self._advance().stdout)
        self.assertEqual((rerun["step"], rerun["action_required"], rerun["performed"]), ("C7", "run-candidate-validation", []))
        self.assertEqual(rerun["commands"], report["commands"])
        self.assertEqual(evidence_path.read_text(encoding="utf-8"), before)
        self.assertEqual(
            [line["command"] for line in self._journal()].count("integrate stage"), 1
        )

    def test_advance_complete_commands_run_unchanged_and_finalize(self) -> None:
        self._advance_ready_task()
        script = self.project / "scripts/check_repository.py"
        script.parent.mkdir(exist_ok=True)
        script.write_text("from pathlib import Path\nassert Path('PROJECT_WORKFLOW.md').is_file()\n", encoding="utf-8")
        script.chmod(0o644)
        command = "python3 scripts/check_repository.py"
        (self.project / meridian.CANDIDATE_VALIDATION_PATH).write_text(json.dumps({
            "version": 1, "state": "declared",
            "outcomes": {outcome: [command] for outcome in ("REUSE", "BOUNDED", "FULL")},
        }), encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=self.project, check=True)
        subprocess.run(["git", "commit", "-m", "runnable declaration"], cwd=self.project,
                       check=True, capture_output=True)
        staged = self._advance(*self._passing())
        self.assertEqual(staged.returncode, 0, staged.stderr)
        report = json.loads(staged.stdout)
        self.assertEqual(report["commands"], ["git diff --check", command])
        self.assertEqual(report["required_fragments"], report["commands"])
        results = []
        for entry in report["commands"]:
            executed = subprocess.run(entry, shell=True, cwd=self.project, text=True, capture_output=True)
            self.assertEqual(executed.returncode, 0, executed.stderr)
            results.extend(("--candidate-command", entry, "--candidate-exit-code", str(executed.returncode)))
        finalized = self._advance(*results)
        self.assertEqual(finalized.returncode, 0, finalized.stderr)
        self.assertEqual(json.loads(finalized.stdout)["action_required"], "push")

    def test_advance_resumes_after_each_mechanical_step_and_reaches_cleanup(self) -> None:
        self._advance_ready_task()
        worktree = json.loads(self.run_cli(
            "worktree", "path", "056", "--project", str(self.project),
            "--worktree-root", str(self.worktree_root), "--format", "json",
        ).stdout)["path"]
        recorded = self.run_cli(
            "worktree", "evidence", "056", "--project", str(self.project),
            "--worktree-root", str(self.worktree_root), "--accepted",
            "--validation-command", "check", "--validation-exit-code", "0", "--format", "json",
            cwd=Path(worktree),
        )
        self.assertEqual(recorded.returncode, 0, recorded.stderr)
        staged = json.loads(self._advance().stdout)
        self.assertEqual((staged["step"], staged["performed"]), ("C7", ["C6"]))
        self.assertEqual([line["command"] for line in self._journal()].count("evidence"), 1)

        identity = meridian.resolve_task_identity(self.project, "056", "existing")
        _state, lease, integration = meridian._lifecycle_paths(self.project, identity)
        subprocess.run(["git", "merge", "--abort"], cwd=self.project, check=True)
        lease.unlink()
        integration.unlink()
        subprocess.run(["git", "merge", "--no-ff", "task-056", "-m", "integrate"], cwd=self.project, check=True, capture_output=True)
        push = json.loads(self._advance().stdout)
        self.assertEqual(
            (push["step"], push["action_required"], push["commands"], push["stop_code"]),
            ("C9", "push", ["git push origin main"], "PUSH_PENDING"),
        )
        self.assertEqual(push["performed"], [])
        subprocess.run(["git", "push", "origin", "main"], cwd=self.project, check=True, capture_output=True)

        done = self._advance()
        self.assertEqual(done.returncode, 0, done.stderr)
        report = json.loads(done.stdout)
        self.assertEqual((report["step"], report["action_required"], report["performed"]), ("C10", "none", ["C10"]))
        self.assertEqual(self._journal()[-2]["command"], "cleanup")
        again = json.loads(self._advance().stdout)
        self.assertEqual((again["action_required"], again["performed"]), ("none", []))
        self.assertEqual([line["command"] for line in self._journal()].count("cleanup"), 1)

    def test_advance_stops_on_failed_or_unaccepted_validation_without_recording(self) -> None:
        evidence_path = self._advance_ready_task()
        failed = self._advance("--accepted", "--validation-command", "check", "--validation-exit-code", "1")
        self.assertEqual(failed.returncode, 2, failed.stderr)
        report = json.loads(failed.stdout)
        self.assertEqual((report["step"], report["action_required"], report["stop_code"]), ("C2", "run-validation", "VALIDATION_FAILED"))
        self.assertEqual(report["resume"], "fix the failure on the task branch and rerun the failing command")
        unaccepted = self._advance("--validation-command", "check", "--validation-exit-code", "0")
        self.assertEqual(unaccepted.returncode, 2, unaccepted.stderr)
        self.assertEqual(json.loads(unaccepted.stdout)["stop_code"], "ACCEPTANCE_UNMET")
        self.assertFalse(evidence_path.exists())
        blocked = [line for line in self._journal() if line["result"] == "blocked"]
        self.assertEqual([line["stop_code"] for line in blocked], ["VALIDATION_FAILED", "ACCEPTANCE_UNMET"])
        mismatch = self._advance("--validation-command", "check")
        self.assertNotEqual(mismatch.returncode, 0)

    def test_advance_without_task_commits_asks_for_work_and_never_runs_supplied_commands(self) -> None:
        prepared = self.run_cli(
            "worktree", "prepare", "056", "--project", str(self.project),
            "--worktree-root", str(self.worktree_root), "--format", "json",
        )
        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        result = self._advance("--accepted", "--validation-command", "touch ran.txt", "--validation-exit-code", "0")
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual((report["step"], report["action_required"], report["stop_code"]), ("C1", "run-validation", "ACCEPTANCE_UNMET"))
        self.assertFalse((self.project / "ran.txt").exists())

    def test_advance_reports_a_blocked_stage_as_a_stop(self) -> None:
        evidence_path = self._advance_ready_task()
        (self.project / "implementation.txt").write_text("main side\n", encoding="utf-8")
        subprocess.run(["git", "add", "implementation.txt"], cwd=self.project, check=True)
        subprocess.run(["git", "commit", "-m", "conflicting main change"], cwd=self.project, check=True, capture_output=True)
        result = self._advance(*self._passing())
        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(
            (report["step"], report["action_required"], report["stop_code"], report["performed"]),
            ("C6", "human", "INTEGRATION_CONFLICT", ["C5"]),
        )
        self.assertIn(str(evidence_path), report["resume"])
        last = self._journal()[-1]
        self.assertEqual((last["command"], last["result"], last["stop_code"]), ("advance", "blocked", "INTEGRATION_CONFLICT"))

    def test_advance_names_the_resume_for_a_stop_the_agent_resolves(self) -> None:
        self._advance_ready_task()
        (self.project / "stray.txt").write_text("stray\n", encoding="utf-8")
        result = self._advance(*self._passing())
        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(
            (report["step"], report["action_required"], report["stop_code"], report["performed"]),
            ("C6", "resolve", "PRIMARY_DIRTY", []),
        )

    def _candidate(self, *commands: str, exit_code: int = 0) -> tuple[str, ...]:
        arguments: list[str] = []
        for command in commands:
            arguments += ["--candidate-command", command, "--candidate-exit-code", str(exit_code)]
        return tuple(arguments)

    def _all_candidate_commands(self) -> tuple[str, ...]:
        return self._candidate("git diff --check", "python3 scripts/check_repository.py", "python3 -m unittest discover")

    def _staged_at_c7(self) -> None:
        self._advance_ready_task()
        staged = json.loads(self._advance(*self._passing()).stdout)
        self.assertEqual(staged["step"], "C7")

    def _main_subject(self) -> str:
        return subprocess.run(
            ["git", "log", "-1", "--format=%s"], cwd=self.project, text=True, capture_output=True, check=True
        ).stdout.strip()

    def test_advance_finalizes_from_candidate_results_and_asks_for_the_push(self) -> None:
        self._staged_at_c7()
        result = self._advance(*self._all_candidate_commands())
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(
            (report["step"], report["action_required"], report["commands"], report["performed"]),
            ("C9", "push", ["git push origin main"], ["C8"]),
        )
        self.assertEqual(self._main_subject(), "Integrate 056")
        self.assertEqual([line["command"] for line in self._journal()].count("integrate finalize"), 1)

    def test_advance_reruns_after_an_interruption_between_finalize_and_push(self) -> None:
        self._staged_at_c7()
        self._advance(*self._all_candidate_commands())
        rerun = self._advance(*self._all_candidate_commands())
        self.assertEqual(rerun.returncode, 0, rerun.stderr)
        report = json.loads(rerun.stdout)
        self.assertEqual((report["step"], report["action_required"], report["performed"]), ("C9", "push", []))
        self.assertEqual([line["command"] for line in self._journal()].count("integrate finalize"), 1)

    def test_advance_aborts_and_stops_when_a_candidate_command_failed(self) -> None:
        self._staged_at_c7()
        result = self._advance(
            *self._candidate("git diff --check", "python3 scripts/check_repository.py"),
            "--candidate-command", "python3 -m unittest discover", "--candidate-exit-code", "1",
        )
        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual((report["step"], report["stop_code"]), ("C7", "CANDIDATE_VALIDATION_FAILED"))
        self.assertIn("aborted", report["resume"])
        self.assertEqual(self._main_subject(), "declare")
        self.assertFalse((self.project / ".git/MERGE_HEAD").exists())
        self.assertEqual(self._journal()[-1]["stop_code"], "CANDIDATE_VALIDATION_FAILED")
        self.assertIn("integrate abort", [line["command"] for line in self._journal()])

    def test_advance_aborts_without_finalizing_when_a_required_command_is_missing(self) -> None:
        self._staged_at_c7()
        result = self._advance(*self._candidate("python3 scripts/check_repository.py"))
        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual((report["step"], report["stop_code"]), ("C7", "UNDECLARED_VALIDATION_COMMANDS"))
        self.assertEqual(report["commands"], ["git diff --check"])
        self.assertNotIn("integrate finalize", [line["command"] for line in self._journal()])
        self.assertFalse((self.project / ".git/MERGE_HEAD").exists())
        self.assertEqual(self._main_subject(), "declare")

    def test_advance_reports_a_candidate_tree_that_changed_after_stage(self) -> None:
        self._staged_at_c7()
        (self.project / "late.txt").write_text("late\n", encoding="utf-8")
        subprocess.run(["git", "add", "late.txt"], cwd=self.project, check=True)
        result = self._advance(*self._all_candidate_commands())
        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual((report["step"], report["stop_code"]), ("C8", "EVIDENCE_MISMATCH"))
        self.assertIn("integrate abort", report["resume"])
        self.assertTrue((self.project / ".git/MERGE_HEAD").exists())
        self.assertEqual(self._journal()[-1]["stop_code"], "EVIDENCE_MISMATCH")

    def test_advance_rejects_unpaired_candidate_results(self) -> None:
        self._staged_at_c7()
        result = self._advance("--candidate-command", "git diff --check")
        self.assertNotEqual(result.returncode, 0)

    def run_console(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(CLI),
                "--framework-root",
                str(ROOT),
                "console",
                "--project",
                str(self.project),
                *arguments,
            ],
            text=True,
            capture_output=True,
            check=False,
            stdin=subprocess.DEVNULL,
        )

    def test_console_rejects_out_of_range_interval(self) -> None:
        for value in ("0.1", "61"):
            result = self.run_console("--interval", value)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--interval must be between 0.2 and 60", result.stderr)

    def test_console_requires_a_terminal(self) -> None:
        result = self.run_console()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("interactive console requires a terminal", result.stderr)

    def test_console_dispatches_to_framework_console_with_project_and_interval(self) -> None:
        import project_console

        with (
            mock.patch.object(
                sys,
                "argv",
                [
                    "meridian",
                    "--framework-root",
                    str(ROOT),
                    "console",
                    "--project",
                    str(self.project),
                    "--interval",
                    "5",
                ],
            ),
            mock.patch.object(sys.stdin, "isatty", return_value=True),
            mock.patch.object(sys.stdout, "isatty", return_value=True),
            mock.patch.object(project_console, "main", return_value=0) as launched,
        ):
            result = meridian.main()

        self.assertEqual(result, 0)
        launched.assert_called_once_with(
            ["--project", str(self.project.resolve()), "--interval", "5.0"]
        )


class LifecycleJournalTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.project = self.root / "project"
        self.project.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=self.project, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Meridian Test"], cwd=self.project, check=True)
        subprocess.run(["git", "config", "user.email", "meridian@example.invalid"], cwd=self.project, check=True)
        (self.project / "tasks").mkdir()
        (self.project / "tasks/056-lifecycle.md").write_text("# Task 056\n\n> **ID**: `056`\n", encoding="utf-8")
        (self.project / "tasks/QUEUE.md").write_text(
            "| Status | ID | Title |\n|---|---|---|\n| `[ ]` | 056 | Lifecycle |\n", encoding="utf-8"
        )
        subprocess.run(["git", "add", "."], cwd=self.project, check=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=self.project, check=True, capture_output=True)
        self.worktree_root = self.root / "worktrees"
        self.worktree_root.mkdir()
        self.journal = self.project / ".git" / "meridian-journal.jsonl"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def lifecycle(
        self, command: str, *extra: str, cwd: Path | None = None
    ) -> subprocess.CompletedProcess[str]:
        root = () if command in ("integrate finalize", "integrate abort") else ("--worktree-root", str(self.worktree_root))
        return subprocess.run(
            [
                sys.executable, str(CLI), "--framework-root", str(ROOT), "worktree", *command.split(), "056",
                "--project", str(self.project), *root, *extra,
            ],
            cwd=cwd or self.project, text=True, capture_output=True, check=False,
        )

    def prepare_with_commit(self) -> Path:
        worktree = Path(json.loads(self.lifecycle("prepare", "--format", "json").stdout)["worktree"])
        (worktree / "implementation.txt").write_text("done\n", encoding="utf-8")
        subprocess.run(["git", "add", "implementation.txt"], cwd=worktree, check=True)
        subprocess.run(["git", "commit", "-m", "complete task"], cwd=worktree, check=True, capture_output=True)
        return worktree

    def lines(self) -> list[dict[str, object]]:
        if not self.journal.exists():
            return []
        return [json.loads(line) for line in self.journal.read_text(encoding="utf-8").splitlines()]

    def test_prepare_resume_is_marked_in_the_journal(self) -> None:
        self.assertEqual(self.lifecycle("prepare", "--format", "json").returncode, 0)
        self.assertEqual(self.lifecycle("prepare", "--resume", "--format", "json").returncode, 0)
        first, second = self.lines()
        self.assertNotIn("resume", first)
        self.assertIs(second["resume"], True)

    def test_resume_survives_a_failed_journal_write(self) -> None:
        self.assertEqual(self.lifecycle("prepare", "--format", "json").returncode, 0)
        self.journal.unlink()
        self.journal.mkdir()
        resumed = self.lifecycle("prepare", "--resume", "--format", "json")
        self.assertEqual(resumed.returncode, 0, resumed.stderr)
        self.assertIs(json.loads(resumed.stdout)["resumed"], True)
        self.assertIn("lifecycle journal not written", resumed.stderr)

    def test_each_journaled_lifecycle_command_appends_one_line(self) -> None:
        evidence = self.root / "evidence.json"
        evidence.write_text("{}", encoding="utf-8")
        commands = (
            ("prepare", "--format", "json"),
            ("check", "--format", "json"),
            ("evidence", "--validation-command", "true", "--validation-exit-code", "0", "--format", "json"),
            ("integrate stage", "--evidence", str(evidence), "--format", "json"),
            ("integrate finalize", "--evidence", str(evidence), "--format", "json"),
            ("integrate abort", "--format", "json"),
            ("cleanup", "--format", "json"),
        )
        for index, (command, *extra) in enumerate(commands, start=1):
            self.lifecycle(command, *extra)
            recorded = self.lines()
            self.assertEqual(len(recorded), index, command)
            line = recorded[-1]
            self.assertEqual(line["command"], command)
            self.assertEqual(line["task"], "056")
            self.assertEqual(line["version"], 1)
            self.assertRegex(str(line["ts"]), r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
            self.assertIn(line["result"], {"ok", "blocked", "error"})
        first = self.lines()[0]
        self.assertEqual((first["result"], first["exit"], first["step"]), ("ok", 0, "check"))
        recorded = self.lines()
        self.lifecycle("closure-status", "--format", "json")
        self.assertEqual(self.lines(), recorded)

    def test_blocked_result_records_its_registered_code(self) -> None:
        self.prepare_with_commit()
        result = self.lifecycle("cleanup", "--format", "json")
        self.assertEqual(result.returncode, 2)
        line = self.lines()[-1]
        self.assertEqual(
            (line["command"], line["result"], line["exit"], line["stop_code"]),
            ("cleanup", "blocked", 2, "CLEANUP_BLOCKED"),
        )
        self.assertNotIn(str(self.root), self.journal.read_text(encoding="utf-8"))

    def test_lines_hold_no_absolute_path_or_agent_supplied_text(self) -> None:
        self.lifecycle("prepare", "--format", "json")
        self.lifecycle(
            "evidence", "--validation-command", "SECRET-COMMAND-TEXT", "--validation-exit-code", "0",
            "--format", "json",
        )
        text = self.journal.read_text(encoding="utf-8")
        self.assertNotIn("SECRET-COMMAND-TEXT", text)
        self.assertNotIn(str(self.root), text)
        self.assertNotIn(str(Path.home()), text)
        for line in self.lines():
            self.assertLessEqual(
                set(line), {"version", "ts", "command", "task", "step", "result", "stop_code", "exit"}
            )

    def test_journal_is_untracked_and_shared_by_every_worktree(self) -> None:
        prepared = json.loads(self.lifecycle("prepare", "--format", "json").stdout)
        worktree = Path(prepared["worktree"])
        self.lifecycle("check", "--format", "json", cwd=worktree)
        self.assertEqual([line["command"] for line in self.lines()], ["prepare", "check"])
        status = subprocess.run(
            ["git", "status", "--short"], cwd=self.project, text=True, capture_output=True, check=True
        )
        self.assertEqual(status.stdout.strip(), "")
        self.assertFalse((worktree / "meridian-journal.jsonl").exists())

    def test_rotation_keeps_one_previous_file(self) -> None:
        directory = self.project / ".git"
        self.journal.write_text("x" * (meridian.JOURNAL_MAX_BYTES + 1), encoding="utf-8")
        (directory / "meridian-journal.1.jsonl").write_text("older\n", encoding="utf-8")
        meridian.append_journal_line(self.project, {"version": 1, "command": "check"})
        rotated = directory / "meridian-journal.1.jsonl"
        self.assertEqual(rotated.stat().st_size, meridian.JOURNAL_MAX_BYTES + 1)
        self.assertEqual(self.lines(), [{"command": "check", "version": 1}])
        self.assertEqual(
            sorted(path.name for path in directory.glob("meridian-journal*")),
            ["meridian-journal.1.jsonl", "meridian-journal.jsonl"],
        )

    def test_write_failure_warns_once_and_keeps_the_result(self) -> None:
        worktree = self.prepare_with_commit()
        self.journal.unlink()
        self.journal.mkdir()
        checked = self.lifecycle("check", "--format", "json", cwd=worktree)
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertEqual(json.loads(checked.stdout)["status"], "ready")
        self.assertEqual(checked.stderr.count("warning: lifecycle journal not written"), 1)

    def test_concurrent_appends_from_two_worktrees_produce_whole_lines(self) -> None:
        other = self.root / "other"
        subprocess.run(
            ["git", "worktree", "add", "-b", "other", str(other)], cwd=self.project, check=True, capture_output=True
        )
        script = (
            "import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); import meridian; "
            "[meridian.append_journal_line(Path(sys.argv[2]), "
            "{'version': 1, 'command': 'check', 'pad': 'p' * 3000, 'n': i}) for i in range(150)]"
        )
        processes = [
            subprocess.Popen([sys.executable, "-c", script, str(ROOT / "scripts"), str(location)])
            for location in (self.project, other, self.project, other)
        ]
        for process in processes:
            self.assertEqual(process.wait(), 0)
        recorded = self.lines()
        self.assertEqual(len(recorded), 600)
        self.assertTrue(all(len(str(line["pad"])) == 3000 for line in recorded))


class FlowReportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.project = Path(self.temporary.name) / "project"
        self.project.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=self.project, check=True, capture_output=True)
        (self.project / "tasks" / "done").mkdir(parents=True)
        (self.project / ".meridian").mkdir()
        self.journal = self.project / ".git" / "meridian-journal.jsonl"
        self.records: list[str] = []
        self.now = datetime(2026, 10, 5, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def stamp(self, day: int, hour: int = 0) -> str:
        moment = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=day, hours=hour)
        return moment.strftime("%Y-%m-%dT%H:%M:%SZ")

    def add(self, day: int, command: str, task: str, result: str = "ok", hour: int = 0, **extra: object) -> None:
        line = {"version": 1, "ts": self.stamp(day, hour), "command": command, "task": task, "result": result,
                "exit": 0 if result == "ok" else 2, **extra}
        self.records.append(json.dumps(line))

    def flush(self) -> None:
        self.journal.write_text("\n".join(self.records) + ("\n" if self.records else ""), encoding="utf-8")

    def task_record(self, task: str, origin: str | None, archived: bool = False) -> None:
        header = f"> **Origin**: {origin}\n" if origin else ""
        folder = self.project / "tasks" / ("done" if archived else "")
        (folder / f"{task}-work.md").write_text(f"# Task {task}\n\n> **ID**: `{task}`\n{header}", encoding="utf-8")

    def targets(self) -> None:
        (self.project / ".meridian" / "flow-targets.json").write_text(json.dumps({
            "version": 1,
            "unbacked_blocks": {"window": 20, "max": 0},
            "lead_time_regression": {"window": 20, "max_percent": 10},
            "friction_share": {"window": 20, "max_percent": 30},
        }), encoding="utf-8")

    def integrated(self, count: int, lead_hours: int = 10, origins: list[str | None] | None = None) -> None:
        for index in range(count):
            task = f"{100 + index}"
            self.add(index, "prepare", task)
            self.add(index, "integrate finalize", task, hour=lead_hours)
            self.task_record(task, origins[index] if origins else None)

    def report(self, since: str | None = None) -> dict[str, object]:
        self.flush()
        return meridian.flow_report(self.project, since, self.now)

    def target_states(self, report: dict[str, object]) -> dict[str, str]:
        return {target["target"]: target["state"] for target in report["targets"]}  # type: ignore[index]

    def test_lead_time_runs_from_first_prepare_to_finalize(self) -> None:
        self.add(0, "prepare", "056")
        self.add(1, "prepare", "056", resume=True)
        self.add(1, "integrate finalize", "056", hour=2)
        self.add(2, "prepare", "057")
        self.task_record("056", None)
        report = self.report()
        by_task = {task["task"]: task for task in report["tasks"]}  # type: ignore[index]
        self.assertEqual(by_task["056"]["lead_time_seconds"], 26 * 3600)
        self.assertIsNone(by_task["057"]["lead_time_seconds"])
        self.assertEqual(report["totals"]["median_lead_time_seconds"], 26 * 3600)  # type: ignore[index]
        self.assertEqual(report["totals"]["integrated"], 1)  # type: ignore[index]

    def test_median_lead_time_across_tasks(self) -> None:
        for task, hours in (("101", 2), ("102", 4), ("103", 100)):
            self.add(0, "prepare", task)
            self.add(0, "integrate finalize", task, hour=hours)
        self.assertEqual(self.report()["totals"]["median_lead_time_seconds"], 4 * 3600)  # type: ignore[index]

    def test_stops_group_by_code_and_registered_class(self) -> None:
        self.add(0, "integrate stage", "056", "blocked", stop_code="PRIMARY_DIRTY")
        self.add(0, "integrate stage", "056", "blocked", stop_code="PRIMARY_DIRTY")
        self.add(1, "check", "056", "blocked")
        self.add(1, "cleanup", "057", "blocked", stop_code="NOT_A_REGISTERED_CODE")
        self.add(1, "check", "057", "error")
        report = self.report()
        self.assertEqual(report["stops_by_code"], {"NOT_A_REGISTERED_CODE": 1, "PRIMARY_DIRTY": 2, "uncoded": 1})
        self.assertEqual(report["stops_by_class"], {"tool": 2, "uncoded": 1, "unknown": 1})
        by_task = {task["task"]: task for task in report["tasks"]}  # type: ignore[index]
        self.assertEqual(by_task["056"]["stops"], {"PRIMARY_DIRTY": 2, "uncoded": 1})
        self.assertEqual(report["totals"]["stops"], 4)  # type: ignore[index]

    def test_aborts_and_resumes_are_counted_per_task(self) -> None:
        self.add(0, "prepare", "056")
        self.add(0, "prepare", "056", resume=True)
        self.add(1, "prepare", "056", resume=True)
        self.add(1, "prepare", "056", "error", resume=True)
        self.add(1, "integrate abort", "056")
        self.add(1, "integrate abort", "056", "blocked")
        task = self.report()["tasks"][0]  # type: ignore[index]
        self.assertEqual((task["resumes"], task["aborts"]), (2, 1))

    def test_since_filters_records_but_keeps_lead_time_history(self) -> None:
        self.add(0, "prepare", "056")
        self.add(5, "integrate stage", "056", "blocked", stop_code="PRIMARY_DIRTY")
        self.add(10, "integrate finalize", "056")
        self.add(1, "integrate stage", "057", "blocked", stop_code="LEASE_HELD")
        report = self.report(since="2026-01-05")
        self.assertEqual([task["task"] for task in report["tasks"]], ["056"])  # type: ignore[index]
        self.assertEqual(report["tasks"][0]["lead_time_seconds"], 10 * 86400)  # type: ignore[index]
        self.assertEqual(report["stops_by_code"], {"PRIMARY_DIRTY": 1})
        with self.assertRaises(meridian.MeridianError):
            meridian.flow_report(self.project, "yesterday", self.now)

    def test_origin_shares_with_archive_and_unknown(self) -> None:
        for task, origin, archived in (("101", "friction", False), ("102", "capability", True), ("103", None, False),
                                       ("104", "bogus", False), ("105", "Friction", True)):
            self.add(0, "check", task)
            self.task_record(task, origin, archived)
        self.add(0, "check", "106")
        report = self.report()
        self.assertEqual(report["origin_counts"], {"capability": 1, "friction": 2, "maintenance": 0, "release": 0, "unknown": 3})
        self.assertEqual(report["origin_share_percent"]["friction"], 33.3)  # type: ignore[index]
        self.assertEqual(report["origin_share_percent"]["unknown"], 50.0)  # type: ignore[index]

    def test_targets_report_insufficient_data(self) -> None:
        self.targets()
        self.integrated(5)
        self.assertEqual(self.target_states(self.report()), {
            "unbacked_blocks": "insufficient data", "lead_time_regression": "insufficient data",
            "friction_share": "insufficient data",
        })

    def test_targets_met(self) -> None:
        self.targets()
        self.integrated(40, origins=["capability"] * 30 + ["friction"] * 5 + ["maintenance"] * 5)
        report = self.report()
        self.assertEqual(self.target_states(report), {
            "unbacked_blocks": "met", "lead_time_regression": "met", "friction_share": "met",
        })
        measured = {target["target"]: target["measured"] for target in report["targets"]}  # type: ignore[index]
        self.assertEqual(measured, {"unbacked_blocks": 0, "lead_time_regression": 0.0, "friction_share": 25.0})

    def test_targets_missed(self) -> None:
        self.targets()
        self.integrated(40, origins=["capability"] * 30 + ["friction"] * 7 + ["maintenance"] * 3)
        for index in range(20, 40):  # the last 20 take 12h against 10h before them: +20%
            self.records[index * 2 + 1] = self.records[index * 2 + 1].replace('T10:00:00Z', 'T12:00:00Z')
        self.add(39, "unbacked", "139", "unbacked_block", hour=13, stop_code="PRIMARY_DIRTY")
        report = self.report()
        self.assertEqual(self.target_states(report), {
            "unbacked_blocks": "missed", "lead_time_regression": "missed", "friction_share": "missed",
        })
        self.assertEqual(report["unbacked_blocks"], 1)

    def test_target_window_ignores_older_unbacked_blocks_and_since(self) -> None:
        self.targets()
        self.add(-5, "unbacked", "099", "unbacked_block", stop_code="PRIMARY_DIRTY")
        self.integrated(20, origins=["capability"] * 20)
        report = self.report(since="2026-01-15")
        self.assertEqual(self.target_states(report)["unbacked_blocks"], "met")
        self.assertEqual(self.target_states(report)["friction_share"], "met")

    def test_missing_targets_file_shows_measurements_only(self) -> None:
        self.integrated(3)
        self.assertEqual(self.report()["targets"], [])

    def test_unreadable_targets_file_is_an_error(self) -> None:
        (self.project / ".meridian" / "flow-targets.json").write_text('{"version": 2}', encoding="utf-8")
        self.integrated(1)
        with self.assertRaises(meridian.MeridianError):
            self.report()

    def test_removal_candidates_are_unemitted_tool_codes(self) -> None:
        tool_codes = {code for code, entry in meridian.load_stop_registry().items() if entry["class"] == "tool"}
        self.add(0, "integrate stage", "056", "blocked", stop_code="PRIMARY_DIRTY")
        self.add(0, "integrate stage", "056", "blocked", stop_code="VALIDATION_FAILED")
        self.add(30, "check", "056")
        report = self.report()
        self.assertEqual(set(report["removal_candidates"]), tool_codes - {"PRIMARY_DIRTY"})  # type: ignore[arg-type]
        self.assertEqual(report["period_days"], (self.now - datetime(2026, 1, 1, tzinfo=timezone.utc)).days)
        self.assertEqual(self.report(since="2026-01-20")["period_days"], (self.now - datetime(2026, 1, 20, tzinfo=timezone.utc)).days)

    def test_malformed_lines_are_counted_and_never_fatal(self) -> None:
        self.add(0, "prepare", "056")
        self.records += ["not json", "[1, 2]", '{"version": 2, "ts": "2026-01-01T00:00:00Z", "command": "x", "result": "ok"}',
                         '{"version": 1, "ts": "yesterday", "command": "x", "result": "ok"}', "", '{"version": 1}']
        self.add(0, "integrate finalize", "056", hour=3)
        report = self.report()
        self.assertEqual(report["malformed_lines"], 5)
        self.assertEqual(report["tasks"][0]["lead_time_seconds"], 3 * 3600)  # type: ignore[index]

    def test_rotated_journal_is_read_before_the_current_one(self) -> None:
        self.add(0, "prepare", "056")
        (self.project / ".git" / "meridian-journal.1.jsonl").write_text(self.records.pop() + "\n", encoding="utf-8")
        self.add(1, "integrate finalize", "056")
        self.assertEqual(self.report()["tasks"][0]["lead_time_seconds"], 86400)  # type: ignore[index]

    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CLI), "--framework-root", str(ROOT), "report", "flow", "--project", str(self.project), *arguments],
            cwd=self.project, text=True, capture_output=True, check=False,
        )

    def test_empty_or_missing_journal_gives_an_empty_report_with_exit_zero(self) -> None:
        for prepare in (lambda: None, self.flush):
            prepare()
            result = self.run_cli("--format", "json")
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual((report["tasks"], report["stops_by_code"], report["removal_candidates"], report["malformed_lines"]), ([], {}, [], 0))
            self.assertEqual(self.run_cli().returncode, 0)

    def test_cli_is_read_only_and_a_missed_target_keeps_exit_zero(self) -> None:
        self.targets()
        self.integrated(2)
        self.add(1, "unbacked", "101", "unbacked_block", hour=11)
        self.flush()
        before = self.journal.read_bytes()
        text = self.run_cli()
        self.assertEqual(text.returncode, 0, text.stderr)
        self.assertIn("Target unbacked_blocks: insufficient data", text.stdout)
        self.assertEqual(json.loads(self.run_cli("--format", "json", "--since", "2026-01-01").stdout)["since"], "2026-01-01")
        self.assertEqual(self.run_cli("--since", "nope").returncode, 2)
        self.assertEqual(self.journal.read_bytes(), before)


class LauncherTest(unittest.TestCase):
    def test_the_bin_launcher_starts_outside_the_scripts_directory(self) -> None:
        # runpy.run_path keeps bin/ on sys.path, so every script-local import
        # must resolve after the entry point adds scripts/ itself.
        environment = dict(os.environ)
        environment.pop("MERIDIAN_ROOT", None)
        result = subprocess.run(
            [sys.executable, str(ROOT / "bin" / "meridian"), "--version"],
            cwd=tempfile.gettempdir(), capture_output=True, text=True, check=False,
            env=environment,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), (ROOT / "VERSION").read_text(encoding="utf-8").strip())


class TaskStateAuditTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        (self.project / "tasks").mkdir()
        (self.project / ".meridian/tasks").mkdir(parents=True)
        (self.project / "tasks/001.md").write_text("# Task 001 — Task\nStatus: QUEUED\n")
        (self.project / "tasks/QUEUE.md").write_text(
            "| ID | Status | File |\n|---|---|---|\n| 001 | QUEUED | [001](001.md) |\n")
        self.path = self.project / ".meridian/tasks/001.json"
        self.path.write_text(json.dumps({"version": 1, "task_id": "001", "workflow": "governed-sdd",
                                         "status": "QUEUED", "transitions": []}))

    def test_audit_pass_and_drift_are_one_read_only_row_per_state(self):
        before = {p: p.read_bytes() for p in self.project.rglob("*") if p.is_file()}
        rows = meridian.audit_task_state_projections(self.project, "governed-sdd")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].status, "PASS")
        self.assertEqual(before, {p: p.read_bytes() for p in before})
        (self.project / "tasks/001.md").write_text("# Task 001 — Task\nStatus: ACCEPTED\n")
        (self.project / "tasks/QUEUE.md").write_text(
            "| ID | Status | File |\n|---|---|---|\n| 001 | IN_PROGRESS | [001](001.md) |\n")
        before = {p: p.read_bytes() for p in before}
        rows = meridian.audit_task_state_projections(self.project, "governed-sdd")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].status, "ADVISORY")
        self.assertIn(".meridian/tasks/001.json", rows[0].detail)
        self.assertIn("tasks/QUEUE.md queue Status: state=QUEUED, projection=IN_PROGRESS", rows[0].detail)
        self.assertIn("tasks/001.md record Status: state=QUEUED, projection=ACCEPTED", rows[0].detail)
        self.assertEqual(before, {p: p.read_bytes() for p in before})
        with mock.patch.object(meridian, "audit_declared_capabilities", return_value=([], "governed-sdd")), \
                mock.patch.object(meridian, "audit_capability_markers", return_value=[]), \
                mock.patch.object(meridian, "audit_duplicate_headings", return_value=[]), \
                mock.patch.object(meridian, "audit_capability_moves", return_value=[]), \
                mock.patch.object(meridian, "audit_entry_router", return_value=[]), redirect_stdout(io.StringIO()) as out:
            meridian.run_audit(self.project, ROOT, "governed-sdd")
        self.assertRegex(out.getvalue(), r"ADVISORY\s+task-state")

    def test_audit_invalid_state_is_coded_and_other_rows_survive(self):
        self.path.write_text("not JSON")
        rows = meridian.audit_task_state_projections(self.project, "governed-sdd")
        self.assertEqual(rows[0].status, "FAIL")
        self.assertIn("TASK_STATE_INVALID", rows[0].detail)

    def test_audit_normalizes_lean_checkbox_and_finds_archived_records(self):
        (self.project / "tasks/done").mkdir()
        (self.project / "tasks/001.md").rename(self.project / "tasks/done/001.md")
        (self.project / "tasks/done/001.md").write_text("# Task 001 — Task\nStatus: DONE\n")
        (self.project / "tasks/QUEUE.md").write_text("")
        (self.project / "tasks/QUEUE_ARCHIVE.md").write_text(
            "| ID | Status | File |\n|---|---|---|\n| 001 | `[x]` | — |\n")
        self.path.write_text(json.dumps({"version": 1, "task_id": "001", "workflow": "lean-delivery",
            "status": "DONE", "transitions": [{"from": "QUEUED", "to": "DONE", "commit": "a" * 40,
                                                "at": "2026-10-11T12:00:00Z"}]}))
        rows = meridian.audit_task_state_projections(self.project, "lean-delivery")
        self.assertEqual(rows[0].status, "PASS")


if __name__ == "__main__":
    unittest.main()
