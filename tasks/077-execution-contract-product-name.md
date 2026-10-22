# Task 077 — Use one product name in the execution contract line

> **ID**: `077`
> **Category**: Bug
> **Priority**: 🔴 P1
> **Estimate**: ~1h
> **Assigned to**: unassigned
> **Session**: Decision 13 planning, 2026-10-22
> **Origin**: maintenance

## Objective

Fix defect 1 of `docs/TEXT_GATE_INVENTORY.md`. `cardine execution contract`
writes the generated line ``- Execution commands: `required via meridian
execution` `` (`src/cardine/tasks/preflight.py`), and
`contract_requires_execution_commands` (`src/cardine/tasks/contract.py`) and
`execution_preflight` check for that literal. The product blueprint
`templates/single/tasks/TASK_BLUEPRINT.md` writes `required via cardine
execution`, so a record copied from the template fails with
`EXECUTION_CONTRACT_UNRESOLVED`.

The line is managed text that Cardine writes and checks (class MI of decision
13, entry T-05), so an exact comparison is the right gate; the defect is that
writer, checker, and template disagree.

## Acceptance Criteria

- [ ] The writer, the checker, the preflight error text, and the product
  blueprint use one constant with the product name, `required via cardine
  execution`, defined once in product code; no product file under
  `src/cardine/` or `templates/single/` contains `required via meridian
  execution`.
- [ ] A test proves that the line in
  `templates/single/tasks/TASK_BLUEPRINT.md` equals the line `cardine
  execution contract` generates, so the template and the code cannot drift
  again.
- [ ] A test creates a task from the product blueprint and passes
  `execution_preflight` without regenerating the block.
- [ ] The handoff explains why the Meridian-identifier guard of task 051 and
  the retired text catalog did not catch this literal, and either extends
  the guard so it would, or states why it cannot.
- [ ] If the template text changes, the pre-1.0 rule of task 031 applies: the
  owning capability's version rises and its baseline is rewritten, with no
  migration and no `VERSION` change.
- [ ] This repository's own lifecycle keeps running on the installed Meridian
  1.4.1; this task changes product code, product templates, and tests
  only.
- [ ] The frozen files stay unchanged: `CLAUDE.md`, `AGENTS.md`,
  `PROJECT_WORKFLOW.md`, `LANGUAGE_POLICY.md`,
  `docs/COMPLETION_REPORT_TEMPLATE.md`, `docs/CONTEXT_BUDGET_POLICY.md`,
  `docs/EXECUTION_EVIDENCE_PROFILE.md`, `docs/WORKTREE_LIFECYCLE.md`,
  `.codex/hooks.json`, `.codex/rules/meridian.rules`, `hooks/hooks.json`,
  `hooks/queue-briefing.sh`, `hooks/read-guard.sh`, and the `meridian
  worktree` line of `.codex/rules/local.rules`. No task runs the
  checkout's `setup --apply` against the real home directory or creates
  `.cardine/` in this repository.
- [ ] `.meridian/` is unchanged, except `.meridian/tasks/077.json`, which only
  the installed `meridian task close 077` writes.
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
| `docs/TEXT_GATE_INVENTORY.md` | Defect 1, entries T-05 and TPL-10. |
| `src/cardine/tasks/preflight.py`, `src/cardine/tasks/contract.py` | Writer and checkers of the line. |
| `templates/single/tasks/TASK_BLUEPRINT.md` | Product blueprint. |
| `capabilities/retired-text-v1.json`, the guard tests of task 051 | Where a retired Meridian literal should have been caught. |

## Technical Context

- It can run at the same time as tasks 069 and 072, which change other files.
- If `worktree advance` stops because another task holds the integration lease
  in the primary checkout, that is not a decision for the developer: wait
  until the other integration finalizes or aborts, then rerun the same
  `advance` command.

## Out of scope

Other inventory entries, and this repository's own Meridian records.

## Dependencies

- **Depends on**: 073
- **Blocks**: 079

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
