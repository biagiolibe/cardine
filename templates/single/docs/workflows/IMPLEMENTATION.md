# Implementation Procedure

Use this procedure only for `Proceed with <TASK-ID>`. Follow `docs/CONTEXT_READING_POLICY.md`.

<!-- CARDINE:BEGIN capability=task-worktree-boundary v3 -->
## Implement

Run `cardine run <TASK-ID> --project <primary-checkout>`, do the `work` it returns inside `work.worktree`, commit the implementation, and call it again. It accepts delivery only from a clean committed HEAD, then validates and continues. Stop writing once it asks for review.
<!-- CARDINE:END -->

<!-- CARDINE:BEGIN capability=manual-verification-precondition v2 -->
Advice: if the task declares `Manual verification: required`, check its rationale first: a missing one, or one naming a property readable as a value in the program, is `BLOCKED SCOPE_CHANGE_REQUIRED`. Otherwise prove the evidence channel with a successful probe before implementing. Report a failed probe; do not search for an alternative.
<!-- CARDINE:END -->

<!-- CARDINE:BEGIN capability=spike-routing v2 -->
Advice: if an acceptance criterion cannot be evaluated without discovering an unknown, return `BLOCKED SCOPE_CHANGE_REQUIRED` naming the spike task that resolves it; do not investigate inside this task.
<!-- CARDINE:END -->
