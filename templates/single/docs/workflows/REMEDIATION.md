# Remediation Procedure

Use this procedure only for `Address review <TASK-ID>`.

<!-- CARDINE:BEGIN capability=task-worktree-remediation v2 -->
## Address the findings

After the reviewer has stopped, run `cardine run <TASK-ID> --project <primary-checkout>` and work in the `work.worktree` it names. Read the task and the review record, resolve every finding the request lists, and mark each resolved in the review record's resolution section. Advice: add no new work, reinterpret no finding, and erase no evidence. Commit, then call `cardine run` again.

A finding that needs new authority or scope stays unresolved and is a scope change. Advice: only an explicit developer authorization restarts it, as a new task.
<!-- CARDINE:END -->
