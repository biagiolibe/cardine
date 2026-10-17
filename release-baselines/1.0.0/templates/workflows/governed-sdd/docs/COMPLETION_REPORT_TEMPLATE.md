# Concise Completion Report

Use this handoff after validation. Keep it short and make every deviation explicit.

```md
## Completion Report — <TASK-ID>

- Files changed: `<paths>`
- Branch: `<task-branch>`
- Implementation commit: `<commit SHA>`
- Base `main` commit: `<commit SHA>`
- Validation: `<commands/checks and pass/fail result>`
- Acceptance criteria: `<all met | list criterion IDs/status>`
- Blockers/deviations: `<none | concrete issue, scope expansion, or context expansion and reason>`
```

Do not claim completion when validation fails or an acceptance criterion is unresolved. For reviews, retain the same four fields in the review record and add the required verdict from `docs/CODE_REVIEW_PROMPT.md`.
