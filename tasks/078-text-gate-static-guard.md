# Task 078 — Add the text gate static guard as a ratchet (decision 13)

> **ID**: `078`
> **Category**: Test
> **Priority**: 🔴 P1
> **Estimate**: ~2h
> **Assigned to**: unassigned
> **Session**: Decision 13 planning, 2026-10-22
> **Origin**: maintenance

## Objective

Implement row G1 of `docs/TEXT_GATE_INVENTORY.md`, section "Static guard".
Decision 13 of `docs/ADR_CARDINE_1_0.md` asks for a static test that lists
every product read of record, handoff, report, queue, or plan text and fails
on a new one. The test lands as a ratchet: the known violations are a table
that can only shrink, so the removals of work items 7 and 8 proceed without
any new read slipping in.

## Acceptance Criteria

- [ ] `tests/test_text_gates.py` scans every `src/cardine/**/*.py` and the
  scripts product code imports with `ast`, and applies the three rules of
  the inventory section: named readers, text read from disk through
  record, handoff, review, queue, plan, or report paths, and options that
  carry declared results (`*-exit-code`, `--accepted`, and the others
  listed there).
- [ ] Findings are keyed by file, qualified function, rule, and name, never by
  line number. The permanent allowlist holds exactly the three classes of
  decision 13: the contract creation path, the managed-text integrity
  checks, and `cardine.legacy`.
- [ ] The known-violation table maps every key to its T-ID in
  `docs/TEXT_GATE_INVENTORY.md`. The test fails when a finding is in
  neither list, when a known violation no longer exists but its row
  remains, or when a T-ID in the table is missing from the inventory.
- [ ] The table matches the code on the `main` this task starts from, after
  tasks 069 and 072. Entries those tasks removed are absent from the
  table, and the inventory marks them as removed by those tasks without
  other changes.
- [ ] A test proves each failure mode with a synthetic source tree: a new
  reader, a stale table row, and an unknown T-ID.
- [ ] The handoff gives the table size by row of destination (SS7, N1, N2, N3,
  RE3, RE5, RE6, work item 9), so that later records can cite it.
- [ ] This repository's own lifecycle keeps running on the installed Meridian
  1.4.1; this task changes product code, product templates, and tests
  only.
- [ ] The frozen files stay unchanged: `CLAUDE.md`, `AGENTS.md`,
  `PROJECT_WORKFLOW.md`, `LANGUAGE_POLICY.md`,
  `docs/COMPLETION_REPORT_TEMPLATE.md`, `docs/CONTEXT_BUDGET_POLICY.md`,
  `docs/EXECUTION_EVIDENCE_PROFILE.md`, `docs/WORKTREE_LIFECYCLE.md`,
  `.codex/hooks.json`, `.codex/rules/meridian.rules`, `hooks/hooks.json`,
  `hooks/queue-briefing.sh`, `hooks/read-guard.sh`, and the `meridian
  worktree` line of `.codex/rules/local.rules`. No task runs the
  checkout's `setup --apply` against the real home directory or creates
  `.cardine/` in this repository.
- [ ] `.meridian/` is unchanged, except `.meridian/tasks/078.json`, which only
  the installed `meridian task close 078` writes.
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
| `docs/TEXT_GATE_INVENTORY.md` | Authority: section "Static guard" and every T-ID. |
| `docs/ADR_CARDINE_1_0.md` | Decision 13. |
| `src/cardine/`, `scripts/codex_read_guard.py`, `scripts/stop_audit.py` | Code to scan. |
| The existing import-graph test for `cardine.legacy` | Reused for the legacy boundary. |

## Technical Context

- It starts after tasks 069 and 072 integrate, because they remove entries;
  starting earlier would make their integration fail on a stale table. Every
  later task that removes a text gate deletes its entries from the table as an
  acceptance criterion.
- If `worktree advance` stops because another task holds the integration lease
  in the primary checkout, that is not a decision for the developer: wait
  until the other integration finalizes or aborts, then rerun the same
  `advance` command.

## Out of scope

Removing any violation; changing production code.

## Dependencies

- **Depends on**: 069, 072
- **Blocks**: 079

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
