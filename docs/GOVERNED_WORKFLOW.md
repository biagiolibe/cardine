# Governed workflow and execution evidence

Cardine provides one task lifecycle with two presets, `lean` and `governed`.
The `governed` preset defaults to required authority, expected code surface,
and independent review. Project defaults and task options can override these
settings. See [project declaration](PROJECT_DECLARATION.md).

A task records its objective, acceptance criteria, dependencies, expected code
surface, and validation commands. `cardine task new` registers the contract;
`cardine run <TASK-ID>` returns the next bounded step. The implementer works
in the returned worktree and commits the implementation. Cardine measures
validation and, when required, an independent reviewer records a verdict.
Verified landing updates the task to `done`.

The task state in `.cardine/tasks/<TASK-ID>.json` is authoritative. The queue
and plan are generated views. The execution evidence profile and validation
results support the task contract. See [run commands](RUN_COMMANDS.md) and
[lifecycle orchestration](LIFECYCLE_ORCHESTRATION.md).
