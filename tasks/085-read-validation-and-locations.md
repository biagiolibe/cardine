# Task 085 — Read validation commands, host impact, and locations from frozen inputs (N2b)

> **ID**: `085`
> **Category**: Refactor
> **Priority**: 🔴 P1
> **Estimate**: ~3h
> **Assigned to**: unassigned
> **Session**: Work item 8 planning, 2026-10-23
> **Origin**: maintenance

## Objective

Implement the second half of row N2 of `docs/TEXT_GATE_INVENTORY.md`: the `##
Validation` commands, the host impact declaration, the required headings, the
record status reads that remain, and the location fallback to
`PROJECT_WORKFLOW.md` prose still come from Markdown after creation.

## Acceptance Criteria

- [ ] Entry T-15: every after-creation reader of the `## Validation` commands
  (`tasks/evidence.py`, `tasks/preflight.py`,
  `tasks/contract.py::verify_execution_evidence`,
  `lifecycle/execution.py::delivery_readiness`,
  `tasks/recording.py::run_validation`) uses the frozen contract. If the
  snapshot lacks a field these readers need, `cardine task new` adds it at
  creation, as task 079 did.
- [ ] Entry T-03: the host impact declaration is validated at creation and
  frozen; `execution_preflight` reads the frozen value. Entry T-06: the
  second read of the required headings is removed, since creation already
  requires them.
- [ ] Entry T-07 at `worktree/checkout.py::registered_worktree_task_states`
  and `lifecycle/execution.py:82`: status comes from state, not from the
  record.
- [ ] Entry T-45: `resolve_project_locations` reads `.cardine/project.json`
  only; the prose fallback to `PROJECT_WORKFLOW.md` and its `DEPRECATED`
  message are removed. A project without the configuration gets a
  diagnostic naming the command that writes it.
- [ ] Tests prove that editing the record's Validation section, host impact
  table, or headings after creation changes no gate.
- [ ] Every row of the known-violation table of `tests/test_text_gates.py` for
  entries T-03, T-06, T-07, T-15, and T-45 that this task removes is
  deleted, and the test passes. The handoff lists the deleted rows and any
  row of those entries that remains, with its destination.
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
- [ ] `.meridian/` is unchanged, except `.meridian/tasks/085.json`, which only
  the installed `meridian task close 085` writes.
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
| `docs/TEXT_GATE_INVENTORY.md` | Authority: row N2 and entries T-03, T-06, T-07, T-15, T-45. |
| `src/cardine/tasks/evidence.py`, `preflight.py`, `contract.py`, `recording.py`, `identity.py`, `creation.py` | The readers and the creation path. |
| `src/cardine/lifecycle/execution.py`, `src/cardine/worktree/checkout.py` | Status and validation readers. |

## Technical Context

- It closes row N2. Row N3 (handoff gates) and the engine rows follow in the
  revised run engine plan of task 082.
- If `worktree advance` stops because another task holds the integration lease
  in the primary checkout, that is not a decision for the developer: wait
  until the other integration finalizes or aborts, then rerun the same
  `advance` command.

## Out of scope

The handoff gates (row N3), the engine of work item 8, and the importer (work
item 10).

## Dependencies

- **Depends on**: 084
- **Blocks**: —

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
