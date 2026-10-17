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
