# Task 029 — Make agents stop only for decisions that need a person

> **ID**: `029`
> **Category**: Workflow
> **Priority**: 🔴 P1
> **Estimate**: ~3h
> **Assigned to**: unassigned
> **Session**: Stop policy review, 2026-10-18
> **Origin**: friction

## Objective

Apply ADR decision 12 to the agent instructions that Cardine ships in its
templates. Today the managed `git-workflow` text tells an agent to stop for
any of these:

- every `BLOCKED <CODE>` line;
- every non-zero exit of a required command;
- every unmet acceptance criterion.

In the first 22 tasks this produced 7 stops, and none of them needed a new
decision from the developer. After this task the product's instructions let
an agent stop only for a guardrail. The agent continues through recoverable
states and iterates on failing work within the validation retry limit.

The task also carries the managed Resume text that task 028 deferred, which
names `worktree check --resume`.

This task changes the templates only. This repository's own `CLAUDE.md`,
`AGENTS.md`, `PROJECT_WORKFLOW.md`, and `.meridian/` stay as they are. The
installed Meridian 1.4.0 runs this repository's lifecycle: it has no `check
--resume`, and the manifest holds whole-file digests. A probe on 2026-10-18
showed two things:
- an edit outside the markers in `CLAUDE.md` makes the self-hosting doctor
  and audit fail;
- the checkout's `upgrade --apply` rewrites the digests of unchanged files
  and deletes `.meridian/baselines/1.4.0`.

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
- [ ] The managed `bounded-worktree-lifecycle` text in both
  `templates/workflows/*/PROJECT_WORKFLOW.md` describes the Resume that task
  028 implemented: run `meridian worktree check <task-id> --resume`, accept
  `status: ready-dirty`, read the status and the diff, then run `execution
  start --resume`. It never writes a bare `BLOCKED` without a registered
  code, so the repository check passes.
- [ ] The text tells the agent where to read a code's class. No CLI command
  shows a registry entry today, so the text names
  `capabilities/stop-codes-v1.json` in the framework, or a new read-only
  command if the task adds one. The handoff names the choice.
- [ ] The registry gains `VALIDATION_RETRY_LIMIT` with `human_decision:
  true`. `VALIDATION_FAILED` keeps `human_decision: false`: a single failed
  validation is failing work, not a stop. Every code that the new text names
  exists in the registry.
- [ ] Template changes follow the pre-1.0 rule of task 031: the capability
  version is bumped and the marker baseline is rewritten. The task adds no
  migration and does not change `VERSION`, `.claude-plugin/plugin.json`, or
  `releases/`.
- [ ] This repository's own `CLAUDE.md`, `AGENTS.md`, `PROJECT_WORKFLOW.md`,
  and `.meridian/` are unchanged, and the checkout's `upgrade` is not run on
  this repository.
- [ ] A test proves that every code the new text names as a guardrail has
  `human_decision: true`, and that the text names no code missing from the
  registry.
- [ ] Every command under Validation passes.

## Relevant Files

| File | Role |
|------|------|
| `templates/workflows/lean-delivery/CLAUDE.md`, `AGENTS.md`, `PROJECT_WORKFLOW.md` | Managed stop and Resume text. |
| `templates/workflows/governed-sdd/` | Governed SDD stop and Resume text. |
| `capabilities/stop-codes-v1.json`, `capabilities/marker-baselines.json` | Registry and marker baseline. |
| `docs/ADR_CARDINE_1_0.md` | Decision 12, the authority. |

## Technical Context

- Current text: "When a gate fails, stop once with `BLOCKED <CODE>` and the
  resume command", and "A stop is valid only when it is backed by a
  `BLOCKED <CODE>` line from a Meridian command, a non-zero exit of a
  required command, an acceptance criterion you can name as unmet, or a
  judgment stop".
- On 2026-10-18 task 028 first changed the Resume text inside its own scope.
  In this repository's `PROJECT_WORKFLOW.md`, the phrase "without a
  `BLOCKED` line" failed the repository check. Without a migration, four
  historical upgrade tests failed. Tasks 032 and 033 remove those tests, so
  this task runs after them.
- Task 030 audits whether each `human_decision` value is right.

## Out of scope

This repository's own managed files and `.meridian/`, the `cardine run`
engine (work item 8), and stop behavior in the commands themselves.

## Dependencies

- **Depends on**: 033
- **Blocks**: 034

## Validation

- `python3 scripts/check_repository.py`
- `python3 scripts/meridian.py --framework-root . profile doctor meridian-self-hosting --project .`
- `python3 scripts/meridian.py --framework-root . audit --project . --mode lean-delivery --ci-profile meridian-self-hosting`
- `python3 scripts/run_tests.py --parallel`
- `python3 scripts/run_tests.py --parallel --clean-clone`
- `git diff --check`

## Developer amendment — Resume, 2026-10-19

The developer authorized this bounded extension after the coordinator confirmed
that all 9 failures at `244d12b` were stale test expectations, not behavior defects:

> Developer amendment to the task scope (record it in the record and in the handoff, quoting this authorization):
> 1. `capabilities/markers-v1.json`: set `requiredVersion` to 15 for `git-workflow` and to 6 for `bounded-worktree-lifecycle` (the lowest version shipped between the two templates, the existing convention), as the task 031 rule in CONTRIBUTING.md requires. The coordinator has verified that check_repository, doctor, and the audit CI_GATE still pass.
> 2. You may edit these tests, only to remove the hard-coded marker versions:
>    - `tests/test_meridian_upgrade_lifecycle.py` (the 5 assertions on `git-workflow v14` / `bounded-worktree-lifecycle v7`) and `tests/test_template_marker_heading.py` (the `expected` dictionary): read the expected version from `capabilities/marker-baselines.json` for the template concerned, not from a literal.
>    - `tests/meridian_cli_support.py`, `configure_1_1_53_to_1_1_54_manual_proceed_upgrade`: make the `bounded-worktree-lifecycle` regex version-agnostic (`v\d+`), keeping the `assertNotEqual` checks.
>    - `tests/test_worktree_lifecycle.py`, `test_stop_registry_covers_closure_codes_and_names_real_tests`: add `VALIDATION_RETRY_LIMIT` to the matching groups (code set and `judgment` set).
>    Do not weaken any other assertion and do not delete tests.

The developer also authorized the following validation handling for this task:

> Validation: rerun the whole Validation section (clean-clone on the final commit). Apply the rule this task introduces: when a failure comes from this task's changes, fix it and revalidate, at most 3 counted attempts; a test that fails once and passes on an identical unchanged rerun is intermittent, recorded in the handoff, and does not count. Only after 3 counted failures stop with BLOCKED VALIDATION_FAILED and a summary.

Only installed `meridian` runs lifecycle commands; the task's doctor and audit
commands remain validation of the framework checkout. Never run upgrade on this
repository. The local managed configuration stays unchanged; `meridian task close`
owns the separately authorized task-state and archive records.
