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
| A runnable recovery command for `EVIDENCE_INCOMPLETE`, proved by an end-to-end test | Row C3c | `tasks/handoffs/030.md`, proposal 1 |
| Rename this repository's managed copy of `CONTEXT_BUDGET_POLICY.md`; the templates are renamed by row SW5 of `docs/SINGLE_WORKFLOW_PLAN.md` | Row C2d | `tasks/handoffs/035.md`, `docs/SINGLE_WORKFLOW_PLAN.md` |
| Delete `MERIDIAN_ROOT`, `bin/`, `scripts/upgrade_project.sh`, and the old release scripts instead of keeping them renamed | Decision 9 and work item 12 | `docs/RENAME_PLAN.md`, choice 6 |
| Remove this repository's own scripts (`python3 scripts/check_repository.py`, `python3 scripts/run_tests.py --parallel`, `python3 -m unittest discover -s tests`) from the product's Claude allowlist (`src/cardine/hosts/claude.py`) and Codex rule probes (`src/cardine/hosts/setup.py`). Cardine ships rules only for its own commands, the lifecycle's Git commands, and the deny list; an adopter's test and validation commands stay in that project's own host configuration. The allowlists are clean; `integration/evidence.py` still proposes this repository's script | Row C7e | Coordinator finding, 2026-10-24 |
| Call product functions in-process in the tests that exercise logic rather than the executable; 38 tests start the CLI as a subprocess | Family C8, after 0.9 | Coordinator code analysis, 2026-10-25 |
| Import product modules directly in the 64 test modules that still go through the `scripts/cardine_cli.py` adapter, and merge the remaining duplicate helpers (`_worktrees`, `_primary_checkout`, `_read_text`, `_load_snapshot`) of the modules still marked as extracted from the legacy CLI | Family C8, after 0.9; helpers in row C7f | Coordinator code analysis, 2026-10-25 |
| Move `cardine task state import` (`tasks/importer.py`) and its queue reader `_queue_task_rows` (`integration/projections.py`, re-exported by `scripts/cardine_cli.py`) into the conversion that rebuilds `cardine adopt`, so that the three documented exceptions of `tests/test_product_prose_readers.py` and entries T-27 and T-31 of `docs/TEXT_GATE_INVENTORY.md` reach zero | Rows C1b, C1c | `tasks/handoffs/070.md`; coordinator decision, 2026-10-22 |
| Protect the installation surface (manifest, marker baselines, capability and probe evidence, upgrade recovery) against coherent project-file forgery, row FI1 | After 1.0 | `docs/FORGERY_INVENTORY.md`, F-E; ADR decision 14, rule 2, as amended on 2026-10-23 |
| Write the records of rows C7a to C7f in Meridian format before boundary B1, so that `adopt` converts real open tasks | Row C6a | `docs/CONVERSION_PLAN.md`, section 5 |

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
- `[x]` 093 — Enforce the expected surface and record delivery identity (RE3a).
- `[x]` 096 — Store execution evidence in one file per task.
- `[x]` 094 — Run task validation in the engine with a retry limit (RE3b).
- `[x]` 095 — Remove the handoff and report gates (N3).
- `[x]` 100 — Resolve each command's context once and bound its Git subprocesses.
- `[x]` 102 — Launch implementer and reviewer with distinct host roles (RE4a).
- `[x]` 103 — Bind verdict, cancel, and abort to issued roles (RE4b).
- `[x]` 104 — Decide landing from pinned policy and Git facts (RE5a).
- `[x]` 105 — Run candidate validation and reconcile finalize and abort (RE5b).
- `[x]` 106 — Query CI by exact repository and commit (RE6a).
- `[x]` 107 — Verify the main push and clean up remote and local branches (RE6b).
- `[x]` 108 — Make self-update repeatable with a pinned target (SR1a).
- `[x]` 109 — Make upgrade and host writes repeatable (SR1b).
- `[x]` 110 — Rewrite the always-read product templates (TR1a).
- `[x]` 111 — Guard template budgets, commands, and stop prose (TR1b).
- `[x]` 112 — Condense the lifecycle and record templates (TR2a).
- `[x]` 113 — Condense the remaining templates and delete folded documents (TR2b).
- `[x]` 114 — Show console previews and actions from verified facts (RE7a).
- `[x]` 115 — Audit the run engine end to end and document its commands (RE7b).
- `[x]` 116 — Plan the host integration (work item 9).
- `[x]` 117 — Prove the receipt writer once and test each operation's own boundaries.
- `[x]` 118 — Print only the generated status in the per-turn briefing (H1a).
- `[x]` 119 — Use one Python read guard with two payload adapters (H1b).
- `[x]` 120 — Run the stop audit in Python and retire the shell wrapper (H1c).
- `[x]` 121 — Load heavy imports only on the release and update paths (H1d).
- `[x]` 122 — Add cardine init with preview and apply (H2a).
- `[x]` 123 — Rename the init slash command and route it to the CLI (H2b).
- `[x]` 124 — Rename the remaining slash commands to Cardine routes (H2c).
- `[x]` 125 — Write the two Cardine skills and fix the Accept route (H3a).
- `[x]` 126 — Remove the four old skills and install the two shared links (H3b).
- `[x]` 127 — Rename the plugin metadata and stop shipping product auto-hooks (H3c).
- `[x]` 128 — Route the entry routers and register the managed templates (H3d).
- `[x]` 129 — Name the Codex rules and profile for Cardine with a bounded migration (H4a).
- `[x]` 130 — Orchestrate setup on Cardine paths without real-home apply (H4b).
- `[x]` 131 — Register user-level hooks on both hosts without duplicates (H4c).
- `[x]` 132 — Unify doctor and drop adopter test-command assumptions (H4d).
- `[x]` 133 — Enforce protected paths and Claude role restrictions (H5a).
- `[x]` 134 — Realize the Codex role policy and profiles (H5b).
- `[x]` 135 — Wire the concrete host transports to issued roles (H5c).
- `[x]` 136 — Prove roles at runtime in doctor and update the host contract (H5d).
- `[x]` 137 — Restore the run engine fixtures in place instead of rebuilding them.
- `[x]` 138 — Restore the remaining heavy fixtures in place.
- `[x]` 139 — Reuse the ready cleanup fixture and measure the real savings.
- `[x]` 140 — Balance test shards by measured duration without reducing coverage.
- `[x]` 141 — Plan the Meridian conversion and cardine adopt (work item 10).
- `[x]` 142 — Limit legacy imports to the adopt package (C1a).
- `[x]` 143 — Move the importer and queue reader under legacy (C1b).
- `[x]` 144 — Bring the prose reader ratchets to zero (C1c).
- `[x]` 145 — Classify and fix the fresh task start failure (C3a).
- `[x]` 146 — Make run perform the contract and worktree steps (C3b).
- `[x]` 147 — Prove a no-review delivery to landing (C3c).
- `[x]` 148 — Align the run help with its behavior (C3d).
- `[x]` 149 — Prove the spike, authority, and resume cases (C3e).
- `[x]` 150 — Add the developer channel for verdict, cancel, and abort (C4a).
- `[x]` 151 — Deliver a required-review task through the developer channel (C4b).
- `[x]` 152 — Deliver a disposable task with an agent following run (C3f).
- `[x]` 153 — Add the read model of a Meridian project (C2a).
- `[x]` 154 — Translate open records for adopt (C2b).
- `[x]` 155 — Plan the adoption as a pure function (C2c).
- `[x]` 156 — Apply the adoption and release the managed copies (C2d).
- `[x]` 157 — Rehearse the adoption on a clone (C2e).
- `[x]` 158 — Expose the cardine adopt command (C2f).
- `[x]` 159 — Make the installation checks conditional (C5a).
- `[x]` 160 — Bind identifier allowances to existing paths (C5b).
- `[x]` 161 — Move live installation tests to fixtures (C5c).
- `[x]` 162 — Run the shell hook tests only while the hooks exist (C5d).
- `[x]` 163 — Prove Meridian and Cardine coexist on one machine (C5e).
- `[x]` 174 — Declare the capability profile at init.
- `[x]` 175 — Rehearse the adoption without patching the process.
- `[x]` 176 — Keep the legacy worktree root in the Codex permission profile.
- `[x]` 177 — Translate Validation sections as the Cardine contract reads them.
- `[x]` 183 — Convert this repository so that its own checks pass.
- `[x]` 164 — Rehearse the conversion of this repository (C6a).
- `[x]` 186 — Make the switch commit pass the repository checks.
- `[x]` 187 — Check path aliases only where the platform resolves them.
- `[x]` 188 — Deliver a task created by init and task new through run alone.
- `[ ]` 178 — Delete the unreachable installation branches (C7a).
- `[ ]` 179 — Remove the shell hooks and their tests (C7b).
- `[ ]` 180 — Restrict the identifier guard to the shipped surfaces (C7c).
- `[ ]` 181 — Stop proposing this repository's script as evidence (C7e).
- `[ ]` 182 — Delete the legacy snapshot reader (C7f).
- `[x]` 184 — Plan the documentation (work item 11).
- `[x]` 185 — Plan the release script (work item 12).
- `[x]` 166 — Reuse the prepared state in the integration and cleanup tests.
- `[x]` 167 — Reduce the cost of the host plugin kill matrix.
- `[x]` 168 — Reuse the prepared state in the receipt and recovery matrices.
- `[x]` 169 — Reuse Git reads that a command cannot have changed.
- `[x]` 170 — Refresh the shard weights after the test cost work.
- `[x]` 171 — Rerun only the failing commands through declared retry variants.
- `[x]` 172 — Run declared quick checks first and limit their failures separately.
- `[x]` 173 — Separate the recovery rules from their Git reads.

<!-- cardine-status:begin -->
<!-- Generated by `cardine status --write`; input digest 41cbb3f3e95fde09c39a51a3c1bfe214421bfa5444792c29096b953fb20ffec9. Do not edit: rerun the command. -->

Preset: lean
Totals: queued=13, in_progress=0, in_review=0, done=21, cancelled=0, total=34

| Status | ID | Title | Phase |
|--------|----|-------|-------|
| done | 178 | Task 178 — Delete the unreachable installation branches (C7a) | - |
| done | 179 | Task 179 — Remove the shell hooks and their tests (C7b) | - |
| queued | 180 | Task 180 — Restrict the identifier guard to the shipped surfaces (C7c) | - |
| done | 181 | Task 181 — Stop proposing this repository's script as evidence (C7e) | - |
| queued | 182 | Task 182 — Delete the legacy snapshot reader (C7f) | - |
| done | 189 | Task 189 — Adopt an existing repository that has no workflow | - |
| done | 190 | Task 190 — Write Claude deny rules that Claude Code accepts | - |
| queued | 191 | Task 191 — Treat archived queue rows as closed dependencies in adoption | - |
| done | 192 | Task 192 — Let the console Run start the developer's agent session | - |
| done | 195 | Task 195 — Cover prose-only record revisions with a receipt | - |
| done | 198 | Task 198 — Keep in-progress operations valid across an accepted Cardine update | - |
| done | 199 | Task 199 — Report a finished cleanup as done after a new authorization | - |
| done | 200 | Task 200 — Register hook commands that run outside an interactive shell | - |
| done | 201 | Task 201 — Keep measured validation fresh across host sessions | - |
| done | 203 | Task 203 — Decide which refusals the engine resolves and how project decisions reach agents | - |
| done | 204 | Task 204 — Redeliver a new implementation after a completed validation attempt | - |
| done | 205 | Task 205 — Move standing decisions to the project workflow and report every out-of-scope path at once | - |
| done | 206 | Task 206 — Let the engine reverse its own stale candidate | - |
| queued | 211 | Task 211 — Make console refreshes cheap | - |
| queued | 213 | Task 213 — Make CI a real gate before landing | - |
| done | 214 | Task 214 — Run on the candidate only the commands that can give a new result | - |
| done | 215 | Task 215 — Repair the tests and the stop that the integrated tasks left behind | - |
| queued | 216 | Task 216 — Let Codex run the lifecycle commands without a prompt | - |
| queued | 217 | Task 217 — Let a repair be delivered after a failed validation attempt | - |
| queued | 193 | Task 193 — Let adoption start again on a new commit | - |
| done | 194 | Task 194 — Keep machine-local Cardine files out of version control | - |
| queued | 196 | Task 196 — Rewrite the README for Cardine (D1) | - |
| done | 197 | Task 197 — Keep the Claude settings that setup writes out of Git | - |
| done | 202 | Task 202 — Let untracked files in the primary checkout stay out of integration | - |
| queued | 207 | Task 207 — Report test-run progress while the suite runs | - |
| queued | 208 | Task 208 — Write a live log of the commands a run executes | - |
| queued | 209 | Task 209 — Follow the live run output of a task in the console | - |
| queued | 210 | Task 210 — Open launched agents in a column beside the console | - |
| done | 212 | Task 212 — Register the Codex hooks once, in the user registry | - |
<!-- cardine-status:end -->
