# Task 040 — Plan the rename of code identifiers (work item 5a)

> **ID**: `040`
> **Category**: Architecture
> **Priority**: 🔴 P1
> **Estimate**: ~2.5h
> **Assigned to**: unassigned
> **Session**: Work items 5 to 12 planning, 2026-10-19
> **Origin**: maintenance

## Objective

Write `docs/RENAME_PLAN.md`, the plan for work item 5a of
`docs/ADR_CARDINE_1_0.md`. It renames the code identifiers from Meridian to
Cardine: the command and entry points, environment variables, the
`.cardine/` project directory, Git-internal files, and the worktree root.
Task 003 planned the module split the same way before any code moved.

Markers and template text belong to work item 5b, after work item 6. This
repository's own installation stays on the installed Meridian until work item
10. The plan must therefore separate what the product renames from what it
must leave alone.

## Acceptance Criteria

- [ ] `docs/RENAME_PLAN.md` exists, in English, and contains:
  - **Identifier classes.** One section per class, with the current and new
    name and every file that uses it, found with `git ls-files` and `git
    grep`. The classes are:
    - the `meridian` command, `bin/meridian`, `scripts/meridian.py`, and the
      `console_scripts` entry points;
    - the `MERIDIAN_*` environment variables (`MERIDIAN_BIN`,
      `MERIDIAN_ROOT`, `MERIDIAN_WORKTREE_ROOT`, `MERIDIAN_SESSION_NOT_FOUND`,
      `MERIDIAN_TEST_SHARD`, and any other);
    - the `.meridian/` project directory and its files;
    - Git-internal files such as `meridian-journal.jsonl` and the integration
      lease;
    - the worktree root `~/.meridian/worktrees` and the user configuration
      that selects it;
    - code names that carry the product name, such as `MeridianError`, test
      support modules, and test file names;
    - user-facing strings and help text that print "Meridian".
  - **Classification.** Each occurrence is in exactly one of these groups:
    1. renamed in work item 5a;
    2. renamed in work item 5b: markers, template text, skills, and slash
       commands;
    3. frozen until work item 10;
    4. historical and kept: `CHANGELOG.md`, `tasks/done/`, `tasks/handoffs/`,
       ADRs, and Meridian design documents;
    5. the read-only Meridian reader for the conversion of work item 10,
       which ADR work item 5a requires and which is not an alias.

    Group 3 is every path that `.meridian/manifest.json` lists in
    `managedFiles` or in a `managedSurface`.
  - **Frozen-surface readers.** A list of every product check in
    `scripts/check_repository.py`, every test, and every product command that
    reads a group 3 file. On 2026-10-19 these included:
    - `check_language_policy`, `check_governed_lifecycle_text`, and
      `check_managed_digests`;
    - `tests/test_queue_briefing.py`, `tests/test_read_guard.py`,
      `tests/test_codex_rules.py`, `tests/test_codex_worktree_hooks.py`, and
      `tests/test_template_manifest.py`;
    - `cardine.console.snapshot.load_snapshot`, which the coordinator runs on
      this repository.

    For each reader, the plan states its behavior after the rename. It either
    keeps reading the installed Meridian's records by their Meridian name, as
    an explicit installation check, or it stops reading this repository. No
    reader may break this repository's validation or the coordinator's
    snapshot before work item 10.
  - **Task sequence.** An ordered list of rename tasks of 2–3 hours, each
    with its scope, the files it touches, the tests that prove it, and its
    dependencies. Two tasks that touch the same file are never parallel. The
    last task adds a test that fails when a group 1 identifier returns.
- [ ] The plan does not plan work item 5b, 6, or 10, but it names any choice
  that would make them harder.
- [ ] No file changes outside `docs/RENAME_PLAN.md` and this task's records:
  the task record, its handoff, its archive under `tasks/done/`, and
  `.meridian/tasks/040.json`, which only the installed `meridian task close
  040` writes.
- [ ] Every command under Validation passes.

## Relevant Files

| File | Role |
|------|------|
| `docs/ADR_CARDINE_1_0.md` | Decisions 1 and 8, work items 5a, 5b, and 10. |
| `.meridian/manifest.json` | The frozen surfaces (read only). |
| `src/cardine/`, `scripts/`, `bin/`, `hooks/`, `tests/`, `pyproject.toml` | Code to inventory. |
| `docs/MODULE_SPLIT_PLAN.md` | Example of a plan document in this repository. |

## Technical Context

- On 2026-10-19 `git grep` outside `tasks/done/`, `tasks/handoffs/`, and
  `CHANGELOG.md` found:
  - `MERIDIAN_*` in 38 files, 152 occurrences;
  - `.meridian/` in 108 files, 354 occurrences;
  - `meridian worktree` in 56 files, 246 occurrences;
  - `meridian-journal` in 5 files, 14 occurrences.
- The frozen surfaces are `.meridian/` and the paths that
  `.meridian/manifest.json` lists:
  - the managed copies `CLAUDE.md`, `AGENTS.md`, `PROJECT_WORKFLOW.md`,
    `LANGUAGE_POLICY.md`, `docs/CONTEXT_BUDGET_POLICY.md`,
    `docs/COMPLETION_REPORT_TEMPLATE.md`, `docs/EXECUTION_EVIDENCE_PROFILE.md`,
    `.codex/hooks.json`, and `.codex/rules/meridian.rules`;
  - the shared-source hooks `hooks/hooks.json`, `hooks/queue-briefing.sh`,
    and `hooks/read-guard.sh`.
  Changing a shared-source hook fails the installed Meridian's profile doctor
  (task 035).
- Task 039 checks this repository's installation only with the installed
  `meridian` command, so the product rename does not need to keep this
  repository's `.meridian/` readable by product code for validation.

## Out of scope

Renaming anything. Work items 5b, 6, and 10.

## Dependencies

- **Depends on**: none
- **Blocks**: the work item 5a rename tasks that the plan defines

## Validation

- `python3 scripts/check_repository.py`
- `meridian profile doctor meridian-self-hosting --project .`
- `meridian audit --project . --mode lean-delivery --ci-profile meridian-self-hosting`
- `git diff --check`

This task changes documentation only. Under the validation-scoping rule of
`PROJECT_WORKFLOW.md`, it skips the test suites and records that skip in the
handoff.
