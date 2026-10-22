# ADR: Cardine 1.0

Status: Accepted

*Proposed and accepted on 2026-10-17, after the Cardine 1.0 design review.
The developer decided every point on that date. The decisions cover the console
in 1.0, the validation retry limit in place of budget counters, conversion of
open work only, and the field-trial exit criterion. They also cover deferred
trademark registration, task state only in JSON, the new repository, the
`lean` and `governed` presets, and pipx as the primary installer. Contoso and
Fabrikam are fictitious names for the maintainer's two private projects.
Decision 11, landing modes and pull requests, was added and accepted on the
same day, as were the release-tooling requirements in work item 12, the
order of work items 4 and 5, quick tasks under decision 4, CI before
landing under decision 11, and the queue-briefing requirements in work items
6, 7, and 9. Decision 12, stops reserved for decisions that need a person,
was proposed and accepted on 2026-10-18. It refines decisions 5 to 7 and adds
no feature to the 1.0 scope. On 2026-10-19 the developer split work item 5 in
two, reset the capability marker versions at the marker rename, and placed the
move of this repository to Cardine after work items 8, 9, and 10. On
2026-10-20 the developer moved the Cardine names of skills, slash commands,
the plugin, and the Codex rules from work item 5b to work item 9. Decision
13, gates that read facts instead of prose, was proposed and accepted on
2026-10-22.*

## Context

Meridian is a delivery workflow for AI coding agents. It has one known user,
the maintainer, with two Governed SDD projects, Contoso and Fabrikam, and
Meridian itself on Lean Delivery.
Over the 14 days to 2026-10-17 the repository had 3 unique visitors, 0 stars,
0 forks, and 0 release asset downloads; its 676 "unique" clones come from CI,
plugin refreshes, and crawlers.

The name does not work:

- About 9,800 GitHub repositories are named `meridian`, several with thousands
  of stars, and a search for this project does not return it.
- Other agent tools already use the name: `haowjy/meridian-cli` ships a
  `meridian` command for LLM work, and `meridianlabs-ai/agents` publishes Claude
  Code workflows.

The code and process have also grown past what one maintainer can keep sharp:

- `scripts/meridian.py` has 13,050 lines and 357 functions;
  `tests/test_meridian_cli.py` has 9,565 lines.
- 72 argument subparsers, about 60 public commands, most of them Stable.
- 69 migrations, `release-baselines/`, and more than 400 code references to
  legacy, compatibility, or migration paths.
- Two parallel workflows. Governed SDD installs 24 files and about 21,000 words
  into a project, Lean Delivery 10 files and about 7,000 words, and four skills
  cover two workflows on two hosts.
- Task status lives in five places: the task record, `tasks/QUEUE.md`,
  `PROJECT_PLAN.md`, `.meridian/tasks/<TASK-ID>.json`, and the handoff.
- The lifecycle needs about ten commands per task, with two `--project`
  conventions. Tasks 218–220 and 227–230 all fixed stops that this shape
  causes.

The name `cardine` was checked on 2026-10-17. It is free on PyPI, npm,
crates.io, RubyGems, Homebrew, Debian, and Docker Hub, and no system command
uses it. No US trademark registration exists for `CARDINE`. The EU and Italian
registers were not checked automatically. Two service businesses use the name
(`cardine.ai`, an AI consultancy in the US, and `cardine.dev`, a software
agency in Brazil). The GitHub account `cardine` is taken, so the repository
will be `biagiolibe/cardine`.

The name keeps Meridian's image. *Cardine* is Italian for hinge and for a
founding principle. It shares its root with the Roman *cardo maximus*, the
north–south street of a city, which is the city's meridian. The logo is an
axis between two arcs, which is a hinge.

## Decision

### 1. Cardine is a new product, released as 1.0.0

Cardine starts at `1.0.0` in a new repository, `biagiolibe/cardine`. It
imports the code of Meridian 1.4.0 in its first commit and states that origin.
It carries no Meridian history and no Meridian tags. Meridian 1.4.0 is the last
Meridian release. After Cardine 1.0.0 the Meridian repository is archived with
a README notice that points to Cardine.

There are no `meridian` aliases, no deprecation period, and no migration
chain, because no external adopter exists. The stability promise restarts at
Cardine 1.0.0, under the rules of `docs/ADR_PUBLIC_SURFACE_AND_STABILITY.md`.

### 2. Positioning

Cardine is the delivery discipline for AI coding agents. Every task lands on
`main` validated, integrated, and reversible, or it stops with a reason and the
exact command to resume.

The 2026 tool market covers two of three phases.

| Category | Examples | Leaves uncovered |
| --- | --- | --- |
| Specification frameworks | GitHub Spec Kit, Kiro, OpenSpec, BMAD-METHOD | No enforcement gate or verification in Spec Kit. None handles Git isolation and integration. |
| Agent orchestrators | Conductor, Composio Agent Orchestrator, Crystal, Claude Squad, Vibe Kanban | No automatic validation before merge, no stop rules. At most a human approval. |
| Host features | Claude Code, Codex, Cursor | Primitives such as worktrees, hooks, and permissions, with no task contract or lifecycle. |

Cardine adds five things:

- a verifiable task contract;
- mechanical gates with registered stop codes;
- a protected `main` with candidate validation and denied destructive actions;
- local, host-neutral operation with no service;
- reliable unattended runs.

Cardine complements the other tools. A Spec Kit specification can become a
task contract, and an orchestrator can run Cardine inside each worktree. README
line: *Specs say what to build. Orchestrators run the agents. Cardine makes
sure what lands on main is right.*

### 3. One lifecycle, two presets: Lean and Governed

Cardine has one lifecycle, one engine, and one template set. The assurances
that are exclusive to Governed SDD today become task options:

- `review: required` or `review: not_required`;
- required `Authority` and `Expected code surface` fields;
- the `spike` class.

A project chooses a preset, which sets the default of every option. Each task
can still raise or lower an option. The two presets keep the identities that
Meridian's workflows established:

| Option | `lean` preset | `governed` preset |
| --- | --- | --- |
| Review | not required | required |
| `Authority` and `Expected code surface` | optional | required |
| Blocking dependencies | yes | yes |
| `spike` class | available | available |
| Validation retry limit | 3 | 3 |

`cardine init` asks for the preset. `lean` replaces Lean Delivery and is the
default for new projects. `governed` reproduces today's Governed SDD
behavior. A project can switch preset later; open tasks keep the options they
were created with.

Task states are `queued`, `in_progress`, `in_review` (only when review is
required), `done`, and `cancelled`. One skill exists per host.

Contoso already chooses review per task: 34 of its 342 task records are
`Review: NOT_REQUIRED`. A Lean project, for example Meridian itself,
cannot require review for one risky task today. Under this decision it can.

Every Governed SDD feature that Contoso and Fabrikam use maps to the
`governed` preset. Counts are task records on 2026-10-17, as Contoso /
Fabrikam.

| Governed SDD feature | Use today | Cardine 1.0 |
| --- | --- | --- |
| Required review | 268 / 47 tasks | Project default `review: required` |
| Review not required, per task | 34 / 0 tasks | `review: not_required` on the task |
| Verdict bound to the approved commit | 167 / 24 review records | Unchanged, in the task's state file |
| Changes requested and a new attempt | yes | `cardine review` with changes requested, then `cardine run` |
| Exploratory tasks with `ANSWERED` or `INCONCLUSIVE` | 41 / 3 tasks | Class `spike` with the same outcomes |
| `Authority` citing ADRs | 282 / 46 tasks | Contract field, required by project default |
| `Expected code surface` | 261 / 43 tasks | Contract field, required by project default |
| ADR log | 139 / 20 ADRs | Unchanged; `cardine adr list` and `cardine adr show` |
| Blocking dependencies | yes | Blocking for every task |
| Milestone task identity | yes | Project option |
| Execution evidence | yes | Recorded by `cardine run` |
| Context budget counters | Contoso | Replaced by the validation retry limit (decision 5) |

### 4. Task state only in its JSON file

`.meridian/tasks/<TASK-ID>.json` becomes `.cardine/tasks/<TASK-ID>.json`. It
remains the only source of truth for status, transitions, and review verdicts,
as `docs/ADR_MACHINE_TASK_STATE.md` decided. It is validated by a schema and
written only by the CLI. `cardine task new` creates it with the task, so it
cannot be missing. A quick task is a minimal task that `cardine task new`
creates in the same way; no lifecycle step runs for a task without a
registered state file. Meridian's Lean rules allowed a quick task without a
task file, while worktree preparation refused any unregistered task ID.

Cardine removes the duplicates that coexist with it in Meridian:

- the `Status` field in the Markdown record;
- the move to `tasks/done/` as a status signal;
- hand-maintained queue and plan status.

`cardine status` generates the queue, and the plan's status lines are
generated too. Keeping state in a front matter block of the Markdown record was
considered and rejected. It would put status back in a file that people and
agents edit by hand, which is the failure the machine-state ADR fixed.

### 5. Context budget: one automatic limit

The usage data, as of 2026-10-17:

- Contoso recorded 261 budget spends across 83 tasks. No command
  emitted `BUDGET_EXHAUSTED` in that time. Two exhaustion stops were declared
  by agents without a command. One of them was the false exhaustion of
  issue #15.
- Fabrikam recorded 6 spends.
- Of the four counters, only diagnostic attempts approached their caps.

In Cardine 1.0:

- **Kept:** task-first reading rules and the read guard for large files.
- **New:** `cardine run` counts consecutive failed validation runs of the task
  itself. After N failures it stops with a registered code and a summary of
  the failures. N defaults to 3 and is configurable per project and per task.
  The counter lives in the task's state file and is bound to the attempt. The
  agent records nothing.
- **Removed:**
  - the self-reported counters: evidence captures, context expansions, and
    investigation scope;
  - the ledger in the Git common directory;
  - `budget show` and `budget spend`;
  - the `Budget usage` handoff line.

### 6. One lifecycle entry point

`cardine run <TASK-ID>` is the only lifecycle command an agent needs. Each call
reads the task state, performs the next possible step, and prints JSON with the
outcome and the next action. Its steps are:

1. contract check;
2. worktree preparation;
3. implementation;
4. validation;
5. review, when required;
6. candidate validation of `main` plus the task;
7. merge, push, and cleanup.

It is rerun after every step and every stop. It resolves the primary checkout
and the task worktree itself and works from any directory. It returns only
commands that run unchanged. These rules close the classes of stops fixed in
tasks 219, 227, 229, and 230. Single-step commands remain Internal, for
diagnosis and manual recovery.

### 7. Scope of 1.0

| Area | Decision |
| --- | --- |
| Migrations and release baselines | Removed. The migration mechanism stays for future releases. |
| `adopt` from historical versions | Removed. `adopt` handles projects without Cardine and Meridian projects (decision 10). |
| Maintainer-only commands (`profile`, `generate-*`, `report flow`, evaluations) | Moved out of the user CLI into development scripts. |
| Duplicate implementations | One each, in Python. Hooks are no longer written in both shell and Python. One entry-router generator. `release.py` and `prepare_release.py` merge. |
| Project console | Stays in 1.0, Experimental, rebuilt on the single task state and the `cardine run` engine. |
| Documentation | User guide, compact agent reference, README with the positioning. Meridian's design history and task records stay in the archived repository. |

Unchanged, because they are the product's value:

- registered stops with exact resume commands, reserved for decisions that
  need a person (decision 12);
- denied destructive actions;
- one worktree and one writer per task;
- candidate validation before integration;
- fragment-based releases with a version-kind check;
- `setup` that always shows a diff before applying.

### 8. Package architecture

Cardine is a Python package. Its modules are:

| Module | Responsibility |
| --- | --- |
| `cardine.cli` | Argument parsing, JSON and text output, exit codes |
| `cardine.tasks` | Contract, states, transitions, dependencies, identity |
| `cardine.lifecycle` | The `cardine run` engine |
| `cardine.worktree` | Preparation, checks, cleanup, canonical paths |
| `cardine.integration` | Candidate, validation, merge, push |
| `cardine.review` | Independent review and verdicts |
| `cardine.stops` | Stop-code registry and resume commands |
| `cardine.hosts` | Setup and doctor for Claude Code and Codex: skills, rules, hooks |
| `cardine.templates` | Project files, markers, upgrade |
| `cardine.console` | Project console over the task state and `cardine run` |
| `cardine.release` | Release tooling, for Cardine development only |

Tests mirror the modules. No source or test file exceeds 1,500 lines.

The Stable surface of 1.0 is:

- `cardine init`, `setup`, `doctor`;
- `cardine task new`, `task list`, `task show`;
- `cardine run`, `status`, `review`, `cancel`, `abort`;
- `cardine upgrade`, `self-update`;
- `cardine adr list`, `adr show`.

`cardine hook …` is Host-facing. `cardine console` is Experimental. The
single-step lifecycle commands are Internal.

### 9. Distribution

Cardine is published on PyPI, with `pyproject.toml`, a registered `cardine`
command, and `requires-python >= 3.12`.

The documented installer is **pipx**, which the Python Packaging User Guide
recommends for stand-alone command-line tools. **uv** is the documented
alternative; GitHub Spec Kit installs through it. Plain `pip` is not
documented: Python builds that mark themselves externally managed (PEP 668),
such as Homebrew's and recent Debian and Ubuntu releases, refuse a `pip install`
outside a virtual environment. On macOS, `brew install pipx` provides the
installer.

Three installation sources are supported with either installer:

| Source | pipx (primary) | uv (alternative) | Use |
| --- | --- | --- | --- |
| PyPI release (default) | `pipx install cardine` | `uv tool install cardine` | Everyone |
| Git tag | `pipx install git+https://github.com/biagiolibe/cardine@v1.0.0` | `uv tool install git+https://github.com/biagiolibe/cardine@v1.0.0` | A pinned release without PyPI |
| Local clone, editable | `pipx install --editable <clone>` | `uv tool install --editable <clone>` | Cardine development |

The installer places the `cardine` command in its application directory,
usually `~/.local/bin`. When that directory is not on `PATH`, `pipx ensurepath`
or `uv tool update-shell` adds it to the shell configuration once. Cardine never edits shell files itself. `cardine doctor`
checks that a non-interactive shell (`zsh -lc` or `bash -lc`) resolves the
same `cardine` that the agent hosts run, and prints the fix when it does not.
The bootstrap task verifies the Git-tag and editable forms against the
installers' current documentation.

This removes the release checkout, `MERIDIAN_ROOT`, `PATH` edits, the wrapper's
Python version guard, and the exact-tag requirement. Templates and skills ship
as package data. Updates use `pipx upgrade cardine` (or `uv tool upgrade
cardine`), then `cardine upgrade` in each project. `cardine self-update`
detects which installer owns the running CLI and runs its upgrade command.

The Claude Code plugin keeps skills and slash commands and calls the installed
CLI. `cardine doctor` checks that the plugin and the CLI versions match.

### 10. Transition from Meridian

1. **Release Meridian 1.4.0.** Integrate tasks 227–230 and publish 1.4.0. Its
   notes announce that Meridian will be archived.
2. **Create `biagiolibe/cardine`.** Import the code and publish a `0.0.1`
   placeholder on PyPI to reserve the name.
3. **Develop toward 0.9** with the work items below.
4. **Convert open work only.** `cardine adopt` converts the open tasks, the ADR
   log, and the project configuration: default assurances, validation commands,
   and task identity. Closed tasks and review records stay in place as an
   archive that Cardine ignores. Conversion runs on copies first, then on the
   originals.
5. **Field trial with an exit criterion.** Cardine 1.0.0 is released only when,
   on 0.9, at least one real task of each case has landed on `main` in Contoso or
   Fabrikam:
   - required review with one round of requested changes;
   - no review;
   - a spike;
   - `Authority` citing an ADR, with a declared code surface;
   - a stop followed by a resume with `cardine run`.

   A case that does not work as it does today becomes a task and blocks 1.0.
6. **Release Cardine 1.0.0** on GitHub and PyPI.
7. **Archive Meridian.** Add a README notice, make the repository read-only, and
   remove the Meridian plugin from its marketplace.

On the maintainer's machine:

- remove the Meridian plugin, `~/.local/share/meridian`, the `MERIDIAN_ROOT`
  and `PATH` lines, and the Meridian blocks under `~/.codex`;
- install Cardine with `pipx install cardine`, then run
  `cardine setup --apply`.

Projects stay on Meridian 1.4.x until their conversion. 1.4.x receives fixes
only for blocking defects.

### 11. Landing modes: direct now, pull requests in 1.1

Meridian lands every task locally: it merges in the primary checkout,
validates the candidate, and pushes `main`. Its `PULL_REQUEST_POLICY.md` opens
no pull request; it pushes a task branch only to obtain CI. That shape is
right for one developer and wrong for a team, where review and merge happen on
a pull request. Cardine supports both as a **landing mode**: an option with a
project default that one task can override, like the presets.

| | `direct` (default) | `pull-request` |
| --- | --- | --- |
| How a task reaches `main` | Local merge, candidate validation, push | A pull request merged on the forge |
| Candidate validation | Local | Required CI checks on the pull request, plus local validation when the project asks for it |
| Review | An agent through `cardine review` | People on the forge, an agent that posts its review on the pull request, or both |
| Who merges | `cardine run` | A person on the forge, or `cardine run` once the pull request is approved and green, when the project allows it |
| Forge dependency | None | `gh`, authenticated by the user; Cardine stores no token |

In `pull-request` mode, `cardine run` keeps the same next-step logic:

1. Validate the task locally, as in `direct` mode.
2. Push the task branch, then open or update the pull request. The body is
   generated from the task contract, the handoff, and the validation evidence.
3. The task is `in_review` while the pull request is open. Each call reads its
   checks and reviews and reports what is missing.
4. Requested changes are new commits on the same branch, never a force push.
   The verdict stays bound to the reviewed head commit.
5. When the pull request is merged, `cardine run` records the task as `done`
   and cleans up the worktree.

`direct` stays the default. A solo developer keeps today's speed, needs no
forge, and learns no new command. One task can still choose `pull-request` to
get the forge's full CI and a public record. In `pull-request` mode `main`
changes only through the pull request. `cardine doctor` checks that the
branch ruleset requires the pull request's checks and reviews, and it never
changes the ruleset.

**CI before landing in `direct` mode.** Local validation can pass where the
project's CI fails, for example in a shallow checkout, on another operating
system, or in a clean environment. Meridian task 004 landed that way and left
`main` red. A project can therefore require, as an option with a project
default that one task can override, that `cardine run` lands a task only after
the project's CI is green on the exact task commit. `cardine run` pushes the
task branch once, reads the checks through `gh`, and reports what is missing
until they pass. Without the option, `direct` mode keeps no forge dependency.
This option is part of 1.0.

After the task lands and `main` is pushed, `cardine run` deletes the remote
task branch it pushed, and only when that branch still points at a commit that
`main` contains. Deleting a branch stays denied to agents; the lifecycle
command does it as part of cleanup. In Meridian, `worktree cleanup` removed
only the local branch, so every pushed `task-NNN` branch stayed on the
remote.

**Scope.** Cardine 1.0 builds the landing mode into the design and ships only
`direct`. These parts are in 1.0:

- `cardine.integration` with the landing mode as its extension point;
- a task state that can record a verdict from an external review, bound to the
  reviewed commit.

Cardine 1.1 ships `pull-request` mode for GitHub, with its own field trial. Two
further items are open for 1.1:

- **Task ownership for teams:** an `owner` field, and detection of a task
  already prepared on another machine through its remote branch or open pull
  request.
- **Other forges.**

### 12. Stops are for people

A stop hands control to a person. It is justified only when that person
brings something the agent lacks: authority, a decision, or information.
Everything else is the agent's work.

The evidence, as of 2026-10-18:

- The stop registry has 55 codes. Only 14 have `human_decision: true`: an
  outstanding review, a merge conflict, a rejected push, a scope change, a
  rule conflict, and a few more.
- In the first 22 Cardine tasks, agents stopped 7 times, and none of those
  stops needed a new decision from the developer:
  - three were a Resume of a worktree with uncommitted changes, which the
    workflow allows (tasks 009, 019, 021);
  - one was a task that skipped `task close`, with a known remedy (task 015);
  - one was a test that failed once and passed on the rerun (task 009);
  - one was a trailing blank line and a missing import path in the task's
    own work (task 021);
  - one was a refused `prepare` for work that had no task record yet; the
    coordinator wrote the record for work the developer had already asked
    for (task 005).
- Each stop cost a round trip through the developer, who pasted a Resume
  directive and added nothing to it.

The cause is a correction that went too far. Meridian agents used to invent
stops, for example the false budget exhaustion of issue #15. The rule that a
stop is valid only when a command prints `BLOCKED` ended that, but the
commands print `BLOCKED` for every state off the happy path, including the
states they know how to resolve. That also contradicts decision 5, which
stops a task after repeated validation failures, not after the first, and
decision 6, which returns the next action instead of a stop.

Every outcome of a lifecycle command belongs to one of three classes:

| Class | Examples | What the agent does |
| --- | --- | --- |
| Guardrail | A denied action; a merge conflict; a rejected push; a required review; a scope change; a rule conflict | Stops. The command prints `BLOCKED <CODE>` and a resume command for the person. |
| Recoverable state | A Resume with uncommitted changes; closure records still to write; a partial cleanup; CI still running | Continues. The command returns `next` with the exact command, and the agent runs it in the same turn. When the recovery is safe and idempotent, the command performs it itself. |
| Failing work | Failing tests, a lint error, a wrong import | Iterates: fixes its work and validates again, within the validation retry limit. |

The registry's `human_decision` field is the rule. A code without it never
prints `BLOCKED` and never stops the agent. Guardrails stay absolute, because
they are the product's value: an agent never runs a denied action, writes
state to pass a gate, changes scope, or decides in place of a review.

The validation retry limit of decision 5 also covers intermittent failures.
A failed validation run is rerun once automatically. If the rerun passes,
the handoff records the test as intermittent and the attempt does not count.
If it fails, the attempt counts toward N.

For unattended runs, decisions that need a person are taken before the run,
in the task contract. The `Expected code surface` bounds what the agent may
change. Work outside it is a scope change and stops.

"Resume" is no longer a ritual for the developer. It follows only a stop
that needed a person; otherwise the agent runs the lifecycle command again.

Two checks keep this true:

- Every recoverable code has a test proving that the command it returns runs
  unchanged and advances the task. A `BLOCKED` line for a code without
  `human_decision` is a defect of the tool.
- The journal counts stops per task by class. The target is that every stop
  is a guardrail.

The rule applies twice. First to the agent instructions in Cardine's
templates: a code without `human_decision` is a next action, not a stop.
Then by construction in the `cardine run` engine (work item 8). This
repository's own lifecycle runs on the installed Meridian 1.4.0 until
`cardine run` can deliver its tasks. Its managed files carry whole-file
digests, and the checkout's upgrade damages them, so neither change reaches
the stops of that lifecycle.

### 13. Gates read facts, not prose

A gate, a verdict, a status, or a stop must rest on something an agent cannot
get wrong by wording it differently, and cannot get right by copying a string.
Free text checked by pattern fails both ways: it blocks correct work written
in other words, and it passes a copied phrase that is not true. It also breaks
whenever a template, a procedure, or a model changes.

The evidence, as of 2026-10-22:

- On Contoso, two consecutive tasks stopped with `EVIDENCE_INCOMPLETE` because
  the handoff's `Current task commit` described the coming delivery commit in
  the agent's words instead of the literal `Deliver <TASK-ID> for review`.
  One description was wrong, the other was right; both cost a correction
  commit, a new delivery, and a new session.
- On Contoso, integration stopped with `TASK_STATE_INVALID` because the
  transition read the review policy from the record's prose and integration
  read it from the state file.
- In `src/cardine` on that date, 23 calls read fields from Markdown records,
  about a dozen regular expressions read handoff lines and queue checkboxes,
  and 8 code paths accept validation exit codes that the agent reports on the
  command line.

A gate may read only three sources:

1. The task state file and its contract snapshot, written by the CLI.
2. Git objects and references.
3. The results of commands that Cardine executed itself: exit codes, digests,
   and the files those commands wrote.

Human intent enters through the task contract. `cardine task new` reads it
once, validates it against a schema, and freezes it in the state file
(decision 4, task 053). After creation the Markdown record describes the
work; no gate parses it again.

Text that an agent writes, such as handoffs, reports, and checkboxes, is an
explanation for people. No gate reads it, no verdict or status is derived from
it, and its wording never causes a stop. No template asks an agent to write a
literal string so that a gate can find it. Evidence an agent declares, such as
an exit code passed as an option, is not evidence; the engine of work item 8
runs validation itself.

Text that Cardine installs and manages, such as marker blocks and their
digests, is checked byte for byte. There the text is the product, and an
integrity check is the right gate.

The reader of an installed Meridian under `cardine.legacy` keeps its prose
parsing until work item 10, because it serves the coordinator of this
repository. No product command calls it.

One check keeps this true: a static test lists every product read of record,
handoff, report, queue, or plan text and fails on a new one outside the
contract creation path, the integrity checks, and `cardine.legacy`. A planning
task inventories the current reads and assigns each to work item 7, work item
8, removal, or the integrity class before the work item 8 tasks are written.

## Work items to 0.9

Most items are one or more tasks of 2–3 hours. Item 3 is mechanical and
leaves behavior unchanged; simplification starts after it. Item 4 removes the
historical migrations before item 5 renames identifiers, so the rename never
touches code that is about to be deleted. For the same reason item 5 is split:
item 5a renames code identifiers before item 6, and item 5b renames the markers
and template text after item 6 has produced one template set.

Until item 10 moves this repository to Cardine, the installed Meridian owns
`.meridian/` and this repository's managed copies and shared-source hooks, as
`.meridian/manifest.json` lists them. Tasks before that point change product
surfaces only and leave those files unchanged.

1. Accept this ADR.
2. Repository bootstrap: `pyproject.toml`, package skeleton, CI, code import.
3. Split `meridian.py` and its tests into the modules of decision 8, with the
   existing suite green.
4. Remove historical compatibility: migrations, baselines, budget counters,
   maintainer commands, and the duplicate entry-router generator. Required
   capability versions move from the migration records to the capability
   catalog. The migration mechanism stays, with an empty chain from which
   Cardine 1.0 starts, and upgrade tests use synthetic fixtures instead of
   Meridian's migrations. Until 1.0 no project runs Cardine, so a template
   change bumps the capability version and rewrites the marker baseline
   without adding a migration. The other duplicates of decision 7 move:
   one Python implementation of each hook to work item 9, and one release
   script to work item 12. Removing release baselines also removes `adopt`
   until work item 10 rebuilds it. `.meridian/` stays untouched, because the
   installed Meridian 1.4.0 runs this repository's lifecycle.
5. Rename identifiers, in two parts.
   - **5a, before item 6:** the command and entry points, environment
     variables, the `.cardine/` project directory, Git-internal files such as
     the journal and the integration lease, and the worktree root. Product
     code keeps one read-only reader of `.meridian/` and `MERIDIAN:BEGIN`
     markers for the conversion of item 10. That reader is not an alias of
     decision 1: no command accepts the Meridian names as input for its own
     work. Until item 10 the same reader also gives the coordinator a
     read-only snapshot of this repository, which the installed Meridian
     still runs; no command dispatches it.
   - **5b, after item 6:** the markers become `CARDINE:BEGIN`, and every
     capability restarts at `v1`. The marker baseline and `requiredVersion`
     values are rewritten to match. Template text loses the Meridian name.
     Skills, slash commands, the plugin, and the Codex rules file and
     profile are not renamed here: item 9 rebuilds them under Cardine names
     (decision of 2026-10-20).
6. Single workflow: one template set, task contract fields, states, review
   option, `spike` class. The preset comes from the project configuration,
   never from the shape of the queue file. In Meridian 1.4.0 the per-turn
   briefing chose the Governed SDD format only when the queue contained a
   governed table. A Governed SDD project that had archived every closed
   phase got the Lean Delivery header and a total of 0. A regression test
   covers a project whose queue lists no task: the briefing still names the
   project's preset. Item 5b follows this item.
7. Single source of truth: state in the task JSON, generated queue and plan
   status. The generated status lists a task as startable only when its state
   is `queued` and its dependencies are met. A task that is `in_progress` or
   `in_review` never appears as startable. Meridian 1.4.0 listed a task under
   review also as "Queued (startable)", because the briefing derived active
   and review tasks from the worktrees but startable tasks only from the
   queue table. Totals count task states, not queue rows, so archiving a
   phase never changes them. Regression tests cover a queued task with met
   dependencies whose state is `in_progress`, the same with `in_review`, and
   a project whose queue lists no task while its task states record done
   tasks.
8. `cardine run` engine: next step, resume, directory independence, runnable
   commands, validation retry limit. It applies decision 12: only guardrails
   stop, recoverable states return the next action or are resolved by the
   engine, and failing work iterates within the retry limit. Rebuild the
   console on this engine. Build integration around the landing mode, with
   `direct` as its only 1.0 mode (decision 11). It applies decision 13: the
   engine runs validation and records the delivered commit itself, so no gate
   reads agent-written text or agent-reported exit codes.
9. Hosts: setup and doctor for Claude Code and Codex, two skills, user-level
   hooks, with one Python implementation of each hook (decision 7). The
   skills, slash commands, plugin, and Codex rules file and profile are
   created under Cardine names, replacing the Meridian-named ones. The per-turn queue briefing is one Python implementation that
   prints the status that work item 7 generates. It computes no task state of
   its own. The regression tests of work items 6 and 7 run against the hook
   output on both hosts.
10. Meridian conversion: open tasks, ADRs, configuration. This item rebuilds
    `cardine adopt`, which work item 4 removes together with the release
    baselines. It ends by converting this repository with `cardine adopt`, so
    that `cardine run` delivers its remaining tasks. That move releases the
    files the installed Meridian owned: the checks and tests that guard them
    are removed or pointed at Cardine's own records, and the changes deferred
    to it, such as the old shell hooks and the managed copy of
    `CONTEXT_BUDGET_POLICY.md`, are made. Items 11 and 12 run on Cardine.
11. Documentation: README positioning, quick start, agent reference.
12. Release: GitHub and PyPI publication from one script, which merges
    `release.py` and `prepare_release.py` (decision 7). Preparing Meridian
    1.4.0 (task 231) exposed three gaps that this script must close:
    - The release kind follows what changed. A template change without a
      migration stops the release; it is never labelled CLI-only.
    - One release can ship several migrations, and the version advances once,
      at preparation. The repository checks, the release script, and the
      contributor guide describe one procedure. In Meridian they described
      two, and a release could carry only one migration.
    - When Cardine manages its own repository, a template-changing release
      brings those project files to the new baseline in the prepared commit.

    Preparing Meridian 1.4.1 (task 234) exposed three more:
    - Preparation runs on the task branch in the task worktree. Meridian's
      `release.py prepare` accepted only `main`, so the release task stopped
      with `RULE_CONFLICT` and fell back to the manual procedure. Publication
      stays a developer step on `main`.
    - Tests never pin the framework's own `VERSION`. A test that needs a
      baseline asserts the baseline, so a CLI-only release does not fail
      the suite.
    - One maintainer document, `docs/RELEASING.md`, holds the release
      procedure, and the release task names it. `CONTRIBUTING.md` keeps only
      the rules for outside contributors and links to it.

    Its tests run a real preparation in a disposable clone, not only a dry
    run, because a dry run skips validation.
13. Release 0.9, run the field trial, release 1.0.0.

## Consequences

- One product name with no collision in package registries or system
  commands.
- One workflow and one skill per host. A project chooses its default
  assurances, and a task can raise or lower them.
- Fewer Stable commands: about 15 instead of about 60 public commands.
- No historical migration code to maintain.
- Installation is one command, independent of the host.
- For several weeks Meridian receives only blocking fixes.
- Cardine's Git history starts at the import commit. Meridian's history stays
  readable in its archived repository.

## Risks

| Risk | Mitigation |
| --- | --- |
| Scope grows during the rewrite ("second system") | This ADR is the 1.0 scope; new ideas wait until after 1.0. |
| Behavior is lost while the code is split | Item 3 is mechanical. The existing suite of more than 1,000 tests stays green with its assertions unchanged; tests change only their imports, patch targets, and file locations (`docs/MODULE_SPLIT_PLAN.md`). |
| The single workflow misses a Governed SDD use | The parity table in decision 3 and the field-trial exit criterion in decision 10. |
| Agent autonomy erodes a guardrail (decision 12) | Guardrails are the registry codes with `human_decision`, and they always stop. Writing false state, running a denied action, and changing scope stay forbidden. Recoverable codes need a test proving their next action. |
| The `cardine` PyPI name is taken meanwhile | Publish a `0.0.1` placeholder first. |
| A trademark conflict with a business using the name | Registration is deferred until after 1.0. EU and Italian registers must be checked before registration. |

## Rejected alternatives

- **Rename the existing repository and keep version numbers.** Tags `v1.0.0`
  to `v1.4.0` already exist, so Cardine 1.0.0 would collide with Meridian
  1.0.0. A rename also carries the rewritten history and the open GitHub
  Support request.
- **Cardine 2.0.0 with deprecated `meridian` aliases, removed in 3.0.0.** This
  follows the stability rules for adopters who do not exist, at the cost of
  dual code paths for a full major cycle.
- **Keep two parallel workflows.** Keeps every cost listed in the context.
  The presets keep their names and identities without a second engine.
- **Lean Delivery only.** Drops independent review, which 268 Contoso tasks used.
- **Task state in Markdown front matter.** Rejected under decision 4.
- **Document plain `pip` installation.** Externally managed Python builds
  refuse it outside a virtual environment, and a global install mixes Cardine's
  dependencies with other tools.
- **Keep the context budget as it is.** The usage data in decision 5 shows cost
  without a single command-backed stop.

## Out of scope

- Trademark registration, deferred until after 1.0.
- Hosts other than Claude Code and Codex.
- Parallel orchestration of several agents. Cardine runs inside each worktree.
- `pull-request` landing mode, planned for 1.1 (decision 11).
- Conversion of closed Meridian tasks and review records.
