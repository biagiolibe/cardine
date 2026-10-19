# Task 033 — Empty the migration chain

> **ID**: `033`
> **Category**: Refactor
> **Priority**: 🔴 P1
> **Estimate**: ~3h
> **Assigned to**: unassigned
> **Session**: Work item 4 planning, 2026-10-18
> **Origin**: maintenance

## Objective

Delete Meridian's 74 migration records. Cardine 1.0 starts its migration
chain empty. Move the remaining tests that read the chain to the synthetic
fixtures from task 032, and remove the code that exists only to audit or
replay Meridian's history.

## Acceptance Criteria

- [x] `migrations/` keeps only what the mechanism needs going forward, such
  as its README, which describes an empty chain. Every numbered migration
  record and its history documents are deleted:
  - `ASSISTED_ADOPTION.md`;
  - `CAPABILITY_MARKERS.md`;
  - `marker-baselines/`, now in `capabilities/` after task 031.

  The handoff lists what remains.
- [x] The tests that still read real migrations use synthetic fixtures:
  `CapabilityMarkerTest`, `ManagedCopyDigestAuditTest`,
  `RetiredInlineMarkerUpgradeTest`, `CapabilityProfileManifestTest`,
  `TaskIdentityResolverTest`, `CapabilityMarkerBaselineTest`, and the
  repository-check tests. A test that only proves a fact about Meridian's
  history is deleted, and the handoff lists each one with the reason. An
  example is "role-scoped agent rules were retired, not deleted by hand".
- [x] Code that exists only for Meridian's history is removed, and so are its
  tests. This covers the historical parts of `cardine.templates.marker_history`
  and `cardine.templates.migration_audit`. The mechanism still loads, orders,
  validates, and applies a chain, and synthetic tests prove it.
- [x] `scripts/check_repository.py` no longer requires any migration file,
  and it accepts an empty chain.
- [x] `scripts/release.py` and its tests work with an empty chain. A release
  without migrations is a CLI-only release unless templates changed.
- [x] `.meridian/` is unchanged.
- [x] The parallel suite reports the same coverage `total` before and after
  the task, minus the deleted history tests listed in the handoff.
- [x] Every command under Validation passes.

## Relevant Files

| File | Role |
|------|------|
| `migrations/` | Records to delete. |
| `src/cardine/templates/migrations.py`, `marker_history.py`, `migration_audit.py` | Mechanism and history code. |
| `scripts/check_repository.py`, `scripts/release.py` | Chain consumers. |
| Test files named above | Tests moved to synthetic fixtures. |

## Technical Context

- The deletion probe of 2026-10-18 lists the consumers. Code that reads the
  chain: `scripts/release.py`, `scripts/meridian.py`,
  `scripts/check_repository.py`, and `cardine.templates` modules `merge`,
  `migration_audit`, `files`, `adoption`, `manifest`, `marker_history`,
  `upgrade_support`, `marker_audit`, `migrations`, and `markers`.
- The release tests passed in the probe.

## Out of scope

Release baselines and adoption from them (task 034), and `.meridian/`.

## Dependencies

- **Depends on**: 032
- **Blocks**: 029

## Validation

- `python3 scripts/check_repository.py`
- `python3 scripts/meridian.py --framework-root . profile doctor meridian-self-hosting --project .`
- `python3 scripts/meridian.py --framework-root . audit --project . --mode lean-delivery --ci-profile meridian-self-hosting`
- `python3 scripts/run_tests.py --parallel`
- `python3 scripts/run_tests.py --parallel --clean-clone`
- `git diff --check`
