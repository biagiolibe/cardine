# ADR: Stops and Denials

Status: Accepted

## Context

Meridian guards agent work in two ways. It **denies** actions: force pushes,
tags, history rewrites, conflict resolution. It also **stops** flows at gates:
a lifecycle command, a validation result, or a sentence in managed text tells
the agent to return `BLOCKED`. Denials protect against irreversible damage.
Stops protect consistency, and every false stop costs a session round trip.
That cost recurs on every task that meets the same gate.

Recent evidence shows the stops failing in four distinct ways, in both
workflows:

| Case | Workflow | What failed |
|------|----------|-------------|
| Task 159 | Governed SDD | Managed text required the agent to confirm that its reasoning level equalled a recorded cap. An agent cannot read that level and no command checks it, so the rule blocked every execution that carried it. |
| Task 161 | Lean Delivery, Governed SDD | Managed text required the primary checkout to be "at `origin/main`". `integrate stage` accepts a local `main` that is ahead. An agent stopped with `MAIN_BEHIND_ORIGIN` for a state the tool allows, and named a condition that did not occur. |
| Issue #6 | Governed SDD | `execution_preflight` requires the task record status to equal the queue row status. The workflow forbids task branches to edit the queue, and a review returns the record to `IN_PROGRESS`. Every remediation is therefore blocked by a gate that the blocked actor is forbidden to satisfy. The only workaround writes a false status. |
| Issue #5 | Governed SDD | `check_handoff` reads `Isolated exploration` and accepts only the exact value `none` when nothing was recorded. A correct statement in other words fails with a message saying an exploration was declared, which is the opposite problem. |
| Issue #2 | Governed SDD | `_archive_completed_queue_sections` skips any section whose heading or table shape it does not recognize. It reports nothing. A project's queue grew to about 88 KB without an archive. |

Two of these are prose-only stops (159, 161). Two are stops implemented in
the CLI and covered by tests (#5, #6). The last one (#2) is the reverse
failure: the tool silently did nothing. Neither "trust the prose" nor
"trust the CLI" is sufficient on its own.

There is no inventory that connects the two surfaces:

- `scripts/meridian.py` emits about 36 free-text `BLOCKED` messages under
  ten prefixes (`handoff check`, `execution preflight`, `execution evidence`,
  `execution contract`, `validation`, `investigation`, `budget spend`, and
  others). Only one of them, `UNDECLARED_VALIDATION_COMMANDS`, carries a code,
  and no workflow document lists that code.
- `closure_status` reports six closure codes through a structured field.
- Managed text lists thirteen closure stop codes. Three of them,
  `INTEGRATION_CONFLICT`, `EVIDENCE_MISMATCH`, and `CLEANUP_BLOCKED`, are
  detected by the CLI but raised as generic errors without the code. Three,
  `VALIDATION_FAILED`, `CANDIDATE_VALIDATION_FAILED`, and `PUSH_REJECTED`,
  come from the exit status of a command that the agent runs. Two,
  `ACCEPTANCE_UNMET` and `REVIEW_REQUIRED`, are judgments or declared gates.

An agent that meets a stop cannot tell which rule it enforces, whether the rule
is real, or what would satisfy it, unless it reads the code.

## Decision

### 1. Asymmetry between denials and stops

Managed text may **deny** an action that is irreversible or acts outside the
repository: force pushes, pushes that delete or mirror references, tags,
releases, history rewrites, deleting unmerged work, and resolving a textual
conflict. A denial stays effective without a supporting command.

Managed text may **not add a stop** to a flow that a directive has already
authorized, unless that stop is registered and backed under Decision 2. Guidance
that is not registered is advice. An agent follows advice when it can, and it
never returns `BLOCKED` on the strength of advice alone.

### 2. Every stop meets the gate contract

Every stop, whether it is written in managed text or implemented in the CLI,
meets four properties:

1. **Backed.** The stop is in the stop registry (Decision 3) with one of three
   classes:
   - `tool`: a Meridian command detects the condition and prints the code. A
     test triggers the stop and asserts the exact output line.
   - `command-exit`: the non-zero exit status of a command that the workflow or
     the task declares.
   - `judgment`: a condition that only the agent or the developer can assess,
     such as an unmet acceptance criterion or a declared review. This class is
     kept to an explicit, short list.
2. **Satisfiable.** The actor that the stop blocks can produce the state that
   clears it, using only files and commands that this actor is permitted to
   use. A gate must never require the blocked actor to change a document that
   it is forbidden to edit, or to report a property that it cannot observe.
3. **Actionable.** The stop prints one line, `BLOCKED <CODE>: <detail>;
   resume: <command>`. For a gate that compares values, `<detail>` names the
   rule, the field or source checked, the accepted values, and the value it
   found. A gate that checks free text compares meaning where it can, such as a
   leading `none` or `no`. It never rejects a cosmetic difference with a message
   that describes a different problem.
4. **Never silent.** A lifecycle step that skips input it does not recognize
   reports what it skipped and why, as a warning or a stop. A no-op is never
   presented as success.

The fixes for issues #2, #5, and #6 must meet these properties. This ADR does
not choose between the options listed in #6. It also does not decide whether an
`INCONCLUSIVE` spike closes its section (#2).

### 3. Stop registry

`capabilities/stop-codes-v1.json` is the single list of stop codes in both
workflows. Each entry records `code`, `class`, `workflows`, `step` (when the
stop belongs to a lifecycle step), `emitter` (the command or declared command
that produces it), `human_decision`, and a `resume` template.

- The CLI emits stops through one helper that accepts only registered codes.
  The current free-text `BLOCKED` messages are given codes. Their wording may
  change; existing code names do not.
- `scripts/check_repository.py` checks that:
  - every stop code named in managed text is registered;
  - every managed line that tells an agent to return `BLOCKED` names a
    registered code;
  - every `tool` code has a test that asserts its output line.
- `closure_status`, the lifecycle commands, and the execution and handoff
  gates all report codes from the same registry.

### 4. Conflicts between rules

When a gate seems to contradict another rule, the agent stops and reports
**both** rules. It never satisfies a gate by writing state that is false at the
moment it is written. For example, it never sets a status temporarily to pass a
preflight.

When a Meridian command has **accepted** a state and managed text appears to
forbid it, the agent follows the command, unless the action is on the deny list.
It records the difference in the handoff under `Rule discrepancies:`. This
clause covers only a state that a command accepted. It never permits overriding
a stop that a command printed.

### 5. Host enforcement of denials

Where the host supports it, `meridian setup` installs the deny list as host
permission rules, alongside the allow rules it already generates. Prefix-based
host rules are defense in depth, not proof: a reworded command can evade them,
so the managed denial text remains in force. Support for Codex deny rules has
not been verified and is part of the follow-up work.

## Consequences

- Managed text becomes shorter. The lists of stop codes in prose are replaced by
  the registry and by the rule in Decision 2. Task 161 lands first with its
  clarified closure sentence, message correction, and ahead-of-origin test;
  task 164 then rewrites the same managed block within the same unreleased
  version.
- Every existing gate is audited once against the gate contract. Gates that are
  not satisfiable, such as the one in issue #6, are fixed or removed. That audit
  is the main cost of adoption.
- `Rule discrepancies:` gives the framework a feedback channel. A repeated
  discrepancy shows that managed text needs to change.
- Command-exit stops are reliable only when the task declares its commands.
  Issue #4, which asks for a declared validation ID for every command that
  proves a criterion, is a natural companion. It is still decided separately.
- This ADR enables the follow-up designs listed below. It does not decide them:
  - a `meridian worktree advance` driver over the C1–C10 closure states. It
    runs only mechanical steps and hands control back to the agent for
    validation and human decisions, consistent with the rejected "one command
    that runs tests" alternative in `TASK_CLOSURE_DESIGN.md`;
  - compact Lean Delivery entry routers. Extending
    `ADR_SHARED_GENERATED_ENTRY_ROUTERS.md` beyond Governed SDD is a separate
    decision;
  - a `context size` report that separates files that must be read from files
    that are only mentioned;
  - a light lane whose eligibility is decided from declared path globs;
  - a lifecycle journal under the Git common directory, a `report flow` command,
    and detection of `BLOCKED` lines that no command emitted, through a Claude
    Code Stop hook. Codex support is unverified;
  - agent-run scenario evaluations graded on the journal and the final Git
    state, kept outside `unittest` and CI. Since 2026-10-08, by the
    developer's decision, they run on demand only and gate no release.

## Rejected alternatives

| Alternative | Reason rejected |
|-------------|-----------------|
| Trust the CLI over the prose in every case | Issues #5 and #6 are tested CLI gates that stop correct work. A command is authoritative for what it accepts, not for whether its own stop is sound. |
| Trust the prose over the CLI | Tasks 159 and 161 are prose stops that no command backs. A careful agent then refuses states that the tool allows. |
| Remove stops that cannot be verified mechanically | Acceptance criteria and declared reviews are real judgments. The `judgment` class keeps them, as a short explicit list. |
| Let the agent work around a contradictory gate | The workaround in #6 requires writing a false status. Falsified records destroy the evidence that the gates exist to protect. |
| Fix each reported gate one at a time | Each fix is correct locally, but the same failure classes keep coming back. Without a contract and a registry, nothing prevents the next unsatisfiable or misleading gate. |

## Rollout Plan

1. Accept this ADR.
2. First release, 1.2.9. Task 159 has already moved `VERSION` to the unreleased
   1.2.9 and shipped migration 063 for it, so this step adds no further
   version bump. It ships with task 161:
   - task 162: the registry and the emission helper, with codes for the
     closure stops and for `UNDECLARED_VALIDATION_COMMANDS`;
   - task 166: codes and actionable messages for the execution and handoff
     gates, which fixes issue #5;
   - task 167: a satisfiable execution preflight during remediation, which
     fixes issue #6. It is P1 and blocks Governed SDD projects in use, so it
     moves into this release; 166 and 167 change only the CLI;
   - task 163: the registry checks in `check_repository.py`;
   - task 164: the Decision 1 and Decision 4 text in the managed
     `git-workflow` block of both workflows. It lands after 161. If 161 has
     already bumped the `git-workflow` marker in an unreleased 1.2.9
     migration, 164 extends that migration and marker version instead of
     adding a second bump;
   - task 165: host deny rules for Claude Code, and a recorded finding on
     Codex support.
3. Second release: task 168 makes skipped queue sections visible (issue #2),
   and task 169 gives codes to the validation, investigation, and budget
   gates, audits them against the gate contract, and makes an uncoded stop a
   repository-check failure.
   Revised after 1.2.9 was published: these two tasks ship in different
   releases by release kind. Task 168 changes only the CLI and ships in the
   CLI-only Release A with tasks 171–175. Task 169 changes managed text and
   ships in the template-changing Release B with task 176, so both share one
   migration and one `git-workflow` marker bump. `tasks/QUEUE.md` (Phase 55)
   records the plan.
4. Follow-up designs listed under Consequences, each through its own task.

## Out of Scope

This ADR does not:

- rename existing stop codes;
- change who may edit governance files;
- decide the `INCONCLUSIVE` archival rule, the freshness of execution evidence
  raised in the comments on issue #6, or the `meridian adr list` command
  (issue #3);
- authorize any change to a consumer project outside `meridian upgrade`.
