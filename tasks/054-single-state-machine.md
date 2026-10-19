# Task 054 — Use one task state machine with review and dependency gates (single workflow SW3)

> **ID**: `054`
> **Category**: Refactor
> **Priority**: 🔴 P1
> **Estimate**: ~3h
> **Assigned to**: unassigned
> **Session**: Work item 6 planning, 2026-10-19
> **Origin**: maintenance

## Objective

Implement row SW3 of `docs/SINGLE_WORKFLOW_PLAN.md`, work item 6 of
`docs/ADR_CARDINE_1_0.md`.

Replace the Lean and Governed SDD statuses with `queued`, `in_progress`,
`in_review`, `done`, and `cancelled`, with the transitions, review gate, and
dependency rule of section 3 of the plan.

## Acceptance Criteria

- [ ] The scope of row SW3 is implemented as the plan describes it, with the
  design of the plan's sections 1 to 6. A file the plan missed but that
  the same change needs is in scope; the handoff lists it.
- [ ] Every test that row SW3 lists under "Tests that prove it" exists and
  passes.
- [ ] "Integration task-state consumers" means every module of `src/cardine/`
  that reads a task status value, found with `git grep` for the old status
  names. The handoff lists them.
- [ ] `load_meridian_snapshot` still reads state files that use the Meridian
  statuses (`QUEUED`, `IN_PROGRESS`, `READY_FOR_REVIEW`,
  `CHANGES_REQUESTED`, `ACCEPTED`, `ANSWERED`, `INCONCLUSIVE`, `DONE`).
  `cardine.legacy` maps them to the new vocabulary for the snapshot,
  read-only, with the mapping table of section 3. Product readers accept
  only the new vocabulary. A test covers both.
- [ ] The frozen files stay unchanged: `CLAUDE.md`, `AGENTS.md`,
  `PROJECT_WORKFLOW.md`, `LANGUAGE_POLICY.md`,
  `docs/COMPLETION_REPORT_TEMPLATE.md`, `docs/CONTEXT_BUDGET_POLICY.md`,
  `docs/EXECUTION_EVIDENCE_PROFILE.md`, `docs/WORKTREE_LIFECYCLE.md`,
  `.codex/hooks.json`, `.codex/rules/meridian.rules`, `hooks/hooks.json`,
  `hooks/queue-briefing.sh`, `hooks/read-guard.sh`, and the `meridian
  worktree` line of `.codex/rules/local.rules`. No task of this work item
  runs the checkout's `setup --apply` against the real home directory or
  creates `.cardine/` in this repository.
- [ ] `.meridian/` is unchanged, except `.meridian/tasks/054.json`, which only
  the installed `meridian task close 054` writes.
- [ ] A test expectation that this task makes stale is updated in this task
  without weakening any other assertion. The parallel suite reports the
  same coverage `total` before and after the task, except for new or
  deliberately removed tests, which the handoff lists with their reason.
- [ ] **Clean-clone validation.** After the implementation commit, run
  `python3 scripts/run_tests.py --parallel --clean-clone` from the clean
  task worktree and record its result line in the handoff.
- [ ] Every command under Validation passes.

## Relevant Files

| File | Role |
|------|------|
| `docs/SINGLE_WORKFLOW_PLAN.md` | Authority: sections 1 to 6 and row SW3, with its bounded files. |
| `docs/ADR_CARDINE_1_0.md` | Decisions 3, 4, 5, 11, and 12; work item 6. |
| `PROJECT_PLAN.md` | Deferred items that name this work item. |

## Technical Context

- The work item 6 tasks run strictly in sequence (plan, section 7).
- Until work item 10 the installed Meridian runs this repository's lifecycle
  and owns the frozen files. Product fixtures are separate from this
  repository's own workflow.
- Coordinator binding: this repository's `.meridian/tasks/*.json` files hold
  `DONE` (51 files on `main` at `2a6caec`), and the coordinator reads them
  through `load_meridian_snapshot`.
- Section 3 of the plan keeps the Markdown status, archive, and queue
  projection machinery for work item 7; this task adapts those consumers to
  the new vocabulary without removing them.

## Out of scope

Other rows of the plan, work items 5b, 7, 8, 9, and 10, and every frozen file.

## Dependencies

- **Depends on**: 053
- **Blocks**: 055

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
