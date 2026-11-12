# ADR: Product direction toward 1.0

Status: Accepted

*Accepted on 2026-11-12 by the developer.*

## Context

By November 2026 the spec-driven tools hold the upstream half of agentic development:

- **GitHub Spec Kit** (MIT) installs commands that make an agent write a spec, a plan
  and a task list before code. In 2026 it added:
  - a `converge` step that checks finished tasks against the spec;
  - drift detection;
  - a workflow engine;
  - tracker integrations (Linear, Jira, GitHub Projects);
  - a community extension catalog of more than 120 entries.

  It supports more than 30 agents. Reviewers note that its enforcement is by convention:
  specs are prose, and nothing measures what lands.
- **Kiro** is an IDE with a mandatory requirements, design and tasks flow, plus hooks and
  steering files.
- **BMAD** (v6) organizes persona-based agile roles into modules.
- **Superpowers** enforces test-driven development.
- **Agent OS** injects standards with no gate.
- **Task Master** keeps task memory across sessions.

None of them measures, integrates and lands a change with evidence. Cardine does. Its
weaknesses are:
- the upstream half, from an idea to tasks;
- the cost of adoption, with many concepts and stops that surprise a new user;
- distribution;
- evidence of its value.

The session of 2026-11-11 to 2026-11-12 showed the cost:
- tasks stalled after a policy change;
- CI that never started;
- a placeholder directory that made a landed task look open;
- `self-update` unable to find releases.

## Decision

**1. Position Cardine as the delivery layer, not as a spec tool.** Cardine is the gate
between an agent's change and `main`. It works with the developer's spec tool instead of
replacing it. The README leads with that, says when not to use Cardine, and compares
honestly.

**2. Simplify what a user must learn.**
- Four first-level concepts: task, run, review, landing. Contracts, receipts, leases and
  authority stay internal and appear only in messages that need an action.
- A policy change takes one guided step, not three commands.
- Every stop reads as what happened, plus the command that resumes. A troubleshooting
  guide collects the stops that users meet.
- User documentation is separate from design records.
- Small tasks use per-task `Options` (`review: not_required`, `ciBeforeLanding: false`),
  which already exist. They are documented as the quick path.

**3. Extend where it multiplies reach or proof.**
- Interoperate with Spec Kit: import its tasks as Cardine records, and publish Cardine
  as a Spec Kit extension.
- Teams: the forge verdict and its `cardine run` integration
  (`docs/ADR_REVIEW_VERDICT_SOURCES.md`, work items 4 and 5).
- More reviewer hosts with headless read-only modes, after their probes.
- Per-task reports and project metrics, which serve both audit and proof.
- An optional test gate for fix tasks: a test that fails before the change and passes
  after it, measured by the engine.

**4. Prove the value with numbers.** Run the benchmark of
`docs/BENCHMARK_PROTOCOL.md` and publish its result.

## Work items

They are listed in order. A **task** is ready to plan now, a **spike** decides a design
first, and **later** waits for an earlier item.

1. **Task:** README and positioning (decision 1).
2. **Task:** troubleshooting guide (decision 2).
3. **Task:** policy change in one step: `cardine authorize` offers to refresh the
   contracts of queued tasks (decision 2).
4. **Spike:** split user documentation from design records. It inventories the files,
   the links and the tests that name them, and proposes the moves (decision 2).
5. **Spike:** Spec Kit interoperability. It covers:
   - the `tasks.md` format, and the mapping to a Cardine record;
   - the extension catalog requirements;
   - what `converge` can read from Cardine (decision 3).
6. **Later, after 5:** `cardine task import`, and the Spec Kit extension package.
7. **Later, after 4:** the documentation moves.
8. **Later:** per-task report and project metrics. A spike first.
9. **Later:** forge verdict and run integration, as work items 4 and 5 of the verdict
   sources ADR.
10. **Later:** an optional test gate for fix tasks. A spike first.
11. **Later:** more reviewer hosts, each after a probe like
    `docs/HOST_CAPABILITY_CONTRACT.md` records for Claude Code and Codex.
12. **Developer:** run the benchmark and publish its result, and record a short demo of
    a task going from `Proceed with` to `main`.

## Consequences

- The README and the troubleshooting guide change first: they are cheap, and they shape
  every first impression.
- Interoperating with Spec Kit trades a competing upstream for a distribution channel.
  Cardine depends on Spec Kit's task format, so the import is versioned and tolerant.
- Simplifying hides concepts; it does not remove guarantees. No gate is relaxed by this
  ADR.
- Work items 8 to 12 are not scheduled. Each is planned when the previous items land.
