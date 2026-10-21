# Task Execution Queue — Archive

Closed phases and sections moved out of the operational queue once every row in them is
`[x]`, to keep that file's reading cost low. Mirrors the queue's own table
structure.

### Phase 1 — Repository bootstrap and module split plan

Authority: `docs/ADR_CARDINE_1_0.md`, work items 2 and 3.

| Status | ID | Title | Priority | Depends on | File |
|--------|----|-------|----------|------------|------|
| `[x]` | 001 | Make the evidence tests independent of Meridian task records | 🔴 P1 | — | [001](done/001-self-contained-evidence-tests.md) |
| `[x]` | 002 | Add `pyproject.toml` and the `cardine` package skeleton | 🔴 P1 | — | [002](done/002-package-skeleton.md) |
| `[x]` | 003 | Plan the split of `meridian.py` into the Cardine modules | 🔴 P1 | 002 | [003](done/003-module-split-plan.md) |

### Phase 2 — Module split

Authority: `docs/ADR_CARDINE_1_0.md`, work item 3, and `docs/MODULE_SPLIT_PLAN.md`.

| Status | ID | Title | Priority | Depends on | File |
|--------|----|-------|----------|------------|------|
| `[x]` | 004 | Extract the leaf modules (split plan E01) | 🔴 P1 | 003 | [004](done/004-extract-leaf-modules.md) |

### Phase 3 — CI repair after the first extraction

Authority: `docs/ADR_CARDINE_1_0.md`, work item 3, and `docs/MODULE_SPLIT_PLAN.md`.

| Status | ID | Title | Priority | Depends on | File |
|--------|----|-------|----------|------------|------|
| `[x]` | 005 | Make the module inventory test pass in a shallow clone | 🔴 P1 | 004 | [005](done/005-shallow-clone-inventory-baseline.md) |

### Phase 4 — Module split, provider extractions

Authority: `docs/ADR_CARDINE_1_0.md`, work item 3, and `docs/MODULE_SPLIT_PLAN.md`.

| Status | ID | Title | Priority | Depends on | File |
|--------|----|-------|----------|------------|------|
| `[x]` | 006 | Extract text, version, Git, JSON, and model modules (split plan E02) | 🔴 P1 | 005 | [006](done/006-extract-shared-git-and-models.md) |

### Phase 5 — Module split, remaining provider extractions

Authority: `docs/ADR_CARDINE_1_0.md`, work item 3, and `docs/MODULE_SPLIT_PLAN.md`.

| Status | ID | Title | Priority | Depends on | File |
|--------|----|-------|----------|------------|------|
| `[x]` | 008 | Extract usage, validation, stop registry, marker, and mode modules (split plan E03) | 🔴 P1 | 006 | [008](done/008-extract-stop-registry-and-markers.md) |
| `[x]` | 009 | Extract protocol, Claude host, budget, project, and catalog modules (split plan E04) | 🔴 P1 | 008 | [009](done/009-extract-protocol-and-catalog.md) |
| `[x]` | 010 | Extract migration, identity, file, router, and authority modules (split plan E05) | 🔴 P1 | 009 | [010](done/010-extract-identity-and-router.md) |
| `[x]` | 011 | Extract stop rendering, manifest, marker history, worktree storage, and Codex host modules (split plan E06) | 🔴 P1 | 010 | [011](done/011-extract-manifest-and-worktree-storage.md) |
| `[x]` | 012 | Extract projection, update, verdict, context, and journal modules (split plan E07) | 🔴 P1 | 011 | [012](done/012-extract-verdict-and-journal.md) |
| `[x]` | 013 | Extract evidence, marker audit, migration audit, worktree path, and skill modules (split plan E08) | 🔴 P1 | 012 | [013](done/013-extract-evidence-and-worktree-paths.md) |
| `[x]` | 014 | Extract flow, task audit, contract, importer, and budget command modules (split plan E09) | 🔴 P1 | 013 | [014](done/014-extract-contract-and-importer.md) |
| `[x]` | 015 | Extract preflight, worktree checkout, integration evidence, execution, and setup modules (split plan E10) | 🔴 P1 | 014 | [015](done/015-extract-worktree-checkout-and-execution.md) |
| `[x]` | 016 | Extract merge, recording, transition, template audit, and closure status modules (split plan E11) | 🔴 P1 | 015 | [016](done/016-extract-merge-and-transitions.md) |

### Phase 6 — Lifecycle defects carried from Meridian 1.4.0

Authority: `docs/ADR_CARDINE_1_0.md`, decisions 6 and 7.

| Status | ID | Title | Priority | Depends on | File |
|--------|----|-------|----------|------------|------|
| `[x]` | 007 | Recover worktree cleanup after a partial removal | 🟡 P2 | 016 | [007](done/007-recover-partial-worktree-cleanup.md) |
| `[x]` | 018 | Resume a Lean closure without state through `task close` | 🟡 P2 | 016 | [018](done/018-lean-closure-resume-uses-task-close.md) |

### Phase 7 — Development tooling defects

Authority: `docs/ADR_CARDINE_1_0.md`, decision 11.

| Status | ID | Title | Priority | Depends on | File |
|--------|----|-------|----------|------------|------|
| `[x]` | 017 | Record wall-clock time and the real CI command in CI evidence | 🟡 P2 | — | [017](done/017-fix-ci-evidence-timestamp.md) |

### Phase 8 — Module split completion

Authority: `docs/ADR_CARDINE_1_0.md`, work item 3, and `docs/MODULE_SPLIT_PLAN.md`.

| Status | ID | Title | Priority | Depends on | File |
|--------|----|-------|----------|------------|------|
| `[x]` | 019 | Extract lifecycle, upgrade support, merge, and adoption modules (split plan E12) | 🔴 P1 | 016, 007, 018 | [019](done/019-extract-lifecycle-and-template-merge.md) |
| `[x]` | 027 | Replace the per-task CI gate with a clean-clone run and a two-platform release gate | 🔴 P1 | — | [027](done/027-clean-clone-validation-and-release-matrix.md) |
| `[x]` | 020 | Extract console models, launch, and snapshot (split plan C01) | 🔴 P1 | 019, 027 | [020](done/020-extract-console-models-launch-snapshot.md) |
| `[x]` | 021 | Extract console state, render, and entry, and split the console tests (split plan C02) | 🔴 P1 | 020 | [021](done/021-extract-console-state-render-entry.md) |
| `[x]` | 028 | Accept a dirty worktree in `worktree check` during an explicit Resume | 🔴 P1 | 021 | [028](done/028-dirty-resume-check-without-stop.md) |
| `[x]` | 022 | Extract upgrade, adopt command, and CLI, and switch the entry points (split plan E13) | 🔴 P1 | 021, 028 | [022](done/022-extract-upgrade-adopt-and-cli.md) |
| `[x]` | 023 | Split the `MeridianCliTest` class by responsibility | 🔴 P1 | 022 | [023](done/023-split-meridian-cli-test-class.md) |
| `[x]` | 024 | Move the remaining `test_meridian_cli.py` classes to domain test files | 🔴 P1 | 023 | [024](done/024-split-remaining-cli-test-classes.md) |
| `[x]` | 025 | Split `test_task_worktree_isolation.py` | 🔴 P1 | 024 | [025](done/025-split-worktree-isolation-tests.md) |
| `[x]` | 026 | Verify the completed module split (split plan V01) | 🔴 P1 | 025 | [026](done/026-verify-module-split-completion.md) |

### Phase 11 — Repository tooling fixes

Authority: the developer decision of 2026-10-18 after the Meridian task 232 candidate validation stop.

| Status | ID | Title | Priority | Depends on | File |
|--------|----|-------|----------|------------|------|
| `[x]` | 037 | Scan only repository files in `check_repository.py` | 🔴 P1 | — | [037](done/037-check-repository-scans-only-repository-files.md) |

### Phase 9 — Stops reserved for decisions that need a person

Authority: `docs/ADR_CARDINE_1_0.md`, decision 12.

| Status | ID | Title | Priority | Depends on | File |
|--------|----|-------|----------|------------|------|
| `[x]` | 029 | Make agents stop only for decisions that need a person | 🔴 P1 | 033 | [029](done/029-stop-only-for-human-decisions.md) |
| `[x]` | 030 | Classify every stop code and prove each recovery command | 🔴 P1 | 028 | [030](done/030-audit-stop-codes-and-prove-recoveries.md) |

### Phase 10 — Remove historical compatibility

Authority: `docs/ADR_CARDINE_1_0.md`, work item 4, and decisions 5 and 7.

| Status | ID | Title | Priority | Depends on | File |
|--------|----|-------|----------|------------|------|
| `[x]` | 031 | Record template changes without migrations until 1.0 | 🔴 P1 | 026, 030 | [031](done/031-pre-1-0-template-baseline.md) |
| `[x]` | 032 | Move the upgrade and merge tests to synthetic migration fixtures | 🔴 P1 | 031 | [032](done/032-synthetic-upgrade-fixtures.md) |
| `[x]` | 033 | Empty the migration chain | 🔴 P1 | 032 | [033](done/033-empty-the-migration-chain.md) |
| `[x]` | 038 | Reject a stale `requiredVersion` in the marker catalog | 🔴 P1 | 029 | [038](done/038-check-marker-required-versions.md) |
| `[x]` | 034 | Remove release baselines and adoption from historical versions | 🔴 P1 | 029, 038 | [034](done/034-remove-release-baselines-and-historical-adoption.md) |
| `[x]` | 035 | Remove the self-reported budget counters | 🔴 P1 | 034 | [035](done/035-remove-budget-counters.md) |
| `[x]` | 039 | Check the self-hosting installation only with the installed Meridian | 🔴 P1 | 035 | [039](done/039-check-self-hosting-with-installed-meridian.md) |
| `[x]` | 036 | Move maintainer commands out of the user CLI and merge the generators | 🔴 P1 | 035, 039 | [036](done/036-move-maintainer-commands.md) |

### Phase 13 — Single workflow

Authority: `docs/ADR_CARDINE_1_0.md`, work item 6, and decisions 3 and 4.

| Status | ID | Title | Priority | Depends on | File |
|--------|----|-------|----------|------------|------|
| `[x]` | 041 | Plan the single workflow (work item 6) | 🔴 P1 | — | [041](done/041-plan-single-workflow.md) |

### Phase 12 — Rename code identifiers

Authority: `docs/ADR_CARDINE_1_0.md`, work item 5a, and decision 1.

| Status | ID | Title | Priority | Depends on | File |
|--------|----|-------|----------|------------|------|
| `[x]` | 040 | Plan the rename of code identifiers (work item 5a) | 🔴 P1 | — | [040](done/040-plan-code-identifier-rename.md) |

### Phase 14 — Code identifier rename

Authority: `docs/ADR_CARDINE_1_0.md`, work item 5a and decision 1, and `docs/RENAME_PLAN.md`.

| Status | ID | Title | Priority | Depends on | File |
|--------|----|-------|----------|------------|------|
| `[x]` | 042 | Introduce the project names accessor (rename plan R1) | 🔴 P1 | — | [042](done/042-introduce-names-accessor.md) |
| `[x]` | 043 | Extract the read-only Meridian installation reader (rename plan R2) | 🔴 P1 | 042 | [043](done/043-extract-meridian-installation-reader.md) |
| `[x]` | 044 | Decouple the frozen-surface readers (rename plan R3) | 🔴 P1 | 043 | [044](done/044-decouple-frozen-surface-readers.md) |
| `[x]` | 045 | Rename the exception and parser classes (rename plan R4) | 🔴 P1 | 044 | [045](done/045-rename-exception-and-parser-classes.md) |
| `[x]` | 046 | Rename the executables, the adapter, and the test modules (rename | 🔴 P1 | 045 | [046](done/046-rename-executables-adapter-and-test-modules.md) |
| `[x]` | 047 | Rename the command word in output and data (rename plan R6) | 🔴 P1 | 046 | [047](done/047-rename-command-word-in-output.md) |
| `[x]` | 048 | Rename the environment names and options (rename plan R7) | 🔴 P1 | 047 | [048](done/048-rename-environment-names-and-options.md) |
| `[x]` | 049 | Rename the project directory and the profile id (rename plan R8) | 🔴 P1 | 048 | [049](done/049-rename-project-directory-and-profile-id.md) |
| `[x]` | 050 | Rename Git-internal files and the worktree root (rename plan R9) | 🔴 P1 | 049 | [050](done/050-rename-git-internal-files-and-worktree-root.md) |
| `[x]` | 051 | Rename the product strings and guard against Meridian identifiers | 🔴 P1 | 050 | [051](done/051-rename-strings-and-guard.md) |

### Phase 15 — Single workflow

Authority: `docs/ADR_CARDINE_1_0.md`, work item 6 and decisions 3 and 4, and `docs/SINGLE_WORKFLOW_PLAN.md`.

| Status | ID | Title | Priority | Depends on | File |
|--------|----|-------|----------|------------|------|
| `[x]` | 052 | Resolve the project preset from the configuration (single workflow SW1) | 🔴 P1 | 051 | [052](done/052-project-presets-and-resolution.md) |
| `[x]` | 053 | Resolve one task contract and store its snapshot (single workflow SW2) | 🔴 P1 | 052 | [053](done/053-single-task-contract.md) |
| `[x]` | 054 | Use one task state machine with review and dependency gates (single workflow SW3) | 🔴 P1 | 053 | [054](done/054-single-state-machine.md) |
| `[x]` | 055 | Build the single template set (single workflow SW4) | 🔴 P1 | 054 | [055](done/055-single-template-set.md) |
| `[x]` | 056 | Reconcile the capability catalog with the single template set (single workflow SW5) | 🔴 P1 | 055 | [056](done/056-reconcile-capabilities.md) |
| `[x]` | 057 | Name the preset in the per-turn briefing (single workflow SW6) | 🔴 P1 | 056 | [057](done/057-preset-briefing-adapter.md) |
| `[x]` | 058 | Remove residual workflow branching and prove parity (single workflow SW7) | 🔴 P1 | 057 | [058](done/058-remove-workflow-branching.md) |

### Phase 16 — Marker and template text rename

Authority: `docs/ADR_CARDINE_1_0.md`, work item 5b, and `docs/RENAME_PLAN.md`.

| Status | ID | Title | Priority | Depends on | File |
|--------|----|-------|----------|------------|------|
| `[x]` | 060 | Remove the Meridian name and the old states from the template text (work item 5b) | 🔴 P1 | 058 | [060](done/060-cardine-template-text.md) |
| `[x]` | 061 | Rename the capability markers and restart every capability at v1 (work item 5b) | 🔴 P1 | 060 | [061](done/061-cardine-markers-from-v1.md) |

### Phase 17 — Single source of task state

Authority: `docs/ADR_CARDINE_1_0.md`, work item 7 and decision 4.

| Status | ID | Title | Priority | Depends on | File |
|--------|----|-------|----------|------------|------|
| `[x]` | 059 | Plan the single source of task state (work item 7) | 🔴 P1 | — | [059](done/059-plan-single-source-of-truth.md) |

### Phase 18 — The cardine run engine

Authority: `docs/ADR_CARDINE_1_0.md`, work item 8 and decisions 5, 6, 11, and 12.

| Status | ID | Title | Priority | Depends on | File |
|--------|----|-------|----------|------------|------|
| `[x]` | 062 | Plan the cardine run engine (work item 8) | 🔴 P1 | 059 | [062](done/062-plan-cardine-run-engine.md) |
