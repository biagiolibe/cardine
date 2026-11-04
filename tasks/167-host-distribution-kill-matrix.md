# Task 167 — Reduce the cost of the host plugin kill matrix

> **ID**: `167`
> **Category**: Refactor
> **Priority**: 🟡 P2
> **Estimate**: ~2h
> **Assigned to**: unassigned
> **Session**: Test suite cost records, 2026-11-04
> **Origin**: maintenance

## Objective

`test_kill_before_and_after_every_copy_and_publication_converges` in
`tests/test_host_distribution.py` took 1,409 s, about 10% of the whole suite, for
one test. It runs the real build in new Python processes before and after each copy
of the real payload, which has 225 entries. The copies go through one loop. Prove the
loop's boundaries on a small payload and keep the real payload for the boundaries
that differ.

## Acceptance Criteria

- [ ] The test kills before and after every copy of a synthetic payload of 3 files
  (first, middle, last in copy order), with the same checks as today: exit 93,
  intent retained, resume keeps the operation ID, identical inventory, no stage
  directory, identical repeat, foreign file untouched.
- [ ] The same checks run on the real `plugin.payload()` for the `assembly` and
  `publication` boundaries and for the first and last real copy.
- [ ] Before reducing, confirm that the copy path of `scripts/build_host_plugin.py` does
  not branch on a file's name or type. If it does, each such case keeps a boundary in
  the test, and the handoff names it.
- [ ] A deliberately broken resume on a middle copy of the synthetic payload makes the
  test fail. The handoff reports this mutation check. The coverage `total` is
  unchanged, and the handoff reports the test's time before and after.
- [ ] Only the files under Relevant Files are edited, together with this
  task's own record and its archive, handoff, and state file. A test file
  outside that list may change only to update an expectation that this change
  made stale, without new behavior, and the handoff lists it. Any other file,
  or new behavior beyond this record, stops the task before editing it and
  names the file.
- [ ] Every test runs against disposable projects and disposable home
  directories. No step runs `setup --apply` against the real home directory or
  writes real host configuration.
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
- [ ] `.meridian/` is unchanged, except `.meridian/tasks/167.json`, which only
  the installed `meridian task close 167` writes.
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
| `tests/test_host_distribution.py`, `scripts/build_host_plugin.py` (only a parameter or seam for the payload the test supplies, with unchanged defaults) | The files this task edits. |

## Technical Context

- This is the one task in this phase where boundaries are sampled rather than kept.
  It does not set a precedent for other matrices.
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
