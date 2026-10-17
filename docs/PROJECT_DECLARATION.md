# Project declaration

`.meridian/project.json` is a consumer-owned declaration of project values that
managed capability blocks cannot safely contain. `meridian upgrade --apply`
never creates or changes it.

The file uses [project-v1.schema.json](../schemas/project-v1.schema.json).
Only `version` is required; omitted values use the existing defaults. Paths are
project-relative and may not be absolute or contain `..`.

```json
{
  "version": 1,
  "project": { "name": "consumer project A", "slug": "consumer-project-a" },
  "locations": {
    "queue": "docs/TASK_QUEUE.md",
    "taskRoots": ["tasks"],
    "reviewRoot": "tasks/reviews",
    "handoffRoot": "tasks/handoffs",
    "adrLog": "docs/ARCHITECTURE_DECISIONS.md",
    "plan": "PROJECT_PLAN.md"
  },
  "validationScoping": [
    { "paths": ["crates/domain/**"], "commands": ["cargo test -p domain"] }
  ],
  "ci": { "provider": "github-actions", "requiredChecks": ["test"] }
}
```

`ci` can instead be `"none"`. The queue archive is intentionally not
declarable: it is always the queue's sibling named `QUEUE_ARCHIVE.md`.

Use `meridian locations` to read resolved locations and `meridian project show`
to print the resolved declaration. `meridian project show --field reviewer-author`
formats the declared project as the Reviewer-Integrator identity.

For compatibility, locations are read from legacy prose after the
`execution-assets` capability only if this file is absent. That fallback emits a
deprecation warning once per command invocation.
