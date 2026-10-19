# Task 049 — Rename the project directory and the profile id (rename plan R8)

> **ID**: `049`
> **Category**: Refactor
> **Priority**: 🔴 P1
> **Estimate**: ~3h
> **Assigned to**: unassigned
> **Session**: Work item 5a planning, 2026-10-19
> **Origin**: maintenance

## Objective

Implement row R8 of `docs/RENAME_PLAN.md`, work item 5a of
`docs/ADR_CARDINE_1_0.md`.

Switch the product to `.cardine/` and rename the `meridian-self-hosting`
profile id of the product catalog to `cardine-self-hosting`.

## Acceptance Criteria

- [ ] The scope of row R8 in `docs/RENAME_PLAN.md` is implemented as the
  plan describes it, on the files it lists. A file the plan missed but that
  the same rename needs is in scope; the handoff lists it.
- [ ] Every test under "Tests that prove it" for row R8 exists and passes.
- [ ] The path-recording test of task 043 fails if `load_snapshot` opens any
  `.meridian` path, a project with only `.meridian/tasks/001.json` reports
  `TASK_STATE_MISSING`, and `load_meridian_snapshot` still reads this
  repository.
- [ ] This repository's `.meridian/` and its manifest profile name
  `meridian-self-hosting` are not changed. The validation commands keep naming
  `meridian-self-hosting`, because they check the installed Meridian's
  installation.
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
- [ ] `.meridian/` is unchanged, except `.meridian/tasks/049.json`, which only
  the installed `meridian task close 049` writes. No task of this phase runs the
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
| `docs/RENAME_PLAN.md` | Authority: rules, groups, reader table, and row R8, with its file list. |
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
- **Coordinator confirmation (gate of plan row R8).** From the integration of
  task 043 on, the coordinator reads this repository's state only through
  `cardine.legacy.meridian_installation.load_meridian_snapshot`. This record
  was written with that commitment on 2026-10-19.

## Out of scope

Other rows of the rename plan, work items 5b, 6, and 10, and every frozen
file.

## Dependencies

- **Depends on**: 048
- **Blocks**: 050

## Developer decisions given in advance

The developer records these decisions in the task contract, so that they
hold however the task is launched, including a bare `Proceed with <TASK-ID>`
from the project console (ADR decision 12). None of these situations needs a
new decision from the developer. After fixing a failure, continue with
revalidation in the same turn; do not stop to report the fix.

- A required command that exits non-zero because of a precondition the agent
  can satisfy (command order, an uncommitted worktree, a missing argument):
  satisfy it and run the command again, once.
- A validation failure caused by this task's own changes, including a name
  collision, a stale reference, a broken link, or a test expectation that the
  task made obsolete: fix it and revalidate, at most 3 counted attempts. A
  test that fails once and passes on an identical unchanged rerun is
  intermittent, recorded in the handoff, and does not count. Only after 3
  counted failures stop with `BLOCKED VALIDATION_FAILED` and a summary of the
  failures.
- A `BLOCKED <CODE>` from a Meridian command whose entry in
  `capabilities/stop-codes-v1.json` of the primary checkout's `main` has
  `human_decision: false`: run the command the stop names, once. If it stops
  again with the same code, stop.
- The deny list, `RULE_CONFLICT`, every guardrail, and a change of scope
  remain stops.

## Validation

- `python3 scripts/check_repository.py`
- `meridian profile doctor meridian-self-hosting --project .`
- `meridian audit --project . --mode lean-delivery --ci-profile meridian-self-hosting`
- `python3 scripts/run_tests.py --parallel`
- `python3 scripts/run_tests.py --parallel --clean-clone`
- `git diff --check`
