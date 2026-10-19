# Task 052 — Resolve the project preset from the configuration (single workflow SW1)

> **ID**: `052`
> **Category**: Refactor
> **Priority**: 🔴 P1
> **Estimate**: ~3h
> **Assigned to**: unassigned
> **Session**: Work item 6 planning, 2026-10-19
> **Origin**: maintenance

## Objective

Implement row SW1 of `docs/SINGLE_WORKFLOW_PLAN.md`, work item 6 of
`docs/ADR_CARDINE_1_0.md`.

Extend `.cardine/project.json` with `preset`, `taskDefaults`, `taskIdentity`,
and `validation`, and make `cardine.templates.mode` a configuration resolver,
so that no product code derives the workflow from `PROJECT_WORKFLOW.md` text
or the shape of the queue.

## Acceptance Criteria

- [ ] The scope of row SW1 is implemented as the plan describes it, with the
  design of the plan's sections 1 to 6. A file the plan missed but that
  the same change needs is in scope; the handoff lists it.
- [ ] Every test that row SW1 lists under "Tests that prove it" exists and
  passes.
- [ ] `detect_mode` resolves the workflow from the configured preset and never
  reads `PROJECT_WORKFLOW.md` or `tasks/QUEUE.md`. Until row SW7 removes
  the branching, it maps `lean` to the internal key `lean-delivery` and
  `governed` to `governed-sdd`, so its 13 current consumers keep working
  unchanged. A missing or malformed configuration is a configuration
  error, never a guess.
- [ ] The detection of the Meridian mode lock in `PROJECT_WORKFLOW.md` moves
  into `cardine.legacy.meridian_installation`. `load_snapshot` accepts the
  workflow resolver as an injected argument; `load_meridian_snapshot`
  passes the legacy detection and every product caller uses the
  configuration resolver. No product command imports `cardine.legacy` (the
  import-graph test of task 043 still passes).
- [ ] `load_meridian_snapshot` still reads a synthetic Meridian-layout project
  that has no `.cardine/project.json`, and a test proves it.
- [ ] The shared test fixture builders (`tests/cardine_cli_support.py`,
  `tests/console_support.py`, `tests/worktree_support.py`) write a
  `.cardine/project.json` with a preset. Test files that wrote a mode lock
  only to select the workflow use the fixture instead.
- [ ] The frozen files stay unchanged: `CLAUDE.md`, `AGENTS.md`,
  `PROJECT_WORKFLOW.md`, `LANGUAGE_POLICY.md`,
  `docs/COMPLETION_REPORT_TEMPLATE.md`, `docs/CONTEXT_BUDGET_POLICY.md`,
  `docs/EXECUTION_EVIDENCE_PROFILE.md`, `docs/WORKTREE_LIFECYCLE.md`,
  `.codex/hooks.json`, `.codex/rules/meridian.rules`, `hooks/hooks.json`,
  `hooks/queue-briefing.sh`, `hooks/read-guard.sh`, and the `meridian
  worktree` line of `.codex/rules/local.rules`. No task of this work item
  runs the checkout's `setup --apply` against the real home directory or
  creates `.cardine/` in this repository.
- [ ] `.meridian/` is unchanged, except `.meridian/tasks/052.json`, which only
  the installed `meridian task close 052` writes.
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
| `docs/SINGLE_WORKFLOW_PLAN.md` | Authority: sections 1 to 6 and row SW1, with its bounded files. |
| `docs/ADR_CARDINE_1_0.md` | Decisions 3, 4, 5, 11, and 12; work item 6. |
| `PROJECT_PLAN.md` | Deferred items that name this work item. |

## Technical Context

- The work item 6 tasks run strictly in sequence (plan, section 7).
- Until work item 10 the installed Meridian runs this repository's lifecycle
  and owns the frozen files. Product fixtures are separate from this
  repository's own workflow.
- Coordinator binding: on `main` at `2a6caec`, `detect_mode` has 13 consumers:
  `scripts/cardine_cli.py`, `src/cardine/cli.py`, `console/snapshot.py`,
  `integration/merge.py`, `integration/projections.py`,
  `lifecycle/closure.py`, `lifecycle/commands.py`, `lifecycle/execution.py`,
  `review/verdict.py`, `shared/context.py`, `tasks/importer.py`,
  `tasks/transitions.py`, and `templates/audit.py`. Seventeen test files and
  three fixture builders write a mode lock.
- This repository has no `.cardine/project.json`, and adding one is out of
  scope until work item 10. That is why the Meridian detection moves into
  `cardine.legacy` instead of being deleted. `docs/SINGLE_WORKFLOW_PLAN.md`,
  section "Coordinator notes", and rename plan choice 5 state the same
  constraint.

## Out of scope

Other rows of the plan, work items 5b, 7, 8, 9, and 10, and every frozen file.

## Dependencies

- **Depends on**: 051
- **Blocks**: 053

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
