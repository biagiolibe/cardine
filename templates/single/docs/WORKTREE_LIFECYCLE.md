# Bounded Worktree Lifecycle

<!-- CARDINE:BEGIN capability=worktree-command-locations v3 -->
## Command locations

Each command checks its own location and refuses a wrong one.

| Command | Runs in | `--project` |
|---|---|---|
| `worktree path`, `prepare`, `advance`, `evidence`, `closure-status`, `cleanup`, `integrate stage/finalize/abort` | Primary checkout | Primary |
| `worktree repair-base`, `states` | Primary or task checkout | Primary |
| `worktree check` | Task worktree | Primary |
| `worktree active` | Task worktree | none |
| `execution start/deliver/validate`, `task close/transition`, `review verdict` | Any directory | Task worktree |
<!-- CARDINE:END -->

<!-- CARDINE:BEGIN capability=worktree-lifecycle v5 -->
`cardine run` normally issues these single steps; use them for diagnosis and recovery. Exit `0` is success, `2` blocked, `64` usage. A legacy worktree is never moved; finish it with `--worktree-root <old-root>`.

- `worktree prepare|check <TASK-ID> --project <primary> --format json` creates or selects, then verifies, the task branch and worktree. Only a Resume directive adds `prepare --resume`, which accepts a dirty worktree and changes nothing.
- `execution start <TASK-ID> --project <task-worktree>` records `queued -> in_progress` once; Resume adds `--resume` after reading status and diff.
- `integrate stage <TASK-ID> --project <primary> --evidence <handoff.json> --format json` takes the lease, merges without a commit, and returns `REUSE`, `BOUNDED`, or `FULL` with the candidate tree. Validate outside it, then run `integrate finalize` with the candidate evidence, or `integrate abort` on failure.
- `cleanup` removes only a clean, integrated, pushed worktree and deletes its merged branch without force.
- `worktree repair-base <TASK-ID> --project <primary> --format json` moves a stale recorded base (`STALE_WORKTREE_BASE`, which is work, not a stop) to the task HEAD, only for a clean branch that `git merge main --ff-only` advanced before any task commit. Renew validation afterwards. An unproven transition reports `BLOCKED WRONG_WORKTREE`.

## Candidate validation

`.cardine/project.json` declares baseline and candidate commands for `REUSE`, `BOUNDED`, and `FULL`; task commands supplement the baseline, and the task's frozen contract fixes them. Every candidate runs `git diff --check`. `REUSE` proves with `git diff --name-only "$VALIDATED_TASK_COMMIT" "$CANDIDATE_TREE"` that only governance records changed; `BOUNDED` adds tests for the modules the task and advanced `main` changed; `FULL` adds the full suite. Candidate evidence names the exact candidate tree and `passed: true`; stale or incomplete evidence is rejected.
<!-- CARDINE:END -->
