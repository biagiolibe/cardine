# Task 116 — Plan the host integration (work item 9)

> **ID**: `116`
> **Category**: Architecture
> **Priority**: 🔴 P1
> **Estimate**: ~3h
> **Assigned to**: unassigned
> **Session**: Work item 9 planning, 2026-10-27
> **Origin**: maintenance

## Objective

Write `docs/HOST_INTEGRATION_PLAN.md`, the plan for work item 9 of
`docs/ADR_CARDINE_1_0.md`: setup and doctor for Claude Code and Codex, two
skills, user-level hooks with one Python implementation each, Cardine names
for every host file, a per-turn briefing that prints only the status of work
item 7, and the host permissions of decision 14 rule 2. The plan fixes the
target, the inventory to replace, and an ordered table of rows small enough to
implement one at a time; no code changes in this task.

## Acceptance Criteria

- [ ] `docs/HOST_INTEGRATION_PLAN.md` exists, in English, and contains the
  sections below.
  - **Inventory.** Every host-facing file the product ships or writes today,
    each with its owning module, whether it carries a Meridian name, and what
    replaces or removes it: the plugin's `commands/`, `skills/`, `hooks/` and
    `.claude-plugin/` files; host routers in `templates/`; the Claude
    allowlist and denylist of `src/cardine/hosts/claude.py`; the Codex rules,
    profile, and probes of `src/cardine/hosts/codex.py` and
    `src/cardine/hosts/setup.py`; setup and doctor; and the launch adapters of
    `src/cardine/hosts/launch.py` (task 102).
  - **Target.** The Cardine names of every host file; the two skills and what
    each one routes; the user-level hooks, each with one Python
    implementation; the per-turn briefing, which prints the status that work
    item 7 generates and computes no task state of its own.
  - **Host permissions.** For each host: the deny rules for agent writes to
    task state and receipt paths and for the developer-only commands; the
    distinct implementer and reviewer profiles that the launch adapters
    select; what each host can enforce and what stays under the declared limit
    of decision 14 rule 2. Doctor proves an installed rule by asking the host
    to evaluate a probe command, as the existing Codex probes do, never by
    reading rule text.
  - **Deferred items.** Each of the six work item 9 rows of `PROJECT_PLAN.md`
    quoted in the excerpt below is assigned to exactly one row of the table.
  - **Regression tests.** Which regression tests of work items 6 and 7 run
    against the hook output on both hosts, and with which fixtures.
  - **Rows.** An ordered table with one line per row in the form `| H<n><a> /
    <hours>h | scope | files | tests | interruption boundaries | depends on
    |`. Each row touches at most 10 files and one or two areas; a larger row
    is split. Every effect a row performs (setup apply, host file write, hook
    installation) lists its interruption boundaries for rule 4 of decision 14.
  - **Developer decisions.** Every choice the plan cannot settle from the ADR,
    such as which two skills ship, listed as a question with its options and
    consequences and left undecided.
- [ ] Every test the plan describes runs against disposable home directories.
  No row runs `setup --apply` against the real home directory, and this
  repository keeps running on the installed Meridian 1.4.1 until work item
  10.
- [ ] The plan checks its rows against `docs/RUN_ENGINE_PLAN.md` and
  `docs/HOST_CAPABILITY_CONTRACT.md` and names any conflict instead of
  resolving it silently.
- [ ] This task changes `docs/HOST_INTEGRATION_PLAN.md` only.
- [ ] The frozen files stay unchanged: `CLAUDE.md`, `AGENTS.md`,
  `PROJECT_WORKFLOW.md`, `LANGUAGE_POLICY.md`,
  `docs/COMPLETION_REPORT_TEMPLATE.md`, `docs/CONTEXT_BUDGET_POLICY.md`,
  `docs/EXECUTION_EVIDENCE_PROFILE.md`, `docs/WORKTREE_LIFECYCLE.md`,
  `.codex/hooks.json`, `.codex/rules/meridian.rules`, `hooks/hooks.json`,
  `hooks/queue-briefing.sh`, `hooks/read-guard.sh`, and the `meridian
  worktree` line of `.codex/rules/local.rules`. No task runs the
  checkout's `setup --apply` against the real home directory or creates
  `.cardine/` in this repository.
- [ ] `.meridian/` is unchanged, except `.meridian/tasks/116.json`, which only
  the installed `meridian task close 116` writes.
- [ ] Every command under Validation passes.

## Relevant Files

| File | Role |
|------|------|
| `docs/HOST_INTEGRATION_PLAN.md` | The plan this task writes. |
| `docs/HOST_CAPABILITY_CONTRACT.md` | The current host contract. |
| `src/cardine/hosts/setup.py`, `src/cardine/hosts/codex.py`, `src/cardine/hosts/claude.py`, `src/cardine/hosts/launch.py` | Setup, doctor, host rules, probes, and launch adapters. |
| `commands/`, `skills/`, `hooks/`, `.claude-plugin/` | The plugin files to inventory. |

## Authority excerpt

The parts of the plan and inventories this task needs, extracted from the
files on `main` when the record was written, so that the task reads them here
instead of the whole documents:

> From `docs/ADR_CARDINE_1_0.md`, section "Work items to 0.9", item 9:
>
> 9. Hosts: setup and doctor for Claude Code and Codex, two skills, user-level
>    hooks, with one Python implementation of each hook (decision 7). The
>    skills, slash commands, plugin, and Codex rules file and profile are
>    created under Cardine names, replacing the Meridian-named ones. The per-turn queue briefing is one Python implementation that
>    prints the status that work item 7 generates. It computes no task state of
>    its own. The regression tests of work items 6 and 7 run against the hook
>    output on both hosts.
>
> From `docs/ADR_CARDINE_1_0.md`, section "14. Robust against weak and strong agents", item 2:
>
> 2. **Nothing to forge, within the host boundary.** Every artifact a gate
>    trusts is written by Cardine. A file an agent writes on the task branch,
>    such as a state file, an evidence file, the project configuration, or the
>    contract snapshot, never changes a gate's outcome. This extends decision
>    13 from text to files. The boundary has three layers:
>    - **Receipts.** Every Cardine write is bound by an operation receipt to
>      its inputs and outputs. A gate rejects an artifact that no receipt
>      covers or that differs from its receipt, which catches an agent's
>      honest mistake, such as the hand-written Contoso state, and any
>      incoherent edit.
>    - **Host permissions.** The host refuses the shortcuts before they
>      happen. Host rules deny agents writes to the state and receipt paths
>      and the developer-only commands, such as recording a verdict as the
>      developer or pushing `main` outside integration. The engine launches
>      the implementer and the reviewer with distinct host profiles, so an
>      implementer cannot approve its own work. Work item 9 installs these
>      rules on both hosts.
>    - **Declared limit.** An agent runs as the developer's user, so a
>      receipt or hash Cardine writes can be rewritten by an agent that
>      deliberately bypasses the host permissions, for example through
>      another host launched with a different profile. Cardine does not claim
>      authenticity against that agent, and never presents a same-user
>      receipt or hash as proof of authorship. A protected signer outside the
>      agent's reach (a separate user, a service, or a key that needs the
>      developer's presence) can later sign the same receipts; it is not part
>      of 1.0.
>
>    The installation surface (the manifest, marker baselines, and capability
>    evidence) is outside this boundary until after 1.0. Those files describe
>    the installed templates and do not decide whether a task lands.
>
> From `PROJECT_PLAN.md`, row Remove the budget lines:
>
> | Remove the budget lines from the per-turn queue briefing | Work item 9 | `tasks/handoffs/035.md` |
>
> From `PROJECT_PLAN.md`, row The queue briefing drops:
>
> | The queue briefing drops every queued task when a title contains an apostrophe (`xargs: unterminated quote`); add a regression test | Work item 9 | Coordinator finding, 2026-10-19 |
>
> From `PROJECT_PLAN.md`, row Add `cardine init`:
>
> | Add `cardine init` (decision 8), replacing the copy steps of the init slash command that task 055 rewrites | Work item 9 | Task 055 record |
>
> From `PROJECT_PLAN.md`, row Remove this repository's own scripts:
>
> | Remove this repository's own scripts (`python3 scripts/check_repository.py`, `python3 scripts/run_tests.py --parallel`, `python3 -m unittest discover -s tests`) from the product's Claude allowlist (`src/cardine/hosts/claude.py`) and Codex rule probes (`src/cardine/hosts/setup.py`). Cardine ships rules only for its own commands, the lifecycle's Git commands, and the deny list; an adopter's test and validation commands stay in that project's own host configuration | Work item 9 | Coordinator finding, 2026-10-24 |
>
> From `PROJECT_PLAN.md`, row Defer the CLI's heavy imports:
>
> | Defer the CLI's heavy imports (`http.client`, `ssl`, `email`, used only by self-update and release) to the commands that need them; startup is 110 ms against 24 ms for bare Python, and per-turn hooks pay it | Work item 9 | Coordinator code analysis, 2026-10-25 |
>
> From `PROJECT_PLAN.md`, row The governed skills route:
>
> | The governed skills route `Accept` to `docs/workflows/LIFECYCLE.md`, which the single template set no longer installs | Work item 9 | `tasks/handoffs/055.md` |
>
## Technical Context

- The row table follows the coordinator's planning rule of 2026-10-27: rows
  are sized by the files they touch, not by hours, so each implementation task
  stays small in context. The coordinator generates one task record per row
  and extracts each row's line from the table into that record.
- The evaluation scenarios of decision 14 rule 5 run after work item 9, on the
  final hosts; this plan does not schedule them.
- If `worktree advance` stops because another task holds the integration lease
  in the primary checkout, that is not a decision for the developer: wait
  until the other integration finalizes or aborts, then rerun the same
  `advance` command.

## Out of scope

Implementing any row; the conversion of work item 10; the evaluation runs of
rule 5; the installation surface, deferred after 1.0.

## Dependencies

- **Depends on**: 115
- **Blocks**: the work item 9 task records, written from the plan's row table

## Developer decisions given in advance

The developer records these decisions in the task contract, so that they
hold however the task is launched, including a bare `Proceed with <TASK-ID>`
from the project console (ADR decision 12). None of these situations needs a
new decision from the developer. After fixing a failure, continue with
revalidation in the same turn; do not stop to report the fix.

- A required command that exits non-zero because of a precondition the agent
  can satisfy (command order, an uncommitted worktree, a missing argument):
  satisfy it and run the command again, once.
- A validation failure caused by this task's own changes, including a name
  collision, a stale reference, a broken link, or a test expectation that the
  task made obsolete: fix it and revalidate, at most 3 counted attempts. A
  test that fails once and passes on an identical unchanged rerun is
  intermittent, recorded in the handoff, and does not count. Only after 3
  counted failures stop with `BLOCKED VALIDATION_FAILED` and a summary of the
  failures.
- A counted attempt is one run of the whole Validation section on a
  committed implementation that the agent considers complete. Test runs
  during implementation are development, not attempts, however many fail.
  An unfinished implementation is never a reason to stop: finish it first.
- A `BLOCKED <CODE>` from a Meridian command whose entry in
  `capabilities/stop-codes-v1.json` of the primary checkout's `main` has
  `human_decision: false`: run the command the stop names, once. If it stops
  again with the same code, stop.
- The deny list, `RULE_CONFLICT`, every guardrail, and a change of scope
  remain stops.

## Validation

- `python3 scripts/check_repository.py`
- `meridian profile doctor meridian-self-hosting --project .`
- `meridian audit --project . --mode lean-delivery --ci-profile meridian-self-hosting`
- `git diff --check`
- `python3 -m unittest tests.test_no_meridian_identifiers`

This task changes documentation only. Under the validation-scoping rule of
`PROJECT_WORKFLOW.md`, it skips the test suites and records that skip in the
handoff. It still runs the identifier guard, which scans documentation.
