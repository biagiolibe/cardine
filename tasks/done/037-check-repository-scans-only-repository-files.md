# Task 037 — Scan only repository files in `check_repository.py`

> **ID**: `037`
> **Category**: Bugfix
> **Priority**: 🔴 P1
> **Estimate**: ~1h
> **Assigned to**: unassigned
> **Session**: Meridian task 232 candidate validation stop, 2026-10-18
> **Origin**: friction

## Objective

Make `python3 scripts/check_repository.py` check only the files of this
repository, so that a host checkout nested in the primary checkout cannot fail
candidate validation.

`check_local_markdown_links`, `check_json`, and `check_bash` walk the
filesystem with `ROOT.rglob(...)`. Claude Code creates its session worktrees
under `.claude/worktrees/` in the primary checkout, and each one is a full copy
of the repository. The exemption for `tasks/QUEUE_TEMPLATE.md` matches only
that exact path relative to the root, so the nested copy fails the link check.
On 2026-10-18 this stopped the integration of Meridian task 232 with `BLOCKED
CANDIDATE_VALIDATION_FAILED`, although the candidate tree itself was correct.
This repository has the same code; it has not failed yet only because no
Claude Code worktree has been nested in its primary checkout.

## Acceptance Criteria

- [x] `check_local_markdown_links`, `check_json`, and `check_bash` select their
  files from one shared helper that lists repository files with `git ls-files
  -z --cached --others --exclude-standard` and keeps only paths that exist as
  files. Tracked, staged, and untracked-but-not-ignored files are still
  checked, so a new file in a task worktree or a staged candidate merge is
  covered.
- [x] A file under an ignored path and any nested Git checkout, such as
  `.claude/worktrees/<name>/`, is never checked, whether or not the directory
  is listed in `.gitignore` or `.git/info/exclude`.
- [x] The helper fails closed: when `git ls-files` exits non-zero, the check
  reports a failure instead of passing with an empty file list.
- [x] Tests in `tests/test_check_repository.py` cover: a broken link in a
  nested Git checkout and in an ignored directory is ignored; the same broken
  link in a tracked file and in an untracked, non-ignored file still fails;
  invalid JSON and invalid Bash in a nested checkout are ignored.
- [x] The existing exemptions (`templates/`, `tasks/QUEUE_TEMPLATE.md`, and the
  archived-queue-row rule) keep their behavior.
- [x] No file under `templates/` or `migrations/` changes, and no managed file
  of this repository or `.meridian/` changes.
- [x] Every command under Validation passes.

## Relevant Files

| File | Role |
|------|------|
| `scripts/check_repository.py` | `check_local_markdown_links`, `check_json`, `check_bash`; `check_no_machine_paths` already lists files with `git ls-files`. |
| `tests/test_check_repository.py` | Repository-check tests. |

## Technical Context

- The scoped `rglob` calls over `templates/`, the workflow template
  directories, and `src/cardine` stay as they are: they read fixed directories
  inside the repository.
- `git ls-files --others` does not descend into a nested Git checkout; it
  lists the directory itself, which the helper drops because it is not a file.
- Meridian task 235 fixes the same defect in Meridian 1.4.x. The two fixes are
  written separately: cross-repository cherry-picks are not part of the
  authorized lifecycle.
- Release scripts move in work item 12. This task changes only the repository
  check and does not anticipate that move.

## Out of scope

Any change to the lifecycle CLI, candidate validation commands, or release
scripts.

## Dependencies

- **Depends on**: none
- **Blocks**: none

## Validation

- `python3 scripts/check_repository.py`
- `python3 scripts/run_tests.py --parallel`
- `python3 scripts/run_tests.py --parallel --clean-clone`
- `git diff --check`
