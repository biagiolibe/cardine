# Task 103 — Bind verdict, cancel, and abort to issued roles (RE4b)

> **ID**: `103`
> **Category**: Feature
> **Priority**: 🔴 P1
> **Estimate**: ~3h
> **Assigned to**: unassigned
> **Session**: Work item 8 records, 2026-10-25
> **Origin**: maintenance

## Objective

Implement row RE4b of `docs/RUN_ENGINE_PLAN.md`, work item 8 of
`docs/ADR_CARDINE_1_0.md`. The plan's row fixes the scope, files, tests,
ratchet keys, and interruption boundaries; this record adds no design.

## Acceptance Criteria

- [x] The scope of row RE4b is implemented as its table cell describes it,
  with the design of the plan's sections "State and next-step resolution",
  "Invocation, locations and output contract", "Stops, recovery and
  bounded work", "Validation attempts", "Review and Stable commands",
  "Direct landing and CI", "Trust boundary", and "Reconciled choices and
  existing inputs": Bind verdict/cancel/owned abort to issued roles and
  operations; two changes-requested loop budget; `review/verdict.py`,
  transitions, E, S, C, K, receipt module, `integration/merge.py`, new
  `lifecycle/control.py`. A file the row missed but that the same change
  needs is in scope; the handoff lists it.
- [x] The row's tests exist and pass: `test_run_review.py`,
  `test_run_control.py`: F01/F11 owner spoof, stale review, loop limit,
  cancel retains branch/new task restart, repeated owned abort.
- [x] Ratchet: no new key appears in the known-violation table of
  `tests/test_text_gates.py`, and the allowlist does not grow.
- [x] Rule 4 of decision 14: Verdict state write then Markdown projection;
  cancel transition; abort merge/state/lease unlink: resume missing output
  once with unchanged verdict/time, preserve foreign lease. Each effect
  test kills the operation immediately before and after each listed
  boundary, runs the identical command again, and checks convergence
  without duplicate commits, verdicts, counters, or deletion of foreign
  work. Pure rows test repeated resolution with no writes.
- [x] Every effect this row performs or changes goes through the operation
  receipts of row RE1b and has changed-input and foreign-owner negative
  tests.
- [x] Nothing in the change claims authenticity beyond the plan's "Trust
  boundary": no same-user receipt or hash is presented as proof of
  authorship, and real host configuration is never installed or changed.
- [x] The subprocess ceilings of `tests/test_command_context.py` (task 100)
  still hold. A new Git observation goes through the single gateway and
  the command context; a ceiling rises only with the observation named in
  the handoff, and never because a fact is read twice.
- [x] Every source and test file stays below 1,500 lines.
- [x] This repository's own lifecycle keeps running on the installed Meridian
  1.4.1. The task changes product code, product templates, tests, and the
  other files its row names only; it never runs `cardine run` on this
  repository, installs or changes real host configuration, or writes to
  the real home directory.
- [x] The frozen files stay unchanged: `CLAUDE.md`, `AGENTS.md`,
  `PROJECT_WORKFLOW.md`, `LANGUAGE_POLICY.md`,
  `docs/COMPLETION_REPORT_TEMPLATE.md`, `docs/CONTEXT_BUDGET_POLICY.md`,
  `docs/EXECUTION_EVIDENCE_PROFILE.md`, `docs/WORKTREE_LIFECYCLE.md`,
  `.codex/hooks.json`, `.codex/rules/meridian.rules`, `hooks/hooks.json`,
  `hooks/queue-briefing.sh`, `hooks/read-guard.sh`, and the `meridian
  worktree` line of `.codex/rules/local.rules`. No task runs the
  checkout's `setup --apply` against the real home directory or creates
  `.cardine/` in this repository.
- [x] `.meridian/` is unchanged, except `.meridian/tasks/103.json`, which only
  the installed `meridian task close 103` writes.
- [x] A test expectation that this task makes stale is updated in this task
  without weakening any other assertion. The parallel suite reports the
  same coverage `total` before and after the task, except for new or
  deliberately removed tests, which the handoff lists with their reason.
- [x] **Clean-clone validation.** After the implementation commit, run
  `python3 scripts/run_tests.py --parallel --clean-clone` from the clean
  task worktree and record its result line in the handoff.
- [x] Every command under Validation passes.

## Relevant Files

| File | Role |
|------|------|
| `docs/RUN_ENGINE_PLAN.md` | Authority: row RE4b of "Ordered implementation tasks", and the design sections it cites. |
| `docs/ADR_CARDINE_1_0.md` | Decisions 6, 8, 11, 12, 13, and 14 (rule 2 as amended on 2026-10-23). |
| `docs/TEXT_GATE_INVENTORY.md`, `docs/RULE_ENFORCEMENT_INVENTORY.md`, `docs/FORGERY_INVENTORY.md`, `docs/STOP_REVIEW.md` | Inventory entries that the plan's "Amendment disposition" assigns to this row. |
| `tests/test_text_gates.py` | The ratchet table. |

## Technical Context

- The plan runs every row serially in table order. This task depends on 102
  and is followed by 104. Rows that share a file with it: E/S/C/K/receipts
  peers above; verdict: RE2b; transitions: RE1c, RE2a, N3; merge abort
  implementation: RE2a, RE5a, RE5b, RE6b.
- The plan estimates this row at 3 hours including its focused tests. If it
  turns out larger, finish the scope; do not stop for the size alone.
- The abbreviations in the row cells are defined in the plan's "Ordered
  implementation tasks": `C` is `src/cardine/cli.py`, `E` is
  `src/cardine/lifecycle/engine.py`, `S` is `src/cardine/tasks/state.py` with
  `schemas/task-state-v1.schema.json`, `K` is
  `capabilities/stop-codes-v1.json` with `schemas/stop-codes-v1.schema.json`,
  and `R` is `tests/test_text_gates.py`; F-numbers are the attacks of
  `docs/FORGERY_INVENTORY.md`.
- If `worktree advance` stops because another task holds the integration lease
  in the primary checkout, that is not a decision for the developer: wait
  until the other integration finalizes or aborts, then rerun the same
  `advance` command.

## Out of scope

Other rows of the plan, work items 9 and 10, the installation surface
(deferred after 1.0), and this repository's own delivery.

## Dependencies

- **Depends on**: 102
- **Blocks**: 104

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

- `meridian profile doctor meridian-self-hosting --project .`
- `meridian audit --project . --mode lean-delivery --ci-profile meridian-self-hosting`
- `python3 scripts/run_tests.py --parallel --clean-clone`
- `git diff --check`

The clean-clone run executes `scripts/check_repository.py` and the parallel
suite on a clone of the committed HEAD, so the task does not run them again
in the worktree as counted validation.
