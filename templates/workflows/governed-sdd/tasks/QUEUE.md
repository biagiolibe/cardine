# Task Execution Queue

Only `ACCEPTED` tasks satisfy dependencies. The developer assigns a specific queued task; agents do not select work autonomously.

New or materially revised tasks must follow `tasks/TASK_BLUEPRINT.md`. A task is startable without repository-wide exploration only when it names its authority, declared dependencies, expected code surface, acceptance criteria, validation, and out-of-scope boundary; dependencies must be `ACCEPTED` before implementation. Record completion evidence with `docs/COMPLETION_REPORT_TEMPLATE.md`, not in the queue row.

| Order | ID | Priority | Status | Review | Dependencies | Task file |
|---:|---|---|---|---|---|---|
| 1 | TASK-001 | P0 | QUEUED | REQUIRED | — | [TASK-001](TASK-001.md) |

A task branch never edits this file. `IN_PROGRESS`, `READY_FOR_REVIEW`, and
`CHANGES_REQUESTED` are recorded in the task record, and `meridian worktree
integrate stage` applies the status here once, on the merged candidate tree. For
`CHANGES_REQUESTED`, the reviewer records `IN_PROGRESS` in the task record
alongside the durable review record; that record, rather than chat output, is
the implementer's source of requested changes.

**Archiving.** `meridian worktree integrate stage` moves closed rows to
`tasks/QUEUE_ARCHIVE.md` on the merged candidate tree, keeping this table to
active and queued work only. `ACCEPTED` rows still satisfy dependencies from
their archived location; moving a row changes only where it is read from.
