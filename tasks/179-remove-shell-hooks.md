# Task 179 — Remove the shell hooks and their tests (C7b)

> **ID**: `179`
> **Category**: Refactor
> **Priority**: 🔴 P1
> **Estimate**: ~2h
> **Assigned to**: unassigned
> **Session**: Records of rows C7, 2026-11-06
> **Origin**: maintenance

## Objective

Implement row C7b of `docs/CONVERSION_PLAN.md`, work item 10 of
`docs/ADR_CARDINE_1_0.md`, after the switch, under Cardine. The row fixes the scope,
the files, and the tests; this record adds the developer's decisions and no design.

remove the shell hooks and their tests.

## Acceptance Criteria

- [ ] Row C7b is implemented as its line in the excerpt describes it.
- [ ] Only the files in the row's files column are edited, together with this task's
  own record, archive, and handoff and the state that Cardine writes for it. A test
  file outside the column may change only to update an expectation that this change
  made stale, without new behavior, and the handoff lists it. Any other file, or new
  behavior beyond the row, stops the task before editing it and names the file, so
  that the coordinator splits the row.
- [ ] The row's tests exist and pass: Suite passes without them.
- [ ] Tests that need a home directory create a disposable one themselves. Run the
  validation commands with the inherited environment, as written; never wrap them in a
  temporary home, and a run that inherited the real home is not a stop. No step runs
  `setup --apply` against the real home directory or writes real host configuration.
- [ ] The subprocess ceilings of `tests/test_command_context.py` still hold.
- [ ] Every source and test file stays below 1,500 lines.
- [ ] The files that `cardine adopt` generated outside `.cardine/` are edited only if
  the row's files column names them; `.cardine/` changes only through Cardine commands.
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
| `hooks/hooks.json`, `hooks/queue-briefing.sh`, `hooks/read-guard.sh`, `tests/test_queue_briefing.py`, `tests/test_read_guard.py`, `tests/test_codex_worktree_hooks.py`, `tests/test_codex_read_guard.py` | The files this row edits, as the plan lists them. |

## Authority excerpt

The parts of the plan this task needs, extracted from the file on `main` when
the record was written, so that the task reads them here instead of the whole
document:

> From `docs/CONVERSION_PLAN.md`, row C7b:
>
> | C7b / 2h | Cardine: remove the shell hooks and their tests. | `hooks/hooks.json`, `hooks/queue-briefing.sh`, `hooks/read-guard.sh`, `tests/test_queue_briefing.py`, `tests/test_read_guard.py`, `tests/test_codex_worktree_hooks.py`, `tests/test_codex_read_guard.py` | Suite passes without them. | Cardine's own. | C7a |

## Technical Context

- This record is written in Meridian format before the switch so that `cardine adopt`
  converts it as a real open task (section 5 of `docs/CONVERSION_PLAN.md`, order table).
  It runs only after the switch, with Cardine: `Proceed with 179` routes to `cardine
  run`. Never start it with the installed Meridian.
- The plan's own dependency cell reads: C7a. Before the switch the dependency is
  expressed on task 164 (C6a), which closes before the switch; the converter drops a
  dependency on a closed task and lists it in the adoption plan.
- Interruption boundaries: Cardine's own. The task adds none of its own.
- Developer decisions of 2026-11-03, binding on every row: DD1 to DD5 in section 1 of
  `docs/CONVERSION_PLAN.md`; in particular DD3 (`.meridian/` is removed at the switch)
  and DD4 (`ci: none`).
- During development, run only what the change touches: `python3
  scripts/run_tests.py --parallel --module <name>` for a module, class, or
  test, and `python3 scripts/run_tests.py --parallel --last-failed` after a
  failed full run. Do not run `python3 -m unittest` directly, and run the full suite
  once, as the counted clean-clone validation.
- Other tasks share this machine. Stop only your own processes, by process ID;
  never `pkill` test runs by pattern.

## Out of scope

Removing `.codex/hooks.json`: after the switch it is the managed copy of the Cardine template (task 183). Other rows of the plan, the switch steps that belong to the developer, the
documentation of work item 11, and the release script of work item 12.

## Dependencies

- **Depends on**: 178
- **Blocks**: 180

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
  counted failures stop and summarize the failures.
- A counted attempt is one run of the whole Validation section on a
  committed implementation that the agent considers complete. Test runs
  during implementation are development, not attempts, however many fail.
  An unfinished implementation is never a reason to stop: finish it first.
- Before the first clean-clone, run `python3 scripts/check_repository.py` and one
  `python3 scripts/run_tests.py --parallel` with `--module` for each edited test module
  and for the repository guards: `test_module_inventory`, `test_layout`,
  `test_no_meridian_identifiers`, `test_text_gates`, `test_stop_registry`, and
  `test_command_word`.
- Let a started clean-clone finish; do not interrupt it to restart after a change.
  After a failed clean-clone, fix, commit, and run `python3 scripts/run_tests.py
  --parallel --last-failed` and a `--module` run for each module the fix touched; only
  when both pass, run the clean-clone again as the next counted attempt.
- A stop printed by `cardine run` whose code in `capabilities/stop-codes-v1.json` has
  `human_decision: false`: run the command the stop names, once. If it stops again
  with the same code, stop.
- A test outside the files this record lists that inventories what the repository
  contains (boundary modules, stop codes, allowances, markers, module bindings) and
  fails only because this row removed an item that the row's files column deletes:
  remove that one inventory item and list the file in the handoff. Widening a pattern,
  or removing any other item, is a change of scope.
- Before stopping for a change of scope, finish everything else, commit it, and run
  the repository check and the affected tests, so that one stop names every file
  needed. Do not stop once per file.
- A change of scope, a guardrail, and every action the project's workflow denies
  remain stops.

## Validation

- `python3 scripts/run_tests.py --parallel --clean-clone`
- `git diff --check`

The clean-clone run executes `scripts/check_repository.py` and the parallel
suite on a clone of the committed HEAD, so the task does not run them again
in the worktree as counted validation.
