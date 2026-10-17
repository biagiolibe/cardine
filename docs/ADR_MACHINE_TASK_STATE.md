# ADR: Machine Task State

Status: Accepted

## Context

Meridian decides whether a task is accepted by reading text that people and
agents write by hand:
- the `Status` cell of the queue row;
- the `Status:` field of the task record;
- the `## Attempt <N> — <VERDICT>` heading of the review record.

`integrate stage` completes a Governed SDD row only when
`latest_review_verdict` finds `APPROVE` in that heading. Its pattern
(`scripts/console_workflow.py`) accepts exactly `## Attempt 1 — APPROVE`.

On 2026-10-11, consumer project A integrated `F2-TOKENS-001` (`be74ae7`) after a
review headed `## Attempt 1 — 2026-10-11 — APPROVE`. The pattern did not match,
so `integrate stage` returned `REVIEW_PENDING`. `meridian worktree advance`
did not treat that as a stop and went on through finalize, push, and cleanup.
The code reached `main`, and the queue row stayed `QUEUED`. The console then
offered the task as ready, and it was prepared again 19 minutes later.
`F2-TILE-001` had failed the same way and was repaired by hand (`5234bf0`).
Of 183 attempt headings in consumer project A's review records, only 18 match the
pattern.

Two weaknesses are involved, and a more tolerant pattern would fix neither:

1. **Acceptance is inferred from prose.** Any wording the parser does not
   expect changes the decision. A stricter or looser parser only moves the
   boundary.
2. **An approval is not bound to the approved code.** Nothing proves that the
   commit being integrated is the commit the reviewer approved. consumer project A
   reviewers check by hand that "the intervening commit changes only the task
   record and the handoff", and write the result into prose.

`docs/ADR_STOPS_AND_DENIALS.md` also requires every gate to be backed and
never silent. A `REVIEW_PENDING` that integrates anyway breaks both rules.

## Decision

### 1. One machine-readable state file per task

The state of every task is a tracked JSON file,
`.meridian/tasks/<TASK-ID>.json`, validated by a schema in `schemas/`:

```json
{
  "version": 1,
  "task_id": "F2-TOKENS-001",
  "workflow": "governed-sdd",
  "status": "ACCEPTED",
  "review": {
    "required": true,
    "verdict": "APPROVE",
    "attempt": 1,
    "reviewed_commit": "<full SHA>",
    "approved_by": "reviewer"
  },
  "transitions": [
    {"from": "QUEUED", "to": "IN_PROGRESS", "commit": "<full SHA>", "at": "<ISO-8601 UTC>"},
    {"from": "IN_PROGRESS", "to": "READY_FOR_REVIEW", "commit": "<full SHA>", "at": "<ISO-8601 UTC>"},
    {"from": "READY_FOR_REVIEW", "to": "ACCEPTED", "commit": "<full SHA>", "at": "<ISO-8601 UTC>"}
  ]
}
```

- The file is the only source of truth for status and review verdict. The
  queue cell, the record's `Status:` field, and the review record's headings
  stay for human readers. No gate reads them to decide.
- There is one file per task, so concurrent tasks never edit the same state
  file. Each task branch may write its own state file, in addition to its
  task record, the record's exact archive, and its handoff. Governance-file
  ownership is otherwise unchanged.
- The file is tracked, not stored under the Git common directory, so it is
  durable, shared by every clone, reviewed with the diff, and visible in
  history.
- Status values keep the existing vocabulary: Governed SDD uses `QUEUED`,
  `IN_PROGRESS`, `CHANGES_REQUESTED`, `READY_FOR_REVIEW`, and `ACCEPTED`, and
  SPIKE tasks use `ANSWERED` and `INCONCLUSIVE`. Lean Delivery uses `QUEUED`
  and `DONE`, with in-progress state still derived from the worktree.

### 2. State changes only through commands that enforce a state machine

- `meridian task transition <TASK-ID> <STATUS>` applies one transition that
  the workflow's state machine allows, and records the current `HEAD`.
- `meridian review verdict <TASK-ID> APPROVE|CHANGES_REQUESTED|BLOCKED`
  records a verdict with `reviewed_commit` set to the task branch `HEAD`, and
  applies its transition: `APPROVE` gives `ACCEPTED`, `CHANGES_REQUESTED`
  gives `CHANGES_REQUESTED`.
- `Accept <TASK-ID>` becomes `meridian review verdict <TASK-ID> APPROVE
  --owner`, recorded with `approved_by: "owner"`.
- A transition that the state machine does not allow, such as `QUEUED` to
  `ACCEPTED`, is refused with a coded stop and changes nothing.
- The commands also update the human-readable projections they own, the
  record's `Status:` field and the review attempt heading, so prose and state
  do not diverge in routine use.

### 3. An approval is bound to the approved code

For a task whose review is required, `integrate stage` integrates only when
all of the following hold, checked from the state file and Git alone:
1. the state file is valid and its `status` is `ACCEPTED`;
2. `review.verdict` is `APPROVE`;
3. `review.reviewed_commit` is an ancestor of the task branch `HEAD`;
4. `git diff --name-only <reviewed_commit> <HEAD>` names only the task's own
   governance paths: its record or exact archive, its handoff, its review
   record, its state file, and the canonical execution-evidence ledger.

Any code change after the approval therefore invalidates it without human
judgment. SPIKE and review-not-required tasks skip conditions 2 to 4. Their
`status` must still be the terminal value that the state machine requires.

### 4. Projections, never inputs

- `integrate stage` writes the queue `Status` cell from the state file on the
  candidate tree, so the queue and the state cannot disagree after
  integration.
- The console reads state files first. It falls back to the queue only for
  tasks that have no state file, and it labels them `legacy`.
- `meridian audit` reports any difference between a state file and its
  projections as an advisory. It never repairs the prose by inference.

### 5. Coded, satisfiable stops; no silent pass

New stop codes, all of class `tool` and registered in
`capabilities/stop-codes-v1.json`:

| Code | Condition | Resume |
|------|-----------|--------|
| `TASK_STATE_MISSING` | a task being integrated has no state file | `meridian task state import <TASK-ID>` |
| `TASK_STATE_INVALID` | schema failure or an impossible transition history | name the field; fix with `meridian task transition` |
| `REVIEW_NOT_APPROVED` | review required, verdict absent or not `APPROVE` | `meridian review verdict <TASK-ID> …` |
| `REVIEW_STALE` | code changed after `reviewed_commit` | review again, then `meridian review verdict` |

Every check runs before the lease and the merge. `REVIEW_PENDING` is retired
as a non-blocking result: `integrate stage` either completes the row or
stops. `meridian worktree advance` reports these stops like any other.

### 6. Adoption without a silent text fallback

- Tasks already terminal need no state file. They are never integrated again.
- `meridian task state import [<TASK-ID>…]` creates state files for open
  tasks from their current queue and record text. It is an explicit command:
  it prints every file it would write and the evidence it read, and writes
  only with `--apply`. Nothing reads prose implicitly at integration time.
- After a project adopts this change, a task without a state file stops with
  `TASK_STATE_MISSING`. It is never integrated from text.

### 7. Growth and read cost

A project gains one state file of about 1 KB per task created after adoption.
Terminal tasks from before adoption get none. consumer project A, measured on
2026-10-11, has 333 task records, 146 review records, 159 handoffs, and a
97 KB queue, so a state file adds one small file to the three that each task
already has. The file count is not the cost to control. Agent context and
full-directory scans are, so:

- State files are never part of an agent's startup read set and are excluded
  from `meridian context size` and from any document an agent is told to
  read. Only Meridian commands read them.
- Gates and the console open a state file by task ID. The console reads only
  the files of rows in the active queue, never the whole `.meridian/tasks/`
  directory, so its cost grows with open tasks, not with project history.
  Only `meridian audit`, an explicit full check, enumerates the directory.
- Compaction is deferred. If measurement shows it is needed, `integrate
  stage` may later fold the state files of a closed queue phase into one
  schema-valid `.meridian/tasks/archive/<phase>.json` at the same moment that
  it archives the phase. That is safe because integration is serialized and
  no gate reads terminal state to decide. It is adopted only through a
  separate decision, based on a measured threshold such as more than 500
  active state files, not built in advance.

### 8. Queue archival from task state

*Amendment 1, proposed 2026-10-13, accepted 2026-10-14. It answers GitHub issue #2.*

Queue archival still decides from table text. Only `###` sections are
candidates, and every row's status cell must be a recognized terminal token.
consumer project A groups its tasks under `##` sections, so its queue (about 97 KB)
never shrinks. A section that holds an `INCONCLUSIVE` spike never closes.
This is the same weakness Decision 1 removed from acceptance, and it is
removed the same way:

- A queue section is archivable when every task row in it has a state file
  whose `status` is terminal for its workflow:
  - Governed SDD: `ACCEPTED`, `ANSWERED`, or `INCONCLUSIVE`;
  - Lean Delivery: `DONE`.
  `INCONCLUSIVE` closes its section. Whether it satisfies a dependency is a
  separate rule, and this amendment does not change it.
- A section ends at the next heading of the same or a higher level, and
  nested headings belong to it, as today. Its heading level no longer
  restricts candidacy. Table shape, column order, and status-cell wording are
  not read for the decision.
- A row without a state file uses the existing conservative rule, so legacy
  sections keep today's behavior. To make legacy sections archivable by state,
  `meridian task state import --include-terminal` creates state files for
  terminal tasks from their current text. It is explicit and shows what it
  would write, like Decision 6, and never runs implicitly during integration.
- `integrate stage` reports every section it archives and every section it
  retains, with the reason and the open or legacy rows. It never skips a
  section silently.

## Consequences

- A task is accepted because its state says `ACCEPTED` and Git proves that
  the approved commit is the integrated code. No heading wording, date, or
  table shape can change that decision.
- Review records become free-form evidence. Their format no longer matters to
  any gate.
- The reviewer's manual "intervening commit" check becomes automatic.
- The managed review procedure, the closure text, and `Accept <TASK-ID>`
  change to name the commands. This makes the release template-changing, so
  it needs a migration and upgrade notes.
- Each task gains one small tracked file. Archiving the record does not move
  it.
- Limitation: the commands cannot prove who ran them. That the reviewer is
  not the implementer remains a process rule, because agent sessions have no
  verifiable identity. The state also cannot detect a hand edit that produces
  a valid file. It guarantees determinism and binding to code, not
  authentication.

## Rejected alternatives

| Alternative | Reason rejected |
|-------------|-----------------|
| A more tolerant heading parser | It still decides from prose, so the next unexpected wording fails again, silently or not. |
| Structured front matter inside the Markdown records | It is still hand-edited text in a free-form file, mixed with prose, and easy to break with an edit nobody notices. |
| State under the Git common directory | It is untracked, so it is lost in a fresh clone and invisible to review and history. Approval must travel with the code. |
| One central state file for all tasks | Concurrent tasks would edit the same file and create the integration conflicts that per-task ownership avoids. |
| Cryptographic signatures on verdicts | Agents have no verifiable identity to sign with. It would add complexity without a real guarantee. |

## Rollout Plan

1. Accept this ADR.
2. Schema, state machines for both workflows, `meridian task transition`,
   `meridian review verdict` (with `--owner`), and the four stop codes. CLI
   only.
3. The `integrate stage` gate (Decision 3), the removal of the non-blocking
   `REVIEW_PENDING`, and the queue projection. CLI only.
4. Console and `audit` read state files. CLI only.
5. `meridian task state import`, the managed review, closure, and `Accept`
   text, the governance-file ownership addition, and a migration with upgrade
   notes. Template-changing.
6. consumer project A and consumer project B adopt through `upgrade` and `task state import`.
7. Amendment 1 (Decision 8), accepted on 2026-10-14: archival from task state and
   `task state import --include-terminal` in the CLI, plus the archival rule
   in the managed `docs/WORKTREE_LIFECYCLE.md` copies (`worktree-lifecycle`),
   which makes it template-changing.

## Out of Scope

This ADR does not:
- authenticate reviewers;
- rewrite historical task, review, or queue records;
- change the queue's Markdown format;
- change Lean Delivery's derived in-progress state;
- replace the lifecycle files under the Git common directory, which describe
  local worktrees and not acceptance.
