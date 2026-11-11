# Cardine workflow guide

Cardine has one task lifecycle with two presets, `lean` and `governed`. The preset supplies defaults for independent review, task authority, and expected code surface; a task can override those defaults. `cardine run` needs an expected code surface in either preset.

For installation and a first task, follow the [quick start](docs/QUICKSTART.md). It installs Cardine, runs `cardine init` (which initializes or adopts the project), and delivers a first task with your agent or from the terminal.

A task contract records its objective, acceptance criteria, dependencies, validation, and expected code surface. The developer assigns the task; an agent follows `cardine run` and its returned next commands until the task lands or a human decision is required. Review, when required, is independent. See [run commands](docs/RUN_COMMANDS.md) and [the task blueprint](tasks/TASK_BLUEPRINT.md).

The project workflow and language policy govern each project. Repository artifacts remain in English; the conversation language is configured in `LANGUAGE_POLICY.md`.
