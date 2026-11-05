# Task 171 — Rerun only the failing commands through declared retry variants

> **ID**: `171`
> **Category**: Feature
> **Priority**: 🟡 P2
> **Estimate**: ~3h
> **Assigned to**: unassigned
> **Session**: Validation cost in Cardine, 2026-11-05
> **Origin**: developer request

## Objective

Today `cardine run` and candidate validation rerun the complete command set after any
failure (`src/cardine/lifecycle/validation.py`, the `while len(runs) < 2` loop;
`src/cardine/integration/candidate.py`, the same loop). A real failure fails again, so
every failed attempt runs the complete set twice: on this repository, up to 74 minutes
each. ADR decision 5, as amended on 2026-11-05, lets a project declare a retry variant
per command, which can end an attempt early but never pass it.

## Acceptance Criteria

- [ ] **Declaration.** `.cardine/project.json` accepts an optional `validation.retry`
  object that maps a declared command ID to a nonempty literal command.
  `_validate_validation` in `src/cardine/shared/project.py` and
  `schemas/project-v1.schema.json` accept it and reject an unknown ID, an empty
  command, and any other new key. A declaration without it validates as today.
- [ ] **Freeze.** Task creation copies `retry` into the frozen contract, and
  `schemas/task-state-v1.schema.json` accepts it. `inputs()` in
  `src/cardine/tasks/validation.py` includes the variants in `commandDigest`, so an attempt
  binds the variants it ran. A task created without `retry` keeps its digest unchanged.
- [ ] **One-sided rerun, task validation.** After a failed complete run, each failed
  command that has a variant runs its variant first, in declaration order. If any variant
  exits 1, the attempt fails now and counts once toward the validation retry limit, with
  no second complete run. If every variant exits 0, or any exits with another status, the
  complete set reruns once and decides, exactly as today. A failed command without a
  variant keeps today's behavior. A passing attempt's last round is always a complete set.
- [ ] **One-sided rerun, candidate validation.** The same rule holds in
  `src/cardine/integration/candidate.py`, with the variant found through the command's
  ID in the frozen contract.
- [ ] Each task-validation variant round is recorded with its commands, exit statuses,
  and logs and appears in the handoff's `Measured validation` section. Candidate
  variant rounds are recorded with commands, exit statuses, and output in
  `run.candidateValidation.runs`, like complete rounds; candidate validation does
  not write the handoff, preserving the validated integration tree. (Coordinator
  decision, 2026-11-05.) Interrupted
  and replayed attempts converge as today: kill tests cover the new round in both loops.
- [ ] Tests in a new `tests/test_validation_quick_commands.py` prove, with cheap literal
  commands, for task and candidate validation: a variant exiting 1 ends the attempt
  after one complete run; a variant exiting 0 leads to a complete rerun that decides
  both ways; a variant exiting 2 leads to a complete rerun; an order-dependent failure
  whose variant passes is never accepted without a passing complete run; no variant
  declared keeps two complete runs. `tests/test_single_workflow_config.py` covers the
  declaration checks.
- [ ] `docs/PROJECT_DECLARATION.md` documents `validation.retry`, the meaning of exit 1, 0,
  and any other status, and that only a complete set passes an attempt.
- [ ] Only the files under Relevant Files are edited, together with this
  task's own record and its archive, handoff, and state file. A test file
  outside that list may change only to update an expectation that this change
  made stale, without new behavior, and the handoff lists it. Any other file,
  or new behavior beyond this record, stops the task before editing it and
  names the file.
- [ ] Tests that need a home directory create a disposable one themselves. Run the
  validation commands with the inherited environment, as written; never wrap them in a
  temporary home, and a run that inherited the real home is not a stop. No step runs
  `setup --apply` against the real home directory or writes real host configuration.
- [ ] The subprocess ceilings of `tests/test_command_context.py` still hold.
- [ ] Every source and test file stays below 1,500 lines.
- [ ] This repository's own lifecycle keeps running on the installed Meridian
  1.4.1.
- [ ] The frozen files stay unchanged: `CLAUDE.md`, `AGENTS.md`,
  `PROJECT_WORKFLOW.md`, `LANGUAGE_POLICY.md`,
  `docs/COMPLETION_REPORT_TEMPLATE.md`, `docs/CONTEXT_BUDGET_POLICY.md`,
  `docs/EXECUTION_EVIDENCE_PROFILE.md`, `docs/WORKTREE_LIFECYCLE.md`,
  `.codex/hooks.json`, `.codex/rules/meridian.rules`, `hooks/hooks.json`,
  `hooks/queue-briefing.sh`, `hooks/read-guard.sh`, and the `meridian
  worktree` line of `.codex/rules/local.rules`. No task runs the
  checkout's `setup --apply` against the real home directory or creates
  `.cardine/` in this repository.
- [ ] `.meridian/` is unchanged, except `.meridian/tasks/171.json`, which only
  the installed `meridian task close 171` writes.
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
| `src/cardine/shared/project.py`, `schemas/project-v1.schema.json`, `schemas/task-state-v1.schema.json`, `src/cardine/tasks/contract.py`, `src/cardine/tasks/validation.py`, `src/cardine/lifecycle/validation.py`, `src/cardine/integration/candidate.py`, `docs/PROJECT_DECLARATION.md`, `tests/test_validation_quick_commands.py` (new), `tests/test_single_workflow_config.py` | The files this task edits. |

## Technical Context

- Authority: ADR decision 5 and the paragraph on intermittent failures under decision
  12, both amended on 2026-11-05. Read them before starting.
- Why a variant can never pass an attempt: tasks 150 and 153 failed three times on a test
  that failed only in the full run's order (a mock binding leaked across tests). Run
  alone, as `--last-failed` does, it passed. A variant that could pass an attempt would
  have recorded it as intermittent and landed the defect.
- This repository's own variant would be `python3 scripts/run_tests.py --parallel
  --last-failed`: exit 1 for remaining failures, exit 2 when no failure was recorded. A
  missing record therefore falls back to the complete rerun, by the rule above.
- The candidate binding holds literal commands. Resolve each to its ID in the frozen
  contract's `validation.commands`; a command without an ID has no variant.
- `tests/test_run_receipts.py`, `tests/test_run_recovery.py`, and
  `tests/fixture_restore_support.py` belong to task 168, and `src/cardine/lifecycle/receipts.py`
  and `tests/fixtures/module_split_baseline.json` to task 169. Do not edit them; the kill
  tests for the new round go in the new test module.
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
- Other tasks share this machine. Stop only your own processes, by process ID;
  never `pkill` test runs by pattern.
- Coordinator measurements of 2026-11-04, on a machine shared with other suites:
  the module weights sum to about 3 hours, so 8 workers cannot finish in under
  24 minutes. Almost all of it is waiting on Git and Python subprocesses.

## Out of scope

Preflight commands, running a variant first on the next attempt, and the separate limit
for quick failures: task 172. Mapping Meridian's candidate validation to `retry` in
`cardine adopt`: a later row. Reducing what a complete run executes. Other rows of the
queue.

## Dependencies

- **Depends on**: none
- **Blocks**: 172

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
- Before the first clean-clone, run `python3 scripts/check_repository.py` and one
  `python3 scripts/run_tests.py --parallel` with `--module` for each edited test module
  and for the repository guards: `test_module_inventory`, `test_layout`,
  `test_no_meridian_identifiers`, `test_text_gates`, `test_stop_registry`,
  `test_command_word`, and `test_run_end_to_end.ReplayInventoryTest`. The guards take
  under a minute and catch most failures that a clean-clone would find.
- Let a started clean-clone finish; do not interrupt it to restart after a change. Its
  failure record lists every failure at once, so fix them all together.
- After a failed clean-clone, do not start another one at once. Fix, commit, and run
  `python3 scripts/run_tests.py --parallel --last-failed`, which reads the failures that
  clean-clone recorded for this worktree, and a `--module` run for each module the fix
  touched. Only when both pass, run the clean-clone again as the next counted attempt.
  Judge whether a failure is intermittent with `--last-failed` on the unchanged tree,
  not with a new clean-clone.
- A `BLOCKED <CODE>` from a Meridian command whose entry in
  `capabilities/stop-codes-v1.json` of the primary checkout's `main` has
  `human_decision: false`: run the command the stop names, once. If it stops
  again with the same code, stop.
- A test outside the files this record lists that inventories what the
  repository contains (boundary modules, stop codes, allowances, markers, module
  bindings) and fails only because this task added an item: add that one item, naming
  the real test or owner the inventory asks for, and list the file in the handoff. This
  is not a change of scope. Removing an item, or widening a pattern beyond the new
  item, is.
- A measurement the record asks the handoff to report: use in-process Python
  (wrap `subprocess.Popen` to count, read `resource.getrusage(RUSAGE_CHILDREN)` for
  CPU), never a tool that needs privileges. If one still cannot be obtained, say so in
  the handoff; that is not a stop.
- Before stopping for a change of scope, finish everything else, commit it, and run
  the repository check and the affected tests, so that one stop names every file
  needed. Do not stop once per file.
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
