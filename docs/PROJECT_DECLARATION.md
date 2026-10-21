# Project declaration

`.cardine/project.json` is the consumer-owned configuration. It is validated
by [project-v1.schema.json](../schemas/project-v1.schema.json); upgrades preserve
it. Paths are relative to the project and cannot contain `..`.

```json
{
  "version": 1,
  "preset": "lean",
  "project": { "name": "Consumer project", "slug": "consumer-project" },
  "taskIdentity": { "mode": "opaque" },
  "taskDefaults": { "review": "required" },
  "validation": {
    "commands": { "tests": "python3 -m unittest discover -s tests" },
    "baseline": ["tests"],
    "candidate": { "REUSE": ["tests"], "BOUNDED": ["tests"], "FULL": ["tests"] }
  },
  "ci": "none"
}
```

Both `version: 1` and `preset: lean|governed` are required. Both presets install
`templates/single/`, register `workflowMode: single`, and use one state machine.
The preset supplies defaults only. Neither queue shape nor workflow prose
selects policy. Missing or malformed configuration is an error.

| Task option | Lean | Governed |
| --- | --- | --- |
| `review` | `not_required` | `required` |
| `authorityRequired` | false | true |
| `expectedCodeSurfaceRequired` | false | true |
| `validationRetryLimit` | 3 | 3 |
| `landingMode` | `direct` | `direct` |
| `ciBeforeLanding` | false | false |

Optional `taskDefaults` override these defaults; explicit task options override
project defaults in either direction. Creation freezes the resolved contract,
commands, preset, and declaration digest in `.cardine/tasks/<ID>.json`.
Configuration edits affect new tasks only. Required review binds approval to
the current implementation commit. Approval leaves a task `in_progress`;
verified landing alone writes `done`. Both presets permit spikes and milestone
identity. Cancellation and inconclusive spikes never satisfy dependencies.

Initialization requires owner-selected literal validation commands. Every
baseline/candidate entry references a declared command ID, and all three
candidate outcomes must be present. An empty list is an explicit choice.
Candidate validation always adds `git diff --check`. Task commands supplement
the baseline. Retry limits are positive integers; the future runner owns their
automatic counting. Context reading guards and evidence tiers remain available
without spend counters.

`ci` may be `none` or an object with `provider` and `requiredChecks`.
`ciBeforeLanding: true` requires a supported provider and nonempty checks.
Only direct landing is supported in 1.0; `pull-request` is rejected without
probing a forge.

Optional `locations` declares `queue`, `taskRoots`, `reviewRoot`, `handoffRoot`,
`adrLog`, and `plan`. The archive remains the queue's sibling `QUEUE_ARCHIVE.md`.
`validationScoping` retains bounded selection by paths and literal commands.
Use `cardine locations` and `cardine project show` to inspect resolved values.
Real Meridian installation conversion remains a separate migration; this
configuration does not activate a second state authority.
