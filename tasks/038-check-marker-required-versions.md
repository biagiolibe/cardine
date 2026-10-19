# Task 038 — Reject a stale `requiredVersion` in the marker catalog

> **ID**: `038`
> **Category**: Bugfix
> **Priority**: 🔴 P1
> **Estimate**: ~1.5h
> **Assigned to**: unassigned
> **Session**: Task 029 validation stop review, 2026-10-19
> **Origin**: friction

## Objective

Make `python3 scripts/check_repository.py` fail when a template change bumps a
capability marker but `capabilities/markers-v1.json` keeps the old
`requiredVersion`.

Task 031 moved the required versions into the marker catalog, and
`CONTRIBUTING.md` says that a template change bumps the capability version and
updates its `requiredVersion`. Nothing enforces the second half. At commit
`244d12b`, task 029 bumped `git-workflow` from v14 to v15 and
`bounded-worktree-lifecycle` from v5 to v6 in the Governed SDD templates. It
rewrote the marker baseline but kept `requiredVersion` at 14 and 5.
`check_repository.py`, the self-hosting doctor, and the audit gate all passed.
Only the coordinator's review found the omission.

## Acceptance Criteria

- [ ] `check_repository.py` checks every required capability in
  `capabilities/markers-v1.json` that is not retired. Its `requiredVersion`
  must equal the version that adoption detection reads from the current
  Governed SDD templates. That version comes from the first marker of the
  capability in the files of `managed_files(root, "governed-sdd")`, in that
  order, the same way `cardine.templates.marker_history` combines them.
  Any other value fails, whether it is lower (a forgotten bump) or higher
  (a fresh install would be reported as missing the capability). The check
  reads only the catalog, the templates, and `managed_files`. It does not
  call `capability_presence_map`, because task 034 may remove that function
  with the adoption code.
- [ ] A required, non-retired capability with no marker in the Governed SDD
  templates fails the check with its name. Today there is none.
- [ ] The failure message names the capability, the catalog value, the version
  the templates ship, and the file that ships it. It tells the contributor to
  update `requiredVersion` in `capabilities/markers-v1.json`.
- [ ] Tests in `tests/test_check_repository.py` cover these cases, each on a
  temporary copy of the catalog and templates:
  - a bumped Governed SDD marker with an unchanged `requiredVersion` fails;
  - a `requiredVersion` above the shipped version fails;
  - a catalog that matches the templates passes;
  - a retired capability is ignored;
  - a capability shipped in two Governed SDD files at different versions
    uses the version of the first file in `managed_files` order. Today
    `lifecycle-orchestration` ships v12 in `docs/LIFECYCLE_ORCHESTRATION.md`
    and v3 in `docs/workflows/LIFECYCLE.md`, and its `requiredVersion` 12 is
    the version detection reads.
- [ ] The check passes on the current `main`. If task 029 has been integrated,
  it also passes with that task's `requiredVersion` values.
- [ ] `CONTRIBUTING.md` explains the rule in the pre-1.0 template paragraph:
  `requiredVersion` is the version that the Governed SDD templates ship,
  because adoption detection reads only those templates. A Lean-only bump
  therefore does not change it.
- [ ] No file under `templates/`, `capabilities/marker-baselines.json`,
  `migrations/`, or `VERSION` changes. This repository's managed files
  (`CLAUDE.md`, `AGENTS.md`, `PROJECT_WORKFLOW.md`) and `.meridian/` stay
  unchanged, except `.meridian/tasks/038.json`, which only the installed
  `meridian task close 038` writes.
- [ ] Every command under Validation passes.

## Relevant Files

| File | Role |
|------|------|
| `scripts/check_repository.py` | New check, next to `check_capability_marker_baselines`. |
| `tests/test_check_repository.py` | Tests for the check. |
| `capabilities/markers-v1.json` | The catalog that is checked; values change only if the check finds a real mismatch. |
| `src/cardine/templates/files.py`, `markers.py` | `managed_files` and `find_capability_marker_version`, reused by the check. |
| `CONTRIBUTING.md` | Pre-1.0 template rule. |

## Technical Context

- `cardine.templates.marker_history.capability_presence_map` runs only for
  `governed-sdd`. It joins the text of the Governed SDD managed files and
  compares the first marker version it finds with `requiredVersion`. This is
  why several catalog values match the Governed SDD version and not the Lean
  one. On `main` at `966335a`:
  - `bounded-worktree-lifecycle`: required 5; Governed 5, Lean 7;
  - `execution-evidence-profile`: required 5; Governed 5, Lean 3;
  - `minimal-read-only-status`: required 3; Governed 3, Lean 1.
- A coordinator probe on 2026-10-19 copied the Governed SDD managed files of
  `main` into a temporary project and ran `capability_presence_map`. It
  reported every required capability present, including
  `lifecycle-orchestration` at v12. Every required, non-retired capability
  has a Governed SDD marker, and only `lifecycle-orchestration` ships two
  different Governed SDD versions.
- A fresh-install test alone would not catch task 029's omission: detection
  accepts a marker at or above `requiredVersion`, so v15 against a required 14
  passes. The check must compare for equality.
- `cardine.templates.merge` also reads `requiredVersion`. Its fallback for a
  conflicted three-way merge, near line 520, extracts each file's marker block
  at `requiredVersion`. For a Lean file whose marker version differs, such as
  `bounded-worktree-lifecycle` v7 against a required 5, that fallback can
  never mark the file verified. Changing the merge is out of scope. The
  handoff states whether the fallback should use the template file's own
  marker version, and proposes a task if so.

## Out of scope

Changes to the upgrade merge, adoption detection, the templates, or the
capability versions themselves.

## Dependencies

- **Depends on**: 029
- **Blocks**: 034. Task 034 may remove adoption code; it must keep this check
  working or move it, and its handoff says which.

## Validation

- `python3 scripts/check_repository.py`
- `python3 scripts/meridian.py --framework-root . profile doctor meridian-self-hosting --project .`
- `python3 scripts/meridian.py --framework-root . audit --project . --mode lean-delivery --ci-profile meridian-self-hosting`
- `python3 scripts/run_tests.py --parallel`
- `python3 scripts/run_tests.py --parallel --clean-clone`
- `git diff --check`
