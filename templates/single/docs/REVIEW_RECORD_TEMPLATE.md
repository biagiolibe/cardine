# Review Record

<!-- MERIDIAN:BEGIN capability=review-remediation-record v6 -->
Use one durable review record per required-review task at the location
`meridian locations` resolves for it. It is the canonical handoff from reviewer to
implementer; chat output may summarize it but must not be the only location of
findings. Create the directory when the first record is needed.

Record every verdict with `meridian review verdict <TASK-ID> APPROVE|CHANGES_REQUESTED|BLOCKED --body <review-evidence>` on the clean reviewed HEAD; owner acceptance adds `--owner`. Never edit a status or verdict by hand. The command owns attempt headings and Status projections. Headings are human-readable only; gates read the task's machine state and Git. Prepare evidence as a command argument before mutating tracked files. Findings must be actionable, prioritized, and tied to evidence. During remediation append a resolution section without changing prior findings, evidence, or verdict headings; commit remediation, validation evidence, and the final handoff, then return to review with `meridian execution deliver <TASK-ID> --project .` last and stop writing.

```md
# Review Record — <TASK-ID>

## Attempt <N> — <CHANGES_REQUESTED | APPROVE | BLOCKED>

- Reviewed commit: `<commit SHA>`
- Base `main` commit: `<commit SHA>`
- Reviewer evidence: `<commands, diff, and task sources inspected>`
- Validation observed: `<commands and pass/fail result>`

### Findings

- [ ] P1 — `<required change>`
  - Evidence: `<path:line, command output, or acceptance-criterion reference>`

### Resolution (implementer; omit until remediation)

- [x] P1 — `<what changed and where>`
  - Evidence: `<commit, path:line, or validation result>`

### Blockers/deviations

`<none | concrete issue>`
```

Use `- [ ]` only for changes that must be made before approval. `P0` and `P1`
findings block approval; `P2` findings are included only when they require a
bounded change in this task. Style-only commentary does not belong in the
record.
<!-- MERIDIAN:END -->

<!-- MERIDIAN:BEGIN capability=manual-verification-record v1 -->
When the task declared `Manual verification: required`, the reviewer
independently confirms the named screenshot against the view it claims to
show and adds `Manual verification observed: <screenshot path — view
checked — result>` alongside the attempt's other evidence fields, rather
than restating the implementer's claim unverified.
<!-- MERIDIAN:END -->
