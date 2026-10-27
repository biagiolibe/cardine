# Task 118 — Print only the generated status in the per-turn briefing (H1a)

> **ID**: `118`
> **Category**: Feature
> **Priority**: 🔴 P1
> **Estimate**: ~3h
> **Assigned to**: unassigned
> **Session**: Work item 9 records, 2026-10-27
> **Origin**: maintenance

## Objective

Implement row H1a of `docs/HOST_INTEGRATION_PLAN.md`, work item 9 of
`docs/ADR_CARDINE_1_0.md`. The row fixes the scope, the files, the tests, and
the interruption boundaries; this record adds the developer's decisions and no
design.

## Acceptance Criteria

- [x] Row H1a is implemented as its line in the excerpt describes it:
  Status-only briefing; budget removal and apostrophe regression.
- [x] Only the files in the row's files column are edited, together with this
  task's own record and its archive, handoff, and state file. A test file
  outside the column may change only to update an expectation that this
  change made stale, without new behavior, and the handoff lists it. If
  the change needs any other file, the task stops before editing it and
  names the file, so that the coordinator splits the row.
- [x] The row's tests exist and pass: Work item 6/7 fixture matrix above on
  both payload adapters.
- [x] Rule 4 of decision 14: Pure status read/output; interrupted output
  reruns without files or state changes. Read-only checks repeat without
  any write.
- [x] Every proof that a host rule, hook, or profile is in force comes from
  the host evaluating a probe or from an observed host decision, never
  from reading rule or policy text.
- [x] Every test runs against disposable home directories. No step runs `setup
  --apply` against the real home directory or writes real host
  configuration.
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
- [x] `.meridian/` is unchanged, except `.meridian/tasks/118.json`, which only
  the installed `meridian task close 118` writes.
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
| `Hbriefing.py`, `Ttest_single_workflow_briefing.py`, new `Ttest_host_briefing.py` (3) | The files this row edits, as the plan lists them. |

## Authority excerpt

The parts of the plan and inventories this task needs, extracted from the
files on `main` when the record was written, so that the task reads them here
instead of the whole documents:

> From `docs/HOST_INTEGRATION_PLAN.md`, row H1a / :
>
> | H1a / 3h | Status-only briefing; budget removal and apostrophe regression | `Hbriefing.py`, `Ttest_single_workflow_briefing.py`, new `Ttest_host_briefing.py` (3) | Work item 6/7 fixture matrix above on both payload adapters | Pure status read/output; interrupted output reruns without files or state changes | 115, SS7 |
>
## Technical Context

- The plan orders the rows serially. This task depends on 116 and is followed
  by 119; the plan's own dependency cell reads: 115, SS7.
- Plan conventions: `H` is `src/cardine/hosts/`, `T` is `tests/`, `C` is
  `src/cardine/cli.py`, `S` is `src/cardine/shared/models.py`; braces expand
  to individual files, and old and new endpoints of a rename both count. For
  every writing row, failure is injected before and after each listed durable
  effect, the same operation reruns, and the result is compared with a fresh
  install; foreign paths, symlinks, and changed user regions are preserved,
  and unknown ownership is never repaired by overwriting. Setup apply uses the
  pinned plan and input digest and the intent, staged, and result protocol of
  SR1b; a new host writer joins it instead of adding a second transaction
  mechanism.
- Developer decisions of 2026-10-27, binding on every row: D1 (2026-10-27):
  option B. Cardine ships exactly two skills, `cardine-project` (project
  administration: init, adopt, upgrade, setup, doctor) and `cardine-delivery`
  (task delivery: proceed and review); the preset stays project configuration.
  D2 (2026-10-27): require a verified minimum Codex runtime. Doctor proves the
  user-level turn event and the trusted user hook loader with a probe; below
  that runtime the briefing is reported unavailable. No session adapter and no
  project hook copy. D3 (2026-10-27): a host whose native policy doctor cannot
  show to enforce the protected paths and role actions is declared unsupported
  for role launches. No guarded transport adapter is built. D4 (2026-10-27):
  remove `cardine codex doctor` and `cardine codex configure` without aliases
  (ADR decision 1); invoking them fails with a migration message naming the
  unified `setup` and `doctor`.
- The plan estimates this row at 3 hours. If it turns out larger, finish the
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

Other rows of the plan, work item 10, the evaluation runs of decision 14 rule
5, and the installation surface deferred after 1.0.

## Dependencies

- **Depends on**: 116
- **Blocks**: 119

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

## Completion

Implemented status-only briefing output from one shared status snapshot. Caller
language, budget, setup advice and legacy queue blocks are discarded. Both host
payload adapters are exercised with disposable command bindings; actual runtime
activation is not claimed and remains the responsibility of H4c/H4d.

Validation passed on implementation commit `31c2bb59f2da5ae3e204ced78842568a002feea0`:
profile doctor, lean-delivery audit, clean-clone repository checks and all 1,846
tests (no failures, errors or skips), and `git diff --check`.
See `tasks/handoffs/118.md` for complete evidence and the corrected first attempt.
