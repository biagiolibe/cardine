> **Cardine is in development.** This repository starts from the code of
> Meridian 1.4.0 and still installs and runs as `meridian`. Until Cardine 0.9,
> use [Meridian 1.4.0](https://github.com/biagiolibe/meridian/releases/tag/v1.4.0).
> The scope of Cardine 1.0 is [docs/ADR_CARDINE_1_0.md](docs/ADR_CARDINE_1_0.md).

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/meridian-mark-dark.svg">
    <img src="docs/assets/meridian-mark-light.svg" alt="Meridian logo" width="96" height="96">
  </picture>
</p>

<h1 align="center">Meridian</h1>

<p align="center"><strong>Explicit tasks, isolated worktrees, verified integration. A delivery workflow for AI coding agents.</strong></p>

<p align="center">
  <a href="https://github.com/biagiolibe/meridian/releases"><img src="https://img.shields.io/github/v/release/biagiolibe/meridian" alt="Release"></a>
  <a href="https://github.com/biagiolibe/meridian/actions/workflows/validate.yml"><img src="https://github.com/biagiolibe/meridian/actions/workflows/validate.yml/badge.svg" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="MIT License"></a>
</p>

Meridian turns a project plan into bounded tasks that AI coding agents can implement, validate, and integrate with a durable record of the result. It supplies workflow instructions, templates, and a CLI; it is not an agent. It prescribes no application stack: each project owns its architecture, invariants, and validation commands. It runs from a local Git checkout, without a service or background process.

## Meridian in 30 seconds

A task makes the change and its proof explicit:

```markdown
# Task 001 — Explain the configuration defaults

## Objective
Document the defaults used when no configuration file exists.

## Acceptance criteria
- README lists each default and the command that overrides it.

## Validation
python3 scripts/check_docs.py
```

In an initialized project, assign it to your agent:

```text
Proceed with 001
```

For a Lean Delivery task, that directive authorizes the whole lifecycle: prepare an isolated task branch and worktree, implement the task, run its validation, record completion, validate the integration candidate, integrate, push `main`, and clean up the merged worktree. Each step proceeds only when its gates pass. A failed gate returns a concrete `BLOCKED <CODE>` and a resume command.

Follow the [quick start](docs/QUICKSTART.md) to initialize a project and close your first task.

## Features

- **Explicit tasks:** objectives, acceptance criteria, context, and validation stay with the code.
- **Per-task worktrees:** one branch, one checkout, and one writer per task isolate concurrent work.
- **Command-backed stops:** lifecycle gates explain why work stopped and how to resume.
- **Denied destructive actions:** task authorization excludes force pushes, history rewriting, tags, releases, and textual conflict resolution.
- **Migration-based upgrades:** versioned baselines and three-way merges preserve project-owned changes.
- **Project console:** inspect tasks, dependencies, worktrees, and the next permitted action with `meridian console` (experimental).
- **Host hooks:** bounded reads, queue briefings, and stop audits reinforce the project workflow.

## Choose a workflow

**Lean Delivery is the default starting point** for small projects, prototypes, demos, and reversible changes. Tasks use `[ ]` → `[/]` → `[x]` and carry enough context to implement and verify one bounded change.

**Governed SDD** adds architectural authority, dependencies, execution evidence, and independent review for higher-risk work involving public APIs, security, persistence, state, or unresolved design decisions. SDD means spec-driven development: the task is the durable specification. Its lifecycle is `QUEUED` → `IN_PROGRESS` → `READY_FOR_REVIEW` → `ACCEPTED`, with a direct acceptance path for eligible low-risk work.

Each project's `PROJECT_WORKFLOW.md` locks its mode and takes precedence over global or remembered instructions. See the [Lean guide](WORKFLOW_GUIDE.md) and [governed workflow](docs/GOVERNED_WORKFLOW.md).

## Install

Requires macOS or Linux, Python 3.12+, Git, and an installed, authenticated agent host. See [platform support](docs/PLATFORM_SUPPORT.md) for the CI-tested matrix and best-effort integrations.

**1. Install the CLI for every host** at the canonical checkout:

```bash
git clone --branch stable https://github.com/biagiolibe/meridian ~/.local/share/meridian
export MERIDIAN_ROOT="$HOME/.local/share/meridian"
export PATH="$MERIDIAN_ROOT/bin:$PATH"
```

Persist both exports (`~/.zshenv` for zsh). The
[quick start](docs/QUICKSTART.md#install-the-cli-for-every-host) covers bash,
non-interactive Python/PATH checks, and release verification.
Use `--branch v<version>` to pin a [specific release](https://github.com/biagiolibe/meridian/releases)
at the same path.

**2. Connect your host.** For Claude Code, install the matching release plugin:

```text
/plugin marketplace add biagiolibe/meridian#stable
/plugin install meridian@meridian
```

Keep plugin and checkout versions aligned; terminal commands use the checkout
CLI. For Codex, run `meridian setup --check`, review the skill-link and
permission-profile diff, then consent with `meridian setup --apply` and
restart. Follow the [quick start](docs/QUICKSTART.md#connect-codex) for
initialization and effective access checks.

## Update

Update the installed plugin or local framework checkout first, restart agent sessions, then preview and apply the project migration on a dedicated branch. The [upgrade guide](docs/HOW_TO_UPGRADE.md) covers both `stable` and tagged checkouts, plugin pins, version checks, [manual updates](docs/HOW_TO_UPGRADE.md#updating-meridian), and [framework upgrades](docs/HOW_TO_UPGRADE.md#framework-upgrades).

## Documentation

**Adopters**

- [Quick start](docs/QUICKSTART.md), [platform support](docs/PLATFORM_SUPPORT.md), and [upgrade guide](docs/HOW_TO_UPGRADE.md)
- [Lean Delivery guide](WORKFLOW_GUIDE.md) and [workflow template](templates/workflows/lean-delivery/PROJECT_WORKFLOW.md)
- [Language behavior](docs/AGENT_OPERATIONS.md#language-behavior)

**Agent operators**

- [Agent operations](docs/AGENT_OPERATIONS.md): console, [Codex command approvals](docs/AGENT_OPERATIONS.md#codex-hooks-and-command-approvals), read guard, and local usage reports
- [Governed execution evidence](docs/GOVERNED_WORKFLOW.md#governed-execution-evidence), [workflow template](templates/workflows/governed-sdd/PROJECT_WORKFLOW.md), and [task template](templates/workflows/governed-sdd/tasks/TASK_BLUEPRINT.md)
- [Review and integration](templates/workflows/governed-sdd/docs/CODE_REVIEW_PROMPT.md), [read-only audit](templates/workflows/governed-sdd/docs/AUDIT_PROMPT_READ_ONLY.md), and [operator prompts](templates/workflows/governed-sdd/docs/OPERATOR_PROMPTS.md)
- [Consumer router adoption](docs/CONSUMER_ROUTER_ADOPTION_PLAYBOOK.md) and [capability audit](commands/meridian-audit.md)

**Maintainers**

- [Contributing and releases](CONTRIBUTING.md), [upgrade CLI](commands/meridian-upgrade.md), [distribution design](docs/DISTRIBUTION_AND_UPDATE_DESIGN.md), and [consumer profiles](docs/CONSUMER_PROFILES.md)
- [Public surface](docs/PUBLIC_SURFACE.md): stable compatibility starts at 1.3.0; `meridian console` and `meridian usage` are experimental.
- [Open tasks](tasks/QUEUE.md) and [project plan](PROJECT_PLAN.md)

## Community and license

Follow the [code of conduct](CODE_OF_CONDUCT.md) and report vulnerabilities privately through the [security policy](SECURITY.md).

Copyright © 2026 Biagio Liberto. Available under the [MIT License](LICENSE).

`meridian self-update` is Experimental. Preview local framework updates with
`meridian self-update --check`, then use `--apply`; see
[the update procedure](docs/HOW_TO_UPGRADE.md#1-update-the-framework-first).
