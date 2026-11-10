# [Project Name]

Read `PROJECT_WORKFLOW.md` and `LANGUAGE_POLICY.md` before acting; the former governs operations. If missing or contradictory, return `BLOCKED RULE_CONFLICT`. Shared rules are generated from `AGENTS.md`.

## Commands

```bash
# Fill in the project's run, test, lint, and format commands.
```

<!-- CARDINE:BEGIN capability=command-triggers v3 -->
## Command triggers

- `Proceed with <TASK-ID>` or `Address review <TASK-ID>` — use `cardine-delivery` for the engine action.
- `Review <TASK-ID>` — use `cardine-delivery` for review.
- `Run lifecycle <TASK-ID>` or `Accept <TASK-ID>` — use `cardine-delivery` and `docs/LIFECYCLE_ORCHESTRATION.md`.
- Init, adopt, upgrade, setup, or doctor — use `cardine-project`.
- Status, project question, or tech-design alignment — use `docs/CONTEXT_READING_POLICY.md`.
- Explicit audit — read `docs/AUDIT_PROMPT_READ_ONLY.md`.
<!-- CARDINE:END -->

Cardine usage: `cardine guide --project <checkout>`.

Production: follow `docs/CODE_ORGANIZATION.md` (advice).
