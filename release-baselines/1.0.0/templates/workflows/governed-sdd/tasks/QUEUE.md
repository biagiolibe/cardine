# Task Execution Queue

Only `ACCEPTED` tasks satisfy dependencies. Choose the highest-priority queued task whose dependencies are all accepted.

New or materially revised tasks must follow `tasks/TASK_BLUEPRINT.md`. A task is startable without repository-wide exploration only when it names its authority, declared dependencies, expected code surface, acceptance criteria, validation, and out-of-scope boundary; dependencies must be `ACCEPTED` before implementation. Record completion evidence with `docs/COMPLETION_REPORT_TEMPLATE.md`, not in the queue row.

| Order | ID | Priority | Status | Review | Dependencies | Task file |
|---:|---|---|---|---|---|---|
| 1 | TASK-001 | P0 | QUEUED | REQUIRED | — | [TASK-001](TASK-001.md) |

Update a task's status here in the same commit that updates its task file.
