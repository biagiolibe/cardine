"""Framework CLI regression tests for cli and entry."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import meridian  # noqa: E402
from cardine.templates import markers as templates_markers
import cardine.shared.hashing as shared_hashing
from cardine.templates import router as owner_templates_router

from meridian_cli_support import MeridianCliFixtureMixin, CLI


class CliEntryTest(MeridianCliFixtureMixin, unittest.TestCase):
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
        self.assertEqual(templates_markers.marker_pairs(upgraded), [])

    def test_explicit_agents_pointer_rejects_duplicate_or_capability_markers(self) -> None:
        self.assertFalse(
            templates_markers.is_agents_pointer(
                "<!-- MERIDIAN:CLAUDE-AGENTS-POINTER v1 -->\n"
                "<!-- MERIDIAN:CLAUDE-AGENTS-POINTER v1 -->\n"
            )
        )
        self.assertFalse(
            templates_markers.is_agents_pointer(
                "<!-- MERIDIAN:CLAUDE-AGENTS-POINTER v1 -->\n"
                "<!-- MERIDIAN:BEGIN capability=test v1 -->\nRule.\n<!-- MERIDIAN:END -->\n"
            )
        )

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
        outputs = owner_templates_router.entry_router_outputs(self.project)
        for target, expected in outputs.items():
            self.assertEqual((self.project / target).read_text(encoding="utf-8"), expected)
        self.assertEqual(owner_templates_router.audit_entry_router(self.project), [])
        manifest = json.loads((self.project / ".meridian/manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["managedFiles"]["AGENTS.md"], shared_hashing.sha256(self.project / "AGENTS.md"))
        self.assertEqual(manifest["managedFiles"]["CLAUDE.md"], shared_hashing.sha256(self.project / "CLAUDE.md"))

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
