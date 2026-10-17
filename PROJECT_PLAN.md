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
- `[ ]` 009 — Extract protocol, Claude host, budget, project, and catalog modules (split plan E04).
- `[ ]` 010 — Extract migration, identity, file, router, and authority modules (split plan E05).
- `[ ]` 011 — Extract stop rendering, manifest, marker history, worktree storage, and Codex host modules (split plan E06).
- `[ ]` 012 — Extract projection, update, verdict, context, and journal modules (split plan E07).
- `[ ]` 013 — Extract evidence, marker audit, migration audit, worktree path, and skill modules (split plan E08).
- `[ ]` 014 — Extract flow, task audit, contract, importer, and budget command modules (split plan E09).
- `[ ]` 015 — Extract preflight, worktree checkout, integration evidence, execution, and setup modules (split plan E10).
- `[ ]` 016 — Extract merge, recording, transition, template audit, and closure status modules (split plan E11).
- `[ ]` 007 — Recover worktree cleanup after a partial removal.
- `[ ]` 017 — Record wall-clock time and the real CI command in CI evidence.
