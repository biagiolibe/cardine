# Task [ID] — [Title]

<!-- MERIDIAN:BEGIN capability=task-blueprint v19 -->
> **ID**: `[NNN]`
> **Category**: [Architecture / Feature / Bugfix / Refactor / Quick / etc.]
> **Priority**: [P0 / P1 / P2]
> **Estimate**: [~1h / ~2h / etc.]
> **Assigned to**: [agent or owner / unassigned]
> **Session**: [conversation ID or temporal reference]
> **Origin**: [optional: capability / friction / maintenance / release]

Status: queued
Class: [omit for a standard task / SPIKE]
Review: [omit to inherit the project default / required / not_required]
Options: [omit, or a JSON object with any `taskDefaults` key, for example `{"authorityRequired": true}`]
Manual verification: [none / required]
Manual verification rationale: [mandatory when Manual verification: required, omitted otherwise; name the tier-3 (perceptual) property that no tier-1 (structural) or tier-2 (derived-value) check can express — see docs/CONTEXT_READING_POLICY.md's evidence tiers]

Every omitted option inherits from the project configuration and its preset;
`false` and `not_required` are explicit overrides, valid in either direction.
The CLI writes the resolved options into the task's state file when the task is
created; a later change to the project defaults never alters an open task. A
quick task (`Category: Quick`) is a minimal registered record with an
objective, acceptance criteria, validation, and dependencies.

`Manual verification rationale` is checked before the evidence-availability
probe, not after: a missing rationale, or one naming a property assertable at
tier 1 or tier 2, returns `BLOCKED SCOPE_CHANGE_REQUIRED` asking for the task to be re-scoped as a
deterministic check instead.

## Spike shape

A `Class: SPIKE` task replaces `Objective` and `Acceptance criteria` with:

```text
Class:       SPIKE
Question:    [the thing that is not known]
Timebox:     [max iterations / max wall time]
Deliverable: an ADR or a documented reference value — not production code
Branch:      canonical task branch in its dedicated task worktree
Probe branch: optional separate local throwaway branch, never merged or pushed
```

The optional probe branch may contain code needed to answer `Question` — a
probe binary, a reproduction, a benchmark harness. Keep it separate from the
canonical task branch; probe code is never merged or pushed. Record the answer
as the `Deliverable` on the canonical task branch, together with only the
lifecycle and evidence records permitted by `PROJECT_WORKFLOW.md` and
`docs/WORKTREE_LIFECYCLE.md` (including the canonical execution-evidence ledger).
Do not commit the deliverable directly to `main`. The canonical task branch
completes through the ordinary worktree closure and integration;
`ANSWERED` or `INCONCLUSIVE` records the spike outcome, not an exemption from
that closure. A spike resolves review like any other task. The deliverable
remains an ADR or documented reference value, never production code. When the
expected code surface is required, it names the deliverable and the permitted
probes, and never permits production changes.

## Objective

[Concrete outcome and why it is needed.]

## Authority

- [Path to ADR/specification that governs this task. Required when the
  resolved `authorityRequired` option is true; when supplied, it constrains
  the work in either case.]

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

## Expected code surface

[Required when the resolved `expectedCodeSurfaceRequired` option is true;
when supplied, it constrains the work in either case. When omitted, the
Objective, the relevant files, and the out-of-scope clauses still bound the
authorization; omission never grants permission for unrelated work.]

- Add or change: [exact module, file, documentation path, or bounded component.]
- Preserve: [interfaces, invariants, and adjacent areas that must not change.]
- Evidence needed: [tests, checks, manual inspection, or handoff evidence.]

## Acceptance Criteria

- [ ] [Measurable observable outcome.]
- [ ] [Measurable invariant or test condition.]

## Relevant Files

| File | Role |
|------|------|
| `[path]` | [Role description.] |

## Technical Context

[Current code state, constraints, and decisions that bound the work.]

## Out of scope

[Adjacent work that must not be implemented.]

## Dependencies

- **Depends on**: [none / TASK-ID, ...]
- **Blocks**: [none / TASK-ID, ...]

## Validation

- `<validation-id>`: `<complete literal command, including its output bound and exit-status handling>`

Declare every command that proves an acceptance criterion or an `Evidence
needed` item here, each under its own validation ID. One ID holds exactly one
command. Write output paths as fixed, task-scoped paths such as
`target/<TASK-ID>/`, and use no `mktemp`, `$(...)`, or time-based paths. An
agent cannot compose a command that is not declared here without a permission
prompt, because a host allowlist cannot match a composed string.

The project's baseline validation commands compose with the commands declared
here; a task command supplements the baseline and never silently removes it.

Run source/build validation only through `meridian execution validate <TASK-ID>
<validation-id> --project .`. The command is deliberately stored in this task:
the runner executes no agent-supplied shell text and records its exit status in
`.meridian/execution-evidence.json` for the completion handoff.

Before a diagnostic, capture, or context expansion, record its
specific evidence gap with `meridian execution evidence <TASK-ID>
<diagnostic|captures|expansions> --gap <reason> --project .`. A capture also
requires its acceptance-criterion ID and artifact path; the command stores
the durable evidence record.

Before a broad or uncertain-yield exploration outside the task's initial
authority, record the question, bounded scope, source paths, and distilled
finding with `meridian execution investigate <TASK-ID> --question <question>
--scope <units> --source <path> --finding <finding> --project .`. This works
with any host or worker arrangement; it preserves the investigation provenance.

## Execution contract — resolved

<!-- Generated by `meridian execution contract <TASK-ID> --project .` when
the task is created or materially re-scoped. Do not edit by hand. -->

- Profile source: `docs/EXECUTION_EVIDENCE_PROFILE.md`
- Profile revision: `sha256:<generated profile digest>`
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

- When the resolved review option is `required`, commit implementation and validation evidence, finalize and commit the completion report at the resolved handoff location (`meridian locations`), then run `meridian execution ready-check <TASK-ID> --project .` before `meridian execution deliver <TASK-ID> --project .` as the final step. Stop writing after its clean committed result. Never edit a status or verdict by hand. The gate requires a complete handoff.
- When the resolved review option is `not_required`, run `meridian task close <TASK-ID>` in the clean task worktree only after validation passes and the completion record and handoff are committed.
- For `Class: SPIKE`, once `Timebox` is exhausted or `Question` is answered, whichever comes first, record the outcome with `meridian task outcome <TASK-ID> ANSWERED` or `meridian task outcome <TASK-ID> INCONCLUSIVE`, then complete the review or closure path the resolved review option selects.
<!-- MERIDIAN:END -->
