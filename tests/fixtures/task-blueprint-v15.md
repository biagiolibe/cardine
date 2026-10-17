# Task [ID] — [Title]

<!-- MERIDIAN:BEGIN capability=task-blueprint v15 -->
Priority: [P0 / P1 / P2]
Status: QUEUED
Review: REQUIRED
Class: [omit for a normal task / SPIKE]
Manual verification: [none / required]
Manual verification rationale: [mandatory when Manual verification: required, omitted otherwise; name the tier-3 (perceptual) property that no tier-1 (structural) or tier-2 (derived-value) check can express — see docs/CONTEXT_BUDGET_POLICY.md's evidence tiers]
Dependencies: [none / TASK-ID, ...]
Diagnostic attempts: [optional; overrides the profile's default cap]
Evidence captures: [optional; overrides the profile's default cap]
Context expansions: [optional; overrides the profile's default cap]
Investigation scope: [optional; overrides the profile's default cap]

`Manual verification rationale` is checked before the evidence-availability
probe, not after: a missing rationale, or one naming a property assertable at
tier 1 or tier 2, returns `BLOCKED SCOPE_CHANGE_REQUIRED` asking for the task to be re-scoped as a
deterministic check instead.

`Diagnostic attempts`, `Evidence captures`, `Context expansions`, and
`Investigation scope` are
optional per-task caps; omit any of them to inherit
`docs/EXECUTION_EVIDENCE_PROFILE.md`'s default. Each is a cap, not a target:
exhausting it requires `BLOCKED BUDGET_EXHAUSTED`, not a silently raised cap. Setting one
above the profile's default requires a one-line rationale in this task.

## Spike shape

A `Class: SPIKE` task replaces `Review`, `Goal`, `Expected code surface`, and
`Acceptance criteria` with:

```text
Class:       SPIKE
Question:    [the thing that is not known]
Budget:      [max iterations / max wall time]
Deliverable: an ADR or a documented reference value — not production code
Branch:      throwaway, never merged
```

The branch may contain code needed to answer `Question` — a probe binary, a
reproduction, a benchmark harness. Only the branch is throwaway, not
everything run on it: the constraint is on what gets merged (nothing) and
what ships (the `Deliverable` alone, committed directly to `main`), not on
what the investigation is allowed to execute.

## Authority

- [Path to ADR/specification that governs this task.]

## Host impact

Choose exactly one shape. Use `REQUIRED` when this task changes workflow
instructions, a generated entry point, hook, command, skill, permission
policy, CLI bootstrap path, host adapter, or managed distribution of one of
those surfaces. Otherwise use `NOT_APPLICABLE`. Do not rewrite historical
task records solely to add this declaration.

### Not applicable

```text
Classification: NOT_APPLICABLE
Rationale: [why this change cannot alter workflow instructions, a hook,
permission policy, generated entry point, skill, CLI bootstrap, or host adapter]
```

### Required

```text
Classification: REQUIRED
Policy outcome: [host-independent behavior protected]

| Profile | Before | Intended after | Activation preconditions | Fallback |
|---|---|---|---|---|
| [host/version/invocation/config layer] | [state] | [state] | [facts] | [safe behavior] |

Evidence plan:
- Static: [fixture or deterministic check]
- Host execution: [command/tool fixture and expected outcome]
- Manual activation: [trust, install, or UI observation when needed]

Completion evidence:
- [profile]: [source, observed result, or explicitly retained `unverified` state]
```

`Before` and `Intended after` use only `enforced`, `advisory`, `unsupported`,
or `unverified`. A profile identity names the host product and version,
invocation mode, and configuration layer that supplies the adapter.

## Goal

[Concrete outcome.]

## Expected code surface

- Add or change: [exact module, file, documentation path, or bounded component.]
- Preserve: [interfaces, invariants, and adjacent areas that must not change.]
- Evidence needed: [tests, checks, manual inspection, or handoff evidence.]

## Out of scope

[Adjacent work that must not be implemented.]

## Acceptance criteria

- [Measurable observable outcome.]
- [Measurable invariant or test condition.]

## Validation

- `<validation-id>`: `<complete literal command, including its output bound and exit-status handling>`

Declare every command that proves an acceptance criterion or an `Evidence
needed` item here, each under its own validation ID. One ID holds exactly one
command. Write output paths as fixed, task-scoped paths such as
`target/<TASK-ID>/`, and use no `mktemp`, `$(...)`, or time-based paths. An
agent cannot compose a command that is not declared here without a permission
prompt, because a host allowlist cannot match a composed string.

Run source/build validation only through `meridian execution validate <TASK-ID>
<validation-id> --project .`. The command is deliberately stored in this task:
the runner executes no agent-supplied shell text and records its exit status in
`.meridian/execution-evidence.json` for the completion handoff.

Before a budgeted diagnostic, capture, or context expansion, record its
specific evidence gap with `meridian execution evidence <TASK-ID>
<diagnostic|captures|expansions> --gap <reason> --project .`. A capture also
requires its acceptance-criterion ID and artifact path; the command consumes
the corresponding cap and stores the durable evidence record.

Before a broad or uncertain-yield exploration outside the task's initial
authority, record the question, bounded scope, source paths, and distilled
finding with `meridian execution investigate <TASK-ID> --question <question>
--scope <units> --source <path> --finding <finding> --project .`. This works
with any host or worker arrangement; it records the investigation cost rather
than treating delegated reading as free.

## Execution contract — resolved

<!-- Generated by `meridian execution contract <TASK-ID> --project .` when
the task is created or materially re-scoped. Do not edit by hand. -->

- Profile source: `docs/EXECUTION_EVIDENCE_PROFILE.md`
- Profile revision: `sha256:<generated profile digest>`
- Budgets: `<generated resolved caps>`
- Validation IDs: `<generated IDs>`
- Execution commands: `required via meridian execution`

## Research handoff

Use this optional checkpoint after a bounded investigation and before a fresh
implementation session. Keep only facts verified from named sources, the
decision they support, remaining uncertainty, and the validation plan. The
durable investigation record remains authoritative for question, scope,
sources, and finding; this section is a concise continuation aid, not a second
transcript.

- Verified facts: `[none / concise facts]`
- Decision: `[none / decision supported by those facts]`
- Remaining uncertainty: `[none / bounded unknown]`
- Validation plan: `[declared validation IDs or revision needed]`

## Completion

- For `Review: REQUIRED`, save the completion report at the resolved handoff location (`meridian locations`), then run `meridian execution ready-check <TASK-ID> --project .` after validation and before setting this task record to `READY_FOR_REVIEW`. The gate requires a complete handoff and declared budget use.
- For `Review: NOT_REQUIRED`, set this task record to `ACCEPTED` only after validation passes.
- For `Class: SPIKE`, once `Budget` is exhausted or `Question` is answered, whichever comes first, self-administer `PROJECT_WORKFLOW.md`'s spike close-out gate and set this task record to `ANSWERED` or `INCONCLUSIVE`.
<!-- MERIDIAN:END -->
