# Cardine quick start

Start in a Git checkout, configure Cardine, and deliver a first task. You can
follow the terminal steps below or delegate them to an agent. See the [README](../README.md#first-5-minutes) for the complete
first-task example.

## Start with an agent

With the Cardine project skill installed, ask: “I want to use Cardine here.”
Without the skill, give the agent this self-contained request:

```text
I want to use Cardine here. Read the Quickstart at
https://github.com/biagiolibe/cardine/blob/main/docs/QUICKSTART.md and guide
me from this checkout to the first integrated task.
```

The agent should inspect prerequisites, collect your choices, show the plan and
ask for consent before applying it. Setup is a separate consent decision.

## Prerequisites

- macOS or Linux, Python 3.12 or later, Git, and pipx.
- An installed and authenticated Claude Code or Codex host.
- A Git repository on `main`, a writable `origin`, a Git author identity, and
  a test command that passes on `main`. Landing pushes `main`.

## Install

Install the latest release from a clone:

```bash
git clone --branch v0.9.1 https://github.com/biagiolibe/cardine ~/src/cardine
pipx install --editable ~/src/cardine
cardine --version
```

For Claude Code, install the host plugin if missing:

```bash
claude plugin marketplace add biagiolibe/cardine#v0.9.1
claude plugin install cardine@cardine
```

Codex receives the skills through the separate `cardine setup` step after
project configuration. The self-contained prompt above works before that.

## Initialize or adopt

From the root of the checkout, start with `cardine guide --project .`. It is
read-only and works offline; `--format json` provides structured output.

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

For a new repository without conflicting generated paths, use `cardine init`
with the same options instead. The preview reports any conflicts. For example, replace `adopt` in
both commands with `init`. For adoption, also rehearse the plan on a disposable
clone with `--rehearse` before applying. Inspect the preview and resolve any
missing inputs before choosing to apply it. Commit and push the initialized
project. Add generated test files such as `__pycache__/` to `.gitignore` and
commit and push that change too: Cardine treats other untracked files as part
of the change.

Run `cardine guide --project .` for project-specific onboarding, or add
`--format json` for structured output. The guide is read-only and works offline.

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

Run `cardine run 001 --project .` and follow each returned `next.command`
until the task is done. When `work` requests implementation, make and commit
the change in the returned worktree, then run the next command. Cardine runs
validation and lands the task when its gates pass. You can instead ask your
agent to follow the same lifecycle. Required independent review needs a
separate session.

## Stops and resume

A `blocked` outcome identifies a guardrail needing a human decision. Read the
stop code and its `resume` instruction, make the required decision or repair,
then run the specified resume command. Check the diagnostics and Git status to see what succeeded; do not repeat successful configuration, commits, or pushes. If a prerequisite is missing, install or configure it and retry the failed command. For a recoverable outcome, follow
`next.command`; for `waiting`, wait the returned `retry_after_seconds`. For
`iterate`, fix the failing work and run the next command again. See
[run commands](RUN_COMMANDS.md#stops-and-recovery) for the outcome reference.
