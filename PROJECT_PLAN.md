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

## Deferred Items

Work that a task found or postponed, recorded here so that the planning of
the named work item finds it on `main`.

| Item | Target | Source |
|------|--------|--------|
| A runnable recovery command for `EVIDENCE_INCOMPLETE`, proved by an end-to-end test | Work item 8 | `tasks/handoffs/030.md`, proposal 1 |
| Split the mixed guardrail codes by cause, so that safe subcases become recoverable | Work item 8 | `tasks/handoffs/030.md`, proposal 2 |
| Remove the budget lines from the per-turn queue briefing | Work item 9 | `tasks/handoffs/035.md` |
| The queue briefing drops every queued task when a title contains an apostrophe (`xargs: unterminated quote`); add a regression test | Work item 9 | Coordinator finding, 2026-10-19 |
| Rename this repository's managed copy of `CONTEXT_BUDGET_POLICY.md`; the templates are renamed by row SW5 of `docs/SINGLE_WORKFLOW_PLAN.md` | Work item 10 | `tasks/handoffs/035.md`, `docs/SINGLE_WORKFLOW_PLAN.md` |
| Verify conflicted merge blocks against each template file's own marker version | Work item 6, row SW5 | `tasks/handoffs/038.md` |
| Delete `MERIDIAN_ROOT`, `bin/`, `scripts/upgrade_project.sh`, and the old release scripts instead of keeping them renamed | Decision 9 and work item 12 | `docs/RENAME_PLAN.md`, choice 6 |
| Keep the coordinator snapshot of this repository working when row SW1 replaces `detect_mode`: the Meridian workflow detection moves into `cardine.legacy` | Work item 6, row SW1 | `docs/RENAME_PLAN.md`, choice 5 |

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
- `[x]` 023 — Split the `MeridianCliTest` class by responsibility.
- `[x]` 024 — Move the remaining `test_meridian_cli.py` classes to domain test files.
- `[x]` 025 — Split `test_task_worktree_isolation.py`.
- `[x]` 026 — Verify the completed module split (split plan V01).
- `[x]` 027 — Replace the per-task CI gate with a clean-clone run and a two-platform release gate.
- `[x]` 028 — Accept a dirty worktree in `worktree check` during an explicit Resume.
- `[x]` 029 — Make agents stop only for decisions that need a person.
- `[x]` 030 — Classify every stop code and prove each recovery command.
- `[x]` 031 — Record template changes without migrations until 1.0.
- `[x]` 032 — Move the upgrade and merge tests to synthetic migration fixtures.
- `[x]` 033 — Empty the migration chain.
- `[x]` 034 — Remove release baselines and adoption from historical versions.
- `[x]` 035 — Remove the self-reported budget counters.
- `[x]` 036 — Move maintainer commands out of the user CLI and merge the generators.
- `[x]` 037 — Scan only repository files in `check_repository.py`.
- `[x]` 038 — Reject a stale `requiredVersion` in the marker catalog.
- `[x]` 039 — Check the self-hosting installation only with the installed Meridian.
- `[x]` 040 — Plan the rename of code identifiers (work item 5a).
- `[x]` 041 — Plan the single workflow (work item 6).
- `[x]` 042 — Introduce the project names accessor (rename plan R1).
- `[ ]` 043 — Extract the read-only Meridian installation reader (rename plan R2).
- `[ ]` 044 — Decouple the frozen-surface readers (rename plan R3).
- `[ ]` 045 — Rename the exception and parser classes (rename plan R4).
- `[ ]` 046 — Rename the executables, the adapter, and the test modules (rename.
- `[ ]` 047 — Rename the command word in output and data (rename plan R6).
- `[ ]` 048 — Rename the environment names and options (rename plan R7).
- `[ ]` 049 — Rename the project directory and the profile id (rename plan R8).
- `[ ]` 050 — Rename Git-internal files and the worktree root (rename plan R9).
- `[ ]` 051 — Rename the product strings and guard against Meridian identifiers.
