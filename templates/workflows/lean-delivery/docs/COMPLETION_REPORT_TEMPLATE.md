# Concise Completion Report

Use this handoff after validation. Keep it short and make every deviation explicit.
Save it at `tasks/handoffs/<TASK-ID>.md`.

```md
## Completion Report — <TASK-ID>

- Files changed: `<paths>`
- Branch: `<task-branch>`
- Worktree: `<task-worktree path relative to the worktree root>`
- Validation: `<exact commands run with their exit status>`
- Validation skips: `<none | test name — test-reported reason; reported by `command`>`
- Manual verification: `<none | evidence and result>`
- Acceptance criteria: `<all met | list criterion IDs/status>`
- Budget usage: `<diagnostics; captures; context expansions; investigation scope>`
- Isolated exploration: `<none | recorded question(s) and finding(s)>`
- Rule discrepancies: `<none | rule, command result, and what was followed>` (optional)
- Blockers/deviations: `<none | concrete issue and reason>`
```

A named sandbox skip is not a passing result for an unrelated failure. Record a
skip only when the test itself names it, including the test-reported reason and
the command that reported it; otherwise treat validation as failed.
