# Task 048 — Rename the environment names and options (rename plan R7)

> **ID**: `048`
> **Category**: Refactor
> **Priority**: 🔴 P1
> **Estimate**: ~2h
> **Assigned to**: unassigned
> **Session**: Work item 5a planning, 2026-10-19
> **Origin**: maintenance

## Objective

Implement row R7 of `docs/RENAME_PLAN.md`, work item 5a of
`docs/ADR_CARDINE_1_0.md`.

Rename the `MERIDIAN_*` environment names and the `--meridian-root` and
`--meridian` options.

## Acceptance Criteria

- [ ] The scope of row R7 in `docs/RENAME_PLAN.md` is implemented as the
  plan describes it, on the files it lists. A file the plan missed but that
  the same rename needs is in scope; the handoff lists it.
- [ ] Every test under "Tests that prove it" for row R7 exists and passes.
- [ ] With only `MERIDIAN_WORKTREE_ROOT` set, the worktree root falls back to the
  default; with only `MERIDIAN_ROOT` set, `setup --check` reports the root as
  not set; the test shards receive `CARDINE_TEST_SHARD` and no `MERIDIAN_*`
  name.
- [ ] The frozen hooks `hooks/queue-briefing.sh` and `hooks/read-guard.sh` keep
  `MERIDIAN_BIN`.
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
- [ ] `.meridian/` is unchanged, except `.meridian/tasks/048.json`, which only
  the installed `meridian task close 048` writes. No task of this phase runs the
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
| `docs/RENAME_PLAN.md` | Authority: rules, groups, reader table, and row R7, with its file list. |
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

## Out of scope

Other rows of the rename plan, work items 5b, 6, and 10, and every frozen
file.

## Dependencies

- **Depends on**: 047
- **Blocks**: 049

## Validation

- `python3 scripts/check_repository.py`
- `meridian profile doctor meridian-self-hosting --project .`
- `meridian audit --project . --mode lean-delivery --ci-profile meridian-self-hosting`
- `python3 scripts/run_tests.py --parallel`
- `python3 scripts/run_tests.py --parallel --clean-clone`
- `git diff --check`
