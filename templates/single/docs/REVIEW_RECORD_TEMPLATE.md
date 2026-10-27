# Review Record

<!-- CARDINE:BEGIN capability=review-remediation-record v3 -->
Keep one durable review record per required-review task at the location `cardine locations` resolves. It is a summary for the implementer; machine state and the issued review operation decide the verdict.

Record each verdict with `cardine review verdict <TASK-ID> APPROVE|CHANGES_REQUESTED|BLOCKED --body <review-evidence>` on the clean reviewed HEAD; the owner adds `--owner`. The command writes the attempt heading and status; never edit either by hand. During remediation append a resolution section and leave prior findings unchanged. Commit the fixes and measured validation, run `cardine execution deliver <TASK-ID> --project .` last, and stop writing.

```md
# Review Record — <TASK-ID>

## Attempt <N> — <CHANGES_REQUESTED | APPROVE | BLOCKED>

- Reviewed commit: `<commit SHA>`
- Reviewer evidence: `<commands, diff, and sources inspected>`
- Validation observed: `<commands and result>`

### Findings

- [ ] P1 — `<required change>`
  - Evidence: `<path:line, command output, or criterion>`

### Resolution (implementer; omit until remediation)

- [x] P1 — `<what changed and where>`
```

Use `- [ ]` only for a change required before approval.
<!-- CARDINE:END -->

<!-- CARDINE:BEGIN capability=manual-verification-record v2 -->
Advice: when the task declared `Manual verification: required`, confirm the named screenshot against the view it claims to show and add `Manual verification observed: <screenshot path — view checked — result>`.
<!-- CARDINE:END -->
