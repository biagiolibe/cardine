# Task 050 — Rename Git-internal files and the worktree root (rename plan R9)

> **ID**: `050`
> **Category**: Refactor
> **Priority**: 🔴 P1
> **Estimate**: ~2h
> **Assigned to**: unassigned
> **Session**: Work item 5a planning, 2026-10-19
> **Origin**: maintenance

## Objective

Implement row R9 of `docs/RENAME_PLAN.md`, work item 5a of
`docs/ADR_CARDINE_1_0.md`.

Rename the journal, integration lease, and worktree-state files, the worktree
root, the user configuration, the backup and temporary names, and the
distribution identifiers in code.

## Acceptance Criteria

- [ ] The scope of row R9 in `docs/RENAME_PLAN.md` is implemented as the
  plan describes it, on the files it lists. A file the plan missed but that
  the same rename needs is in scope; the handoff lists it.
- [ ] Every test under "Tests that prove it" for row R9 exists and passes.
- [ ] The product ignores `.git/meridian-journal.jsonl`,
  `.git/meridian-integration.*`, and `.git/meridian-worktrees/`; the default
  worktree root is `~/.cardine/worktrees`; `meridian/config.json` is not read;
  `load_meridian_snapshot` still reads the Meridian names.
- [ ] The `setup --check` output keys `codex-profile`, `codex-detail`, and
  `codex-root-mismatch` do not change, because the frozen hook parses them.
- [ ] A test proves that each renamed old name is ignored, not accepted as an
  alias (plan rule 1). Each such test carries the tag `MERIDIAN-OLD-NAME-TEST`
  on the line or the line above.
- [ ] No group 2, group 3, or group 4 identifier changes, except the group 4
  exceptions the plan names (`docs/PUBLIC_SURFACE.md` and
  `docs/examples/LEAN_DELIVERY_WALKTHROUGH.md`). The frozen files stay
  unchanged: `CLAUDE.md`, `AGENTS.md`, `PROJECT_WORKFLOW.md`,
  `LANGUAGE_POLICY.md`, `docs/COMPLETION_REPORT_TEMPLATE.md`,
  `docs/CONTEXT_BUDGET_POLICY.md`, `docs/EXECUTION_EVIDENCE_PROFILE.md`,
  `docs/WORKTREE_LIFECYCLE.md`, `.codex/hooks.json`,
  `.codex/rules/meridian.rules`, `hooks/hooks.json`,
  `hooks/queue-briefing.sh`, `hooks/read-guard.sh`, and the `meridian
  worktree` line of `.codex/rules/local.rules`.
- [ ] `.meridian/` is unchanged, except `.meridian/tasks/050.json`, which only
  the installed `meridian task close 050` writes. No task of this phase runs the
  checkout's `setup --apply` against the real home directory (plan choice 7).
- [ ] A test expectation that this task makes stale, such as a renamed
  path, class, or string, is updated in this task without weakening any
  other assertion. The parallel suite reports the same coverage `total`
  before and after the task, except for new tests, which the handoff lists.
- [ ] **Clean-clone validation.** After the implementation commit, run
  `python3 scripts/run_tests.py --parallel --clean-clone` from the clean task
  worktree and record its result line in the handoff.
- [ ] Every command under Validation passes.

## Relevant Files

| File | Role |
|------|------|
| `docs/RENAME_PLAN.md` | Authority: rules, groups, reader table, and row R9, with its file list. |
| `docs/ADR_CARDINE_1_0.md` | Decision 1 (no alias) and work item 5a. |
| `.meridian/manifest.json` | The frozen surfaces (read only). |

## Technical Context

- The rename tasks run strictly in sequence; no two run in parallel (plan,
  "Task sequence").
- Until work item 10 the installed Meridian runs this repository's
  lifecycle and owns the frozen files. Its validation commands keep the
  Meridian names on purpose.
- The plan lists files by their names at its baseline, commit `fcdbb0e`. A
  file that an earlier row renamed is meant under its new name, for example
  `scripts/cardine_cli.py` for `scripts/meridian.py` after row R5.
- The installed Meridian keeps writing `.git/meridian-journal.jsonl` and
  creating worktrees under `~/.meridian/worktrees` for this repository's
  lifecycle. The product rename does not touch them.

## Out of scope

Other rows of the rename plan, work items 5b, 6, and 10, and every frozen
file.

## Dependencies

- **Depends on**: 049
- **Blocks**: 051

## Validation

- `python3 scripts/check_repository.py`
- `meridian profile doctor meridian-self-hosting --project .`
- `meridian audit --project . --mode lean-delivery --ci-profile meridian-self-hosting`
- `python3 scripts/run_tests.py --parallel`
- `python3 scripts/run_tests.py --parallel --clean-clone`
- `git diff --check`
