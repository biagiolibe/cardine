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

## Configure the project

From your project checkout, run:

```sh
cardine init
cardine setup --check
cardine setup --apply
```

`init` chooses between initialization and adoption and shows each choice with a
default. Press Enter to keep a choice or type a replacement. Confirm the plan to apply
it, then confirm again to commit and push the configuration. If no test command is
detected, run `cardine init --test "<command>"`. If the push fails, Cardine prints the
command to retry.

`setup` connects Claude Code or Codex: it registers Cardine's hooks, command rules, and
skills for your agent. Restart the agent afterwards so that it loads them. Skip `setup`
if you work only from the terminal.

## Work with your agent

Open your agent in the project checkout and ask: “I want to use Cardine here.” Then
describe a small change. The agent drafts the task record, asks for your approval,
registers it, and delivers it with `cardine run` until the change is integrated on
`main`. It asks you when a decision is yours.

In true Cardine fashion, you can delegate the installation too. Open your agent in the
project checkout, before installing anything, and ask:

```text
I want to use Cardine here. Install it with pipx from
https://github.com/biagiolibe/cardine at tag v0.9.2, then follow
https://github.com/biagiolibe/cardine/blob/v0.9.2/docs/QUICKSTART.md
to the first integrated task. Ask before you write or publish anything.
```

The agent shows you each choice before it applies or publishes the configuration. It
asks you to run `cardine setup --apply` in your terminal and to restart it: changing its
own permissions and hooks stays your call.

## Start in the terminal

Without an agent, write a task record from `tasks/TASK_BLUEPRINT.md` in your project,
outside the checkout. Register and publish it:

```sh
cardine task new <ID> --record <file>
cardine status --write
git add tasks/<ID>.md tasks/QUEUE.md .cardine/tasks/<ID>.json
git commit -m "Add task <ID>"
git push origin main
```

Then run `cardine run <ID>` and repeat it, following the `next` command it prints, until
it reports `done` or a stop with its reason and the command to resume. When `step` is
`implementation`, make the change in the directory that `work.worktree` names and
commit it there: that worktree is the task's branch, not your checkout. For advanced
validation settings, see `cardine init --help`.

## Project console

Run `cardine console` to see task status and the current step.
