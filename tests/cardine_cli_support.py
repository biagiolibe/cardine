"""Fixture-only support for the framework CLI responsibility tests."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import cardine_cli  # noqa: E402
from cardine.templates import markers as templates_markers
import cardine.shared.constants as shared_constants
from cardine.templates import router as owner_templates_router

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "cardine_cli.py"


from project_config_support import write_project_config


class CardineCliFixtureMixin:
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.framework = root / "framework"
        self.project = root / "project"
        shutil.copytree(ROOT / "templates", self.framework / "templates")
        shutil.copytree(ROOT / "migrations", self.framework / "migrations")
        shutil.copytree(ROOT / "capabilities", self.framework / "capabilities")
        (self.framework / "VERSION").write_text("1.1.0\n", encoding="utf-8")
        self.project.mkdir()
        self.copy_governed_templates()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def copy_governed_templates(self) -> None:
        write_project_config(self.project, "governed")
        source = self.framework / "templates" / "single"
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

    def write_synthetic_migration(
        self, identifier: str, source: str, target: str, paths: list[str] | None = None, **declared: object
    ) -> None:
        record = {
            "id": identifier, "from": source, "to": target, "description": "Synthetic " + identifier,
            "managedPaths": paths or [], "verification": ["fixture assertions"], **declared,
        }
        (self.framework / "migrations" / f"{identifier}.json").write_text(json.dumps(record), encoding="utf-8")

    def configure_1_1_40_to_1_1_41_upgrade(self) -> None:
        """Lock the entry points immediately before migration 044."""
        workflow = self.framework / "templates/single"
        for name in ("AGENTS.md", "CLAUDE.md"):
            current = workflow / name
            old_text = current.read_text(encoding="utf-8").replace(
                "CARDINE:BEGIN capability=command-triggers v1",
                "CARDINE:BEGIN capability=command-triggers v2",
            ).replace(
                "- `Restart rejected <TASK-ID>` — read `docs/LIFECYCLE_ORCHESTRATION.md`.\n",
                "",
            )
            current.write_text(old_text, encoding="utf-8")
            (self.project / name).write_text(old_text, encoding="utf-8")
        (self.framework / "VERSION").write_text("1.1.40\n", encoding="utf-8")
        self.write_synthetic_migration("001-synthetic-before-restart", "1.1.39", "1.1.40")
        self.assertEqual(self.run_cli("lock", "--mode", "single").returncode, 0)
        for name in ("AGENTS.md", "CLAUDE.md"):
            source = ROOT / "templates/single" / name
            (workflow / name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        (self.framework / "VERSION").write_text("1.1.41\n", encoding="utf-8")
        self.write_synthetic_migration(
            "002-synthetic-restart", "1.1.40", "1.1.41", ["AGENTS.md", "CLAUDE.md"],
            capabilities=[{"capability": "command-triggers", "capabilityVersion": 1}],
        )

    def configure_1_1_53_to_1_1_54_manual_proceed_upgrade(self) -> tuple[Path, Path]:
        """Lock the implementation and workflow-lock blocks in their legacy form, immediately before 056."""
        workflow = self.framework / "templates/single"
        implementation = workflow / "docs/workflows/IMPLEMENTATION.md"
        project_workflow = workflow / "PROJECT_WORKFLOW.md"
        current_implementation = implementation.read_text(encoding="utf-8")
        current_workflow = project_workflow.read_text(encoding="utf-8")
        legacy_implementation = "\n".join((
            "<!-- CARDINE:BEGIN capability=task-worktree-boundary v4 -->",
            "The coordinator runs `meridian worktree prepare` before starting this worker",
            "and passes its returned branch, absolute worktree path, primary checkout, and",
            "worktree root as launch inputs. Start in that exact existing directory; do not",
            "use host automatic isolation or create another checkout. Before reading the",
            "task, implementation files, or diff, run `meridian worktree check <TASK-ID>",
            "--project <primary-checkout> --format json`. Any blocked",
            "result stops all task work and preserves both checkouts. Run every later read,",
            "implementation, validation, status, and handoff operation in the same verified",
            "worktree, never the primary checkout.",
            "<!-- CARDINE:END -->",
            "",
        ))
        legacy_workflow = "\n".join((
            "<!-- CARDINE:BEGIN capability=workflow-mode-lock v2 -->",
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
            "<!-- CARDINE:END -->",
            "",
        ))
        previous_implementation = re.sub(
            r"<!-- CARDINE:BEGIN capability=task-worktree-boundary v\d+ -->.*?<!-- CARDINE:END -->\n",
            legacy_implementation,
            current_implementation,
            count=1,
            flags=re.DOTALL,
        )
        previous_workflow = re.sub(
            r"<!-- CARDINE:BEGIN capability=workflow-mode-lock v\d+ -->.*?<!-- CARDINE:END -->\n",
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
        locked = self.run_cli("lock", "--mode", "single")
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
            f"- {lifecycle_triggers}: `docs/LIFECYCLE_ORCHESTRATION.md`.\n"
            "- Explicit audit: `docs/AUDIT_PROMPT_READ_ONLY.md`.\n"
        )
        router_path = self.project / shared_constants.ENTRY_ROUTER_PATH
        router_path.parent.mkdir(parents=True, exist_ok=True)
        router_path.write_text(router, encoding="utf-8")
        (self.project / shared_constants.ENTRY_ROUTER_MAP_PATH).write_text(
            json.dumps(shared_constants.ENTRY_ROUTER_ROUTES, indent=2) + "\n", encoding="utf-8"
        )
        for route, relative in shared_constants.ENTRY_ROUTER_ROUTES.items():
            target = self.project / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            text = target.read_text(encoding="utf-8") if target.is_file() else "# Routed procedure\n"
            missing = [
                token
                for token in shared_constants.ENTRY_ROUTER_SAFEGUARDS[route]
                if token not in text.lower()
            ]
            if missing:
                target.write_text(text.rstrip() + "\n\n" + " ".join(missing) + "\n", encoding="utf-8")
        for target, output in owner_templates_router.entry_router_outputs(self.project).items():
            (self.project / target).write_text(output, encoding="utf-8")

    def reset_project_to_installed_baseline(self) -> None:
        """Overwrite every managed project file with the exact content
        `.cardine/baselines/<installed version>` recorded at `lock` time,
        simulating a vanilla consumer that never diverged from its installed
        release — the premise `--stop-before-retirement`'s content-cap tests
        need, since `setUp()` otherwise leaves the real repository's own
        current AGENTS.md/CLAUDE.md in the project directory."""
        manifest = json.loads((self.project / ".cardine/manifest.json").read_text(encoding="utf-8"))
        baseline_root = self.project / ".cardine/baselines" / str(
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
        manifest = json.loads((self.project / ".cardine/manifest.json").read_text(encoding="utf-8"))
        baseline_root = self.project / ".cardine/baselines" / str(
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
        workflow = self.framework / "templates/single"
        agents = workflow / "AGENTS.md"
        claude = workflow / "CLAUDE.md"
        router_v1 = (
            "<!-- CARDINE:BEGIN capability=entry-router v1 -->\n"
            "Read the entry-point procedures.\n<!-- CARDINE:END -->\n"
        )
        router_v2 = (
            "<!-- CARDINE:BEGIN capability=entry-router v2 -->\n"
            "Read the managed procedures.\n<!-- CARDINE:END -->\n"
        )
        moved = (
            "<!-- CARDINE:BEGIN capability=route-rule v1 -->\n"
            "Run the managed route rule.\n<!-- CARDINE:END -->"
        )
        agents.write_text("# Agent entry point\n\n" + router_v1, encoding="utf-8")
        claude.write_text("# Claude entry point\n\n" + router_v1, encoding="utf-8")
        target = workflow / "docs/workflows/IMPLEMENTATION.md"
        target.unlink()
        (self.project / "docs/workflows/IMPLEMENTATION.md").unlink()
        for path in (self.framework / "migrations").glob("*.json"):
            path.unlink()
        (self.framework / "VERSION").write_text("1.1.0\n", encoding="utf-8")
        self.assertEqual(self.run_cli("lock", "--mode", "single").returncode, 0)

        agents.write_text("# Agent entry point\n\n" + router_v2, encoding="utf-8")
        claude.write_text("# Compact Claude router\n", encoding="utf-8")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# Implementation\n\n" + moved + "\n", encoding="utf-8")
        digest = templates_markers.marker_block_sha256(moved)

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
        locked = self.run_cli("lock", "--mode", "single")
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
        workflow = self.framework / "templates/single/PROJECT_WORKFLOW.md"
        workflow.write_text(
            workflow.read_text(encoding="utf-8") + "\nVersion split marker.\n",
            encoding="utf-8",
        )
        (self.framework / "VERSION").write_text("1.1.1\n", encoding="utf-8")

    REASONING_CONTRACT_BLOCK = (
        "<!-- CARDINE:BEGIN capability=reasoning-budget-contract v1 -->\n"
        "## Reasoning budget contract\n\n"
        "Select the lowest reliable reasoning effort while designing the task.\n"
        "<!-- CARDINE:END -->\n\n"
    )

    def _lock_project_with_reasoning_contract(self) -> tuple[Path, Path]:
        """Lock a governed project from templates that still carry the retired
        block and the superseded `execution-evidence-profile` v1 marker."""
        policy = self.framework / "templates/single/docs/CONTEXT_READING_POLICY.md"
        current = (ROOT / "templates/single/docs/CONTEXT_READING_POLICY.md").read_text(
            encoding="utf-8"
        )
        previous = current.replace(
            "\n## Context-size ceilings", "\n" + self.REASONING_CONTRACT_BLOCK + "## Context-size ceilings", 1
        ).replace("capability=bounded-context-readers v2", "capability=bounded-context-readers v1", 1)
        self.assertIn("reasoning-budget-contract", previous)
        policy.write_text(previous, encoding="utf-8")
        (self.framework / "VERSION").write_text("1.2.8\n", encoding="utf-8")
        self.write_synthetic_migration("001-synthetic-before-retirement", "1.2.7", "1.2.8")
        shutil.rmtree(self.project)
        self.project.mkdir()
        self.copy_governed_templates()
        self.assertEqual(self.run_cli("lock", "--mode", "single").returncode, 0)
        policy.write_text(
            current,
            encoding="utf-8",
        )
        (self.framework / "VERSION").write_text("1.2.9\n", encoding="utf-8")
        self.write_synthetic_migration(
            "002-synthetic-retire-contract", "1.2.8", "1.2.9", ["docs/CONTEXT_READING_POLICY.md"],
            capabilities=[{"capability": "bounded-context-readers", "capabilityVersion": 2}],
            removes=[{"capability": "reasoning-budget-contract", "capabilityVersion": 1}],
        )
        return policy, self.project / "docs/CONTEXT_READING_POLICY.md"
