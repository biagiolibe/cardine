---
name: meridian-lean-delivery-claude-code
description: Operate a small project, prototype, demo, or reversible low-risk change using Meridian Lean Delivery from Claude Code.
---

# Meridian Lean Delivery (Claude Code)

Use this skill when the project uses `LEAN_DELIVERY`, or when the developer
asks to bootstrap or operate Meridian's lightweight delivery workflow from
Claude Code. Do not use it for a repository whose `PROJECT_WORKFLOW.md`
declares `GOVERNED_SDD`.

Read `LANGUAGE_POLICY.md`, `PROJECT_WORKFLOW.md`, and `CLAUDE.md` before acting.
If a generated project also has `AGENTS.md`, keep its process rules aligned with
`CLAUDE.md`. `PROJECT_WORKFLOW.md` is the mode lock: before any mutation or
completion claim, confirm it declares `LEAN_DELIVERY`. Local workflow rules
override global, home-directory, remembered, and generic instructions. If local
authority is missing, contradictory, or unreadable, return `BLOCKED` without a
mutation.

Lean Delivery uses `[ ]` → `[/]` → `[x]` in `tasks/QUEUE.md`. Implement only a
task explicitly assigned by the developer; do not select a queue item
autonomously. Verify the task's acceptance criteria, stated validation, and
applicable baseline checks before marking it `[x]` or archiving it. Keep an
unverified or failed task `[/]` and report the blocker. Follow the project's Git
conventions; do not infer Governed SDD branch, review, author, or integration
controls. Reviews are read-only unless a separate fix is authorized.

When bootstrapping, ask the developer to choose `opaque` or `milestone` task
identity. `opaque` keeps task IDs as labels; `milestone` uses
`M<milestone>-<WORKSTREAM>-<ordinal>` for new IDs. Never choose by default;
pass the answer to `meridian setup --apply --task-identity <choice>` and note
that the project can later change it by editing the declaration.

After validation, commit the completed task record and handoff, then run `meridian task close <TASK-ID>` in the clean task worktree. It writes DONE state and stages the exact record archive and state file without committing; commit these closure records together. Never edit status or verdict fields by hand. On explicit Resume, if the record is already archived and its state is DONE, skip `meridian execution start --resume`: commit any staged closure records, then run `meridian worktree advance` with the validation evidence. Task branches own their own `.meridian/tasks/<TASK-ID>.json` in addition to their task record, exact archive, and handoff.

Before switching from prepare/check to execution start, consult the project’s
command location table in `docs/WORKTREE_LIFECYCLE.md#command-locations`
([framework reference](../../docs/WORKTREE_LIFECYCLE.md#command-locations)).

<!-- MERIDIAN:BEGIN capability=execution-boundaries v1 -->
After prepare and worktree check, run `meridian execution start <TASK-ID>
--project .` before substantive authority/source analysis, advisor consultation,
or implementation. Lean start verifies the worktree and preserves its existing
worktree-derived progress without adding IN_PROGRESS to machine state. Only
explicit Resume adds --resume after status/diff inspection and sole-writer
confirmation, unless the record is archived and state is DONE; in that case
skip execution start, commit staged closure records, and run worktree advance. Console, manual, and orchestrated workers use this same ordering;
read-only review/status requests never start work.
<!-- MERIDIAN:END -->
