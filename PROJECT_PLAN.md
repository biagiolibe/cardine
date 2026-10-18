# Project Plan — Cardine

## Task Lifecycle

```text
[ ] TODO -> [/] IN_PROGRESS -> [x] DONE
```

## Vision

Cardine is the delivery discipline for AI coding agents. Every task lands on
`main` validated, integrated, and reversible, or it stops with a reason and the
exact command to resume. The scope of 1.0 is
[docs/ADR_CARDINE_1_0.md](docs/ADR_CARDINE_1_0.md).

## Origin

This repository starts from the code of Meridian 1.4.0
(<https://github.com/biagiolibe/meridian>, tag `v1.4.0`). Meridian's history,
task records, and design reports stay in that repository. Until `cardine run`
can deliver its own tasks, Cardine is developed with the Meridian 1.4.0 Lean
Delivery workflow that this import carries.

## Active Delivery

The work items to 0.9 are listed in the ADR.

- `[x]` 001 — Make the evidence tests independent of Meridian task records.
- `[x]` 002 — Add `pyproject.toml` and the `cardine` package skeleton.
- `[x]` 003 — Plan the split of `meridian.py` into the Cardine modules.
- `[x]` 004 — Extract the leaf modules (split plan E01).
- `[x]` 005 — Make the module inventory test pass in a shallow clone.
- `[x]` 006 — Extract text, version, Git, JSON, and model modules (split plan E02).
- `[x]` 008 — Extract usage, validation, stop registry, marker, and mode modules (split plan E03).
- `[x]` 009 — Extract protocol, Claude host, budget, project, and catalog modules (split plan E04).
- `[x]` 010 — Extract migration, identity, file, router, and authority modules (split plan E05).
- `[x]` 011 — Extract stop rendering, manifest, marker history, worktree storage, and Codex host modules (split plan E06).
- `[x]` 012 — Extract projection, update, verdict, context, and journal modules (split plan E07).
- `[x]` 013 — Extract evidence, marker audit, migration audit, worktree path, and skill modules (split plan E08).
- `[x]` 014 — Extract flow, task audit, contract, importer, and budget command modules (split plan E09).
- `[x]` 015 — Extract preflight, worktree checkout, integration evidence, execution, and setup modules (split plan E10).
- `[x]` 016 — Extract merge, recording, transition, template audit, and closure status modules (split plan E11).
- `[x]` 007 — Recover worktree cleanup after a partial removal.
- `[x]` 017 — Record wall-clock time and the real CI command in CI evidence.
- `[x]` 018 — Resume a Lean closure without state through `task close`.
- `[x]` 019 — Extract lifecycle, upgrade support, merge, and adoption modules (split plan E12).
- `[x]` 020 — Extract console models, launch, and snapshot (split plan C01).
- `[x]` 021 — Extract console state, render, and entry, and split the console tests (split plan C02).
- `[x]` 022 — Extract upgrade, adopt command, and CLI, and switch the entry points (split plan E13).
- `[ ]` 023 — Split the `MeridianCliTest` class by responsibility.
- `[ ]` 024 — Move the remaining `test_meridian_cli.py` classes to domain test files.
- `[ ]` 025 — Split `test_task_worktree_isolation.py`.
- `[ ]` 026 — Verify the completed module split (split plan V01).
- `[x]` 027 — Replace the per-task CI gate with a clean-clone run and a two-platform release gate.
- `[x]` 028 — Accept a dirty worktree in `worktree check` during an explicit Resume.
- `[ ]` 029 — Make agents stop only for decisions that need a person.
- `[ ]` 030 — Classify every stop code and prove each recovery command.
- `[ ]` 031 — Record template changes without migrations until 1.0.
- `[ ]` 032 — Move the upgrade and merge tests to synthetic migration fixtures.
- `[ ]` 033 — Empty the migration chain.
- `[ ]` 034 — Remove release baselines and adoption from historical versions.
- `[ ]` 035 — Remove the self-reported budget counters.
- `[ ]` 036 — Move maintainer commands out of the user CLI and merge the generators.
- `[ ]` 037 — Scan only repository files in `check_repository.py`.
