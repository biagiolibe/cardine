# [Project Name]

Read `PROJECT_WORKFLOW.md` and `LANGUAGE_POLICY.md` before acting; `PROJECT_WORKFLOW.md` is the source of operational rules. If either is missing or they contradict, return `BLOCKED RULE_CONFLICT`. The shared rules below are generated from `AGENTS.md`.

## Commands

```bash
# Fill in the project's run, test, lint, and format commands.
```

<!-- CARDINE:BEGIN capability=command-triggers v3 -->
## Command triggers

- `Proceed with <TASK-ID>` or `Address review <TASK-ID>` — use `cardine-delivery`.
- `Review <TASK-ID>` — use `cardine-delivery`.
- `Run lifecycle <TASK-ID>` or `Accept <TASK-ID>` — use `cardine-delivery` and `docs/LIFECYCLE_ORCHESTRATION.md`.
- Init, adopt, upgrade, setup, or doctor — use `cardine-project`.
- Cardine usage — `cardine guide --project <checkout>`.
- Status, project questions, or tech-design alignment — use `docs/CONTEXT_READING_POLICY.md`.
- Audit — read `docs/AUDIT_PROMPT_READ_ONLY.md`.
<!-- CARDINE:END -->

Production changes: follow `docs/CODE_ORGANIZATION.md` (advice).
