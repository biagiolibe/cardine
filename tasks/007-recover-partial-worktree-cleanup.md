# Task 007 — Recover worktree cleanup after a partial removal

> **ID**: `007`
> **Category**: Bugfix
> **Priority**: 🟡 P2
> **Estimate**: ~3h
> **Assigned to**: unassigned
> **Session**: Meridian 1.4.0 defect report from a Governed SDD project, 2026-10-17
> **Origin**: friction

## Objective

Make task worktree cleanup idempotent across a partial `git worktree remove`.
A Governed SDD project on Meridian 1.4.0 hit this twice: Git deleted the task
worktree directory, the host sandbox then denied the write that removes its
administrative directory under `.git/worktrees/`, and cleanup stopped with
`CLEANUP_BLOCKED`. The resume command it printed can never succeed, so the
only way out was a manual `git worktree prune`, `git branch -d`, and deletion
of the lifecycle state file.

ADR decision 6 requires that the lifecycle returns only commands that run
unchanged, and decision 7 keeps registered stops with exact resume commands.
This task brings cleanup in line with both.

## Acceptance Criteria

- [ ] `inspect_task_worktree` reports a registered worktree whose directory
  does not exist as `missing-worktree`, not `dirty-worktree`. A directory that
  exists and has changes still reports `dirty-worktree`.
- [ ] **Registered, directory missing.** When `git worktree list --porcelain`
  lists the task worktree as `prunable` and every other cleanup gate holds
  (task commit in `main`, `main` proven pushed, primary checkout clean, no
  integration lease or staged integration), cleanup removes that one entry with
  a non-force `git worktree remove <path>`, then continues as a normal cleanup.
  It never runs the repository-wide `git worktree prune`, which would also drop
  other missing worktrees under the shared worktree root.
- [ ] **Unregistered, branch and state present.** Cleanup treats the
  worktree as removed and proves integration from the task branch tip
  (`git merge-base --is-ancestor <branch> main`), since no registered `HEAD`
  exists any more.
- [ ] **Branch already deleted, state present.** Cleanup removes the lifecycle
  state file only when the worktree is unregistered, no lease or staged
  integration exists, and the tracked task state on `main` records the task as
  done. The `task_commit` in the lifecycle state file is the branch tip at
  preparation time, so it is not proof of integration.
- [ ] Each recovered path keeps the empty directory for Codex Stop hooks,
  deletes the branch only with non-force `git branch -d`, removes the lifecycle
  state file, and returns `status: cleaned` with a field that names the partial
  state it recovered from.
- [ ] A worktree directory that exists and is dirty is never force-removed,
  and an unmerged branch is never deleted, in any of these states.
- [ ] When `git worktree remove` fails after the directory is already gone,
  the `CLEANUP_BLOCKED` stop names the partial state and states that cleanup
  needs write access to the primary checkout's `.git` directory. Its resume
  command is the same cleanup command, which then succeeds once that access is
  available. A test proves the resume succeeds.
- [ ] `docs/WORKTREE_LIFECYCLE.md` states that cleanup writes to the primary
  checkout's `.git` directory and that sandboxed hosts may deny that write.
- [ ] Regression tests cover:
  - the directory deleted while the registration remains (`prunable`);
  - the registration removed while the branch and state remain;
  - the branch deleted while the state remains;
  - a second task's missing worktree, which cleanup leaves registered;
  - an existing dirty worktree, which still stops with `dirty-worktree`.
- [ ] The fix lives in the owner modules that split rows E10 and E11 assign:
  `cardine.worktree.checkout` for `inspect_task_worktree` and
  `cardine.integration.merge` for `cleanup_task_worktree`. The module
  inventory tests stay green.
- [ ] **CI before integration.** After validation, push the task branch once
  (`git push origin task-007`, authorized by `Proceed with`) and record
  `T1_CI` evidence for the exact task commit with `python3
  scripts/ci_evidence.py --commit <sha> --task 007 --output <path> --wait 900`.
  Integrate only when that evidence reports a successful run on both operating
  systems.
- [ ] Every command under Validation passes.

## Relevant Files

| File | Role |
|------|------|
| `src/cardine/worktree/checkout.py` | `inspect_task_worktree` after split row E10. |
| `src/cardine/integration/merge.py` | `cleanup_task_worktree` after split row E11. |
| `tests/test_task_worktree_isolation.py` | Existing cleanup tests; new regression tests. |
| `docs/WORKTREE_LIFECYCLE.md` | Cleanup preconditions and recovery. |

## Technical Context

- **Current behavior**: `inspect_task_worktree` runs `git status --porcelain`
  in the expected path. A missing path exits 128, `clean` becomes false, and
  the error is `dirty-worktree`. `cleanup_task_worktree` short-circuits to
  `already_cleaned` only when the path is unregistered, the branch is gone,
  and the state file is absent. Every state in between fails the preflight
  (`dirty-worktree` or `unregistered-worktree`).
- **Desired behavior**: every state between "registered and clean" and "fully
  cleaned" is recoverable by the same bounded command, under the same gates.
- Checked with Git on 2026-10-17: `git worktree remove <missing-path>` exits 0
  and removes only that entry, while `git worktree prune` removes every entry
  whose directory is missing.
- `parse_worktree_records` keeps every porcelain key, including `prunable`.
- The lifecycle state written by `prepare_task_worktree` records
  `task_commit` as the branch commit at preparation time.

## Out of scope

The remote task-branch deletion that the ADR adds to cleanup under decision
11, and the `cardine run` engine (work item 8). This task fixes the existing
cleanup command, which `cardine run` will call.

## Dependencies

- **Depends on**: split row E11, which has no task ID yet. Do not start this
  task before the task that implements E11 has landed; when that task is
  planned, record its ID in this field and in the queue row.
- **Blocks**: none

## Validation

- `python3 scripts/check_repository.py`
- `python3 scripts/meridian.py --framework-root . profile doctor meridian-self-hosting --project .`
- `python3 scripts/meridian.py --framework-root . audit --project . --mode lean-delivery --ci-profile meridian-self-hosting`
- `python3 scripts/run_tests.py --parallel`
- `python3 -m unittest discover -s tests -v`
- `git diff --check`
- `python3 scripts/ci_evidence.py --commit <task commit> --task 007 --output <path> --wait 900`
