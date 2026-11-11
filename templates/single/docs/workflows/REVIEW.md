# Review Procedure

Use this procedure only for `Review <TASK-ID>`.

<!-- CARDINE:BEGIN capability=task-worktree-review-procedure v5 -->
## Review

Review in a fresh session that did not write the implementation. Run `cardine review <TASK-ID> --project <primary-checkout>`; it hands off only a committed `in_review` delivery with a clean worktree, apart from the task state, handoff and evidence file that `cardine run` keeps uncommitted until landing. Never stage, commit or edit them. Read the task contract, its cited authority, and the exact diff against the recorded base in the `work.worktree` it names. Re-derive the evidence; do not trust the implementer's report.

Check scope, dependencies, non-goals, acceptance criteria, project invariants, and unrelated changes. Use a completed CI run for this exact commit when it covers the validation surface, otherwise validate within the diff's scope by running the project's commands, not `cardine execution validate`; never accept a bare "tests passed".

Advice: if `Manual verification: required`, confirm its rationale names a perceptual property and the evidence gathered matches it; apply every item of a `## Project review checklist` after this block as extra scope; report only actionable findings, each with `P0`, `P1`, or `P2` priority and file and line evidence (`P0` and `P1` block approval); omit style commentary; keep the final report within ten lines.

End with the verdict, `APPROVE`, `CHANGES_REQUESTED` or `BLOCKED`, and its evidence. The developer records it from an interactive terminal with `cardine review verdict <TASK-ID> <VERDICT> --owner --project <work.worktree> --body <review-evidence>`, which binds it to the reviewed HEAD. Commit nothing. Edit no implementation file, never push, and never edit a status or verdict by hand. After `APPROVE`, `cardine run` lands the task: do not merge, push, or touch the integration lease yourself. Two consecutive `CHANGES_REQUESTED` verdicts end in `REVIEW_LOOP_EXHAUSTED`.
<!-- CARDINE:END -->
