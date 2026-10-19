"""Framework CLI regression tests for task identity project."""

from __future__ import annotations

from meridian_cli_support import CLI, ROOT
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from cardine.shared import project as owner_shared_project
import cardine.shared.constants as shared_constants
import cardine.shared.errors as shared_errors
from cardine.tasks import identity as owner_tasks_identity
from cardine.shared import budget_commands as owner_shared_budget_commands
from cardine.hosts import setup as owner_hosts_setup


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
        absent = owner_tasks_identity.resolve_task_identity(self.project, "023", "existing")
        self.declare("opaque")
        explicit = owner_tasks_identity.resolve_task_identity(self.project, "task-023", "existing")
        self.assertEqual(absent, explicit)
        self.assertEqual(explicit.kind, "opaque")
        self.assertEqual(explicit.canonical_id, "TASK-023")
        self.assertEqual(explicit.branch_name, "task-023")
        self.assertEqual(explicit.task_path, task.resolve())

    def test_milestone_normalizes_command_input_and_derives_every_surface(self) -> None:
        self.declare()
        task = self.add_task("M30-INSPECT_UI-001")
        self.write_queue([("M30-INSPECT_UI-001", "M30-INSPECT_UI-001.md")])
        resolved = owner_tasks_identity.resolve_task_identity(self.project, "m30-inspect_ui-001", "existing")
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
        legacy = owner_tasks_identity.resolve_task_identity(self.project, "LEGACY-7", "existing")
        self.assertEqual(legacy.kind, "legacy-opaque")
        with self.assertRaisesRegex(shared_errors.MeridianError, "unknown"):
            owner_tasks_identity.resolve_task_identity(self.project, "OTHER-7", "existing")
        with self.assertRaisesRegex(shared_errors.MeridianError, "must use"):
            owner_tasks_identity.resolve_task_identity(self.project, "OTHER-7", "new")
        created = owner_tasks_identity.resolve_task_identity(self.project, "m31-build-999", "new")
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
        resolved = owner_tasks_identity.resolve_task_identity(self.project, "M8-API-011", "existing")
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
                with self.assertRaises(shared_errors.MeridianError):
                    owner_tasks_identity.resolve_task_identity(self.project, "TASK-001", "new")

    def test_ambiguity_collisions_mixed_case_and_traversal_are_rejected(self) -> None:
        self.declare()
        self.add_task("M2-API-001")
        self.add_task("M2-Api-002")
        self.write_queue([("M2-API-001", "M2-API-001.md"), ("M2-Api-002", "M2-Api-002.md")])
        with self.assertRaisesRegex(shared_errors.MeridianError, "canonical uppercase"):
            owner_tasks_identity.resolve_task_identity(self.project, "M2-Api-002", "existing")
        with self.assertRaises(shared_errors.MeridianError):
            owner_tasks_identity.resolve_task_identity(self.project, "../M2-API-001", "existing")

        self.declare("opaque")
        self.add_task("TASK-007")
        self.add_task("007")
        self.write_queue([("TASK-007", "TASK-007.md"), ("007", "007.md")])
        with self.assertRaisesRegex(shared_errors.MeridianError, "collision"):
            owner_tasks_identity.resolve_task_identity(self.project, "TASK-007", "existing")

    def test_mismatched_duplicate_and_unsafe_authorities_are_rejected(self) -> None:
        self.declare()
        self.add_task("M4-API-001")
        self.add_task("M4-API-002")
        self.write_queue([("M4-API-001", "M4-API-002.md")])
        with self.assertRaisesRegex(shared_errors.MeridianError, "disagree"):
            owner_tasks_identity.resolve_task_identity(self.project, "M4-API-001", "existing")

        duplicate = self.project / "tasks/nested/M4-API-001.md"
        duplicate.parent.mkdir()
        duplicate.write_text("ID: M4-API-001\n", encoding="utf-8")
        with self.assertRaisesRegex(shared_errors.MeridianError, "ambiguous"):
            owner_tasks_identity.resolve_task_identity(self.project, "M4-API-001", "existing")

        self.declare("opaque")
        with self.assertRaises(shared_errors.MeridianError):
            owner_tasks_identity.resolve_task_identity(self.project, "foo..bar", "new")

    def test_structured_grammar_rejects_noncanonical_new_ids(self) -> None:
        self.declare()
        invalid = (
            "M0-API-001", "M01-API-001", "M1--001", "M1-_API-001",
            "M1-API_-001", "M1-API-000", "M1-API-1000", "M1-API-01",
        )
        for task_id in invalid:
            with self.subTest(task_id=task_id), self.assertRaises(shared_errors.MeridianError):
                owner_tasks_identity.resolve_task_identity(self.project, task_id, "new")

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
        direct = owner_tasks_identity.resolve_task_identity(self.project, "m9-cli-003", "existing")
        self.assertEqual(payload, owner_tasks_identity.task_identity_json(self.project, direct))
        runtime_state: dict[str, object] = {}
        runtime_key, _text = owner_shared_budget_commands.resolve_budget_key(self.project, runtime_state, "m9-cli-003")
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
        key, _text = owner_shared_budget_commands.resolve_budget_key(self.project, runtime_state, "009")
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
        self.assertEqual(payload, owner_tasks_identity.resolve_task_identity(self.project, "M9-CLI-008", "new").as_json(self.project))
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
        for mode in shared_constants.WORKFLOW_MODES:
            template = ROOT / "templates/workflows" / mode / "PROJECT_WORKFLOW.md"
            self.assertIn("capability=task-identity-policy v1", template.read_text(encoding="utf-8"))

        root = Path(self.temporary.name)
        framework = root / "framework"
        consumer = root / "consumer"
        for source in ("templates", "migrations", "capabilities"):
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
        self.assertFalse((consumer / shared_constants.TASK_IDENTITY_PATH).exists())


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
        defaults = owner_tasks_identity.resolve_project_locations(self.project)
        self.assertEqual(defaults.queue, Path("tasks/QUEUE.md"))
        self.write({"version": 1, "locations": {"queue": "docs/QUEUE.md"}})
        self.assertEqual(owner_tasks_identity.resolve_project_locations(self.project).queue, Path("docs/QUEUE.md"))
        self.write({"version": 1, "locations": {"queue": "docs/QUEUE.md", "taskRoots": ["work/tasks"], "reviewRoot": "reviews", "handoffRoot": "handoffs", "adrLog": "docs/ADR.md", "plan": "docs/PLAN.md"}})
        locations = owner_tasks_identity.resolve_project_locations(self.project)
        self.assertEqual((locations.queue, locations.task_roots, locations.plan), (Path("docs/QUEUE.md"), (Path("work/tasks"),), Path("docs/PLAN.md")))
        for declaration in ({"version": 2}, {"version": 1, "unknown": True}, {"version": 1, "locations": {"queue": "/tmp/QUEUE.md"}}, {"version": 1, "locations": {"queue": "../QUEUE.md"}}):
            self.write(declaration)
            with self.subTest(declaration=declaration), self.assertRaises(shared_errors.MeridianError):
                owner_shared_project.read_project_declaration(self.project)

    def test_declaration_overrides_legacy_and_cli_fields(self) -> None:
        (self.project / "PROJECT_WORKFLOW.md").write_text("<!-- MERIDIAN:BEGIN capability=execution-assets v2 -->\n<!-- MERIDIAN:END -->\nTask files live at `legacy/tasks/<TASK-ID>.md`; queue is `legacy/QUEUE.md`.\n", encoding="utf-8")
        self.write({"version": 1, "project": {"name": "Example", "slug": "example"}, "locations": {"queue": "docs/QUEUE.md"}})
        result = subprocess.run([sys.executable, str(CLI), "locations", "--field", "queue", "--project", str(self.project)], text=True, capture_output=True, check=False)
        self.assertEqual((result.returncode, result.stdout.strip(), result.stderr), (0, "docs/QUEUE.md", ""))
        author = subprocess.run([sys.executable, str(CLI), "project", "show", "--field", "reviewer-author", "--project", str(self.project)], text=True, capture_output=True, check=False)
        self.assertEqual(author.stdout.strip(), "Example Reviewer-Integrator <reviewer-integrator@example.local>")
        self.assertEqual(owner_tasks_identity.resolve_project_locations(self.project).queue.with_name("QUEUE_ARCHIVE.md"), Path("docs/QUEUE_ARCHIVE.md"))

    def test_declaration_overrides_an_invalid_legacy_location(self) -> None:
        (self.project / "PROJECT_WORKFLOW.md").write_text(
            "<!-- MERIDIAN:BEGIN capability=execution-assets v2 -->\n<!-- MERIDIAN:END -->\n"
            "queue is `/tmp/QUEUE.md`.\n",
            encoding="utf-8",
        )
        self.write({"version": 1, "locations": {"queue": "docs/QUEUE.md"}})
        self.assertEqual(owner_tasks_identity.resolve_project_locations(self.project).queue, Path("docs/QUEUE.md"))

    def test_legacy_location_warning_is_emitted_once_per_process(self) -> None:
        (self.project / "PROJECT_WORKFLOW.md").write_text(
            "<!-- MERIDIAN:BEGIN capability=execution-assets v2 -->\n<!-- MERIDIAN:END -->\n"
            "Task files live at `legacy/tasks/<TASK-ID>.md`; queue is `legacy/QUEUE.md`.\n",
            encoding="utf-8",
        )
        output = io.StringIO()
        with redirect_stderr(output):
            owner_tasks_identity.resolve_project_locations(self.project)
            owner_tasks_identity.resolve_project_locations(self.project)
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
        plan = owner_hosts_setup.plan_setup(None, self.project / "config.toml", home=self.project, framework_root=ROOT, project_root=self.project)
        self.assertEqual(plan.project_declaration_state, "advisory-incomplete")
        self.assertEqual(plan.project_declaration_proposal["project"]["slug"], "project")
