# Consumer profiles and project-owned sections

A Meridian-managed file holds framework text only inside `MERIDIAN:BEGIN` and
`MERIDIAN:END` blocks. A project extends the framework by writing its own
sections after a block, never by editing inside one. `meridian upgrade` keeps
those sections, and `meridian audit` verifies the blocks region by region, so
project text outside them never fails an audit.

| File | Project-owned section after the managed block |
|---|---|
| `docs/CODE_REVIEW_PROMPT.md` | `## Project review checklist`. The reviewer applies every item as extra review scope. |
| `docs/AUDIT_PROMPT_READ_ONLY.md` | `## Project-specific checks`. Each check cites an accepted ADR. |
| `docs/CODE_ORGANIZATION.md` | `## Project module map`. |

## Whole-file managed copies

A managed file that carries no capability markers, such as
`docs/OPERATOR_PROMPTS.md` in Governed SDD or `docs/COMPLETION_REPORT_TEMPLATE.md`
in Lean Delivery, is a verbatim copy. `meridian audit` reports a `FAIL` row
(`managed-copy-digest`) when its digest differs from the one `meridian upgrade`
recorded in `.meridian/manifest.json`. Restore the released text and put
project-specific content in a project file. `docs/EXECUTION_EVIDENCE_PROFILE.md`, which a project configures for its
stack, `docs/ARCHITECTURE_DECISIONS.md`, `AGENTS.md`, `CLAUDE.md`, and the queue
belong to the project and are never digest-checked.

## Declaring a consumer profile

A protocol v2 manifest without `capabilityProfiles` audits as `UNVERIFIED`
(`declaration/legacy-compatibility`). The catalog ships `governed-sdd-consumer`
and `lean-delivery-consumer` so a consumer can declare what is installed:

```bash
meridian profile bootstrap governed-sdd-consumer --check   # print the manifest it would write
meridian profile bootstrap governed-sdd-consumer --apply   # write it
meridian audit
```

Use the profile that matches the manifest's `workflowMode`. Bootstrap records
installation evidence only. Host activation and verification stay `UNVERIFIED`
until a probe records stronger evidence, so the audit still exits `1`, not `2`.

Bootstrap refuses a markerless managed copy that differs from its recorded
digest, because recording the edited file would hide the drift. Restore the
file, then bootstrap again. A file with capability blocks may carry project
sections; it is verified by its block rows. `meridian profile doctor <id>`
also expects the probe files named in the catalog under
`.meridian/probes/<profile>/`, which a consumer adds when it records host
evidence.
