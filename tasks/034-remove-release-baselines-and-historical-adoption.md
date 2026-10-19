# Task 034 — Remove release baselines and adoption from historical versions

> **ID**: `034`
> **Category**: Refactor
> **Priority**: 🔴 P1
> **Estimate**: ~3h
> **Assigned to**: unassigned
> **Session**: Work item 4 planning, 2026-10-18
> **Origin**: maintenance

## Objective

ADR decision 7 removes `adopt` from historical versions. `release-baselines/`
holds Meridian's packaged release baselines, and `meridian adopt` migrates a
project from one of them. Remove both. Decision 10 assigns conversion of
projects without Cardine and of Meridian projects to work item 10. That item
rebuilds `cardine adopt` on the single workflow, so until then the CLI has
no adoption command.

## Acceptance Criteria

- [ ] `release-baselines/` is deleted. So are the `adopt` and
  `finalize-adoption` commands and the code that serves only them in
  `cardine.templates.adoption`, `cardine.templates.adopt_command`, and
  `cardine.templates.files`. Code that `init`, `upgrade`, or `audit` still
  uses stays, and the handoff names it.
- [ ] `lock`, if it exists only to register a project for upgrades from a
  packaged baseline, is removed too. Otherwise it stays, and the handoff
  states which applies.
- [ ] Tests that only prove historical adoption are deleted, and the handoff
  lists them. `SelfHostingBaselineTest` and the other tests that read
  `release-baselines/` either use a synthetic baseline or are deleted with a
  reason.
- [ ] The README, CONTRIBUTING, and the command reference no longer describe
  `adopt` or `finalize-adoption`, and they say that conversion returns with
  work item 10.
- [ ] `.meridian/`, including `.meridian/baselines/1.4.0`, is unchanged. It
  belongs to the installed Meridian 1.4.0.
- [ ] Every command under Validation passes.

## Relevant Files

| File | Role |
|------|------|
| `release-baselines/` | Packaged baselines to delete. |
| `src/cardine/templates/adoption.py`, `adopt_command.py`, `files.py` | Adoption code. |
| `scripts/meridian.py`, `src/cardine/cli.py` | Command registration, wherever task 022 left it. |
| `README.md`, `CONTRIBUTING.md`, `docs/` | User and contributor docs. |

## Technical Context

- The 2026-10-18 deletion probe failed `SelfHostingBaselineTest` and several
  upgrade tests with a missing `release-baselines` directory.
- `cardine.shared.constants`, `cardine.templates.adoption`, and
  `cardine.templates.files` reference the baseline directory.
- Task 038 adds a `check_repository.py` check that compares `requiredVersion`
  in `capabilities/markers-v1.json` with the Governed SDD templates through
  `managed_files`. If this task removes or changes code that check uses, it
  keeps the check working, and the handoff says how.

## Out of scope

Work item 10's conversion command, and `.meridian/`.

## Dependencies

- **Depends on**: 029, 038
- **Blocks**: 035

## Validation

- `python3 scripts/check_repository.py`
- `python3 scripts/meridian.py --framework-root . profile doctor meridian-self-hosting --project .`
- `python3 scripts/meridian.py --framework-root . audit --project . --mode lean-delivery --ci-profile meridian-self-hosting`
- `python3 scripts/run_tests.py --parallel`
- `python3 scripts/run_tests.py --parallel --clean-clone`
- `git diff --check`
