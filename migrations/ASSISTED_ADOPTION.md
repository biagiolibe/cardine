# Capability-Aware Legacy Adoption

Use assisted adoption when a project predates `.meridian/manifest.json` and
has adapted Meridian workflow documents. A generic three-way template merge is
safe only when it has no conflicts; it must not be used to overwrite an
established project workflow.

```text
meridian adopt --assisted --check
  -> NEXT_ACTION IMPLEMENT_MIGRATION  -> bounded migration implementation
  -> NEXT_ACTION REVIEW_MIGRATION     -> independent review
  -> NEXT_ACTION ADDRESS_REVIEW       -> remediation, then review again
  -> NEXT_ACTION FINALIZE             -> meridian finalize-adoption
```

`--mode` and `--from` are detected from the project's `PROJECT_WORKFLOW.md`
mode lock and the sole packaged baseline for that mode when omitted; pass them
explicitly only when the command reports the detection as ambiguous.

The capability plan detects framework behavior, not just template hashes. For
example, review remediation is present only when both a review-record template
and an `Address review` trigger exist. Lifecycle orchestration is present only
when both its documentation and the `Run lifecycle` trigger exist. Assisted
adoption is meaningful only for `governed-sdd`; it tracks no capabilities for
`lean-delivery` and refuses `--assisted` there.

Every run recomputes a single `NEXT_ACTION` token from two durable sources —
detected capabilities and `.meridian/adoption-review.md` — and maps it to the
command's existing exit codes: `3` for `IMPLEMENT_MIGRATION`, `REVIEW_MIGRATION`,
and `ADDRESS_REVIEW` (agent work required), `0` for `FINALIZE`
(`READY_TO_FINALIZE`), and `2` for `BLOCKED`. A coordinator therefore needs no
memory of its own: run the command, read `NEXT_ACTION` and the exit code, act,
and rerun.

The command emits a complete implementer prompt between
`IMPLEMENTER_PROMPT_BEGIN` and `IMPLEMENTER_PROMPT_END` (only when a migration
is required), a reviewer prompt between `REVIEWER_PROMPT_BEGIN` and
`REVIEWER_PROMPT_END`, and an `ORCHESTRATOR_PROMPT` describing the same loop
for a host or human coordinator. Append `--emit implementer` or
`--emit reviewer` to `--assisted --check` to fetch exactly one block without
parsing the markers. An orchestration host sends the implementer and reviewer
texts to distinct sessions — independent Task-tool subagents where the host
supports them, otherwise separate fresh chats — never in the same session that
did the other role. A human can use the same emitted prompts directly.

The migration agent reads the plan and its named migration records, works only
on missing capabilities, validates, and hands the diff to an independent
reviewer. It must not copy generic framework files wholesale.

The reviewer records its verdict as a machine-readable header in
`.meridian/adoption-review.md`:

```text
Verdict: APPROVE | CHANGES_REQUESTED | BLOCKED
Attempt: <n>

## Findings
- [ ] unresolved finding, with evidence
```

On `CHANGES_REQUESTED`, the orchestrator starts a fresh implementer that reads
this record and addresses only its unchecked findings, then a fresh reviewer
for the next attempt (incrementing `Attempt`). After two consecutive
`CHANGES_REQUESTED` verdicts, the command reports `BLOCKED` on its own —
resolve the underlying issue manually before restarting the loop. This durable
record prevents chat output from becoming the handoff interface.

`finalize-adoption` is allowed only after the required capabilities are
present and the review record shows an unconditional `APPROVE` (no unchecked
findings) — or after an explicit `--owner-accepted` flag from a developer who
personally reviewed the migration, mirroring the project's own
`Accept <TASK-ID>` owner-acceptance path. It writes the manifest and
installed-template baseline that make all future framework updates
deterministic.
