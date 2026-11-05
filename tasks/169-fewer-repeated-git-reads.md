# Task 169 — Reuse Git reads that a command cannot have changed

> **ID**: `169`
> **Category**: Refactor
> **Priority**: 🟡 P2
> **Estimate**: ~3h
> **Assigned to**: unassigned
> **Session**: Test suite cost records, 2026-11-04
> **Origin**: maintenance

## Objective

One delivery test makes 865 Git calls, of which 85 are distinct. Some repeats are
needed, because state changes between them. These are not: writing a state file discards
every read in the command, including refs (67 of 113 invalidations); branch-name checks and
ancestry of two full object IDs cannot change; two entry points run without a scope. A
coordinator prototype of the three changes below reduces that test to 517 calls. Real commands get
faster by the same amount.

## Acceptance Criteria

- [ ] **Narrow invalidation.** `write_state_bytes` calls a new
  `invalidate_tree_facts()` in `src/cardine/shared/git.py`. It keeps only Git reads of
  `rev-parse`, `merge-base`, `rev-list`, `for-each-ref`, `log`, `cat-file`,
  `check-ref-format`, `ls-remote`, `worktree list`, `remote`, and `config`. Status, diff,
  `ls-files`, `show`, and every `scoped_observation` entry are discarded, as today.
- [ ] **Stable reads.** Within a command scope, these survive effects run by `_run_git`:
  `check-ref-format --branch`, and `merge-base --is-ancestor` with two full object IDs,
  exit 0 or 1 only; and, per resolved root, `rev-parse --git-common-dir` and `rev-parse
  --git-path`, success only, discarded by any worktree effect. A call with an explicit `env`
  is not reused.
- [ ] **Missing scopes.** `stage_task_integration` and `receipts.write_operation` are
  `@scoped_command`. Any read made before waiting for the integration lease or a task lock
  is discarded once the wait ends, so that a waiter never decides from a value read before
  it waited. Add this invalidation if the code does not already do it.
- [ ] Tests prove each case fails safe, in `tests/test_command_context.py`: after a state file
  write a ref read is reused and `status` is not; after a commit `rev-parse HEAD` is new; after
  `worktree add` or `worktree remove` the list and path reads are new; an ancestry result on
  a full object ID is reused across an effect and one on a branch name is not; a failed
  read is not reused after an effect; a second process moving `main` during a lock wait is seen by the waiter.
- [ ] The ceilings in `tests/test_command_context.py` are lowered to the new measured
  values, each with its previous value in the comment. No ceiling rises. No gate reads a
  reused value that the rule above discards.
- [ ] The handoff reports Git calls before and after for
  `test_run_cleanup.CleanupTest.test_push_cleanup_and_identical_repeat`, and the full
  clean-clone result. Authority and receipt checks (`require_authority`,
  `observed_authority`) get no other caching in this task.
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
- [ ] `.meridian/` is unchanged, except `.meridian/tasks/169.json`, which only
  the installed `meridian task close 169` writes.
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
| `src/cardine/shared/git.py`, `src/cardine/tasks/state_core.py`, `src/cardine/integration/merge.py`, `src/cardine/lifecycle/receipts.py`, `tests/test_command_context.py`, `tests/fixtures/module_split_baseline.json` | The files this task edits. |

## Technical Context

- The prototype passed `test_command_context`, `test_worktree_lifecycle`,
  `test_run_cleanup`, `test_run_receipts`, `test_run_recovery`, `test_run_integration`,
  `test_review_verdict`, and the repository check. The full suite did not run, and the lock
  wait case is not proved by it: treat that as open.
- `_read_only` and the existing `invalidate_facts` semantics for Git effects stay as
  they are: any Git effect still ends everything except the stable reads above.
- The order of reads in a test helper that counts calls may change; a ceiling test
  is the measure, not a list of calls.
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

Reducing what the counted validation runs, skipping tests, marking tests as
optional, and any change to the coverage `total` that the handoff cannot
justify. Other rows of the queue.

## Dependencies

- **Depends on**: none
- **Blocks**: 170

## Coordinator decision — 2026-11-05

`invalidate_facts()` clears every fact at external effect seams. Stable reads survive
only Git effects run by `_run_git`. Failed reads may be cached within a read-only
pass but never survive invalidation; full-object-ID ancestry exit 1 is a stable
result. No additional source files are in scope.

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
