# Concise Completion Report

This optional human summary helps explain the change after validation. Keep it
short and make deviations explicit. No wording or field in this report grants
completion, validation, host activation or review authority. The runner records
measured results separately; `cardine execution ready-check` reads those facts.

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
- Isolated exploration: `<none | question(s), sources, and distilled finding(s)>`
- Rule discrepancies: `<none | rule, command result, and what was followed>` (optional)
- Blockers/deviations: `<none | concrete issue, scope expansion, or context expansion and reason>`
```

<!-- CARDINE:BEGIN capability=handoff-correction-redelivery v2 -->
Completion prose is optional and has no readiness authority. Report-only edits
do not require delivery or a new review commit. Current measured validation,
committed implementation and the machine review state determine the next step.
<!-- CARDINE:END -->

Do not claim completion when validation fails or an acceptance criterion is unresolved. For reviews, summarize actionable findings in the review record and submit the verdict through the review command. Measured results and machine state remain authoritative.

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
