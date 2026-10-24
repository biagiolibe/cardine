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
| Delete `MERIDIAN_ROOT`, `bin/`, `scripts/upgrade_project.sh`, and the old release scripts instead of keeping them renamed | Decision 9 and work item 12 | `docs/RENAME_PLAN.md`, choice 6 |
| Add `cardine init` (decision 8), replacing the copy steps of the init slash command that task 055 rewrites | Work item 9 | Task 055 record |
| Remove this repository's own scripts (`python3 scripts/check_repository.py`, `python3 scripts/run_tests.py --parallel`, `python3 -m unittest discover -s tests`) from the product's Claude allowlist (`src/cardine/hosts/claude.py`) and Codex rule probes (`src/cardine/hosts/setup.py`). Cardine ships rules only for its own commands, the lifecycle's Git commands, and the deny list; an adopter's test and validation commands stay in that project's own host configuration | Work item 9 | Coordinator finding, 2026-10-24 |
| Move `cardine task state import` (`tasks/importer.py`) and its queue reader `_queue_task_rows` (`integration/projections.py`, re-exported by `scripts/cardine_cli.py`) into the conversion that rebuilds `cardine adopt`, so that the three documented exceptions of `tests/test_product_prose_readers.py` and entries T-27 and T-31 of `docs/TEXT_GATE_INVENTORY.md` reach zero | Work item 10 | `tasks/handoffs/070.md`; coordinator decision, 2026-10-22 |
| Protect the installation surface (manifest, marker baselines, capability and probe evidence, upgrade recovery) against coherent project-file forgery, row FI1 | After 1.0 | `docs/FORGERY_INVENTORY.md`, F-E; ADR decision 14, rule 2, as amended on 2026-10-23 |
| The governed skills route `Accept` to `docs/workflows/LIFECYCLE.md`, which the single template set no longer installs | Work item 9 | `tasks/handoffs/055.md` |

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
- `[x]` 043 — Extract the read-only Meridian installation reader (rename plan R2).
- `[x]` 044 — Decouple the frozen-surface readers (rename plan R3).
- `[x]` 045 — Rename the exception and parser classes (rename plan R4).
- `[x]` 046 — Rename the executables, the adapter, and the test modules (rename.
- `[x]` 047 — Rename the command word in output and data (rename plan R6).
- `[x]` 048 — Rename the environment names and options (rename plan R7).
- `[x]` 049 — Rename the project directory and the profile id (rename plan R8).
- `[x]` 050 — Rename Git-internal files and the worktree root (rename plan R9).
- `[x]` 051 — Rename the product strings and guard against Meridian identifiers.
- `[x]` 052 — Resolve the project preset from the configuration (single workflow SW1).
- `[x]` 053 — Resolve one task contract and store its snapshot (single workflow SW2).
- `[x]` 054 — Use one task state machine with review and dependency gates (single workflow SW3).
- `[x]` 055 — Build the single template set (single workflow SW4).
- `[x]` 056 — Reconcile the capability catalog with the single template set (single workflow SW5).
- `[x]` 057 — Name the preset in the per-turn briefing (single workflow SW6).
- `[x]` 058 — Remove residual workflow branching and prove parity (single workflow SW7).
- `[x]` 059 — Plan the single source of task state (work item 7).
- `[x]` 060 — Remove the Meridian name and the old states from the template text (work item 5b).
- `[x]` 061 — Rename the capability markers and restart every capability at v1 (work item 5b).
- `[x]` 062 — Plan the cardine run engine (work item 8).
- `[x]` 063 — Plan the preparation of the benchmark against a minimal procedure.
- `[x]` 064 — Extract the installation snapshot path (single source SS1).
- `[x]` 065 — Build the task status service and cardine status (single source SS2).
- `[x]` 066 — Create the task record and its state together (single source SS3).
- `[x]` 067 — Generate the queue and the plan status region (single source SS4).
- `[x]` 068 — Remove the product prose status gates (single source SS5).
- `[x]` 071 — Report the stop detail in worktree advance output.
- `[x]` 069 — Keep task records stable through close and landing (single source SS6).
- `[x]` 073 — Inventory the product gates that read text (decision 13).
- `[x]` 072 — Remove the delivery commit gate.
- `[x]` 070 — Switch the console and the briefing to the status service (single source SS7).
- `[x]` 074 — Inventory the template rules and their enforcement (decision 14).
- `[x]` 075 — Map what an agent can forge among the artifacts gates trust (decision 14).
- `[x]` 076 — Review every stop the tool could resolve itself (decision 14).
- `[x]` 077 — Use one product name in the execution contract line.
- `[x]` 078 — Add the text gate static guard as a ratchet (decision 13).
- `[x]` 079 — Freeze the remaining human contract fields in the snapshot (N1, part 1).
- `[x]` 080 — Read the human contract fields from the snapshot (N1, part 2).
- `[x]` 081 — Allow every task record in the identifier guard by pattern.
- `[x]` 082 — Revise the run engine plan with the inventories and the trust boundary.
- `[x]` 083 — Remove the self-reported evidence counters (RX1).
- `[x]` 084 — Read class, review policy, and deliverables from the snapshot (N2a).
- `[x]` 085 — Read validation commands, host impact, and locations from frozen inputs (N2b).
- `[x]` 086 — Add the pure run resolver and output envelope (RE1a).
- `[x]` 087 — Write and verify operation receipts (RE1b).
- `[x]` 088 — Make state readers and preparation require receipts (RE1c).
- `[x]` 089 — Classify worktree, state, lease, and cleanup stops by cause (RE2a).
- `[x]` 090 — Consolidate the approval, configuration, and workflow codes (RE2b).
- `[x]` 097 — Add focused development runs to the test runner.
- `[x]` 098 — Build heavy lifecycle test fixtures once per class.
- `[x]` 099 — Keep the test failure record writable in the sandbox.
- `[x]` 091 — Classify self-update, upgrade, and host stops by cause (RE2c).
- `[x]` 092 — Dispatch typed outcomes through one renderer (RE2d).
- `[ ]` 093 — Enforce the expected surface and record delivery identity (RE3a).
- `[ ]` 096 — Store execution evidence in one file per task.
- `[ ]` 094 — Run task validation in the engine with a retry limit (RE3b).
- `[ ]` 095 — Remove the handoff and report gates (N3).
