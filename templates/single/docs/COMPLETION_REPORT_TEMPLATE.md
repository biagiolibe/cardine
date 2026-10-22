# Concise Completion Report

Use this handoff after validation. Keep it short and make every deviation explicit.
Save it at the handoff location `cardine locations` resolves; `cardine execution handoff-check`
and `ready-check` use that canonical path when no report path is supplied.

```md
## Completion Report — <TASK-ID>

- Files changed: `<paths>`
Candidate validation declaration: `<declared fragments per REUSE/BOUNDED/FULL | none; undeclared blocks before stage>`

<!-- CARDINE:BEGIN capability=task-worktree-handoff v2 -->
- Branch: `<task-branch>`
- Worktree: `<task-worktree path relative to the worktree root, as returned in handoff_worktree; never an absolute path>`
- Integration requirement: `<bounded gate | full combined-tree validation with reason>`
- Declared integration surface: `<files/directories; dependencies; generated/configuration inputs; schemas; shared-governance records; behavioral surfaces, or explicit none for each category>`
<!-- CARDINE:END -->
- Validation: `<exact commands run with their exit status, or the CI check run and its conclusion for this exact commit — not a bare "passed">`
- Validation skips: `<none | test name — test-reported reason; reported by `command`>`
- Manual verification: `<none | screenshot path — view checked — result>`
- Acceptance criteria: `<all met | list criterion IDs/status>`
- Isolated exploration: `<none | question(s) recorded through cardine execution investigate>`
- Rule discrepancies: `<none | rule, command result, and what was followed>` (optional)
- Blockers/deviations: `<none | concrete issue, scope expansion, or context expansion and reason>`
```

<!-- CARDINE:BEGIN capability=handoff-correction-redelivery v1 -->
After committing a handoff-only correction on an `in_review` task, rerun
`cardine execution deliver <TASK-ID> --project .` before beginning the next
review attempt. The command creates a fresh `Deliver <TASK-ID> for review`
commit at the corrected handoff and preserves the existing state transitions.
Changes to any other record or implementation file require renewed implementation
and validation rather than this correction path.
<!-- CARDINE:END -->

Do not claim completion when validation fails or an acceptance criterion is unresolved. For reviews, retain the same four fields in the review record and add the required verdict from `docs/CODE_REVIEW_PROMPT.md`. When changes are requested, name that review-record path and its local handoff commit in the concise chat report; the record itself remains the canonical evidence.

A named sandbox skip is not a passing result for an unrelated failure. Record a
skip only when the test itself names it, including the test-reported reason and
the command that reported it; otherwise treat validation as failed.

<!-- CARDINE:BEGIN capability=manual-verification-record v1 -->
When the task declares `Manual verification: required`, name the screenshot
path, the view checked, and the result (pass/fail) — a reviewer must be able
to use it without reconstructing the session. When the task declares
`Manual verification: none`, state that explicitly rather than omitting the
field.
<!-- CARDINE:END -->

<!-- CARDINE:BEGIN capability=ci-verified-validation v1 -->
Report validation as falsifiable evidence, not an assertion: a self-reported
"tests passed" is exactly the claim an independent reviewer exists to verify,
not to repeat back. Name the exact command(s) actually run and their exit
status (or the CI check run for this commit), so a reviewer can decide,
per `docs/INTEGRATION_POLICY.md`, whether to trust an independent CI result
or perform its own scoped validation.
<!-- CARDINE:END -->
