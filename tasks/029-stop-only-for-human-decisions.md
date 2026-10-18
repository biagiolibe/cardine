# Task 029 — Make agents stop only for decisions that need a person

> **ID**: `029`
> **Category**: Workflow
> **Priority**: 🔴 P1
> **Estimate**: ~3h
> **Assigned to**: unassigned
> **Session**: Stop policy review, 2026-10-18
> **Origin**: friction

## Objective

Apply ADR decision 12 to the operational instructions that Cardine still
inherits from Meridian. Today the managed `git-workflow` text tells an agent
to stop for any of these:

- every `BLOCKED <CODE>` line;
- every non-zero exit of a required command;
- every unmet acceptance criterion.

In the first 22 tasks this produced 7 stops, and none of them needed a new
decision from the developer. After this task an agent stops only for a
guardrail. It continues through recoverable states and iterates on failing
work within the validation retry limit.

## Acceptance Criteria

- [ ] The managed `git-workflow` text in
  `templates/workflows/lean-delivery/CLAUDE.md` and `AGENTS.md`, and the
  Governed SDD text that carries the same stop rules, state the three classes
  of decision 12:
  - **Guardrail.** Stop on a `BLOCKED <CODE>` whose registry entry has
    `human_decision: true`, on a denied action, and on a scope change.
  - **Recoverable state.** For a code without `human_decision`, run the
    command the stop names, in the same turn, and continue. If that command
    stops again with the same code, the stop becomes a `BLOCKED` for the
    person. The agent never runs a recovery twice.
  - **Failing work.** When validation fails, fix the task's own work and
    validate again. Rerun a failed validation once without changes. If the
    rerun passes, record the test as intermittent in the handoff, and the
    attempt does not count. After 3 consecutive counted failures, stop with
    `BLOCKED VALIDATION_RETRY_LIMIT` and a summary of the failures.
- [ ] The text keeps the deny list, the ban on writing false state to pass a
  gate, `RULE_CONFLICT`, and the rule that guidance no command backs is
  advice, word for word where they do not conflict with decision 12.
- [ ] The text tells the agent where to read a code's class. No CLI command
  shows a registry entry today, so the text names
  `capabilities/stop-codes-v1.json` in the framework, or a new read-only
  command if the task adds one. The handoff names the choice.
- [ ] The registry gains `VALIDATION_RETRY_LIMIT` with `human_decision:
  true`. `VALIDATION_FAILED` keeps `human_decision: false`: a single failed
  validation is failing work, not a stop. Every code that the new text names
  exists in the registry.
- [ ] The change is a capability version bump with a migration, as the
  repository checks require. `meridian upgrade` applies it to this
  repository's own `CLAUDE.md` and `AGENTS.md`, and the result is committed.
- [ ] A test proves that every code the new text names as a guardrail has
  `human_decision: true`, and that the text names no code missing from the
  registry.
- [ ] Every command under Validation passes.

## Relevant Files

| File | Role |
|------|------|
| `templates/workflows/lean-delivery/CLAUDE.md`, `AGENTS.md` | Managed `git-workflow` text with the stop rules. |
| `templates/workflows/governed-sdd/` | Governed SDD stop rules. |
| `capabilities/stop-codes-v1.json` | Registry with `human_decision`. |
| `capabilities/`, `migrations/` | Capability version and migration. |
| `CLAUDE.md`, `AGENTS.md` | This repository's own copies, updated through `meridian upgrade`. |
| `docs/ADR_CARDINE_1_0.md` | Decision 12, the authority. |

## Technical Context

- Current text: "When a gate fails, stop once with `BLOCKED <CODE>` and the
  resume command", and "A stop is valid only when it is backed by a
  `BLOCKED <CODE>` line from a Meridian command, a non-zero exit of a
  required command, an acceptance criterion you can name as unmet, or a
  judgment stop".
- The registry has 55 codes, and 14 of them have `human_decision: true`.
  Task 030 audits whether each value is right. Until then, the rule that a
  recovery stopping again with the same code becomes a stop for the person
  covers a code whose value is wrong.
- Task 028 removes the false `BLOCKED` for a dirty Resume in `worktree
  check`. Task 030 proves the recovery command of each recoverable code.

## Out of scope

The `cardine run` engine (work item 8), which applies decision 12 by
construction. Changes to stop behavior in the commands themselves.

## Dependencies

- **Depends on**: 028
- **Blocks**: none

## Validation

- `python3 scripts/check_repository.py`
- `python3 scripts/meridian.py --framework-root . profile doctor meridian-self-hosting --project .`
- `python3 scripts/meridian.py --framework-root . audit --project . --mode lean-delivery --ci-profile meridian-self-hosting`
- `python3 scripts/run_tests.py --parallel`
- `python3 scripts/run_tests.py --parallel --clean-clone`
- `git diff --check`
