# Task 147 — Prove a no-review delivery to landing (C3c)

> **ID**: `147`
> **Category**: Feature
> **Priority**: 🔴 P1
> **Estimate**: ~3h
> **Assigned to**: unassigned
> **Session**: Work item 10 records, 2026-11-03
> **Origin**: maintenance

## Objective

Implement row C3c of `docs/CONVERSION_PLAN.md`, work item 10 of
`docs/ADR_CARDINE_1_0.md`. The row fixes the scope, the files, the tests, and
the interruption boundaries; this record adds the developer's decisions and no
design.

disposable end-to-end run of a no-review task to landing with a local bare remote; the test plays the implementer. Fixes what it exposes.

## Acceptance Criteria

- [x] Row C3c is implemented as its line in the excerpt describes it.
- [x] Only the files in the row's files column are edited, together with
  this task's own record and its archive, handoff, and state file. A test
  file outside the column may change only to update an expectation that this
  change made stale, without new behavior, and the handoff lists it. A
  repository check, test helper, or product module outside the column that
  fails only because this row's rename or route made its expectation stale
  is adapted to the new name or route in this task, minimally and without
  loosening it: no check is removed, skipped, or widened, and a route a gate
  cannot resolve still fails. The handoff lists each such file with the
  check that required it. Any other file, or a change that adds behavior
  beyond that adaptation, stops the task before editing it and names the
  file, so that the coordinator splits the row.
- [x] The row's tests exist and pass: Queued to landed and cleaned; `EVIDENCE_INCOMPLETE` recovered through `run`.
- [x] Rule 4 of decision 14: Commit, state write, merge, push, cleanup.
- [x] Every test runs against disposable projects and disposable home
  directories. No step runs `setup --apply` against the real home directory or
  writes real host configuration.
- [x] The subprocess ceilings of `tests/test_command_context.py` still hold.
- [x] Every source and test file stays below 1,500 lines.
- [x] This repository's own lifecycle keeps running on the installed Meridian
  1.4.1.
- [x] The frozen files stay unchanged: `CLAUDE.md`, `AGENTS.md`,
  `PROJECT_WORKFLOW.md`, `LANGUAGE_POLICY.md`,
  `docs/COMPLETION_REPORT_TEMPLATE.md`, `docs/CONTEXT_BUDGET_POLICY.md`,
  `docs/EXECUTION_EVIDENCE_PROFILE.md`, `docs/WORKTREE_LIFECYCLE.md`,
  `.codex/hooks.json`, `.codex/rules/meridian.rules`, `hooks/hooks.json`,
  `hooks/queue-briefing.sh`, `hooks/read-guard.sh`, and the `meridian
  worktree` line of `.codex/rules/local.rules`. No task runs the
  checkout's `setup --apply` against the real home directory or creates
  `.cardine/` in this repository.
- [x] `.meridian/` is unchanged, except `.meridian/tasks/147.json`, which only
  the installed `meridian task close 147` writes.
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
| `tests/test_run_delivery_disposable.py`, `tests/run_delivery_support.py`, plus at most 8 files | The files this row edits, as the plan lists them. |

## Authority excerpt

The parts of the plan this task needs, extracted from the file on `main` when
the record was written, so that the task reads them here instead of the whole
document:

> From `docs/CONVERSION_PLAN.md`, row C3c:
>
> | C3c / 3h | Meridian: disposable end-to-end run of a no-review task to landing with a local bare remote; the test plays the implementer. Fixes what it exposes. | `tests/test_run_delivery_disposable.py`, `tests/run_delivery_support.py`, plus at most 8 files | Queued to landed and cleaned; `EVIDENCE_INCOMPLETE` recovered through `run`. | Commit, state write, merge, push, cleanup. | C3b |

## Technical Context

- This task depends on 146; the plan's own dependency cell reads:
  C3b.
- Developer decisions of 2026-11-03, binding on every row: DD1: a developer
  channel from an interactive terminal covers the owner verdict, `cancel`, and
  `abort`; reviewer sessions stay refused. DD2: the private projects are converted
  in item 13; `cardine.legacy` and `adopt` stay. DD3: `.meridian/` is removed at
  the switch. DD4: `ci: none`. DD5: the standalone ADR files stay and are cited by
  path.
- Sections 1, 5, and 7 of `docs/CONVERSION_PLAN.md` hold the observations (O1 to
  O9) and the switch that this row serves; read only the parts the row cites.
- The plan estimates this row at 3h. If it turns out larger, finish the
  scope; do not stop for the size alone.
- If `worktree advance` stops because another task holds the integration lease
  in the primary checkout, that is not a decision for the developer: wait
  until the other integration finalizes or aborts, then rerun the same
  `advance` command.
- During development, run only what the change touches: `python3
  scripts/run_tests.py --parallel --module <name>` for a module, class, or
  test, and `python3 scripts/run_tests.py --parallel --last-failed` after a
  failed full run. Both print only failures. Do not run `python3 -m unittest`
  directly, and run the full suite once, as the counted clean-clone
  validation.

## Out of scope

Other rows of the plan, the switch steps that belong to the developer, the
documentation of work item 11, the release script of work item 12, and the
installation surface deferred after 1.0.

## Dependencies

- **Depends on**: 146
- **Blocks**: 149, 151, 152

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
