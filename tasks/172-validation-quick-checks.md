# Task 172 — Run declared quick checks first and limit their failures separately

> **ID**: `172`
> **Category**: Feature
> **Priority**: 🟡 P2
> **Estimate**: ~3h
> **Assigned to**: unassigned
> **Session**: Validation cost in Cardine, 2026-11-05
> **Origin**: developer request

## Objective

Task 171 stops a failed attempt from running the complete set twice. Two more savings
remain under ADR decision 5, as amended on 2026-11-05. A command that failed last time
reruns only its failures before anything else on the next attempt. Declared preflight
commands, such as fast inventory tests, run before the complete set. A failure of either
ends the attempt early and counts toward a separate quick failure limit, not toward the
validation retry limit of 3.

## Acceptance Criteria

- [ ] **Declaration.** `validation.preflight` is an optional list of unique declared
  command IDs, and `taskDefaults.quickFailureLimit` is a positive integer, 10 in both
  presets. `src/cardine/shared/project.py`, `schemas/project-v1.schema.json`, and
  `schemas/task-state-v1.schema.json` accept both and freeze them in the contract, with
  the same per-task override as `validationRetryLimit`. A declaration without them
  validates as today.
- [ ] **Order of an attempt**, task and candidate validation: first the variant of every
  command whose last complete run in this task, of the same kind, failed; then the
  preflight commands; then the complete set. Any quick command exiting non-zero ends the
  attempt there, as a quick failure. A variant exiting with a status other than 0 or 1 is
  not a quick failure: the attempt continues to the complete set.
- [ ] **Separate limit.** Quick failures count in their own counter, shared by task and
  candidate validation like `failure_count`. Only a passing complete set resets it; a new
  commit or attempt does not. They never count toward `validationRetryLimit`. Reaching
  `quickFailureLimit` stops with `VALIDATION_RETRY_LIMIT`, whose detail names the quick
  failure limit and lists the failed quick commands.
- [ ] A passing attempt still requires a passing complete set in its last round. The
  first attempt of a task, and the first candidate attempt, run no variant.
- [ ] Each quick round is recorded like the rounds of task 171, appears in the handoff's
  `Measured validation` section, and converges after an interruption, proved by kill
  tests.
- [ ] Tests in `tests/test_validation_quick_commands.py` prove, with cheap literal
  commands: the order above; a failing variant or preflight runs no complete set and
  leaves `validationRetryLimit` untouched; the quick counter survives a new commit, resets
  only on a passing complete set, and stops at its limit with the detail above; a project
  without quick commands behaves as after task 171.
- [ ] `docs/PROJECT_DECLARATION.md` documents `validation.preflight`, `quickFailureLimit`,
  and the order of an attempt.
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
- [ ] `.meridian/` is unchanged, except `.meridian/tasks/172.json`, which only
  the installed `meridian task close 172` writes.
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
| `src/cardine/shared/project.py`, `schemas/project-v1.schema.json`, `schemas/task-state-v1.schema.json`, `src/cardine/tasks/contract.py`, `src/cardine/tasks/validation.py`, `src/cardine/lifecycle/validation.py`, `src/cardine/integration/candidate.py`, `docs/PROJECT_DECLARATION.md`, `tests/test_validation_quick_commands.py` | The files this task edits. |

## Technical Context

- Authority: ADR decision 5 and the paragraph on intermittent failures under decision
  12, both amended on 2026-11-05, and the developer's decision of the same day that quick
  failures have a limit of their own.
- Why the counter resets only on a passing complete set: a reset on each new commit
  would let an agent loop on cheap failures without end.
- `VALIDATION_RETRY_LIMIT` is reused, so `capabilities/stop-codes-v1.json` does not
  change. If its registry entry's text must name the new limit, that is a stale
  expectation under the standing clauses, not a scope change.
- The same files of tasks 168 and 169 stay out of bounds, as in task 171.
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

Mapping Meridian's candidate validation to `retry` and `preflight` in `cardine adopt`:
a later row. Reducing what a complete run executes. Other rows of the queue.

## Dependencies

- **Depends on**: 171
- **Blocks**: none

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
