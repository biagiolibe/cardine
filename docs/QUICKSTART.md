# Cardine quick start

## Prerequisites

macOS or Linux, Python 3.12 or later, Git, and pipx. A Git checkout of your project on
`main`, with a writable `origin` and a test command that passes. For a new repository,
create and push a first commit before you start.

## Install

```sh
pipx install git+https://github.com/biagiolibe/cardine@v0.9.2
```

Run `cardine guide` in your project checkout at any time. It says where the checkout
stands and what to do next.

## Start in the terminal

From your project checkout, run:

```sh
cardine init
```

Cardine chooses between initialization and adoption and shows each choice with a
default. Press Enter to keep a choice or type a replacement. Confirm the plan to apply
it, then confirm again to commit and push the configuration. If no test command is
detected, run `cardine init --test "<command>"`. If the push fails, Cardine prints the
command to retry.

Then connect your agent from the same terminal:

```sh
cardine setup --check
cardine setup --apply
```

Skip `setup` if you work only from the terminal.

## Start with an agent

Run `cardine init` and `cardine setup --apply` as above, then open your agent in the
project checkout and ask: “I want to use Cardine here.” The agent proposes a first task
and asks you to approve it.

To let the agent configure the project as well, install Cardine, open the agent in the
project checkout, and give it this request:

```text
I want to use Cardine here. Read the quick start at
https://github.com/biagiolibe/cardine/blob/v0.9.2/docs/QUICKSTART.md and guide
me from this checkout to the first integrated task.
```

The agent shows you each choice and asks before it applies or publishes the
configuration. It asks you to run `cardine setup --apply` in your terminal, because host
setup is yours to approve.

## Deliver your first task

With an agent, describe a small change. The agent drafts the task, asks for your
approval, registers it, and delivers it with `cardine run`.

From the terminal, write a short record outside the checkout, for example
`~/task-001.md`:

```markdown
# Task 001 — Describe the project in the README

> **ID**: `001`
> **Category**: Quick

## Objective

Add one sentence to README.md that says what the project does.

## Acceptance Criteria

- README.md describes the project in one sentence.

## Expected code surface

- `README.md`

## Dependencies

None.

## Validation

- `test`: `python3 -m unittest`
```

Replace `python3 -m unittest` with your test command. Register the task, publish its
records, and deliver it:

```sh
cardine task new 001 --quick --record ~/task-001.md
cardine status --write
git add tasks/001.md tasks/QUEUE.md .cardine/tasks/001.json
git commit -m "Add task 001"
git push origin main
cardine run 001
```

`cardine run` prints JSON. When `step` is `implementation`, make the change in the
directory that `work.worktree` names and commit it there; that worktree is the
task's branch, not your checkout. Then run `cardine run 001` again after each step,
following the `next` command it prints, until it reports `done` or a stop with its
reason and the command to resume. The full record format is in
`tasks/TASK_BLUEPRINT.md` in your project. For advanced validation settings, see
`cardine init --help`.

## Project console

Run `cardine console` to see task status and the current step.
