# Context Budget and Evidence Policy

This policy is workflow-neutral. It limits context and validation cost without
adding lifecycle states, roles, or acceptance gates.

## Task-first context

- Read the local workflow and language rules, then the assigned task.
- Read only the files needed to implement or verify the task. Expand the scope
  only to resolve a named evidence gap or authority conflict.
- Reuse unchanged evidence already present in the active session.

<!-- MERIDIAN:BEGIN capability=queue-briefing v1 -->
Use the resolved queue briefing at the start of a turn instead of opening the
whole queue. Open the queue only when the briefing is absent, omits a required
field, or conflicts with another project record.
<!-- MERIDIAN:END -->

<!-- MERIDIAN:BEGIN capability=read-guard v2 -->
Large-file reads are bounded mechanically where the host supports an adapter.
The active task comes from the verified task worktree, and the router read set
is exempt from the read threshold up to the router file ceiling. Locate the
relevant range first; adapter installation is not proof that the host loaded or
enforced it.
<!-- MERIDIAN:END -->

## Bounded exploration

State the question, expected answer shape, and source scope before broad or
uncertain exploration. Keep the distilled finding and validate any finding
that becomes material to an acceptance criterion.

<!-- MERIDIAN:BEGIN capability=minimal-read-only-status v1 -->
## Minimal read-only status

For a status-only request, read the active workflow rules, non-terminal queue
entries, directly relevant task dependencies, and current Git state. Report
the workflow mode, active work, readiness, next permitted action, and blockers.
Do not load completed history or perform a conformance audit unless a concrete
discrepancy or explicit request requires it.
<!-- MERIDIAN:END -->

<!-- MERIDIAN:BEGIN capability=validation-scoping v2 -->
## Validation scope

Classify the diff as documentation/policy or source/build/runtime. Skip checks
that cannot exercise the changed surface unless the task explicitly requires
them, and record each skip. Run all task-required checks and every applicable
project baseline; scoping never weakens an acceptance criterion.
<!-- MERIDIAN:END -->

<!-- MERIDIAN:BEGIN capability=evidence-tiers v1 -->
## Evidence tiers

Use deterministic structural evidence for presence, identity, ordering, and
state. Use readable derived values for program-computed output. Reserve manual
evidence for genuinely perceptual properties that exist only in a rendered
artifact; if the value can be read back, assert it instead.
<!-- MERIDIAN:END -->

<!-- MERIDIAN:BEGIN capability=execution-evidence-profile v3 -->
## Execution evidence

Apply `docs/EXECUTION_EVIDENCE_PROFILE.md`. Run each required command with its
declared output bound and preserve the producer exit status. Escalate from
ordinary output to targeted diagnostics, then to full traces only when a named
evidence gap remains. Inspect every changed hunk and retain exact commands,
exit codes, and material results in the task handoff.
<!-- MERIDIAN:END -->

## Communication

Keep plans and updates short. Report state changes, material findings,
validation outcomes, and blockers rather than replaying command transcripts.

## Context-size policy v1

`meridian context size --role <role> --format text` reports the startup read
set using byte-derived token estimates (bytes / 4 to bytes / 3.3), not a claim
of tokenizer accuracy. Set a per-file enforcement threshold in
`.meridian/context-size.json` as `{ "version": 1, "fileBytesThreshold": 12000 }`,
or pass `--threshold-bytes`; without either, the report is advisory.
The same version-1 file may set `routerFileLinesCeiling` (default: 1000).
Router startup files are exempt from the runtime read-guard threshold only up
to that ceiling; shrink an oversized router file rather than reading it in
ranges.

Template read-set ceilings are checked by `scripts/check_repository.py`:

| Workflow | Role | Ceiling (bytes) |
| --- | --- | ---: |
| Lean Delivery | implementation | 100000 |
| Lean Delivery | review | 100000 |
