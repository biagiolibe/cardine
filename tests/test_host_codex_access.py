"""Framework CLI regression tests for host codex access."""

from __future__ import annotations

from cardine_cli_support import CLI, ROOT
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock
import cardine.shared.errors as shared_errors
from cardine.tasks import identity as owner_tasks_identity
from cardine.hosts import codex as owner_hosts_codex
from cardine.worktree import paths as owner_worktree_paths
import cardine_cli


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
        first_path = owner_worktree_paths.task_worktree_path(first, worktrees, "TASK-054")
        second_path = owner_worktree_paths.task_worktree_path(second, worktrees, "task-054")
        self.assertEqual(first_path.relative_to(worktrees).parts, ("github.com", "acme", "one", "task-054"))
        self.assertEqual(second_path.relative_to(worktrees).parts, ("gitlab.example", "acme", "two", "task-054"))
        self.assertNotEqual(first_path, second_path)

    def test_local_identity_contains_name_and_common_directory_hash(self) -> None:
        project = self.repository("local-project")
        identity = owner_worktree_paths.repository_identity(project)
        self.assertEqual((identity.remote_host, identity.owner), ("local", "repositories"))
        self.assertRegex(identity.repository, r"^local-project-[0-9a-f]{12}$")
        self.assertEqual(identity, owner_worktree_paths.repository_identity(project))

    def test_unsafe_identity_task_and_root_are_rejected(self) -> None:
        project = self.repository("safe", "git@example.com:../repo.git")
        with self.assertRaises(shared_errors.CardineError):
            owner_worktree_paths.repository_identity(project)
        with self.assertRaises(shared_errors.CardineError):
            owner_tasks_identity.canonical_task_id("../054")
        with self.assertRaises(shared_errors.CardineError):
            owner_worktree_paths.task_worktree_path(self.repository("other"), Path.home(), "054")

    def test_existing_path_for_another_repository_is_a_collision(self) -> None:
        first = self.repository("one", "git@github.com:acme/shared.git")
        second = self.repository("two", "git@github.com:acme/shared.git")
        path = self.root / "existing"
        subprocess.run(["git", "-C", str(first), "worktree", "add", "-b", "task-054", str(path), "main"], check=True, capture_output=True)
        with self.assertRaisesRegex(shared_errors.CardineError, "collision"):
            owner_worktree_paths.validate_worktree_collision(second, path, "054")

    def test_namespaced_symlink_escape_is_rejected(self) -> None:
        project = self.repository("safe", "git@github.com:acme/repo.git")
        worktrees = self.root / "worktrees"
        worktrees.mkdir()
        outside = self.root / "outside"
        outside.mkdir()
        (worktrees / "github.com").symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(shared_errors.CardineError, "symlink"):
            owner_worktree_paths.task_worktree_path(project, worktrees, "054")

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
        plan = owner_hosts_codex.plan_codex_configuration(config, root)
        self.assertEqual(plan.status, "approval-required")
        self.assertTrue(owner_hosts_codex.apply_codex_configuration(plan))
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
        self.assertLess(changed.index('model = "gpt-test"'), changed.index(cardine_cli.CODEX_MANAGED_BEGIN))
        self.assertLess(changed.index(cardine_cli.CODEX_MANAGED_END), changed.index("[features]"))
        self.assertEqual(config.with_name("config.toml.meridian.bak").read_text(encoding="utf-8"), original)
        second = owner_hosts_codex.plan_codex_configuration(config, root)
        self.assertEqual(second.status, "ready")
        self.assertFalse(owner_hosts_codex.apply_codex_configuration(second))

    def test_config_plan_repairs_managed_block_inserted_before_root_keys(self) -> None:
        config = self.root / "config.toml"
        root = (self.root / "worktrees").resolve()
        broken = (
            owner_hosts_codex._codex_managed_block(root)
            + '\n\nnotify = ["/usr/bin/example", "turn-ended"]\n'
            + 'model = "gpt-test"\n\n'
            + '[features]\nnetwork_proxy = false\n'
        )
        config.write_text(broken, encoding="utf-8")

        plan = owner_hosts_codex.plan_codex_configuration(config, root)

        self.assertEqual(plan.status, "approval-required")
        repaired = plan.proposed_text or ""
        parsed = tomllib.loads(repaired)
        self.assertEqual(parsed["notify"], ["/usr/bin/example", "turn-ended"])
        self.assertEqual(parsed["model"], "gpt-test")
        self.assertEqual(
            parsed["permissions"]["meridian-worktrees"]["workspace_roots"],
            {str(root): True},
        )
        self.assertLess(repaired.index('model = "gpt-test"'), repaired.index(cardine_cli.CODEX_MANAGED_BEGIN))

    def test_atomic_replace_failure_keeps_original(self) -> None:
        config = self.root / "config.toml"
        original = 'model = "gpt-test"\n'
        config.write_text(original, encoding="utf-8")
        plan = owner_hosts_codex.plan_codex_configuration(config, self.root / "worktrees")
        with mock.patch.object(cardine_cli.os, "replace", side_effect=OSError("simulated")):
            with self.assertRaises(OSError):
                owner_hosts_codex.apply_codex_configuration(plan)
        self.assertEqual(config.read_text(encoding="utf-8"), original)

    def test_conflicting_and_malformed_configuration_is_blocked(self) -> None:
        config = self.root / "config.toml"
        config.write_text('sandbox_mode = "workspace-write"\n', encoding="utf-8")
        with self.assertRaisesRegex(shared_errors.CardineError, "legacy"):
            owner_hosts_codex.plan_codex_configuration(config, self.root / "worktrees")
        config.write_text("broken = [\n", encoding="utf-8")
        with self.assertRaisesRegex(shared_errors.CardineError, "malformed"):
            owner_hosts_codex.plan_codex_configuration(config, self.root / "worktrees")

    def test_managed_requirements_must_allow_the_profile(self) -> None:
        config = self.root / "config.toml"
        requirements = self.root / "requirements.toml"
        requirements.write_text('[allowed_permission_profiles]\nother = true\n', encoding="utf-8")
        with self.assertRaisesRegex(shared_errors.CardineError, "managed"):
            owner_hosts_codex.plan_codex_configuration(config, self.root / "worktrees", requirements)
        requirements.write_text('[allowed_permission_profiles]\nmeridian-worktrees = true\n', encoding="utf-8")
        self.assertEqual(
            owner_hosts_codex.plan_codex_configuration(config, self.root / "worktrees", requirements).status,
            "approval-required",
        )

    def test_existing_permission_profile_selection_is_replaced_without_losing_profiles(self) -> None:
        config = self.root / "config.toml"
        config.write_text(
            'default_permissions = ":workspace"\n\n[permissions.other]\nextends = ":read-only"\n',
            encoding="utf-8",
        )
        plan = owner_hosts_codex.plan_codex_configuration(config, self.root / "worktrees")
        self.assertIsNotNone(plan.proposed_text)
        parsed = tomllib.loads(plan.proposed_text or "")
        self.assertEqual(parsed["default_permissions"], "meridian-worktrees")
        self.assertEqual(parsed["permissions"]["other"]["extends"], ":read-only")

    def test_initializer_only_offers_explicit_check_and_apply(self) -> None:
        instructions = (ROOT / "commands/meridian-init.md").read_text(encoding="utf-8")
        self.assertIn("meridian setup --check", instructions)
        self.assertIn("meridian setup --apply` only after explicit confirmation", instructions)
        self.assertIn("not invalidate initialization", instructions)
