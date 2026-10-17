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
