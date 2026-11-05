# Task 173 — Separate the recovery rules from their Git reads

> **ID**: `173`
> **Category**: Refactor
> **Priority**: 🟡 P2
> **Estimate**: ~3h
> **Assigned to**: unassigned
> **Session**: Test suite cost records, 2026-11-05
> **Origin**: developer request

## Objective

Four recovery decisions read Git and the filesystem and apply their rule in the same
function: `lease_stop_code`, `cleanup_branch_stop_code`, and `main_ahead_of_origin` in
`src/cardine/stops/causes.py`, and `landing_residue` in `src/cardine/integration/residue.py`.
Their tests therefore build a staged or landed task, and often run the CLI in a child
process, only to check one condition. For example, `test_lease_without_ownership_proof_stays_held`
runs a complete `worktree integrate stage` five times to check five lease fields. Split
each decision into a pure rule over a small facts value and a reader that gathers those
facts, as `resolve_run(RunFacts)` in `src/cardine/lifecycle/engine.py` already does. Test
every rule outcome without Git, and keep a real-Git test for each outcome that reaches a
person.

## Acceptance Criteria

- [ ] **Pure rules.** Each of the four decisions has a rule function that takes a frozen
  dataclass of facts and returns the same value as today: a stop code, a boolean, or the
  residue dictionary or `None`. A rule function performs no I/O, imports no Git helper,
  and reads no clock or environment. The public functions keep their names, signatures,
  and results, so their callers in `src/cardine/integration/merge.py`,
  `src/cardine/integration/cleanup.py`, and `src/cardine/worktree/closure_status.py`
  do not change.
- [ ] **Readers keep short-circuits.** A reader gathers only the facts its rule needs on
  that path, in the same order as today. For example, it reads `MERGE_HEAD` only when the
  merge head file exists and the lease matches. No path makes a Git call or file read that
  it does not make today, and the subprocess ceilings of `tests/test_command_context.py`
  hold unchanged.
- [ ] **Rule tests.** A new `tests/test_recovery_rules.py` covers every branch of every
  rule with literal facts: each lease mismatch, unreadable lease, live writer, matching
  and mismatching merge head; each cleanup condition; origin absent, equal, behind, and
  diverged; and each residue refusal (foreign owner, changed authority, wrong file set,
  wrong kind, wrong status, changed source, changed or symlinked staged bytes, foreign
  status line). It creates no repository and starts no process.
- [ ] **Real-Git tests kept per outcome.** In `tests/test_run_recovery.py`, these move to
  rule tests and leave the module, listed in the handoff:
  - the four `test_lease_without_ownership_proof_stays_held` subtests other than
    "other task", which stays as an end-to-end proof that a mismatched lease is held;
  - `test_staged_merge_that_no_longer_matches_the_lease_stays_held`, whose real
    merge-head case is already covered by `test_foreign_merge_with_an_owned_lease_is_never_aborted`;
  - the two direct `cleanup_branch_stop_code` assertions in
    `test_unmerged_or_protected_branches_are_never_a_partial_cleanup`, whose CLI part stays.

  Every other test in the module stays as it is. Each removed check has a rule test
  with the same input and the same expected result, and the handoff maps each one to
  its replacement.
- [ ] The handoff gives process counts and child CPU for `tests/test_run_recovery.py`
  before and after, measured the same way, and the coverage `total` before and after,
  with the difference explained by the moved checks and the new rule tests.
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
- [ ] `.meridian/` is unchanged, except `.meridian/tasks/173.json`, which only
  the installed `meridian task close 173` writes.
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
| `src/cardine/stops/causes.py`, `src/cardine/integration/residue.py`, `tests/test_recovery_rules.py` (new), `tests/test_run_recovery.py` | The files this task edits. |

## Technical Context

- Authority: the developer's request of 2026-11-05 to separate Git reads from
  decisions, after the coordinator's analysis of the five heaviest test modules.
- Why not every test: tests of kill recovery, concurrency, remotes, and real merges
  check what Git and the filesystem do, and stay on real Git. This task changes only
  tests that check a rule's condition.
- Time-of-check: the readers run at the same moments as today. Do not cache facts
  across calls or move a read before an effect.
- `src/cardine/lifecycle/validation.py` and `src/cardine/integration/candidate.py`
  belong to tasks 171 and 172, and `src/cardine/shared/git.py` and
  `src/cardine/lifecycle/receipts.py` to task 169. Do not edit them; `landing_residue`
  keeps calling the receipt helpers it calls today.
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

The same split for validation counting, candidate decisions, and cleanup effects:
later rows once 171, 172, and 169 land. Changing any rule's result. Other rows of the
queue.

## Dependencies

- **Depends on**: none
- **Blocks**: 170

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
