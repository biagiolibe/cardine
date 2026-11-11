# Cardine quick start

Use a Git checkout on `main` with a writable `origin` and a passing test
command. For a new repository, create and publish the first commit before
configuring Cardine.

## Install

Use macOS or Linux with Python 3.12 or later, Git, and pipx.

```sh
pipx install git+https://github.com/biagiolibe/cardine@v0.9.2
```

## Start with an agent

Open your agent in the project checkout and ask it to guide you from setup
through the first task. If the Cardine skill is unavailable, give it this
request:

```text
I want to use Cardine here. Read the Quickstart at
https://github.com/biagiolibe/cardine/blob/main/docs/QUICKSTART.md and guide
me from this checkout to the first integrated task.
```

Review the choices and the setup plan. Confirm before the agent applies
project configuration or publishes it under your project's permissions.
The agent uses explicit mode flags. Run host setup from your terminal when
the agent identifies a host change that needs your approval.

## Start in the terminal

From your project checkout, run:

```sh
cardine init
```

Cardine chooses initialization or adoption. Press Enter to keep a displayed
choice or type a replacement. Confirm the plan to apply it. After inspecting
the written paths and commit message, confirm again to commit and push the
configuration. If the push fails, Cardine prints the retry command.

To connect an agent host, preview with `cardine setup --check`. Apply the
reviewed changes from your terminal with `cardine setup --apply`. Terminal
users can proceed without setting up an agent host.

## Deliver your first task

Ask your agent to register a small change with an objective, acceptance
criteria, the files it may edit, and the checks it must pass. After the
registration is committed on `main`, ask it to proceed with that task.

From a terminal, prepare the record using the project's task blueprint, then
register it. This example uses task 001. Substitute your chosen ID and the
path to your draft.

```sh
cardine task new 001 --record /path/to/draft.md --project .
cardine status --write --project .
```

Review and commit the registration and queue, then publish them under your
project's workflow. Run `cardine run 001 --project .` and follow each action
it returns until it reports `done` or asks for a decision.

For advanced validation configuration, see `cardine init --help` and
its `--validation` option.

## Project console

Run `cardine console --project .` to inspect task status and the current step.
