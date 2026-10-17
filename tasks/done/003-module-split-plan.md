# Task 003 — Plan the split of `meridian.py` into the Cardine modules

> **ID**: `003`
> **Category**: Architecture
> **Priority**: 🔴 P1
> **Estimate**: ~3h
> **Assigned to**: unassigned
> **Session**: Cardine bootstrap, 2026-10-17
> **Origin**: maintenance

## Objective

Work item 3 of `docs/ADR_CARDINE_1_0.md` splits `scripts/meridian.py` (13,050
lines) and its tests into the modules of decision 8, with the existing suite
green. Before any code moves, write the plan that makes this mechanical and
divides it into tasks of 2–3 hours. This task changes no code.

## Acceptance Criteria

- [x] `docs/MODULE_SPLIT_PLAN.md` exists, in English, and contains:
  - [x] **Mapping**: every top-level function, class, and constant of
    `scripts/meridian.py` assigned to one module of decision 8 under
    `src/cardine/`, or to a named shared module when several modules need it.
    The plan lists the import dependencies between modules and shows that they
    form no cycle.
  - [x] **Patch targets**: an inventory of every `mock.patch(...)` and
    `patch.object(meridian, ...)` in `tests/` that targets a name in
    `meridian.py` (at least 33 `patch.object(meridian, ...)` calls on
    2026-10-17). After a split, patching `meridian.X` no longer reaches a call
    made inside another module. The plan chooses one approach and its rule,
    either a compatibility re-export or test edits, and states plainly whether
    "suite unchanged" still holds.
  - [x] **Path references**: an inventory of every file that names
    `scripts/meridian.py` or reads it as text, with the change each one needs.
    Known cases: `bin/meridian` runs it with `runpy`; `scripts/release.py`
    reads `PROTOCOL_VERSION` from it with a regular expression; also check
    `scripts/check_repository.py`, `.codex/` rules and hooks, the self-hosting
    probes, managed digests, and 21 files in total on 2026-10-17.
  - [x] **File size**: the ADR limit of 1,500 lines applies to source and test
    files. List the files over it (`scripts/meridian.py`,
    `scripts/project_console.py`, `tests/test_meridian_cli.py`,
    `tests/test_project_console.py`, `tests/test_task_worktree_isolation.py`)
    and how each is split.
  - [x] **Task sequence**: an ordered list of extraction tasks of 2–3 hours,
    each with its scope, the tests that prove it, and its dependencies. The
    first task is the one with the fewest incoming dependencies.
- [x] The plan covers only work item 3. It does not plan the removal of
  migrations (item 4) or the rename (item 5), but it names any choice that
  would make those items harder.
- [x] No change outside `docs/MODULE_SPLIT_PLAN.md` and this task's records.
- [x] `python3 scripts/check_repository.py` and `git diff --check` pass.

## Relevant Files

| File | Role |
|------|------|
| `docs/ADR_CARDINE_1_0.md` | Decision 8 (modules) and work items 3–5. |
| `scripts/meridian.py` | The code to map. |
| `tests/` | Patch targets and test files to split. |
| `src/cardine/` | Package skeleton from task 002. |

## Out of scope

Moving any code. Work items 4 and 5.

## Dependencies

- **Depends on**: 002
- **Blocks**: the extraction tasks it plans

## Validation

Documentation only:

- `python3 scripts/check_repository.py`
- `git diff --check`

## Completion evidence

- Delivered `docs/MODULE_SPLIT_PLAN.md` with exact baseline ownership for all
  506 bindings, a ranked acyclic graph, all 35 Meridian-related mock calls,
  33 tracked path-reference files, the five oversized files and 16 proposed
  2–3 hour steps (13 extraction, two console, one final verification).
- AST inspection corrects the older estimates: 26 direct module patches plus
  nine imported-object patches; 33 tracked files mention the source basename.
- Required repository and whitespace checks passed. No source or tests changed.
- See `tasks/handoffs/003.md` for validation and integration evidence.
