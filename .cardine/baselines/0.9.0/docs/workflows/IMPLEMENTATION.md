# Implementation Procedure

Use this procedure only for `Proceed with <TASK-ID>`. Follow `docs/CONTEXT_READING_POLICY.md`.

<!-- CARDINE:BEGIN capability=task-worktree-boundary v3 -->
## Implement

Run `cardine run <TASK-ID> --project <primary-checkout>`, do the `work` it returns inside `work.worktree`, commit the implementation, and call it again. It accepts delivery only from a clean committed HEAD, then validates and continues. Stop writing once it asks for review.
<!-- CARDINE:END -->

<!-- CARDINE:BEGIN capability=manual-verification-precondition v2 -->
If the task declares `Manual verification: required`, a missing rationale, or one naming a property readable as a value in the program, is a scope change. Advice: otherwise prove the evidence channel with a successful probe before implementing; report a failed probe and do not search for an alternative.
<!-- CARDINE:END -->

<!-- CARDINE:BEGIN capability=spike-routing v2 -->
A criterion that cannot be evaluated without discovering an unknown is a scope change: name the spike task that resolves it. Advice: do not investigate inside this task.
<!-- CARDINE:END -->
