# Task 071 — Report the stop detail in worktree advance output

> **ID**: `071`
> **Category**: Bug
> **Priority**: 🔴 P1
> **Estimate**: ~2h
> **Assigned to**: unassigned
> **Session**: Defect triage, 2026-10-22
> **Origin**: maintenance

## Objective

`cardine worktree advance` returns a JSON result with `stop_code` and
`resume`, but drops the detail of the stop it caught. At C6, a
`TASK_STATE_INVALID` raised by `read_task_state` carries the failing field
(for example `transitions[1].to: allowed ['in_review']; found 'done'`), and
the agent sees only the code. The same loss happens in every `stopped(...)`
path of `src/cardine/lifecycle/closure.py`.

The defect was found on Meridian 1.4.1 in a governed project
(`scripts/meridian.py`, the C6 branch of `worktree advance`), and Cardine
inherited the same code. Make the advance result carry the detail of every
stop, so that the agent can act on it without rerunning single-step commands.

## Acceptance Criteria

- [x] Every result of `cardine worktree advance` that has a non-null
  `stop_code` also has a `stop_detail` string: the detail of the caught
  stop as `format_stop` would print it after the code, including the file
  and field that `read_task_state` names. Results without a stop have
  `stop_detail: null`. The result keeps `version: 1`, because the field is
  added and no field changes meaning.
- [x] A test drives `worktree advance` to C6 with a task state whose recorded
  history violates its review policy, and asserts that `stop_detail` names
  the state file and the failing `transitions[...]` field. A second test
  covers a stop returned through `stopped(...)` in another step.
- [x] The steps that build a stop from a status code with no caught error (for
  example `VALIDATION_FAILED` at C2) set `stop_detail` from the closure
  status reason when one exists, and never to an invented text.
- [x] `docs/RUN_ENGINE_PLAN.md` already gives `cardine run` a `stop.detail`
  field; the handoff states that this change matches it, and changes
  nothing in that plan.
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
- [x] `.meridian/` is unchanged, except `.meridian/tasks/071.json`, which only
  the installed `meridian task close 071` writes.
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
| `src/cardine/lifecycle/closure.py` | `result(...)` and `stopped(...)` of `worktree advance`, and the C6 branch. |
| `src/cardine/tasks/state.py` | `read_task_state` and the detail of `TASK_STATE_INVALID`. |
| `src/cardine/stops/` | `format_stop` and the stop error type. |
| `tests/test_worktree_lifecycle.py`, `tests/test_task_integration_state.py` | Existing advance and integration-state tests. |
| `docs/RUN_ENGINE_PLAN.md` | Output contract of `cardine run`, with `stop.detail`. |

## Technical Context

- The two other parts of the report are already closed in Cardine. The first
  transition stores the resolved contract in the state, and
  `review_is_required` reads the review policy from it, so transition and
  integration use one source (task 053). `cardine task new` creates the record
  and its state together (task 066), so a new task needs no hand-written state
  file.
- Meridian 1.4.x receives fixes only for blocking defects (ADR decision 10).
  This defect has a workaround and its origin is a hand-written state file, so
  it gets no Meridian fix.
- Task 069 (single source SS6) also edits `src/cardine/lifecycle/closure.py`;
  it waits for this task.

## Out of scope

Changing the stop registry, the stop codes, or `format_stop`; the `cardine
run` engine of work item 8; any Meridian release.

## Dependencies

- **Depends on**: 066
- **Blocks**: 069

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

- `python3 scripts/check_repository.py`
- `meridian profile doctor meridian-self-hosting --project .`
- `meridian audit --project . --mode lean-delivery --ci-profile meridian-self-hosting`
- `python3 scripts/run_tests.py --parallel`
- `python3 scripts/run_tests.py --parallel --clean-clone`
- `git diff --check`
