# Context Budget and Reasoning Policy

This policy reduces context and reasoning overhead while preserving governed-SDD authority and review quality.

## Task-first loading

For an implementation or review:

1. Read `AGENTS.md` or `CLAUDE.md`, then the assigned task.
2. Read only the task's `Authority` entries and the minimum files needed to verify its `Expected code surface`.
3. Do not scan the repository, full backlog, unrelated ADRs/specifications, prior chats, or generic design documents without a task-specific need.
4. Expand context only when the task is blocked, an acceptance criterion cannot be verified, or an authoritative conflict is discovered. Record the reason in the completion or review report.
5. <!-- MERIDIAN:BEGIN capability=queue-briefing v1 -->For the task queue, rely on the resolved briefing that fires at the start of each turn — active, in-review, next-startable, and dependency-blocked rows — instead of opening the queue file. Open it directly only when the briefing did not fire, a row's exact wording or a column it does not surface is needed, or its resolved state conflicts with other evidence.<!-- MERIDIAN:END -->
6. <!-- MERIDIAN:BEGIN capability=authority-excerpt v1 -->For a task's cited ADRs and specification sections, run `meridian context authority <TASK-ID>` and read its resolved excerpts instead of opening the ADR log or a spec file directly. Open the file itself only when the command reports the entry unresolved or an excerpt is insufficient to verify an acceptance criterion.<!-- MERIDIAN:END -->

<!-- MERIDIAN:BEGIN capability=read-guard v2 -->
Item 2's rule is enforced mechanically, not only in prose. A `Read` of a file
past the configured `Read-guard threshold` with no `offset` or `limit` is
denied. The active task comes from the verified task worktree, and the task's
Authority and exemption paths are allowed. The router read set is exempt from
the threshold up to the router file ceiling. Locate the needed lines first,
then read that range.
<!-- MERIDIAN:END -->

Dependencies establish readiness; they do not automatically require rereading their entire implementation history.

<!-- MERIDIAN:BEGIN capability=isolated-exploration v1 -->
## Isolated exploration

When one specific question requires broad or uncertain-yield material outside a
task's declared `Authority` or `Expected code surface`, use a bounded
exploration before loading its raw material into the implementation session.
The mechanism is deliberately host-agnostic: it may be a separate session, a
worker, or a direct read when the declared scope is small.

- State the exact question, the expected answer shape, and the source scope
  before reading. A file already named by the task remains a targeted direct
  read; do not add process overhead for it.
- Record broad exploration with `meridian execution investigate <TASK-ID>`:
  question, scope units, sources materially used, and the distilled finding.
  Return or retain that finding, not a raw transcript or unconstrained search
  output.
- Delegation never erases cost. Each scope unit covers at most three primary
  files or 300 lines of primary material; a larger scope consumes additional
  `Investigation scope` budget or requires a task revision.
- The implementation worker remains responsible for validating any finding
  that becomes material to an acceptance criterion or implementation decision.

Use isolated exploration only for a genuinely open-ended question. Do not use
it to bypass a task's authority boundary, conceal a broad repository scan, or
replace a required spike when the unknown changes the task's design premise.
<!-- MERIDIAN:END -->

<!-- MERIDIAN:BEGIN capability=minimal-read-only-status v3 -->
## Minimal read-only status

For a request to report the current governed-SDD status without modifying
files, minimize context deliberately:

1. Read `LANGUAGE_POLICY.md`, then only the portions of `AGENTS.md` or
   `CLAUDE.md` and `PROJECT_WORKFLOW.md` needed to confirm the active mode and
   the local status-reporting rules.
2. Read this policy, read the queue's non-terminal entries through the
   resolved queue briefing rather than opening the whole queue, and inspect
   Git's current branch, clean/dirty state, and configured remote relation when
   relevant.
3. Read only the direct dependencies and task records needed to establish
   readiness for the next permitted governance action. Read a cited ADR or
   specification section only through `meridian context authority <TASK-ID>` or
   `meridian adr show <ADR-ID>`, never by opening the whole ADR log. Discover
   which ADR governs a question with `meridian adr list`, which prints one
   line per ADR.
4. Do not load completed milestones, broad file inventories, full
   specifications, ADRs, audit prompts, review records, or Git history unless
   a concrete discrepancy, blocker, or requested handoff requires them.
5. Before every expanded read, state the specific evidence gap it resolves.

A status report is not a conformance audit. It reports workflow mode,
non-terminal work, dependency readiness, Git state, the next permitted action,
and blockers; use the audit procedure only when the developer asks for an
audit.
<!-- MERIDIAN:END -->

## Validation scope

<!-- MERIDIAN:BEGIN capability=validation-scoping v2 -->
Before running validation, classify the diff by surface: *documentation/policy
text* (Markdown, comments, configuration prose with no build or runtime
effect) versus *source/build* (application code, dependency manifests, build
or CI configuration). Run only the validation commands whose surface
intersects the actual diff. For a documentation/policy-only change, skip the
project's full build, test, and lint suites and state so explicitly in the
completion or review report (for example: "skipped: full test/build/lint
suite — no source or build surface changed") instead of running them
defensively. This is distinct from the existing exemption for a command that
is inapplicable because its target artifact does not exist yet: skip a
command here because its surface was not touched, not because it cannot run.

A reviewer verifies the same scoping: confirm that validation evidence
matches the actual diff surface, that nothing relevant was skipped, and that
nothing irrelevant was run and reported as if it were meaningful evidence.
<!-- MERIDIAN:END -->

<!-- MERIDIAN:BEGIN capability=evidence-tiers v1 -->
## Evidence tiers

Before declaring `Manual verification: required`, name which tier the
property belongs to; only tier 3 justifies it.

1. **Structural** — counts, presence, identity, ordering, spawn/despawn invariants. Assertable directly.
2. **Derived value** — any observable the program itself computes and can read back: layout geometry, formatted output, serialized state, a colour held as a value, a duration. Assertable once you know where to read it.
3. **Perceptual** — exists only in the rendered artifact and nowhere as a value: shading, font rendering, visual balance, "does it read correctly".

If the property is readable as a value anywhere in the program, assert it instead of capturing it.
<!-- MERIDIAN:END -->

<!-- MERIDIAN:BEGIN capability=execution-evidence-profile v5 -->
## Execution evidence discipline

Apply the project-specific `docs/EXECUTION_EVIDENCE_PROFILE.md` before an
implementation, remediation, or review. It translates this stack-agnostic
discipline into the project's commands, log locations, diagnostic tools, and
manual-evidence channels. Configure that profile during bootstrap or before the
first implementation after an upgrade that adds it.

- Do not reload or reproduce instructions, source text, tool documentation, or
  successful command output already available in the active session unless the
  source changed or an exact passage is needed to resolve a recorded evidence
  gap.
- Run the profile's literal declared command string for every required
  validation command, output bound included; do not run the bare command and
  summarize or truncate its output afterwards, since a bound applied only
  after the fact cannot stop already-billed output from entering context.
  Preserve the command and its exit status; expose expanded logs only for a
  failure, and start with the narrowest diagnostic output that can identify
  the failing component.
- Escalate diagnostics progressively. Do not request a full backtrace, trace,
  verbose mode, or complete log until ordinary output and a targeted diagnostic
  leave the cause or location unresolved. Record the reason for escalation.
- Do not use repeated test-and-tune cycles as a substitute for an approved
  implementation strategy. Before a second diagnostic attempt that changes an
  implementation hypothesis, state the evidence gap it will resolve. If a
  focused failure exposes a conflict between the task's acceptance criteria,
  authority, or allowed code surface, return `BLOCKED SCOPE_CHANGE_REQUIRED`; do not continue
  searching for a workaround past the profile's declared diagnostic-attempt
  budget.
- Inspect every changed hunk, beginning with a change summary and then
  per-file/hunk evidence. A complete printed diff is not required merely to
  establish diff scope.
- Plan manual evidence from the task's acceptance criteria before invoking UI
  or capture tools. Gather only the distinct views the criteria require; do not
  repeat a tool discovery call or acquire extra images without an evidence gap.
  Prefer a project-declared direct capture path when it supplies the required
  evidence without interaction.
- Reuse unchanged successful validation evidence during independent review
  unless a credibility or coverage gap requires a rerun. Independent source and
  diff review remain mandatory.

If the active agent interface offers a faster execution mode, it may be used
only when it does not reduce required evidence.
<!-- MERIDIAN:END -->

<!-- MERIDIAN:BEGIN capability=phase-reads v1 -->
## Phase reads

When this policy is the routed document for a status or design request, read
each document when its phase begins. This changes only when a document is read;
no rule here is waived by reading a document later.

- At start: this policy.
- At first validation, only for an implementation, remediation, or review: `docs/EXECUTION_EVIDENCE_PROFILE.md`.
<!-- MERIDIAN:END -->

## Lifecycle orchestration

For `Run lifecycle <TASK-ID>`, the orchestrator reads only the task and queue
status, the latest implementation commit, the latest review-record attempt,
and worker result fields. It delegates implementation and review to distinct
sessions and never copies their conversational context. Do not add a separate
summarization step or rerun an unchanged successful validation.

## Planning and communication

- Keep execution plans to three bullets or fewer.
- Report only state changes, material findings, validation results, or blockers.
- Keep routine completion and review reports concise; include detail only for deviations or unresolved risk.
- Do not use parallel agents or repeated inspections when they add no independent evidence.

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
| Governed SDD | status | 100000 |
| Governed SDD | design | 100000 |
| Governed SDD | implementation | 100000 |
| Governed SDD | review | 100000 |
| Governed SDD | remediation | 100000 |
| Governed SDD | lifecycle | 100000 |
