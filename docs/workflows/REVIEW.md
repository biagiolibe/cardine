# Review Procedure

Use this procedure only for `Review <TASK-ID>`.

<!-- CARDINE:BEGIN capability=task-worktree-review-procedure v4 -->
## Review

Review in a fresh session that did not write the implementation. Run `cardine review <TASK-ID> --project <primary-checkout>`; it hands off only a committed `in_review` delivery with a clean worktree. Read the task contract, its cited authority, and the exact diff against the recorded base in the `work.worktree` it names. Re-derive the evidence; do not trust the implementer's report.

Check scope, dependencies, non-goals, acceptance criteria, project invariants, and unrelated changes. Use a completed CI run for this exact commit when it covers the validation surface, otherwise validate within the diff's scope; never accept a bare "tests passed".

Advice: if `Manual verification: required`, confirm its rationale names a perceptual property and the evidence gathered matches it; apply every item of a `## Project review checklist` after this block as extra scope; report only actionable findings, each with `P0`, `P1`, or `P2` priority and file and line evidence (`P0` and `P1` block approval); omit style commentary; keep the final report within ten lines.

Record the verdict on the clean reviewed HEAD with `cardine review verdict <TASK-ID> APPROVE|CHANGES_REQUESTED|BLOCKED --request-id <launch-request-id> --body <review-evidence>`, where the request ID is that of the review request that launched this session. It binds the verdict to that HEAD. Commit only the files it wrote. Edit no implementation file, never push, and never edit a status or verdict by hand. After `APPROVE`, `cardine run` lands the task: do not merge, push, or touch the integration lease yourself. Two consecutive `CHANGES_REQUESTED` verdicts end in `REVIEW_LOOP_EXHAUSTED`.
<!-- CARDINE:END -->
