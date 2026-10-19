"""Framework CLI regression tests for host codex repair."""

from __future__ import annotations

from cardine_cli_support import CLI, ROOT
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
import cardine.shared.errors as shared_errors
from cardine.hosts import codex as owner_hosts_codex
from cardine.hosts import setup as owner_hosts_setup
import cardine_cli


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
            f"{cardine_cli.CODEX_MANAGED_BEGIN}\n"
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
        with self.assertRaisesRegex(shared_errors.CardineError, pattern):
            owner_hosts_codex.plan_codex_configuration(self.config, self.worktrees)
        self.assertEqual(self.config.read_text(encoding="utf-8"), text)

    def test_observed_rewrite_is_a_named_repairable_state(self) -> None:
        text = self.rewritten()
        self.config.write_text(text, encoding="utf-8")

        plan = owner_hosts_codex.plan_codex_configuration(self.config, self.worktrees)

        self.assertEqual(plan.status, "repair-required")
        self.assertIn("ownership-metadata-repair", plan.detail)
        self.assertEqual(tomllib.loads(plan.proposed_text or ""), tomllib.loads(text))
        self.assertEqual(self.config.read_text(encoding="utf-8"), text)

    def test_damaged_exact_profile_with_an_old_root_is_repaired_and_replaced(self) -> None:
        old_root = self.root / "old-worktrees"
        original = self.rewritten(tables=self.profile_tables(old_root))
        self.config.write_text(original, encoding="utf-8")

        plan = owner_hosts_codex.plan_codex_configuration(self.config, self.worktrees)

        self.assertEqual(plan.status, "repair-and-replace-required")
        self.assertIn("restores Cardine's ownership metadata and replaces the one configured worktree root", plan.detail)
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
        report = owner_hosts_setup.codex_doctor(self.root, self.config, self.worktrees)
        self.assertEqual(report["permission-model"], "repair-and-replace-required")
        self.assertEqual(report["profile-ownership"], "repair-and-replace-required")

        applied = self.run_cli("--apply")
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertIn("ownership metadata repaired and root replaced", applied.stdout)
        backup = self.config.with_name("config.toml.cardine-repair.bak")
        self.assertEqual(backup.read_text(encoding="utf-8"), original)
        self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
        ready = owner_hosts_codex.plan_codex_configuration(self.config, self.worktrees)
        self.assertEqual(ready.status, "ready")
        self.assertFalse(owner_hosts_codex.apply_codex_configuration(ready))

    def test_moved_and_normalized_markers_with_an_old_root_use_the_combined_state(self) -> None:
        old_root = self.root / "old-worktrees"
        base = self.rewritten(tables=self.profile_tables(old_root))
        shapes = {
            "moved": cardine_cli.CODEX_MANAGED_END + "\n" + base,
            "normalized": base.replace("# MERIDIAN:BEGIN", "# MERIDIAN:BEGIN  "),
        }
        for name, text in shapes.items():
            with self.subTest(name):
                self.config.write_text(text, encoding="utf-8")
                plan = owner_hosts_codex.plan_codex_configuration(self.config, self.worktrees)
                self.assertEqual(plan.status, "repair-and-replace-required")
                self.assertEqual(
                    tomllib.loads(plan.proposed_text or "")["permissions"]["meridian-worktrees"]["workspace_roots"],
                    {str(self.worktrees): True},
                )

    def test_every_damaged_marker_shape_is_repaired_to_a_fixed_point(self) -> None:
        begin, end = cardine_cli.CODEX_MANAGED_BEGIN, cardine_cli.CODEX_MANAGED_END
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
                plan = owner_hosts_codex.plan_codex_configuration(self.config, self.worktrees)
                self.assertEqual(plan.status, "repair-required")
                self.assertEqual(tomllib.loads(plan.proposed_text or ""), tomllib.loads(text))
                self.config.write_text(plan.proposed_text or "", encoding="utf-8")
                again = owner_hosts_codex.plan_codex_configuration(self.config, self.worktrees)
                self.assertEqual(again.status, "ready")
                self.assertFalse(owner_hosts_codex.apply_codex_configuration(again))

    def test_apply_repairs_with_exclusive_private_backup_and_preserves_unrelated_text(self) -> None:
        original = self.rewritten()
        self.config.write_text(original, encoding="utf-8")
        stale = self.config.with_name("config.toml.cardine.bak")
        stale.write_text("stale first-apply backup\n", encoding="utf-8")
        old_backup = self.config.with_name("config.toml.meridian-repair.bak")  # MERIDIAN-OLD-NAME-TEST
        old_backup.write_text("old repair backup", encoding="utf-8")

        plan = owner_hosts_codex.plan_codex_configuration(self.config, self.worktrees)
        self.assertTrue(owner_hosts_codex.apply_codex_configuration(plan))

        repaired = self.config.read_text(encoding="utf-8")
        self.assertIn("# app-managed header", repaired)
        self.assertIn("[plugins.example]", repaired)
        self.assertEqual(repaired.count(cardine_cli.CODEX_MANAGED_BEGIN), 1)
        self.assertEqual(repaired.count(cardine_cli.CODEX_MANAGED_END), 1)
        self.assertEqual(stale.read_text(encoding="utf-8"), "stale first-apply backup\n")
        backup = self.config.with_name("config.toml.cardine-repair.bak")
        self.assertEqual(backup.read_text(encoding="utf-8"), original)
        self.assertEqual(old_backup.read_text(encoding="utf-8"), "old repair backup")
        self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.config.stat().st_mode & 0o777, 0o600)
        self.assertEqual(owner_hosts_codex.plan_codex_configuration(self.config, self.worktrees).status, "ready")

        # A later app rewrite gets its own backup instead of overwriting the earlier one.
        later = repaired.replace(cardine_cli.CODEX_MANAGED_END + "\n", "")
        self.config.write_text(later, encoding="utf-8")
        self.assertTrue(owner_hosts_codex.apply_codex_configuration(owner_hosts_codex.plan_codex_configuration(self.config, self.worktrees)))
        self.assertEqual(backup.read_text(encoding="utf-8"), original)
        self.assertEqual(self.config.with_name("config.toml.cardine-repair.1.bak").read_text(encoding="utf-8"), later)

    def test_apply_refuses_when_the_file_changed_after_planning(self) -> None:
        self.config.write_text(self.rewritten(), encoding="utf-8")
        plan = owner_hosts_codex.plan_codex_configuration(self.config, self.worktrees)
        changed = self.rewritten() + "# edited after planning\n"
        self.config.write_text(changed, encoding="utf-8")
        with self.assertRaisesRegex(shared_errors.CardineError, "changed since"):
            owner_hosts_codex.apply_codex_configuration(plan)
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
                    cardine_cli.CODEX_MANAGED_BEGIN + "\n", ""
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
        with self.assertRaisesRegex(shared_errors.CardineError, "legacy"):
            owner_hosts_codex.plan_codex_configuration(self.config, self.worktrees)

    def test_stray_markers_without_a_profile_remain_blocked(self) -> None:
        for text in (
            f"{cardine_cli.CODEX_MANAGED_BEGIN}\nmodel = \"x\"\n",
            f"model = \"x\"\n{cardine_cli.CODEX_MANAGED_END}\n",
            f"{cardine_cli.CODEX_MANAGED_END}\n{cardine_cli.CODEX_MANAGED_BEGIN}\n",
        ):
            with self.subTest(text=text):
                self.assert_blocked_unchanged(text, "incomplete or damaged")

    def test_intact_markers_with_another_root_keep_the_managed_replace_path(self) -> None:
        old_root = self.root / "old-root"
        self.config.write_text(owner_hosts_codex._codex_managed_block(old_root) + "\n", encoding="utf-8")
        plan = owner_hosts_codex.plan_codex_configuration(self.config, self.worktrees)
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
        self.assertIn(f"+{cardine_cli.CODEX_MANAGED_END}", checked.stdout)
        self.assertEqual(self.config.read_text(encoding="utf-8"), text)
        self.assertFalse(list(self.root.glob("*.bak")))

        applied = self.run_cli("--apply")
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertIn("does not prove", applied.stdout)
        self.assertIn(cardine_cli.CODEX_MANAGED_END, self.config.read_text(encoding="utf-8"))
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
        workflow = (ROOT / "templates/single/PROJECT_WORKFLOW.md").read_text(encoding="utf-8")
        region = workflow.split("capability=codex-worktree-access v4 -->", 1)[1].split("<!-- MERIDIAN:END -->", 1)[0]
        for fragment in ("repair-required", "`--apply` only", "`blocked` status", "fresh session"):
            self.assertIn(fragment, region)

    def test_doctor_reports_ownership_separately_from_root_access(self) -> None:
        self.config.write_text(self.rewritten(), encoding="utf-8")
        report = owner_hosts_setup.codex_doctor(self.root, self.config, self.worktrees)
        self.assertEqual(report["permission-model"], "repair-required")
        self.assertEqual(report["profile-ownership"], "repair-required")
        self.assertEqual(report["worktree-root-write"], "ready")
        self.assertIn("git-metadata", report)

        other_root = self.root / "other-root"
        self.config.write_text(owner_hosts_codex._codex_managed_block(other_root) + "\n", encoding="utf-8")
        different = owner_hosts_setup.codex_doctor(self.root, self.config, self.worktrees)
        self.assertEqual(
            different["codex-root-mismatch"],
            f"profile={other_root} resolved={self.worktrees}",
        )

        self.config.write_text(self.rewritten(tables=self.profile_tables(extends='":read-only"')), encoding="utf-8")
        blocked = owner_hosts_setup.codex_doctor(self.root, self.config, self.worktrees)
        self.assertEqual(blocked["permission-model"], "blocked")
        self.assertEqual(blocked["profile-ownership"], "blocked")
        self.assertEqual(blocked["worktree-root-write"], "approval-required")

    def test_doctor_reports_skill_links_and_cardine_root_without_writing(self) -> None:
        before = sorted(path.relative_to(self.root) for path in self.root.rglob("*"))
        report = owner_hosts_setup.codex_doctor(
            self.root,
            self.config,
            self.worktrees,
            framework_root=ROOT,
            home=self.root,
            environment={"CARDINE_ROOT": str(ROOT)},
        )
        self.assertEqual(report["skill-links"], "missing")
        self.assertEqual(report["CARDINE_ROOT"], "ready")
        after = sorted(path.relative_to(self.root) for path in self.root.rglob("*"))
        self.assertEqual(before, after)
