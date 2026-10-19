# Task 039 — Check this repository's installation only with the installed Meridian

> **ID**: `039`
> **Category**: Bugfix
> **Priority**: 🔴 P1
> **Estimate**: ~2h
> **Assigned to**: unassigned
> **Session**: Task 035 rule-conflict review, 2026-10-19
> **Origin**: friction

## Objective

Stop validating this repository's Meridian installation with the checkout's
product code.

`.meridian/` and the managed copies of this repository belong to the
installed Meridian 1.4.1, which runs the lifecycle. They never change with
Cardine work. Four checks still compare them with the checkout's product
catalog, templates, migrations, or releases:
- the task-contract validation line `python3 scripts/meridian.py
  --framework-root . profile doctor meridian-self-hosting --project .`;
- the matching `audit ... --ci-profile meridian-self-hosting` line;
- the same two steps in `.github/workflows/validate.yml`;
- `check_self_hosting_baseline` in `scripts/check_repository.py`.

As Cardine moves away from Meridian, these checks fail on correct product
changes. On 2026-10-19 task 035 stopped with `BLOCKED RULE_CONFLICT`. It
renamed the context policy surface in `capabilities/catalog-v1.json`, and the
product doctor failed because `.meridian/manifest.json` still declares the
old surface. A coordinator probe also showed that changing the shared-source
`hooks/queue-briefing.sh` fails the same doctor. Run by the installed
Meridian, the same profile check passes, because it compares the installation
with the framework that owns it.

## Acceptance Criteria

- [ ] The installation of this repository is checked only by the installed
  Meridian, with these two commands:
  - `meridian profile doctor meridian-self-hosting --project .`;
  - `meridian audit --project . --mode lean-delivery --ci-profile
    meridian-self-hosting`.
  `tasks/TASK_BLUEPRINT.md`, `CONTRIBUTING.md`, and every open task record
  under `tasks/` use these lines in place of the `python3 scripts/meridian.py
  --framework-root . profile doctor ...` and `... audit ... --ci-profile
  meridian-self-hosting` lines. No validation line runs the checkout's
  `profile doctor` or `audit` against this repository's `.meridian/`. The
  planning commit of this task already updated task 036.
- [ ] `.github/workflows/validate.yml` no longer runs the checkout's
  `profile doctor` or `audit` against this repository. CI has no installed
  Meridian, and installation integrity is a local lifecycle check. Any
  release workflow step that does the same is removed too. The handoff lists
  the removed steps.
- [ ] `check_self_hosting_baseline` is removed from `scripts/check_repository.py`.
  It compares the checkout's migrations and releases with the installed
  baseline, and its message tells the contributor to run the checkout's
  `upgrade`, which is forbidden on this repository.
- [ ] `check_managed_digests` stays: it compares the managed copies with the
  digests the installed Meridian recorded, which is a valid integrity check.
  Its failure message tells the contributor to restore the managed copy from
  `main`, not to rewrite digests. The `--write-managed-digests` option of
  `check_repository.py` is removed if only this repository used it.
  Otherwise it refuses to write this repository's `.meridian/manifest.json`.
  The handoff says which applies.
- [ ] `profile doctor` and `audit` keep their behavior for other projects.
  Tests that run them on synthetic projects still pass. A new test changes
  the `meridian-self-hosting` profile surface in a temporary copy of the
  repository's catalog and proves that `check_repository.py` passes.
- [ ] `CONTRIBUTING.md`, section "Managed copies of this repository", says:
  - the installed Meridian owns `.meridian/` and the managed copies;
  - the two commands above check them;
  - they are never edited by hand, and the checkout's `upgrade` is never run
    on this repository.
- [ ] No file under `templates/` or `migrations/` changes, and this
  repository's managed files (`CLAUDE.md`, `AGENTS.md`, `PROJECT_WORKFLOW.md`,
  `LANGUAGE_POLICY.md`, `docs/CONTEXT_BUDGET_POLICY.md`,
  `docs/COMPLETION_REPORT_TEMPLATE.md`, `docs/EXECUTION_EVIDENCE_PROFILE.md`,
  `.codex/`, `hooks/hooks.json`, `hooks/queue-briefing.sh`,
  `hooks/read-guard.sh`) stay unchanged. `.meridian/` is unchanged, except
  `.meridian/tasks/039.json`, which only the installed `meridian task close
  039` writes.
- [ ] Every command under Validation passes.

## Relevant Files

| File | Role |
|------|------|
| `scripts/check_repository.py` | `check_self_hosting_baseline`, `check_managed_digests`, `--write-managed-digests`. |
| `tests/test_check_repository.py` | Tests for those checks. |
| `.github/workflows/validate.yml`, `.github/workflows/` | CI steps. |
| `tasks/TASK_BLUEPRINT.md`, `tasks/036-move-maintainer-commands.md` | Validation lines. |
| `CONTRIBUTING.md` | Managed-copy rules. |

## Technical Context

- On 2026-10-19, at `main` `6bfc410`, `meridian profile doctor
  meridian-self-hosting --project .` reported `PASS=11 FAIL=0`. `meridian
  audit --project . --mode lean-delivery --ci-profile meridian-self-hosting`
  reported `CI_GATE ... worst=PASS required=8 failures=0`. Both exited with 0.
- `.meridian/candidate-validation.json` declares only `check_repository.py`
  and `run_tests.py --parallel` for candidate validation, so this task does
  not affect integration.
- Task 036 moves `profile` and `report` into a development entry point. After
  this task, nothing runs the checkout's `profile doctor` against this
  repository, so task 036 does not need to move such a caller.
- Task 035 deferred two changes that the coupling blocked: the budget lines in
  `hooks/queue-briefing.sh` (work item 9) and the rename of
  `CONTEXT_BUDGET_POLICY.md` and the `context-budgeting` capability. This task
  does not make them. It only removes the coupling.

## Out of scope

The deferred changes of task 035, the CLI move of task 036, and any edit to
`.meridian/` or to this repository's managed copies.

## Dependencies

- **Depends on**: 035
- **Blocks**: 036

## Validation

- `python3 scripts/check_repository.py`
- `meridian profile doctor meridian-self-hosting --project .`
- `meridian audit --project . --mode lean-delivery --ci-profile meridian-self-hosting`
- `python3 scripts/run_tests.py --parallel`
- `python3 scripts/run_tests.py --parallel --clean-clone`
- `git diff --check`
