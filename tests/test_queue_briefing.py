"""Regression tests for hooks/queue-briefing.sh (task 009 of
docs/PLAN_TOKEN_EFFICIENCY.md): the briefing must resolve a project's
declared queue location, tell a startable QUEUED row apart from one blocked
on an unmet dependency, and stay well under its 5s hook timeout even on a
large queue -- all without a session ever opening the queue file itself.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "hooks" / "queue-briefing.sh"

GOVERNED_HEADER = (
    "| Order | ID | Priority | Status | Review | Dependencies | Task file |\n"
    "|---:|---|---|---|---|---|---|\n"
)


def run_hook(cwd: Path, environment: dict[str, str] | None = None, hook: Path = HOOK) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(hook)], cwd=str(cwd), capture_output=True, text=True,
        check=False, env=environment,
    )


class QueueBriefingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.project = Path(self.temporary.name)
        (self.project / "tasks").mkdir()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_queue(self, rows: str, path: str = "tasks/QUEUE.md") -> Path:
        target = self.project / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(GOVERNED_HEADER + rows, encoding="utf-8")
        return target

    def write_language_policy(self, value: str, extra: str = "") -> Path:
        target = self.project / "LANGUAGE_POLICY.md"
        target.write_text(
            "# Language Policy\n\n"
            f"**Conversation language:** `{value}`\n"
            f"{extra}",
            encoding="utf-8",
        )
        return target

    def test_silent_exit_outside_a_meridian_project(self) -> None:
        result = run_hook(self.project)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_reports_one_line_when_codex_profile_uses_another_root(self) -> None:
        self.write_queue("| 1 | TASK-001 | P0 | QUEUED | REQUIRED | — | [TASK-001](TASK-001.md) |\n")
        home = self.project / "home"
        config = home / ".codex/config.toml"
        config.parent.mkdir(parents=True)
        other = self.project / "old-root"
        config.write_text(
            '# MERIDIAN:BEGIN worktree-permissions v1\n'
            'default_permissions = "meridian-worktrees"\n\n'
            '[permissions.meridian-worktrees]\n'
            'description = "Workspace access plus Meridian-managed task worktrees."\n'
            'extends = ":workspace"\n\n'
            '[permissions.meridian-worktrees.workspace_roots]\n'
            f'"{other}" = true\n'
            '# MERIDIAN:END worktree-permissions\n',
            encoding="utf-8",
        )
        result = run_hook(
            self.project,
            {**os.environ, "HOME": str(home), "XDG_CONFIG_HOME": str(home / ".config")},
        )
        mismatch = [line for line in result.stdout.splitlines() if "Codex worktree root differs" in line]
        self.assertEqual(len(mismatch), 1, result.stdout)
        self.assertIn(str(other), mismatch[0])
        self.assertIn(str(home / ".meridian/worktrees"), mismatch[0])

    def test_reports_combined_codex_repair_and_root_replacement_on_one_line(self) -> None:
        self.write_queue("| 1 | TASK-001 | P0 | QUEUED | REQUIRED | — | [TASK-001](TASK-001.md) |\n")
        home = self.project / "home"
        config = home / ".codex/config.toml"
        config.parent.mkdir(parents=True)
        old_root = self.project / "old-root"
        config.write_text(
            '# MERIDIAN:BEGIN worktree-permissions v1\n'
            'default_permissions = "meridian-worktrees"\n\n'
            '[permissions.meridian-worktrees]\n'
            'description = "Workspace access plus Meridian-managed task worktrees."\n'
            'extends = ":workspace"\n\n'
            '[permissions.meridian-worktrees.workspace_roots]\n'
            f'"{old_root}" = true\n',
            encoding="utf-8",
        )
        result = run_hook(
            self.project,
            {**os.environ, "HOME": str(home), "XDG_CONFIG_HOME": str(home / ".config")},
        )
        notice = [line for line in result.stdout.splitlines() if "ownership repair" in line]
        self.assertEqual(len(notice), 1, result.stdout)
        self.assertIn("meridian setup --apply", notice[0])
        self.assertNotIn("Codex worktree root differs", result.stdout)

    def test_emits_language_policy_without_a_queue(self) -> None:
        self.write_language_policy("Italian")

        result = run_hook(self.project)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[Meridian Language Policy]", result.stdout)
        self.assertIn("Conversation language: Italian", result.stdout)
        self.assertIn("Repository artifacts: English only", result.stdout)
        self.assertNotIn("Meridian Governed Queue", result.stdout)
        self.assertNotIn("Meridian Lean Delivery Queue", result.stdout)

    def test_does_not_present_a_placeholder_as_a_configured_language(self) -> None:
        self.write_language_policy("[Conversation language]")

        result = run_hook(self.project)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Conversation language is not configured.", result.stdout)
        self.assertNotIn("Conversation language: [Conversation language]", result.stdout)

    def test_warns_when_the_language_policy_is_ambiguous(self) -> None:
        self.write_language_policy(
            "Italian",
            extra="\n**Conversation language:** `English`\n",
        )

        result = run_hook(self.project)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Conversation language unavailable: policy is missing or ambiguous.", result.stdout)
        self.assertNotIn("Conversation language: Italian", result.stdout)
        self.assertNotIn("Conversation language: English", result.stdout)

    def test_resolves_active_review_ready_and_blocked_rows(self) -> None:
        self.write_language_policy("Italian")
        self.write_queue(
            "| 1 | TASK-001 | P0 | ACCEPTED | REQUIRED | — | [TASK-001](TASK-001.md) |\n"
            "| 2 | TASK-002 | P0 | IN_PROGRESS | REQUIRED | TASK-001 | [TASK-002](TASK-002.md) |\n"
            "| 3 | TASK-003 | P1 | QUEUED | REQUIRED | TASK-001 | [TASK-003](TASK-003.md) |\n"
            "| 4 | TASK-004 | P1 | QUEUED | REQUIRED | TASK-002 | [TASK-004](TASK-004.md) |\n"
            "| 5 | TASK-005 | P2 | READY_FOR_REVIEW | REQUIRED | — | [TASK-005](TASK-005.md) |\n"
            "| 6 | TASK-006 | P2 | QUEUED | NOT_REQUIRED | — | [TASK-006](TASK-006.md) |\n"
        )
        result = run_hook(self.project)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Conversation language: Italian", result.stdout)
        self.assertIn("[Meridian Governed Queue]", result.stdout)
        self.assertIn("In progress: TASK-002", result.stdout)
        self.assertIn("In review: TASK-005", result.stdout)
        # Ready: no dependency (TASK-006), or a dependency that is ACCEPTED
        # (TASK-003, on TASK-001). Blocked: a dependency still IN_PROGRESS
        # (TASK-004, on TASK-002).
        self.assertIn("Queued (startable): TASK-003, TASK-006", result.stdout)
        self.assertIn("Blocked on dependencies: TASK-004", result.stdout)
        self.assertIn("Accepted: 1", result.stdout)

    def test_answered_satisfies_a_dependency_but_not_the_accepted_tally(self) -> None:
        """task-lifecycle v2: ANSWERED satisfies a dependency the same as
        ACCEPTED; INCONCLUSIVE does not. Neither counts toward the ACCEPTED
        tally -- a SPIKE row is invisible to that count by design."""
        self.write_queue(
            "| 1 | TASK-001 | P0 | ANSWERED | REQUIRED | — | [TASK-001](TASK-001.md) |\n"
            "| 2 | TASK-002 | P0 | INCONCLUSIVE | REQUIRED | — | [TASK-002](TASK-002.md) |\n"
            "| 3 | TASK-003 | P1 | QUEUED | REQUIRED | TASK-001 | [TASK-003](TASK-003.md) |\n"
            "| 4 | TASK-004 | P1 | QUEUED | REQUIRED | TASK-002 | [TASK-004](TASK-004.md) |\n"
        )
        result = run_hook(self.project)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Queued (startable): TASK-003", result.stdout)
        self.assertIn("Blocked on dependencies: TASK-004", result.stdout)
        blocked_line = next(line for line in result.stdout.splitlines() if "Blocked on dependencies" in line)
        self.assertNotIn("TASK-003", blocked_line)
        self.assertIn("Accepted: 0", result.stdout)

    def test_a_dependency_accepted_in_the_archive_still_satisfies(self) -> None:
        """This task's own archiving convention (governed-SDD's tasks/QUEUE.md)
        moves ACCEPTED rows to tasks/QUEUE_ARCHIVE.md. A row still depending
        on one of them must read as satisfied, not blocked, just because the
        dependency is no longer in the active table."""
        self.write_queue(
            "| 2 | TASK-002 | P0 | QUEUED | REQUIRED | TASK-001 | [TASK-002](TASK-002.md) |\n"
        )
        (self.project / "tasks/QUEUE_ARCHIVE.md").write_text(
            GOVERNED_HEADER + "| 1 | TASK-001 | P0 | ACCEPTED | REQUIRED | — | [TASK-001](TASK-001.md) |\n",
            encoding="utf-8",
        )
        result = run_hook(self.project)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Queued (startable): TASK-002", result.stdout)
        self.assertNotIn("Blocked", result.stdout)
        # The accepted tally covers the archive too, the same as Lean Delivery.
        self.assertIn("Accepted: 1", result.stdout)

    def test_resolves_a_projects_declared_queue_location(self) -> None:
        """The consumer project A-shaped customization: an annotated paragraph right
        after execution-assets' MERIDIAN:END, still inside the section,
        naming a different queue path than the tasks/QUEUE.md default."""
        (self.project / "PROJECT_WORKFLOW.md").write_text(
            "# Project Workflow\n\n"
            "<!-- MERIDIAN:BEGIN capability=execution-assets v1 -->\n"
            "## Execution assets\n\n"
            "**Canonical locations.** Task files live at `tasks/<TASK-ID>.md`, "
            "the queue at `tasks/QUEUE.md`, and durable review records at "
            "`tasks/reviews/<TASK-ID>.md`, unless this section declares "
            "different locations for this project.\n"
            "<!-- MERIDIAN:END -->\n\n"
            "This project declares its real locations: `docs/TASK_QUEUE.md` "
            "for the queue and `docs/tasks/reviews/<TASK-ID>.md` for review "
            "records.\n\n"
            "## Roles\n",
            encoding="utf-8",
        )
        self.write_queue(
            "| 1 | TASK-001 | P0 | QUEUED | REQUIRED | — | [TASK-001](TASK-001.md) |\n",
            path="docs/TASK_QUEUE.md",
        )
        result = run_hook(self.project)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Queued (startable): TASK-001", result.stdout)

    def test_accepts_a_governed_queue_without_optional_review_column(self) -> None:
        """consumer project A's established queue omits `Review`; lifecycle parsing
        must use the required named columns rather than fall back to Lean."""
        queue = self.project / "docs/TASK_QUEUE.md"
        queue.parent.mkdir(parents=True, exist_ok=True)
        queue.write_text(
            "| Order | ID | Priority | Status | Dependencies | Estimate |\n"
            "|---:|---|---|---|---|---:|\n"
            "| 1 | TASK-001 | P0 | IN_PROGRESS | — | 10m |\n",
            encoding="utf-8",
        )
        (self.project / "PROJECT_WORKFLOW.md").write_text(
            "<!-- MERIDIAN:BEGIN capability=execution-assets v1 -->\n"
            "<!-- MERIDIAN:END -->\n"
            "The queue is `docs/TASK_QUEUE.md`.\n\n## Roles\n",
            encoding="utf-8",
        )
        result = run_hook(self.project)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[Meridian Governed Queue]", result.stdout)
        self.assertIn("In progress: TASK-001", result.stdout)

    def test_ambiguous_declared_zone_falls_back_to_the_default_silently(self) -> None:
        """The zone also documents archiving to a *QUEUE*ARCHIVE*.md-shaped
        file (task 009's own recommendation) -- indistinguishable from a
        real declaration by a bare `*queue*.md` regex. Resolving to the
        wrong file with no error is worse than resolving to the default, so
        this must fall back rather than guess."""
        (self.project / "PROJECT_WORKFLOW.md").write_text(
            "# Project Workflow\n\n"
            "<!-- MERIDIAN:BEGIN capability=execution-assets v1 -->\n"
            "## Execution assets\n\n"
            "**Canonical locations.** Task files live at `tasks/<TASK-ID>.md`, "
            "the queue at `tasks/QUEUE.md`, and durable review records at "
            "`tasks/reviews/<TASK-ID>.md`, unless this section declares "
            "different locations for this project.\n"
            "<!-- MERIDIAN:END -->\n\n"
            "Archive terminal rows to `docs/TASK_QUEUE_ARCHIVE.md` once a phase closes.\n\n"
            "## Roles\n",
            encoding="utf-8",
        )
        self.write_queue(
            "| 1 | TASK-001 | P0 | QUEUED | REQUIRED | — | [TASK-001](TASK-001.md) |\n"
        )
        result = run_hook(self.project)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Queued (startable): TASK-001", result.stdout)

    def test_lean_delivery_checkbox_format_is_unaffected(self) -> None:
        (self.project / "tasks/QUEUE.md").write_text(
            "# Task Execution Queue\n\n"
            "| Status | ID | Title | File |\n"
            "|--------|----|-------|------|\n"
            "| `[x]` | 001 | Done thing | [001](done/001.md) |\n"
            "| `[/]` | 002 | Active thing | [002](002.md) |\n"
            "| `[ ]` | 003 | Next thing | [003](003.md) |\n",
            encoding="utf-8",
        )
        result = run_hook(self.project)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[Meridian Lean Delivery Queue]", result.stdout)
        self.assertIn("In progress: Active thing", result.stdout)
        self.assertIn("Queued: 003 - Next thing", result.stdout)
        self.assertIn("Completed: 1", result.stdout)

    def test_governed_states_come_from_registered_worktrees_not_queue_rows(self) -> None:
        self.write_queue(
            "| 1 | TASK-001 | P0 | QUEUED | REQUIRED | — | [TASK-001](TASK-001.md) |\n"
            "| 2 | TASK-002 | P0 | QUEUED | REQUIRED | — | [TASK-002](TASK-002.md) |\n"
        )
        hook_root = self.project / "hook-root"
        hook = hook_root / "hooks/queue-briefing.sh"
        hook.parent.mkdir(parents=True)
        hook.write_text(HOOK.read_text(encoding="utf-8"), encoding="utf-8")
        runner = hook_root / "bin/meridian"
        runner.parent.mkdir()
        runner.write_text(
            "#!/bin/sh\n"
            "case \"$1 $2\" in\n"
            "  locations*) echo tasks/QUEUE.md ;;\n"
            "  worktree\\ states) echo '[{\"task_id\":\"TASK-001\",\"status\":\"IN_PROGRESS\"},{\"task_id\":\"TASK-002\",\"status\":\"READY_FOR_REVIEW\"}]' ;;\n"
            "  budget\\ show) echo 'Attempt 2 · Diagnostics 1/3' ;;\n"
            "esac\n",
            encoding="utf-8",
        )
        runner.chmod(0o755)
        result = run_hook(self.project, hook=hook)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("In progress: TASK-001", result.stdout)
        self.assertIn("In review: TASK-002", result.stdout)
        self.assertIn("Attempt 2 · Diagnostics 1/3", result.stdout)

    def test_times_out_only_the_optional_worktree_state_lookup(self) -> None:
        self.write_language_policy("Italian")
        self.write_queue("| 1 | TASK-001 | P0 | QUEUED | REQUIRED | — | [TASK-001](TASK-001.md) |\n")
        hook_root = self.project / "hook-root"
        hook = hook_root / "hooks/queue-briefing.sh"
        hook.parent.mkdir(parents=True)
        hook.write_text(HOOK.read_text(encoding="utf-8"), encoding="utf-8")
        runner = hook_root / "bin/meridian"
        runner.parent.mkdir()
        runner.write_text(
            "#!/bin/sh\n"
            "case \"$1 $2\" in\n"
            "  locations*) echo tasks/QUEUE.md ;;\n"
            "  worktree\\ states) sleep 3; echo '[]' ;;\n"
            "esac\n",
            encoding="utf-8",
        )
        runner.chmod(0o755)

        result = run_hook(self.project, hook=hook)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("In-progress lookup skipped", result.stdout)
        self.assertLess(result.stdout.index("[Meridian Language Policy]"), result.stdout.index("In-progress lookup skipped"))

    def test_lean_registered_active_task_does_not_require_a_checkbox_edit(self) -> None:
        (self.project / "tasks/QUEUE.md").write_text(
            "| Status | ID | Title | File |\n|--------|----|-------|------|\n"
            "| `[ ]` | 002 | Active thing | [002](002.md) |\n",
            encoding="utf-8",
        )
        hook_root = self.project / "hook-root"
        hook = hook_root / "hooks/queue-briefing.sh"
        hook.parent.mkdir(parents=True)
        hook.write_text(HOOK.read_text(encoding="utf-8"), encoding="utf-8")
        runner = hook_root / "bin/meridian"
        runner.parent.mkdir()
        runner.write_text(
            "#!/bin/sh\n"
            "case \"$1 $2\" in\n"
            "  locations*) echo tasks/QUEUE.md ;;\n"
            "  worktree\\ active) echo '{\"task_id\":\"002\"}' ;;\n"
            "esac\n",
            encoding="utf-8",
        )
        runner.chmod(0o755)
        result = run_hook(self.project, hook=hook)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("In progress: Active thing", result.stdout)

    def test_reports_a_300_row_queue(self) -> None:
        rows = []
        for i in range(1, 301):
            task_id = f"TASK-{i:03d}"
            status = "IN_PROGRESS" if i == 100 else ("ACCEPTED" if i % 7 == 0 else "QUEUED")
            dep = "—" if i == 1 else f"TASK-{i - 1:03d}"
            rows.append(f"| {i} | {task_id} | P1 | {status} | REQUIRED | {dep} | [{task_id}]({task_id}.md) |")
        self.write_queue("\n".join(rows) + "\n")

        result = run_hook(self.project)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[Meridian Governed Queue]", result.stdout)
        self.assertIn("In progress: TASK-100", result.stdout)


if __name__ == "__main__":
    unittest.main()
