# Governed workflow and execution evidence

```text
Project plan → architecture decisions → atomic task → implementation → independent review → acceptance/integration
                                                     ↖ requested changes ↙
```

The project keeps durable process artifacts close to the code:

```text
PROJECT_WORKFLOW.md             # Lifecycle, precedence, roles, and Git rules
AGENTS.md / CLAUDE.md           # Agent-specific project instructions
LANGUAGE_POLICY.md              # Persistent conversation language and English-only repository text
docs/ARCHITECTURE_DECISIONS.md  # Accepted architecture decisions
docs/CONTEXT_BUDGET_POLICY.md   # Task-first context policy
tasks/QUEUE.md                  # Canonical dependency and status queue
tasks/TASK-NNN.md               # One bounded unit of work
tasks/reviews/TASK-NNN.md       # Reviewer evidence and requested-change handoff
```

### Bounded exploration and durable evidence

For a focused source already named by a task, the worker reads it directly.
For broad or uncertain-yield research, the task instead records a bounded
question and the distilled answer. This preserves a small implementation
context without concealing the investigation from review:

```text
Declared task authority
        │
        ├─ targeted, named source ───────────────→ direct read
        │
        └─ broad or uncertain question
                    │
                    ▼
          bounded isolated exploration
          (question, scope, sources, finding)
                    │
                    ▼
          .meridian/execution-evidence.json
                    │
                    ▼
      completion handoff + ready-check cross-check
```

The worker or host used for the exploration is not normative. Delegating work
does not erase its declared investigation budget, and a completion report is
not accepted as a substitute for durable validation or exploration evidence.

### Task contract

A governed task declares:

- the decision or specification that authorizes it;
- its expected code surface and explicit non-goals;
- dependencies;
- `REQUIRED` or `NOT_REQUIRED` review policy;
- measurable acceptance criteria and validation commands.

The task is the agent’s initial navigation map. It reads its authority and expected code surface first, then widens context only when evidence is insufficient or a blocker requires it.

### Roles and integration

Meridian separates the roles that make a code change from those that accept it:

- The **tech designer** records decisions and creates scoped tasks.
- The **implementer** works on one task in a dedicated branch/worktree and validates it.
- The **reviewer-integrator** independently reviews required-review work in a fresh session, verifies the task branch is a fast-forward descendant of `main`, and integrates only after approval.

If the verdict is `CHANGES_REQUESTED`, the reviewer records prioritized,
file-or-command-backed findings in `tasks/reviews/<TASK-ID>.md`, returns the
task to `IN_PROGRESS`, and creates a local handoff commit. The implementer can
then simply run `Address review <TASK-ID>`: it resolves only the unchecked
findings, records resolution evidence, validates, and opens the next review
attempt. This keeps the chat as a notification channel instead of the system
of record.

### Governed execution evidence

For source/build tasks, the execution-evidence profile is resolved into the
task before implementation. This makes the task—not a separately remembered
policy document—the operational contract for validation, evidence budgets, and
the review handoff.

```text
Create or materially re-scope task
        |
        +-- declare authority, scope, acceptance criteria, budget caps,
        |   and named literal validation commands
        |
        +-- meridian execution contract <TASK-ID> --project .
              records the profile digest and resolved contract in the task
        |
meridian execution preflight <TASK-ID> --project .
        |
        +-- requires a current profile digest, executable task state,
        |   complete task contract, and matching task/queue state
        |
Implement and collect evidence
        |
        +-- meridian execution validate <TASK-ID> <validation-id>
        +-- meridian execution evidence <TASK-ID> diagnostic|expansions --gap <reason>
        +-- meridian execution evidence <TASK-ID> captures --gap <reason>
        |      --criterion <AC-ID> --artifact <absolute-path>
        |
Completion report
        |
meridian execution ready-check <TASK-ID> <report> --project .
        |
        +-- verifies preflight and structured handoff evidence
        |
READY_FOR_REVIEW --> independent review --> APPROVE --> ACCEPTED/integration
                    |                         |
                    +-- CHANGES_REQUESTED ----+--> IN_PROGRESS/remediation
```

The wrapper records validation exit statuses and budgeted evidence in
`.meridian/execution-evidence.json`; task-attempt counters live in
`.meridian/budget.json`. A project upgrades its templates before using these
gates, then backfills only non-terminal tasks with their resolved contracts.

For a fully delegated required-review task, `Run lifecycle <TASK-ID>` adds a
coordination-only agent that starts distinct implementer and reviewer sessions,
loops through the durable review record when changes are requested, and
integrates only after approval and all repository and forge gates. See
[lifecycle orchestration](../templates/workflows/governed-sdd/docs/LIFECYCLE_ORCHESTRATION.md).

This is a process boundary, not a claim that every project needs bureaucracy. Use Lean Delivery when the work is low-risk and reversible; use stronger gates when a mistake is expensive.


## Workflow boundaries

Each initialized project contains a `PROJECT_WORKFLOW.md` mode lock. Its local
workflow documents take precedence over global or remembered agent
instructions. An agent must not import Lean Delivery lifecycle rules into a
Governed SDD project, or governed branches and review gates into Lean Delivery.
If the local workflow documents cannot be read or conflict, agents stop with
`BLOCKED` before changing repository or Git state.

**SDD means spec-driven development:** before implementation, an agent receives an explicit, durable specification of the change—its authority, scope, constraints, acceptance criteria, and validation. In Meridian, a task file is that specification.

In governed SDD, low-risk documentation, mechanical configuration, scaffolding, and narrowly scoped tests may use the direct `QUEUED` → `IN_PROGRESS` → `ACCEPTED` path. Changes to domain rules, public APIs, dependencies, state transitions, persistence, deterministic behavior, security, or unresolved design decisions require review.

Only an `ACCEPTED` task satisfies another task's dependency.
