# Cardine quick start

Initialize or adopt a project, connect your agent host, and deliver a first
task. See the [README](../README.md#first-5-minutes) for the complete
first-task example.

## Prerequisites

- macOS or Linux, Python 3.12 or later, Git, and pipx.
- An installed and authenticated Claude Code or Codex host.
- A Git repository on `main`, a writable `origin`, a Git author identity, and
  a test command that passes on `main`. Landing pushes `main`.

## Install

Install the latest release from a clone:

```bash
git clone --branch v0.9.0 https://github.com/biagiolibe/cardine ~/src/cardine
pipx install --editable ~/src/cardine
cardine --version
```

## Initialize or adopt

In the Contoso repository, put the project's actual validation commands in
`~/contoso-validation.json`. For example, if its test command is
`python3 -m unittest`:

```json
{"commands": {"test": "python3 -m unittest"},
 "baseline": ["test"],
 "candidate": {"REUSE": [], "BOUNDED": ["test"], "FULL": ["test"]}}
```

Choose `lean` or `governed`: both use the same lifecycle. Governed defaults to
independent review and requires an authority field; lean does not. Each task
can override the preset defaults. Both need an expected code surface for
`cardine run`.

Preview adoption of an existing project, then apply the plan:

```bash
cardine adopt --project . --check --name "Contoso API" --slug contoso-api \
  --preset lean --language English --task-identity opaque \
  --validation ~/contoso-validation.json
cardine adopt --project . --apply --name "Contoso API" --slug contoso-api \
  --preset lean --language English --task-identity opaque \
  --validation ~/contoso-validation.json
```

For a repository without a `README.md`, `AGENTS.md`, or `CLAUDE.md`, use
`cardine init` with the same options instead. Commit and push the initialized
project. Add generated test files such as `__pycache__/` to `.gitignore` and
commit and push that change too: Cardine treats other untracked files as part
of the change.

## Connect the host

From the project, preview and apply setup:

```bash
cardine setup --check --project .
cardine setup --apply --project .
```

For Claude Code, run:

```bash
cardine doctor --host claude --project .
```

For Codex, restart Codex after setup, then run:

```bash
cardine doctor --host codex --project .
```

Inspect the diagnostics and address any reported access or configuration
problems before assigning work.

## Create and deliver a task

Write `~/proposal-001.md` with an objective, measurable acceptance criteria,
expected code surface, dependencies, and validation. For example:

```markdown
# Task 001 — Document the configuration defaults

> **ID**: `001`
> **Category**: Quick

## Objective

Document the defaults used when no configuration file exists.

## Acceptance Criteria

- README.md lists each default and the option that overrides it.

## Expected code surface

- `README.md`

## Dependencies

None.

## Validation

- `test`: `python3 -m unittest`
```

Create the task, then commit and push the task records on `main`:

```bash
cardine task new 001 --quick --record ~/proposal-001.md --project .
git add -A
git commit -m "Add task 001"
git push origin main
```

Ask your agent to run `cardine run 001` and follow each returned `next.command`
until the task is done. The agent implements in the worktree Cardine returns;
Cardine runs validation and lands the task when its gates pass.

## Stops and resume

A `blocked` outcome identifies a guardrail needing a human decision. Read the
stop code and its `resume` instruction, make the required decision or repair,
then run the specified resume command. For a recoverable outcome, follow
`next.command`; for `waiting`, wait the returned `retry_after_seconds`. For
`iterate`, fix the failing work and run the next command again. See
[run commands](RUN_COMMANDS.md#stops-and-recovery) for the outcome reference.
