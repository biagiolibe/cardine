---
name: meridian-lean-delivery
description: Operate a small project, prototype, demo, or reversible low-risk change using Meridian Lean Delivery without governed-SDD overhead.
---

# Meridian Lean Delivery

Use this skill when the project uses `LEAN_DELIVERY`, or when the developer
asks to bootstrap or operate Meridian's lightweight delivery workflow. Do not
use it for a repository whose `PROJECT_WORKFLOW.md` declares `GOVERNED_SDD`.

Read the target project's `LANGUAGE_POLICY.md`, `PROJECT_WORKFLOW.md`, and
`AGENTS.md` before acting. `PROJECT_WORKFLOW.md` is the mode lock: before any
file edit, Git mutation, task selection, or completion claim, confirm it
declares `LEAN_DELIVERY`. Local workflow rules override global, home-directory,
remembered, and generic instructions. If local authority is missing,
contradictory, or unreadable, return `BLOCKED` without making a mutation.

Lean Delivery uses `[ ]` → `[/]` → `[x]` and keeps the operational queue in
`tasks/QUEUE.md`. Work only on the task explicitly assigned by the developer;
never choose the next task autonomously. Before marking completion, verify
acceptance criteria and run task validation plus applicable project baseline
checks. Keep a failed or insufficiently verified task `[/]`, report the
blocker, and do not archive it.

Keep scope proportional: use a task file for work that needs context; allow a
quick task only when it is small, reversible, and immediately verifiable.
Follow project Git conventions rather than inferring governed-SDD branch,
reviewer, author, or integration controls. A review is read-only unless the
developer separately authorizes a fix.

When bootstrapping a project, ask the developer to choose `opaque` or
`milestone` task identity. Explain that `opaque` keeps task IDs as labels while
`milestone` uses `M<milestone>-<WORKSTREAM>-<ordinal>` for new IDs. Never
choose on the developer's behalf; pass the selected value to `meridian setup
--apply --task-identity <choice>`, and explain that the file can later be
edited to change the choice.

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
