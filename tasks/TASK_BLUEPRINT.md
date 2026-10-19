# Task [ID] — [Task Title]

> **ID**: `[NNN]`
> **Category**: [Architecture / Feature / Bugfix / Refactor / etc.]
> **Priority**: [🔴 P1 / 🟡 P2 / 🟢 P3]
> **Estimate**: [~1h / ~2h / etc.]
> **Assigned to**: [Claude CLI / unassigned]
> **Session**: [conversation ID or temporal reference]
> **Origin**: [optional: capability / friction / maintenance / release — `friction` fixes a problem caused by Meridian's own rules or tools]

## 🎯 Objective

[What needs to be done?]
[Why is it needed?]

## 📋 Acceptance Criteria

[A task is complete when:]

- [ ] The code compiles without errors.
- [ ] Feature X works as described.
- [ ] [Add specific criteria...]

## 📁 Relevant Files

| File | Role |
|------|------|
| `src/module/file.ts` | Role description. |

## 🧩 Technical Context

[Paste type definitions, interfaces, or describe the current code state here.]

- **Current behavior**: [What happens now?]
- **Desired behavior**: [What should happen afterward?]

## 🔨 Suggested Implementation

[Suggested steps for the AI agent]

1. [Step 1]
2. [Step 2]

```
// Optional example snippet
```

## ⚠️ Constraints and Considerations

- **Style**: Follow the conventions defined in `TECH_DESIGN.md`.
- **Performance**: [Any specific constraints]

## 🔗 Dependencies

- **Depends on**: [previous task ID or none]
- **Blocks**: [next task ID or none]

## 🤖 How to delegate this task to Claude CLI

```bash
claude "$(cat tasks/[NNN]-name.md)"$'\n\nExecute this task in the current project.'
```

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
