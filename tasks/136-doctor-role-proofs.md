# Task 136 — Prove roles at runtime in doctor and update the host contract (H5d)

> **ID**: `136`
> **Category**: Feature
> **Priority**: 🔴 P1
> **Estimate**: ~3h
> **Assigned to**: unassigned
> **Session**: Work item 9 records, 2026-10-27
> **Origin**: maintenance

## Objective

Implement row H5d of `docs/HOST_INTEGRATION_PLAN.md`, work item 9 of
`docs/ADR_CARDINE_1_0.md`. The row fixes the scope, the files, the tests, and
the interruption boundaries; this record adds the developer's decisions and no
design.

## Acceptance Criteria

- [ ] Row H5d is implemented as its line in the excerpt describes it: Doctor
  runtime role proofs and host contract update.
- [ ] It applies the developer's decisions: D3 (2026-10-27): a host whose
  native policy doctor cannot show to enforce the protected paths and role
  actions is declared unsupported for role launches. No guarded transport
  adapter is built. D4 (2026-10-27): remove `cardine codex doctor` and
  `cardine codex configure` without aliases (ADR decision 1); invoking
  them fails with a migration message naming the unified `setup` and
  `doctor`.
- [ ] Only the files in the row's files column are edited, together with
  this task's own record and its archive, handoff, and state file. A test
  file outside the column may change only to update an expectation that this
  change made stale, without new behavior, and the handoff lists it. A
  repository check, test helper, or product module outside the column that
  fails only because this row's rename or route made its expectation stale
  is adapted to the new name or route in this task, minimally and without
  loosening it: no check is removed, skipped, or widened, and a route a gate
  cannot resolve still fails. The handoff lists each such file with the
  check that required it (coordinator clause of 2026-10-30). Any other file,
  or a change that adds behavior beyond that adaptation, stops the task
  before editing it and names the file, so that the coordinator splits the
  row.
- [ ] The row's tests exist and pass: Disposable fresh sessions; all
  denies/false-deny controls; work item 6/7 hook regressions; identifier
  guard removes only retired work item 9 allowances.
- [ ] Rule 4 of decision 14: Probe/result persistence cannot promote an
  incomplete run; interrupted proof repeats against same config digest;
  role activation gated on actual effective proof. Read-only checks repeat
  without any write.
- [ ] Every proof that a host rule, hook, or profile is in force comes from
  the host evaluating a probe or from an observed host decision, never
  from reading rule or policy text.
- [ ] Every test runs against disposable home directories. No step runs `setup
  --apply` against the real home directory or writes real host
  configuration.
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
- [ ] `.meridian/` is unchanged, except `.meridian/tasks/136.json`, which only
  the installed `meridian task close 136` writes.
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
| `Hsetup.py`, `Ttest_host_doctor.py`, `Ttest_host_transports.py`, `docs/HOST_CAPABILITY_CONTRACT.md`, `tests/test_no_meridian_identifiers.py` (5) | The files this row edits, as the plan lists them. |

## Authority excerpt

The parts of the plan and inventories this task needs, extracted from the
files on `main` when the record was written, so that the task reads them here
instead of the whole documents:

> From `docs/HOST_INTEGRATION_PLAN.md`, row H5d / :
>
> | H5d / 3h | Doctor runtime role proofs and host contract update | `Hsetup.py`, `Ttest_host_doctor.py`, `Ttest_host_transports.py`, `docs/HOST_CAPABILITY_CONTRACT.md`, `tests/test_no_meridian_identifiers.py` (5) | Disposable fresh sessions; all denies/false-deny controls; work item 6/7 hook regressions; identifier guard removes only retired work item 9 allowances | Probe/result persistence cannot promote an incomplete run; interrupted proof repeats against same config digest; role activation gated on actual effective proof | H5c, H4d |
>
## Technical Context

- The plan orders the rows serially. This task depends on 135 and is followed
  by work item 10; the plan's own dependency cell reads: H5c, H4d.
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

- **Depends on**: 135
- **Blocks**: work item 10

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
