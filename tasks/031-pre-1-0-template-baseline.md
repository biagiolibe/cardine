# Task 031 — Record template changes without migrations until 1.0

> **ID**: `031`
> **Category**: Refactor
> **Priority**: 🔴 P1
> **Estimate**: ~3h
> **Assigned to**: unassigned
> **Session**: Work item 4 planning, 2026-10-18
> **Origin**: maintenance

## Objective

Start work item 4 of `docs/ADR_CARDINE_1_0.md` by removing every dependency
that new template work has on Meridian's migration chain. Today
`CONTRIBUTING.md` says that "a task that changes a managed template ships a
migration and bumps `VERSION`". If that rule still held in items 4, 6, and 9,
it would fill the chain that Cardine 1.0 must start with empty, or it would
create new stops. No project runs Cardine yet, so until 1.0 a template change
bumps the capability version and rewrites the marker baseline, without
adding a migration.

This task also moves the two pieces of current state that live only in
migration records:
- the required capability versions;
- the list of retired capabilities.

It moves the marker baseline out of `migrations/`, so that task 033 can
delete the chain.

## Acceptance Criteria

- [ ] The capability catalog under `capabilities/` records each capability's
  required version and whether it is retired. `cardine.templates.adoption`,
  `cardine.templates.migrations` (`retired_capability_ids`), and
  `scripts/check_repository.py` read these values from the catalog, not from
  migration records. Their results are unchanged for the current templates,
  and a test proves it.
- [ ] The marker baseline moves from
  `migrations/marker-baselines/CAPABILITY_MARKER_BASELINES.json` to
  `capabilities/marker-baselines.json`. `check_repository.py
  --write-marker-baselines` writes the new path, and the content check still
  fails when protected content changes without a version bump.
- [ ] `CONTRIBUTING.md` states the pre-1.0 rule. A template change bumps the
  capability version and runs `check_repository.py --write-marker-baselines`
  in the same commit. It adds no migration and does not bump `VERSION`.
  Retiring a capability marks it retired in the catalog. The repository
  checks no longer require a migration for a template change.
- [ ] `docs/ADR_CARDINE_1_0.md` work item 4 names this rule. That edit is
  already made by the planning commit, so the task verifies that the text
  matches the implementation.
- [ ] `.meridian/` is unchanged. Its manifest, baselines, and task states
  belong to the installed Meridian 1.4.0 that runs this repository's
  lifecycle.
- [ ] Every command under Validation passes.

## Relevant Files

| File | Role |
|------|------|
| `capabilities/` | Catalog; new required-version and retired fields; new baseline location. |
| `src/cardine/templates/catalog.py`, `adoption.py`, `migrations.py` | Readers of required and retired capabilities. |
| `scripts/check_repository.py` | Marker-baseline and migration checks. |
| `CONTRIBUTING.md` | Contributor rule for template changes. |

## Technical Context

- A probe on 2026-10-18 deleted `migrations/*.json` and `release-baselines/`
  in a disposable clone. `profile doctor meridian-self-hosting` and `audit
  --project .` still passed, so the self-hosting checks do not read the chain.
  The repository check failed first on a required migration file.
  About 112 tests failed, in the upgrade, marker-retirement, managed-copy
  digest, and self-hosting baseline test classes. Tasks 032 and 033 own those
  tests.
- `cardine.templates.adoption` derives requirements as `(required_version,
  migration_id)` pairs from migration records today.

## Out of scope

Deleting migration records (task 033), changing upgrade behavior, and
`.meridian/`.

## Dependencies

- **Depends on**: 026, 030
- **Blocks**: 032

## Validation

- `python3 scripts/check_repository.py`
- `python3 scripts/meridian.py --framework-root . profile doctor meridian-self-hosting --project .`
- `python3 scripts/meridian.py --framework-root . audit --project . --mode lean-delivery --ci-profile meridian-self-hosting`
- `python3 scripts/run_tests.py --parallel`
- `python3 scripts/run_tests.py --parallel --clean-clone`
- `git diff --check`
