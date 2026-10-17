# Task 002 — Add `pyproject.toml` and the `cardine` package skeleton

> **ID**: `002`
> **Category**: Architecture
> **Priority**: 🔴 P1
> **Estimate**: ~2h
> **Assigned to**: unassigned
> **Session**: Cardine bootstrap, 2026-10-17
> **Origin**: maintenance

## Objective

Complete work item 2 of `docs/ADR_CARDINE_1_0.md`: make this repository an
installable Python package named `cardine`, with a `cardine` command, so that
work item 3 can move code into `src/cardine/`. Behavior stays that of
Meridian 1.4.0; this task only adds the packaging around it.

## Acceptance Criteria

- [x] `pyproject.toml` declares the package `cardine`, `requires-python =
  ">=3.12"`, the MIT license, and one console script, `cardine`. No console
  script is named `meridian`: in agent sessions `meridian` on `PATH` is the
  released Meridian CLI, and a second one would shadow it.
- [x] The package version is read from `VERSION` at build time; `VERSION`
  stays the only source of truth. `VERSION` remains `1.4.0`: its reset to a
  `0.x` version waits for work item 4, because `check_repository.py` ties it
  to the plugin version, the release ledger, and the migration targets.
- [x] `src/cardine/__init__.py` and `src/cardine/cli.py` exist. `cardine`
  runs the existing CLI of `scripts/meridian.py` with this checkout as the
  framework root. `bin/meridian` and `scripts/meridian.py` keep working
  unchanged.
- [x] After an editable install, `cardine --version` prints this checkout's
  `VERSION`, also when `MERIDIAN_ROOT` points at another Meridian checkout. A
  test covers that case. Agents validate in a temporary virtual environment,
  never with a user-level `pipx` install: the task worktree is removed after
  integration and would leave a broken command.
- [x] `.github/workflows/validate.yml` adds, on both operating systems, an
  editable install followed by `cardine --version`.
- [x] `README.md` or `CONTRIBUTING.md` states that the package must not be
  published from this state, and documents the editable install for
  development.
- [x] `python3 scripts/check_repository.py`, `python3 scripts/run_tests.py
  --parallel`, and `git diff --check` pass.

## Relevant Files

| File | Role |
|------|------|
| `pyproject.toml` | New. |
| `src/cardine/` | New package skeleton. |
| `bin/meridian`, `scripts/meridian.py` | Existing entry points; unchanged. |
| `.github/workflows/validate.yml` | CI. |
| `scripts/check_repository.py` | May need the new root files in its inventory. |

## Technical Context

- `bin/meridian` runs `scripts/meridian.py` with `runpy`. The CLI resolves the
  framework root from an inherited `MERIDIAN_ROOT` before its own location, so
  `cardine` must pass this checkout explicitly.
- Meridian's task 231 hit the same trap: a test read the version from
  `MERIDIAN_ROOT` instead of the checkout.
- Hatchling can read the version from a file through `[tool.hatch.version]`.

## Out of scope

Package data, a non-editable install, and any publication to PyPI. Moving
code out of `scripts/` (work item 3). Renaming identifiers (work item 5).

## Dependencies

- **Depends on**: none
- **Blocks**: 003

## Validation

- `python3 scripts/check_repository.py`
- `python3 scripts/run_tests.py --parallel`
- `git diff --check`
- In a temporary virtual environment: `pip install --editable .`, then
  `cardine --version`.
