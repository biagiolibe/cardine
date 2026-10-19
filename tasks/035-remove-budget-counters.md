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
- [ ] Both template copies of `docs/CONTEXT_BUDGET_POLICY.md` retain their
  names and are reduced to reading rules and the read guard; the installed
  managed copy and shared-source hook stay identical to main.
- [ ] The read guard (`hooks/read-guard.sh`, `scripts/codex_read_guard.py`,
  and `meridian hook read-guard`) behaves exactly as before, and its tests
  pass unchanged.
- [ ] `.meridian/` is unchanged except for the state written by installed
  `meridian task close 035` to `.meridian/tasks/035.json`.
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
- `meridian --framework-root . profile doctor meridian-self-hosting --project .`
- `meridian --framework-root . audit --project . --mode lean-delivery --ci-profile meridian-self-hosting`
- `python3 scripts/run_tests.py --parallel`
- `python3 scripts/run_tests.py --parallel --clean-clone`
- `git diff --check`

## Developer amendment

> The criterion "`.meridian/` is unchanged" and the out-of-scope item `.meridian/` cover the manifest, `.meridian/baselines/`, and every other file under `.meridian/`, except `.meridian/tasks/035.json`. That file is written and staged by the installed `meridian task close 035`, as PROJECT_WORKFLOW.md requires, and is allowed. Before advance, verify with `git diff main -- .meridian` that the only entry is tasks/035.json.

The developer also directs this resume to use only installed `meridian`, never
`scripts/meridian.py` from the task worktree, and never run `upgrade` here.
The two CLI validation commands below therefore use installed `meridian`.
Task 036 and its amendment on main (6bfc410) remain untouched.

### Scope amendment resolving the policy/manifest conflict

> `.meridian/` stays fully unchanged, except `.meridian/tasks/035.json` written by `meridian task close 035`. The manifest is not updated. Therefore:
>
> 1. Policy rename deferred. The acceptance criterion "deleted, or reduced to the reading rules and renamed" becomes: in the two templates, `templates/workflows/{governed-sdd,lean-delivery}/docs/CONTEXT_BUDGET_POLICY.md` is reduced to the reading rules and the read guard, but keeps its file name. Remove the new `CONTEXT_READING_POLICY.md` files (in the templates and in `docs/`) and revert the references to the old name. Mentions of the file name `CONTEXT_BUDGET_POLICY.md` are allowed by the criterion "no longer mentions budgets"; the content is not.
> 2. Hook change deferred to work item 9. Remove the criterion "`hooks/queue-briefing.sh` no longer prints the budget lines" from this task: `hooks/queue-briefing.sh` is a `shared-source` surface with a digest in the manifest, and the coordinator's probe confirms that changing it fails the self-hosting doctor.
> 3. Restore unchanged (identical to main) every surface the manifest declares: `docs/CONTEXT_BUDGET_POLICY.md` (this repository's managed copy, which belongs to the installed Meridian), `hooks/queue-briefing.sh`, `hooks/hooks.json`, `hooks/read-guard.sh`, `docs/COMPLETION_REPORT_TEMPLATE.md`, `docs/EXECUTION_EVIDENCE_PROFILE.md`, `.codex/hooks.json`, `.codex/rules/meridian.rules`, `CLAUDE.md`, `AGENTS.md`, `PROJECT_WORKFLOW.md`, `LANGUAGE_POLICY.md`.
> 4. In `capabilities/catalog-v1.json`, the `meridian-self-hosting` profile keeps the same capabilities, IDs, and `managedSurface` (including `context-budgeting` → `docs/CONTEXT_BUDGET_POLICY.md`). Other catalog changes are allowed only if the doctor passes.
> 5. The rest of the task stays: removing the modules, the `budget` command, the readers, the stop codes used only by budgets, and the budget text in the templates (capability version bump, baseline rewrite, `requiredVersion` aligned to the Governed SDD version, no migration).
