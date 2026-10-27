# Task [ID] — [Title]

<!-- CARDINE:BEGIN capability=task-blueprint v9 -->
> **ID**: `[NNN]`
> **Category**: [Architecture / Feature / Bugfix / Refactor / Quick / etc.]
> **Priority**: [P0 / P1 / P2]
> **Estimate**: [~1h / ~2h / etc.]
> **Assigned to**: [agent or owner / unassigned]
> **Session**: [conversation ID or temporal reference]
> **Phase**: [optional delivery phase]
> **Origin**: [optional: capability / friction / maintenance / release]

Class: [omit for a standard task / SPIKE]
Review: [omit to inherit the project default / required / not_required]
Options: [omit, or a JSON object with any `taskDefaults` key, for example `{"authorityRequired": true}`]
Manual verification: [none / required]
Manual verification rationale: [mandatory when Manual verification: required, omitted otherwise; name the tier-3 (perceptual) property that no tier-1 (structural: counts, presence, identity, ordering) or tier-2 (derived-value: anything the program computes and can read back, such as layout geometry, formatted output, or a colour held as a value) check can express]

Every omitted option inherits from the project configuration and its preset;
`false` and `not_required` are explicit overrides, valid in either direction.
The CLI writes the resolved options into the task's state file when the task is
created; a later change to the project defaults never alters an open task. A
quick task (`Category: Quick`) is a minimal registered record with an
objective, acceptance criteria, validation, and dependencies.

Creation also freezes dependencies (canonical registered task IDs), title,
priority, phase, origin, spike deliverable paths, Authority citations, and the
stable record path. Omitted optional labels become empty strings; omitted
citations and deliverables become empty arrays. Quick tasks without a title
use their canonical ID. Spike deliverables name project-relative `docs/` paths.
Edit the record and run `cardine task contract update <ID> --project .` to
revalidate and atomically revise the snapshot with state history. Audit reports
record drift and older incomplete snapshots with this command; it never fills
missing fields from prose. Status, dependencies, and startability are read from
state with `cardine status`; a record carries no status line.

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

[Required for unattended runs, even when interactive Lean work may omit it.
List one normalized repository-relative path or glob per bullet, optionally
in backticks. Replace the examples below with the authorized files. `*`
matches one path segment; `**` matches nested segments. Absolute paths,
parent traversal, and symlink escapes are rejected. Creation or an explicit
contract update freezes these paths; editing this section later grants no
additional authority. Keep preservation requirements and evidence in the
out-of-scope and validation sections. CLI-owned state, evidence and views
are separate from implementation files.]

- `src/example/**`
- `tests/test_example.py`

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

Run source/build validation only through `cardine execution validate <TASK-ID>
<validation-id> --project .`. The command is deliberately stored in this task:
the runner executes no agent-supplied shell text and records its exit status in
`.cardine/evidence/<TASK-ID>.json` for the completion handoff.

## Execution contract — resolved

<!-- Generated by `cardine execution contract <TASK-ID> --project .` when
the task is created or materially re-scoped. Do not edit by hand. -->

- Profile source: `docs/EXECUTION_EVIDENCE_PROFILE.md`
- Profile revision: `sha256:<generated profile digest>`
- Validation IDs: `<generated IDs>`
- Execution commands: `required via cardine execution`

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

- When the resolved review option is `required`, commit implementation and validation evidence, optionally write a human completion summary, then run `cardine execution ready-check <TASK-ID> --project .` before `cardine execution deliver <TASK-ID> --project .` as the final step. Stop writing after its clean committed result. Never edit a status or verdict by hand. The gate reads measured validation and committed delivery, never completion prose.
- When the resolved review option is `not_required`, run `cardine task close <TASK-ID>` in the clean task worktree only after validation passes and the task record and measured results are committed.
- For `Class: SPIKE`, once `Timebox` is exhausted or `Question` is answered, whichever comes first, record the outcome with `cardine task outcome <TASK-ID> ANSWERED` or `cardine task outcome <TASK-ID> INCONCLUSIVE`, then complete the review or closure path the resolved review option selects.
<!-- CARDINE:END -->
