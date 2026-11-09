# Cardine workflow guide

Cardine has one task lifecycle with two presets, `lean` and `governed`. The preset supplies defaults for independent review, task authority, and expected code surface; a task can override those defaults. `cardine run` needs an expected code surface in either preset.

For installation and a worked Contoso project, follow [First 5 minutes](README.md#first-5-minutes) in order. That walkthrough declares validation, adopts the project, sets up the host, creates a task, and runs it. For a new repository without the existing entry files, `cardine init` provides the same configuration options.

A task contract records its objective, acceptance criteria, dependencies, validation, and expected code surface. The developer assigns the task; an agent follows `cardine run` and its returned next commands until the task lands or a human decision is required. Review, when required, is independent. See [run commands](docs/RUN_COMMANDS.md) and [the task blueprint](tasks/TASK_BLUEPRINT.md).

The project workflow and language policy govern each project. Repository artifacts remain in English; the conversation language is configured in `LANGUAGE_POLICY.md`.
