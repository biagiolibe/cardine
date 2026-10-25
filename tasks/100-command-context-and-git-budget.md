# Task 100 — Resolve each command's context once and bound its Git subprocesses

> **ID**: `100`
> **Category**: Refactor
> **Priority**: 🔴 P1
> **Estimate**: ~3h
> **Assigned to**: unassigned
> **Session**: Coordinator code analysis, 2026-10-25
> **Origin**: maintenance

## Objective

Product functions receive a path and rebuild the same context from it, through
Git subprocesses and file reads, many times within one operation. The
coordinator measured this on `main` at 4a26053 with the
`tests/test_run_delivery.py` fixture:

| Operation | Subprocesses | Time |
|---|---:|---:|
| `deliver` | 161 | 2.3 s |
| repeated `deliver` (idempotent no-op) | 84 | 1.2 s |
| task state read | 5 | 0.08 s |
| console snapshot, one task | 33 | 0.46 s |

One `deliver` runs `git worktree list` 53 times and `git rev-parse
--git-common-dir` 38 times, calls `resolve_project_locations` 13 times,
`read_project_declaration` 23 times, and `resolve_task_identity` 8 times.
`observed_authority` (`src/cardine/lifecycle/receipts.py`) reads and hashes
the whole runtime (164 files, about 1.3 MB, about 10 ms) on every call, and
receipt verification calls it about fifty times per `deliver`. Product Git
calls go through seven different helpers, so nothing can count or reuse them.

Every `cardine` command an agent runs pays this cost, and decision 14 rule 4
makes agents rerun commands. The rows from RE4a onward add receipt checks, and
RE7a routes the per-turn console through verified facts, so the cost would
grow with each row. This task builds the context once per command and bounds
the subprocesses with a test, without weakening any check.

## Acceptance Criteria

- [x] **One Git gateway.** Every Git subprocess in `src/cardine`, outside
  `cardine.legacy`, goes through one function in `cardine.shared.git`. A
  test parses the product sources and fails on any other `subprocess` call
  whose command starts with `git`.
- [x] **One context per command.** Each lifecycle command builds one immutable
  context at its entry point, extending `resolve_run_locations`. It holds
  the primary checkout, the task worktree, the Git common directory, the
  canonical task identity, the project declaration, the worktree root, and
  the runtime digest. Functions reached from the command receive this
  context instead of resolving it again from a path. Signatures that the
  CLI or other entry points call keep working.
- [x] **Runtime digest once.** The runtime digest that `observed_authority`
  uses is computed at most once per process.
- [x] **Read-only scope, never across a write.** Git facts such as the
  worktree list, the common directory, and refs are read once per
  read-only verification pass. No reused value outlives a write by the
  same process: `prepare`, `cleanup`, `write_operation`, a commit, a
  merge, or any other effect closes the scope first. A test performs a
  write inside one command and proves that the next read sees the new
  fact. Nothing reused is written to disk.
- [x] **No-op replay.** A repeated `deliver` whose current receipt already
  covers the same delivery returns the same result after one verification
  pass and writes nothing.
- [x] **Subprocess budget test.** A test counts the subprocesses that the
  gateway starts for `deliver`, a repeated `deliver`, a task state read,
  `prepare`, and the console snapshot on a fixture of the same shape. It
  fails when a count exceeds its ceiling. The handoff records each count
  before and after the change. `deliver` and the repeated `deliver` need
  at most half of their measured counts; no other count grows. The test in
  `tests/test_console_snapshot.py` that allows one ref check per open task
  is the precedent.
- [x] **No check is weakened.** Verification still runs on every command.
  Every existing receipt, authority, forgery, scope, and interruption test
  passes with its assertions unchanged. If a ceiling cannot be met without
  dropping a check, the check stays and the handoff names the subprocesses
  it needs.
- [x] `test_snapshot_still_reads_this_repository` in
  `tests/test_legacy_meridian_installation.py` stops depending on this
  repository having an open task. Today it fails on `main` whenever the
  queue is empty. It asserts that the snapshot loads this repository's
  installation and its task records, whether or not a task is open.
- [x] This repository's own lifecycle keeps running on the installed Meridian
  1.4.1; this task changes product code and tests only.
- [x] The frozen files stay unchanged: `CLAUDE.md`, `AGENTS.md`,
  `PROJECT_WORKFLOW.md`, `LANGUAGE_POLICY.md`,
  `docs/COMPLETION_REPORT_TEMPLATE.md`, `docs/CONTEXT_BUDGET_POLICY.md`,
  `docs/EXECUTION_EVIDENCE_PROFILE.md`, `docs/WORKTREE_LIFECYCLE.md`,
  `.codex/hooks.json`, `.codex/rules/meridian.rules`, `hooks/hooks.json`,
  `hooks/queue-briefing.sh`, `hooks/read-guard.sh`, and the `meridian
  worktree` line of `.codex/rules/local.rules`. No task runs the
  checkout's `setup --apply` against the real home directory or creates
  `.cardine/` in this repository.
- [x] `.meridian/` is unchanged, except `.meridian/tasks/100.json`, which only
  the installed `meridian task close 100` writes.
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
| `src/cardine/shared/git.py` | The gateway and the existing scoped worktree cache (`_SHARED_WORKTREES`). |
| `src/cardine/lifecycle/receipts.py` | `observed_authority`, `require_authority`, `verify_receipts`, and a local `_git`. |
| `src/cardine/lifecycle/engine.py`, `lifecycle/delivery.py`, `lifecycle/source.py`, `lifecycle/execution.py` | `resolve_run_locations`, delivery, and its callers. |
| `src/cardine/tasks/identity.py`, `src/cardine/shared/project.py` | Location, identity, and declaration resolution. |
| `src/cardine/console/snapshot.py`, `src/cardine/worktree/checkout.py` | Other Git helpers and the console path. |
| `tests/test_run_delivery.py`, `tests/test_console_snapshot.py`, `tests/test_legacy_meridian_installation.py` | The measured fixture, the budget precedent, and the snapshot test. |

## Technical Context

- Coordinator profile of one `deliver`, 2026-10-25: Git calls by subcommand
  were `worktree list` 53, `rev-parse --git-common-dir` 38, `merge-base
  --is-ancestor` 15, `rev-parse --verify` 13, `check-ref-format --branch` 8,
  `rev-parse HEAD` 7. Product helpers that run Git today: `git_output` and
  `_run_git` in `shared/git.py`, and `_git` in `lifecycle/receipts.py`,
  `lifecycle/delivery.py`, and `console/snapshot.py`, plus `_git_result` and
  `_git_optional`.
- Reused facts stay in memory for one command (ADR decisions 13 and 14). A
  verification result or digest saved to disk would be a new artifact an agent
  could rewrite, and a value reused after a write would read a stale fact.
- Task 101, written after this task integrates, splits the interruption tests
  whose subTest loop repeats the whole setUp, measured on the new hot path.
- If `worktree advance` stops because another task holds the integration lease
  in the primary checkout, that is not a decision for the developer: wait
  until the other integration finalizes or aborts, then rerun the same
  `advance` command.

## Out of scope

Splitting or rescheduling tests (task 101); lazy imports in the CLI; migrating
tests away from the `scripts/cardine_cli.py` adapter; `cardine.legacy`; any
change to what a receipt, authority, or scope check accepts.

## Dependencies

- **Depends on**: 095
- **Blocks**: the work item 8 task records from RE4a onward

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
