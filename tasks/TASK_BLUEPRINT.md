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

## Validation

Before registering the task, search the tests for the behavior or text you
plan to change. Check callers and shared checks, including tests in modules
with different names. Choose the relevant modules and add each to `task-tests`
with a separate `--module` flag alongside the feature tests and standard
guards. The planner owns the selection. The full suite runs in CI.

- `task-tests`: `python3 scripts/run_tests.py --parallel --module <touched test modules> --module test_module_inventory --module test_layout --module test_no_meridian_identifiers --module test_text_gates --module test_stop_registry --module test_command_word`
- `adopt-466c2f308b48c766`: `git diff --check`
