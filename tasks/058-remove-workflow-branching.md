# Task 058 — Remove residual workflow branching and prove parity (single workflow SW7)

> **ID**: `058`
> **Category**: Refactor
> **Priority**: 🔴 P1
> **Estimate**: ~2h
> **Assigned to**: unassigned
> **Session**: Work item 6 planning, 2026-10-19
> **Origin**: maintenance

## Objective

Implement row SW7 of `docs/SINGLE_WORKFLOW_PLAN.md`, work item 6 of
`docs/ADR_CARDINE_1_0.md`.

Remove the remaining product branches on the two workflows, including the
internal `lean-delivery` and `governed-sdd` keys that row SW1 kept, and prove
the twelve parity rows of section 6 for both presets.

## Acceptance Criteria

- [ ] The scope of row SW7 is implemented as the plan describes it, with the
  design of the plan's sections 1 to 6. A file the plan missed but that
  the same change needs is in scope; the handoff lists it.
- [ ] Every test that row SW7 lists under "Tests that prove it" exists and
  passes.
- [ ] `git grep` for `lean-delivery`, `governed-sdd`, `LEAN_DELIVERY`, and
  `GOVERNED_SDD` in `src/cardine/` finds only `cardine.legacy` and group 2
  text that work item 5b renames. The handoff lists what remains and why.
- [ ] The handoff names, for work items 5b, 7, 8, and 9, what this work item
  leaves to each, following section 8 of the plan.
- [ ] The frozen files stay unchanged: `CLAUDE.md`, `AGENTS.md`,
  `PROJECT_WORKFLOW.md`, `LANGUAGE_POLICY.md`,
  `docs/COMPLETION_REPORT_TEMPLATE.md`, `docs/CONTEXT_BUDGET_POLICY.md`,
  `docs/EXECUTION_EVIDENCE_PROFILE.md`, `docs/WORKTREE_LIFECYCLE.md`,
  `.codex/hooks.json`, `.codex/rules/meridian.rules`, `hooks/hooks.json`,
  `hooks/queue-briefing.sh`, `hooks/read-guard.sh`, and the `meridian
  worktree` line of `.codex/rules/local.rules`. No task of this work item
  runs the checkout's `setup --apply` against the real home directory or
  creates `.cardine/` in this repository.
- [ ] `.meridian/` is unchanged, except `.meridian/tasks/058.json`, which only
  the installed `meridian task close 058` writes.
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
| `docs/SINGLE_WORKFLOW_PLAN.md` | Authority: sections 1 to 6 and row SW7, with its bounded files. |
| `docs/ADR_CARDINE_1_0.md` | Decisions 3, 4, 5, 11, and 12; work item 6. |
| `PROJECT_PLAN.md` | Deferred items that name this work item. |

## Technical Context

- The work item 6 tasks run strictly in sequence (plan, section 7).
- Until work item 10 the installed Meridian runs this repository's lifecycle
  and owns the frozen files. Product fixtures are separate from this
  repository's own workflow.
- This task closes work item 6. Work item 5b follows.

## Out of scope

Other rows of the plan, work items 5b, 7, 8, 9, and 10, and every frozen file.

## Dependencies

- **Depends on**: 057
- **Blocks**: work item 5b

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
- A counted attempt is one run of the whole Validation section on a
  committed implementation that the agent considers complete. Test runs
  during implementation are development, not attempts, however many fail.
  An unfinished implementation is never a reason to stop: finish it first.
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
