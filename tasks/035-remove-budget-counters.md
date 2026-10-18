# Task 035 — Remove the self-reported budget counters

> **ID**: `035`
> **Category**: Refactor
> **Priority**: 🔴 P1
> **Estimate**: ~3h
> **Assigned to**: unassigned
> **Session**: Work item 4 planning, 2026-10-18
> **Origin**: maintenance

## Objective

Apply the removals of ADR decision 5. Remove these:

- the self-reported counters: evidence captures, context expansions, and
  investigation scope;
- the ledger in the Git common directory;
- `budget show` and `budget spend`;
- the `Budget usage` handoff line.

Keep the task-first reading rules and the read guard. The validation retry
limit that replaces the counters belongs to work item 8.

## Acceptance Criteria

- [ ] The `budget` command, `cardine.shared.budget`, and
  `cardine.shared.budget_commands` are removed with their tests. So are the
  budget fields that other modules read: execution contract, preflight,
  recording, closure status, worktree checkout, template audit and router,
  and host setup. The handoff lists each reader and what replaced it.
- [ ] Template and workflow text no longer mentions budgets, budget caps,
  `budget spend`, `BUDGET_EXHAUSTED`, or the `Budget usage` handoff line. The
  text that keeps the read guard and the task-first reading rules stays.
  Template changes follow the pre-1.0 rule from task 031: capability version
  bump and baseline rewrite, with no migration.
- [ ] Every stop code that only budgets use is removed from
  `capabilities/stop-codes-v1.json`: `BUDGET_EXHAUSTED`,
  `BUDGET_ATTEMPT_REQUIRES_AUTHORIZATION`, `CONTRACT_EXHAUSTED`, and any
  other. The handoff lists them.
- [ ] `hooks/queue-briefing.sh` no longer prints the budget lines.
  `docs/CONTEXT_BUDGET_POLICY.md` is deleted, or reduced to the reading rules
  and renamed, and the handoff states which.
- [ ] The read guard (`hooks/read-guard.sh`, `scripts/codex_read_guard.py`,
  and `meridian hook read-guard`) behaves exactly as before, and its tests
  pass unchanged.
- [ ] `.meridian/` is unchanged.
- [ ] Every command under Validation passes.

## Relevant Files

| File | Role |
|------|------|
| `src/cardine/shared/budget.py`, `budget_commands.py` | Modules to remove. |
| `src/cardine/tasks/`, `src/cardine/worktree/`, `src/cardine/templates/`, `src/cardine/hosts/` | Budget readers. |
| `templates/workflows/`, `capabilities/` | Budget text and stop codes. |
| `hooks/queue-briefing.sh`, `docs/CONTEXT_BUDGET_POLICY.md` | Budget echo and policy. |

## Technical Context

- ADR decision 5 gives the usage data. Contoso recorded 261 spends across 83
  tasks, and no command ever emitted `BUDGET_EXHAUSTED`.
- `scripts/run_agent_evals.py` and `scripts/codex_read_guard.py` also mention
  budgets. The read guard stays; evaluations move in task 036.

## Out of scope

The validation retry limit (work item 8), and `.meridian/`.

## Dependencies

- **Depends on**: 034
- **Blocks**: 036

## Validation

- `python3 scripts/check_repository.py`
- `python3 scripts/meridian.py --framework-root . profile doctor meridian-self-hosting --project .`
- `python3 scripts/meridian.py --framework-root . audit --project . --mode lean-delivery --ci-profile meridian-self-hosting`
- `python3 scripts/run_tests.py --parallel`
- `python3 scripts/run_tests.py --parallel --clean-clone`
- `git diff --check`
