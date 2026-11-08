<h1 align="center">Cardine</h1>

<p align="center"><strong>The delivery discipline for AI coding agents.</strong></p>

> **Status: in development, before 0.9.** There is no release yet: install the
> CLI from a clone of this repository. The scope of 1.0 is
> [docs/ADR_CARDINE_1_0.md](docs/ADR_CARDINE_1_0.md); what is proven today is
> listed under [Status and evidence](#status-and-evidence).

Coding agents can write the change. Nothing in the agent itself checks that
what reaches `main` was validated, integrated with the latest `main`, and can
be undone. Cardine does that part.

Every task lands on `main` validated, integrated, and reversible, or it stops
with a reason and the exact command to resume.

## What Cardine does

You describe one task in a short contract: objective, acceptance criteria,
validation commands, dependencies. Your agent then calls one command,
`cardine run <TASK-ID>`, again and again. Each call performs the next step of
the task and prints JSON with the outcome and the exact command to run next.

Cardine runs locally, inside your Git repository, with no service and no
account. It works with Claude Code and Codex. It is not an agent and not an
orchestrator: it is the lifecycle your agent follows.

> Specs say what to build. Orchestrators run the agents. Cardine makes sure
> what lands on main is right.

## How a task lands

`cardine run` moves a task through seven steps:

1. **Contract.** Check the task contract that `cardine task new` froze.
2. **Worktree.** Prepare one branch and one linked worktree for the task.
3. **Implementation.** The agent makes the change and commits it.
4. **Validation.** Cardine runs the task's validation commands itself.
5. **Review**, when the task requires it.
6. **Candidate.** Validate `main` plus the task before merging.
7. **Landing.** Merge, push `main`, clean up the worktree and branch.

Every outcome falls into one of three classes:

| Class | Examples | What happens |
| --- | --- | --- |
| Guardrail | Merge conflict, rejected push, required review, scope change, denied action | The agent stops. Cardine prints `BLOCKED <CODE>` and the command a person runs to resume. |
| Recoverable state | Unfinished closure records, an interrupted cleanup, CI still running | The agent continues with the `next` command Cardine returns. |
| Failing work | Failing tests, a lint error | The agent fixes its work and validates again, up to a retry limit (3 by default). |

## Why it holds

**Stops are for people.** A stop is justified only when a person brings
something the agent lacks: authority, a decision, or information. Each stop
code in the registry declares whether it needs a person, and `cardine run`
refuses to print a stop for any code that does not. A failed validation run
is rerun once, so a test that fails intermittently does not consume the retry
limit. ([ADR decision 12](docs/ADR_CARDINE_1_0.md#12-stops-are-for-people))

**Gates read facts, not prose.** A gate reads only the task's state file
written by Cardine, Git objects, and the results of commands Cardine ran
itself. Handoffs and reports explain the work to people; no gate parses them.
An exit code that an agent reports is not evidence.
([decision 13](docs/ADR_CARDINE_1_0.md#13-gates-read-facts-not-prose))

**It holds with weak and strong agents.** An agent needs little to read: the
next action and a short contract. Rules whose violation causes harm are
enforced by a CLI gate, a hook, or a host permission rule, not only written
down. The files that gates trust are written by Cardine and bound to
operation receipts, so a file an agent writes on the task branch does not
change a gate's outcome. Host rules deny agents the state files and
developer-only commands, and an implementer cannot approve its own work.
Every step can be interrupted and rerun.
([decision 14](docs/ADR_CARDINE_1_0.md#14-robust-against-weak-and-strong-agents))

**One task, one worktree, one writer.** Agents never force-push, rewrite
history, create tags, delete unmerged branches, or resolve textual conflicts.
Those stay with you.

## First 5 minutes

You need a Git repository on `main` with a writable `origin` (landing pushes
`main`) and a test command that passes on `main`. Install the CLI first; see
[Install](#install).

Declare the project's validation commands once, in a small JSON file outside
the repository, `~/contoso-validation.json`:

```json
{"commands": {"test": "python3 -m unittest"},
 "baseline": ["test"],
 "candidate": {"REUSE": [], "BOUNDED": ["test"], "FULL": ["test"]}}
```

Ignore and commit the files your tests generate, such as `__pycache__/` for
Python. Cardine treats any other untracked file as part of the change.

```bash
printf "__pycache__/\n" >> .gitignore
git add .gitignore && git commit -m "Ignore generated test files" && git push origin main
```

Convert the project. `--check` shows the plan and changes nothing. Your
files are kept; an existing `AGENTS.md` or `CLAUDE.md` gets Cardine's text
followed by yours. In a repository without a `README.md`, `AGENTS.md`, or
`CLAUDE.md`, `cardine init` takes the same options.

```bash
cardine adopt --project . --check --name "Contoso API" --slug contoso-api \
  --preset lean --language English --task-identity opaque \
  --validation ~/contoso-validation.json
```

Run it again with `--apply` instead of `--check`, then commit and push:

```bash
git add -A && git commit -m "Adopt Cardine" && git push origin main
```

Connect your host. `setup --check` shows every change it would make; nothing
is written until `--apply`.

```bash
cardine setup --check --project .
cardine setup --apply --project .
cardine doctor --host claude --project .
```

Write a first task as a quick contract, `~/proposal-001.md`:

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

```bash
cardine task new 001 --quick --record ~/proposal-001.md --project .
git add -A && git commit -m "Add task 001" && git push origin main
```

Then ask your agent to deliver it:

```text
Run `cardine run 001` and follow its next command until the task is done.
```

Each call prints one JSON result. One of them, with the path shortened and
the other fields left out:

```json
{"task_id": "001", "step": "landing", "outcome": "next", "action": "finalize",
 "next": {"command": "cardine run 001 --project /path/to/contoso-api",
          "reason": "Push and clean up the landed task"},
 "stop": null}
```

`outcome` is one of `progress`, `next`, `waiting`, `iterate`, `blocked`, or
`done`. The agent keeps going until the task is `done` on `main`, or until a
`blocked` result names the command you run to resume.

## Lean or Governed

One lifecycle, two presets. A preset sets the project's defaults; each task
can raise or lower them.

| | `lean` (default) | `governed` |
| --- | --- | --- |
| Independent review | not required | required |
| `Authority` and `Expected code surface` fields | optional | required |
| Validation retry limit | 3 | 3 |

A `spike` task class for exploratory work, with an `ANSWERED` or
`INCONCLUSIVE` outcome, is available in both.

## What Cardine is not

- **Not an agent.** Your host (Claude Code or Codex) does the work.
- **Not an orchestrator.** It does not run several agents in parallel. An
  orchestrator can run Cardine inside each worktree.
- **Not a service.** Everything runs locally; `direct` landing needs no forge.
- **Not proof of authorship.** Agents run as your user. Receipts and host
  rules catch mistakes and refuse shortcuts, but an agent that deliberately
  bypasses the host's permissions could rewrite them. Cardine does not claim
  otherwise.
- **Not yet for team workflows.** Landing through pull requests is planned
  for 1.1.

The project console, `cardine console`, is experimental.

## Status and evidence

Proven:

- in disposable test projects with a local bare remote: a task without
  review, from queued to landed on `main`; a task with required review and
  one round of requested changes; an agent that followed only what
  `cardine run` printed; a stop followed by a resume;
- the path of [First 5 minutes](#first-5-minutes), from `cardine adopt` and
  a quick task to landing, in a disposable project with the CLI installed
  from a clone;
- on Cardine's own repository: its tasks land through `cardine run`.

Not yet proven or measured:

- a task landed through Cardine in another project;
- installation from a released package;
- the field trial that gates 1.0 (ADR decision 10);
- the comparison with and without Cardine. Its
  [protocol](docs/BENCHMARK_PROTOCOL.md) is decided; nothing has been run.
  Results will be published with the disclosure that the author of Cardine
  arbitrated disagreements, and they will state what they do not cover: the
  `lean` preset on a real adopter, Codex, and other models.

## Install

Requires macOS or Linux, Python 3.12 or later, Git, pipx, and an installed,
authenticated Claude Code or Codex.

Until the first release, install from a clone:

```bash
git clone https://github.com/biagiolibe/cardine ~/src/cardine
pipx install --editable ~/src/cardine
cardine --version
```

From 0.9, `pipx install cardine` installs a release.

## Documentation

- **Using Cardine:** [run commands](docs/RUN_COMMANDS.md),
  [converting an existing project](docs/ADOPT_COMMANDS.md),
  [platform support](docs/PLATFORM_SUPPORT.md).
- **Design:** [design decisions](docs/ADR_CARDINE_1_0.md),
  [public surface](docs/PUBLIC_SURFACE.md).
- **Being rewritten from Meridian:** [quick start](docs/QUICKSTART.md),
  [agent operations](docs/AGENT_OPERATIONS.md),
  [upgrade guide](docs/HOW_TO_UPGRADE.md).
- **Contributing:** [contributing](CONTRIBUTING.md).

Tooling must read `--format json` output; human-readable output is never
stable.

## Origin and license

Cardine starts from the code of Meridian 1.4.0, which it replaces. Meridian's
history and design records stay in its
[repository](https://github.com/biagiolibe/meridian).

Follow the [code of conduct](CODE_OF_CONDUCT.md) and report vulnerabilities
through the [security policy](SECURITY.md).

Copyright © 2026 Biagio Liberto. Available under the [MIT License](LICENSE).
