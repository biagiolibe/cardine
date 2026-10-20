# Task 061 — Rename the capability markers and restart every capability at v1 (work item 5b)

> **ID**: `061`
> **Category**: Refactor
> **Priority**: 🔴 P1
> **Estimate**: ~3h
> **Assigned to**: unassigned
> **Session**: Work items 5b and 7 planning, 2026-10-20
> **Origin**: maintenance

## Objective

Finish work item 5b of `docs/ADR_CARDINE_1_0.md`: the capability markers
become `CARDINE:BEGIN` and `CARDINE:END`, the router pointer becomes
`CARDINE:CLAUDE-AGENTS-POINTER`, and every live capability restarts at `v1`,
as the developer decided on 2026-10-19.

## Acceptance Criteria

- [ ] Every marker under `templates/single/` uses the Cardine syntax at `v1`.
  Every live capability in `capabilities/markers-v1.json` has
  `requiredVersion: 1`, and `capabilities/marker-baselines.json` is
  rewritten to match. Retired entries keep their historical values; the
  handoff says why they are kept.
- [ ] The product's marker patterns (`cardine.shared.constants`,
  `cardine.templates.markers`, `marker_history`, `audit`, `files`,
  `cardine.tasks.identity`, `cardine.shared.models`, and
  `scripts/check_repository.py`) read only the Cardine syntax. A test
  proves that a `MERIDIAN:BEGIN` block is not recognized by the product
  and is not upgraded.
- [ ] `cardine.legacy.meridian_installation` keeps the Meridian patterns.
  `load_meridian_snapshot` still reads this repository, including the
  `execution-assets` block of its frozen `PROJECT_WORKFLOW.md`, through an
  injected reader in the same way that task 052 injected the workflow
  resolver. No product command imports `cardine.legacy`.
- [ ] `tests/test_codex_rules.py` no longer compares the frozen
  `.codex/rules/meridian.rules` copy with the templates (rename plan
  choice 2).
- [ ] The archive fixtures `tests/fixtures/release-1.1.49-governed-sdd.tar.gz`
  and `tests/fixtures/release-1.3.0-upgrade.tar.gz` are retired with the
  tests that only they serve, or read through `cardine.legacy` (rename
  plan choice 3). The handoff lists which.
- [ ] The Codex profile block `# MERIDIAN:BEGIN worktree-permissions` and the
  rules markers in `cardine.hosts.codex` and `cardine.hosts.setup` are not
  changed: work item 9 replaces them.
- [ ] The marker allowances of `tests/test_no_meridian_identifiers.py` are
  removed; each remaining group 2 entry names work item 9 or work item 10.
- [ ] The frozen files stay unchanged: `CLAUDE.md`, `AGENTS.md`,
  `PROJECT_WORKFLOW.md`, `LANGUAGE_POLICY.md`,
  `docs/COMPLETION_REPORT_TEMPLATE.md`, `docs/CONTEXT_BUDGET_POLICY.md`,
  `docs/EXECUTION_EVIDENCE_PROFILE.md`, `docs/WORKTREE_LIFECYCLE.md`,
  `.codex/hooks.json`, `.codex/rules/meridian.rules`, `hooks/hooks.json`,
  `hooks/queue-briefing.sh`, `hooks/read-guard.sh`, and the `meridian
  worktree` line of `.codex/rules/local.rules`. No task runs the
  checkout's `setup --apply` against the real home directory or creates
  `.cardine/` in this repository.
- [ ] `.meridian/` is unchanged, except `.meridian/tasks/061.json`, which only
  the installed `meridian task close 061` writes.
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
| `templates/single/`, `capabilities/markers-v1.json`, `capabilities/marker-baselines.json` | Markers and versions. |
| `src/cardine/shared/constants.py`, `src/cardine/templates/`, `src/cardine/tasks/identity.py`, `src/cardine/shared/models.py`, `scripts/check_repository.py` | Marker patterns. |
| `src/cardine/legacy/meridian_installation.py`, `src/cardine/console/snapshot.py` | The Meridian reader and the snapshot injection. |
| `tests/test_codex_rules.py`, `tests/fixtures/release-*.tar.gz`, `tests/test_no_meridian_identifiers.py` | Tests named by the rename plan. |

## Technical Context

- `docs/RENAME_PLAN.md`, section "Choices in this plan that make 5b, 6, or 10 harder", items 1 to 3, lists what 5b must change together.
- On `main` at `d236eee`, `MERIDIAN:BEGIN` appears 65 times under `templates/`
  and in 10 product source files, and 52 capabilities are live.
- No project runs Cardine before 1.0, so restarting at `v1` needs no migration
  (decision 1).

## Out of scope

Skills, slash commands, the plugin, the Codex rules file and profile (work
item 9), conversion of Meridian projects (work item 10), and every frozen
file.

## Dependencies

- **Depends on**: 060
- **Blocks**: work item 7

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
