# Task 036 — Move maintainer commands out of the user CLI and merge the generators

> **ID**: `036`
> **Category**: Refactor
> **Priority**: 🔴 P1
> **Estimate**: ~3h
> **Assigned to**: unassigned
> **Session**: Work item 4 planning, 2026-10-18
> **Origin**: maintenance

## Objective

ADR decision 7 moves the maintainer-only commands out of the user CLI into
development scripts, and keeps one entry-router generator:
- `profile`;
- `generate-claude-md` and `generate-entry-routers`;
- `report flow`;
- the agent evaluations.

This task closes work item 4. The other duplicates of decision 7 belong
elsewhere: one Python implementation of each hook belongs to work item 9, and
one release script belongs to work item 12.

## Acceptance Criteria

- [ ] `profile`, `generate-claude-md`, `generate-entry-routers`, and `report`
  are no longer subcommands of the user CLI. They run from one development
  entry point, for example `python3 scripts/dev.py <command>`, with the same
  arguments and output. `scripts/run_agent_evals.py` is reachable from it
  too.
- [ ] One generator produces both the `CLAUDE.md` shared body and the entry
  routers. Its `--check` mode passes on the current templates, and it
  replaces both old commands.
- [ ] Every caller uses the new entry point:
  - `CONTRIBUTING.md`;
  - `scripts/check_repository.py`;
  - the tests;
  - the validation lines in `tasks/TASK_BLUEPRINT.md`, if any.
  The planning commit that follows this task updates the open task
  contracts.
- [ ] The CLI help lists only user and host-facing commands. A test fails if
  a maintainer command returns to it.
- [ ] `.meridian/` is unchanged, except `.meridian/tasks/036.json`, which only
  the installed `meridian task close 036` writes. The manifest, the baselines,
  and every other file under `.meridian/` stay as they are.
- [ ] Every command under Validation passes.

## Relevant Files

| File | Role |
|------|------|
| `scripts/meridian.py`, `src/cardine/cli.py` | Command registration, wherever task 022 left it. |
| `scripts/dev.py` (new) or equivalent | Development entry point. |
| `src/cardine/templates/router.py` and the shared-body generator | The two generators to merge. |
| `CONTRIBUTING.md`, `tests/` | Remaining callers of `profile` and `report`. |

## Technical Context

- Task 039 checks this repository's installation only with the installed
  Meridian and removes the checkout's `profile doctor` and `audit` from CI and
  from the task validation lines. The callers of `profile` that remain are
  the tests and the documentation, and they move to the new entry point.
- Task 030 extends the journal report that `report flow` prints. That
  behavior moves with the command.

## Out of scope

Hook duplicates (work item 9), the release script merge (work item 12), and
`.meridian/` other than this task's own state file.

## Dependencies

- **Depends on**: 035, 039
- **Blocks**: none

## Validation

- `python3 scripts/check_repository.py`
- `meridian profile doctor meridian-self-hosting --project .`
- `meridian audit --project . --mode lean-delivery --ci-profile meridian-self-hosting`
- `python3 scripts/run_tests.py --parallel`
- `python3 scripts/run_tests.py --parallel --clean-clone`
- `git diff --check`
