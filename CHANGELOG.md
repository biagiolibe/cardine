# Changelog

All notable changes to Meridian are documented here. Versions before this file
existed are reconstructed from `migrations/*.json` and `VERSION`, which remain
the authoritative, machine-checked source of truth (`scripts/check_repository.py`
verifies the migration sequence is contiguous and ends at `VERSION`). This file
adds human-readable context on top of that record; it does not replace it.

Format loosely follows [Keep a Changelog](https://keepachangelog.com/); version
numbers are release versions, the `frameworkVersion` tracked in generated
projects' `.meridian/manifest.json`. The `workflowBaselineVersion` follows a
separate, slower cadence: it advances only in releases that ship a migration, so
a CLI-only release appears here without moving it. `releases/<version>.json`
records which release moved it.

## [Unreleased]


## [1.4.0]

Template-changing release: migration `070-worktree-template-delivery` delivers the 1.4.0 managed workflow changes.

### Added

- Experimental `meridian self-update --check` and `--apply` plan and update the running CLI checkout to a published release, with explicit tag rollback and guarded Git operations.
- Add developer-authorized `worktree prepare --new-attempt --reason` with a journaled reason and historical counters; show the current attempt in budget output and active queue briefings.

### Changed

- Install the CLI once at `~/.local/share/meridian` for every host, with persistent shell setup and aligned Claude Code plugin releases.

### Deprecated

- Meridian 1.4.0 is the last planned Meridian release. Meridian will be archived in favor of its successor, Cardine, a new project in the `biagiolibe/cardine` repository. Cardine starts at 1.0.0 and provides no `meridian` command alias. Until Cardine 1.0.0, Meridian 1.4.x receives fixes only for blocking defects. Projects stay on Meridian 1.4.x until they convert their open work to Cardine.

### Fixed

- Block release publication while changelog fragments remain and provide `changelog render --prepared --write` to merge them into an already-prepared release.
- Report the required Python version, detected version, and interpreter path before loading the CLI on Python older than 3.12.
- Governed tasks can be delivered again after committed handoff-only corrections,
  with a fresh review anchor and unchanged state transitions. Delivery preflight
  rejects missing or malformed `Current task commit` fields before delivery.
- Block task worktree re-preparation when the retired budget attempt has inherited spends, preserving its history.
- Run execution and task closure commands with an explicit task worktree from any directory. Wrong-project stops identify the caller, supplied project, and expected worktree and preserve the invocation in their recovery command. Document lifecycle command locations.
- Separate runnable candidate validation commands from required fragments in `worktree advance`, preserve fragment declarations, and propose complete setup commands.
- Release preparation and publish preflight reject a CLI-only release when
  templates changed since the previous release tag without a migration, naming
  the changed template files.

### Documentation

- Rewrite the README around one host-neutral description and a short task example; align plugin metadata and move operational detail into linked guides.
- Use the stable release ref in the quick start and document updates for both stable and tagged local framework checkouts, including release verification and session restart.

### Upgrade notes

- Run `meridian upgrade --apply` for migration `070-worktree-template-delivery`.
  Both workflows update `PROJECT_WORKFLOW.md` and `docs/WORKTREE_LIFECYCLE.md`;
  Governed SDD also updates `docs/COMPLETION_REPORT_TEMPLATE.md`. Adapted command
  location, budget-retirement, or handoff-correction text may conflict and need
  owner reconciliation. The managed capabilities are `worktree-command-locations`
  v1, `worktree-budget-retirement` v1, and `handoff-correction-redelivery` v1.
  No minimum framework or `protocolVersion` change.

## [1.3.0] - 2026-10-15

Template-changing release: atomic Lean task closure, the public surface and
stability promise, and bounded Codex command rules.

### Added

- `meridian task close <TASK-ID>` writes Lean DONE state, archives the exact record, and stages both without committing. Archived DONE Resume returns the next closure action.
- `meridian setup` plans and installs a bounded user-level Codex command rules block, preserves foreign rules, warns about broad approvals, and reports its state through `codex doctor`.

### Changed

- Release preparation enforces minimum version bumps from migrations and
  changelog fragment headings, including explicit version selections.

### Fixed

- Detect missing or non-terminal task state before advance starts integration, direct missing-state recovery to the registered task worktree, and allow state transition/import with records at their exact archive paths.
- Keep an empty task directory after worktree cleanup so Codex can launch its
  final Stop hook. Hook commands also tolerate an inherited deleted working
  directory. Document the primary project hook trust reused by linked worktrees.

### Documentation

- Publish the public surface classification and versioning and deprecation
  rules. The stable compatibility promise starts at 1.3.0.
- Declare the platform support matrix: macOS and Linux have CI coverage on
  Python 3.12, Windows is unsupported, and host integrations, clipboard access,
  and macOS iTerm2 agent launch are best-effort.
- Add security and community conduct policies, bug and feature request templates,
  and a pull request template with task, validation, and changelog guidance.

### Upgrade notes

- Run `meridian upgrade --apply` to install Lean `git-workflow` v14 and `bounded-worktree-lifecycle` v7 in `AGENTS.md`, `CLAUDE.md`, and `PROJECT_WORKFLOW.md`; both Lean skills now name `task close`. Adapted closure or Resume text may conflict. No minimum framework or protocolVersion change.

## [1.2.15]

Template-changing release: migration `068-adr-list-discovery` advances `workflowBaselineVersion` to `1.2.15`. Queue archival now decides from task state at any heading level, `meridian adr list` adds ADR discovery, and the project console launches agents without freezing and refreshes faster. The manifest shape and `protocolVersion` 2 are unchanged.

### Added

- `meridian adr list [--project <path>] [--status <value>] [--format text|json]` prints one line per ADR with its ID, title, and status, so an agent can discover the ADR that governs a question without opening the whole log. It resolves entries exactly as `meridian adr show` does and reports a malformed or duplicate entry as a warning on stderr.

### Changed

- The project console refreshes faster: a snapshot reads the registered worktrees once, reuses its resolved task identities for closure and lifecycle lookups, and skips the delivery check of an unchanged review-ready task until its worktree, handoff, or task state changes.
- Queue archival decides from task state: a section closes when every task row in it has a state file whose status is terminal (`DONE` in Lean Delivery; `ACCEPTED`, `ANSWERED`, or `INCONCLUSIVE` in Governed SDD), at any heading level and whatever the table shape. A row without a state file keeps the `###` table rule, and a mixed section archives only when both rules agree. `INCONCLUSIVE` still does not satisfy a dependency.
- `integrate stage` reports every section it archives and every section it retains, with the reason and the open or legacy rows.
- `meridian task state import --include-terminal` previews, and with `--apply` writes, state for terminal legacy tasks from their current texts; it stops with `TASK_STATE_INVALID` when the texts disagree and never creates an approval.

### Fixed

- Pressing `1` or `2` in the project console no longer freezes the interface: the launch is revalidated against the selected task only and started on a background thread, with a `Launching…` notice and a success or failure message when it finishes.

### Upgrade notes

- Affected capabilities: `worktree-lifecycle` v6 (both workflows); in Governed SDD also `minimal-read-only-status` v3 and `bounded-context-readers` v2. Managed paths: `docs/WORKTREE_LIFECYCLE.md`, and in Governed SDD `docs/CONTEXT_BUDGET_POLICY.md` and `docs/workflows/{IMPLEMENTATION,REMEDIATION,REVIEW}.md`.
- Required action: run `meridian upgrade --check`, then `meridian upgrade --apply` to receive migration `068-adr-list-discovery`. To let sections of terminal legacy tasks archive, run `meridian task state import --include-terminal --project <path> --format json`, review the proposal, and repeat with `--apply`. The import never creates an approval and stops with `TASK_STATE_INVALID` when texts disagree.
- Likely conflict areas for adapted projects: adapted archival text in `docs/WORKTREE_LIFECYCLE.md` and adapted ADR-discovery guidance in the Governed SDD context policy and workflow documents. Resolve them in place and keep protected markers intact.
- No minimum framework or `protocolVersion` change; Python 3.12 remains the minimum.

## [1.2.14]

Template-changing release: migration `067-execution-boundaries` advances `workflowBaselineVersion` to `1.2.14` and delivers explicit execution-start and final review-delivery boundaries. The manifest shape and `protocolVersion` 2 are unchanged.

### Added

- `meridian execution start` verifies the canonical worktree and execution contract before recording Governed SDD `IN_PROGRESS`; repeated starts and explicit Resume preserve the first start event. Lean Delivery retains worktree-derived progress without adding a new machine state.
- `meridian execution deliver` checks committed implementation, source-bound validation evidence, and the final committed handoff, then commits only task state and its owned projection as the final review-delivery step.

### Changed

- The console offers review only for clean, committed, valid delivery. Uncommitted `READY_FOR_REVIEW` or later changes display pending delivery/changes without rewriting the authoritative lifecycle status.
- Manual, console-launched, and orchestrated workers follow the same start and delivery ordering. Read-only review/status requests do not start implementation; no advisor-call interception or agent-process monitoring is introduced.

### Upgrade notes

- Update the installed framework to v1.2.14, preview `meridian upgrade --check`, then run `meridian upgrade --apply` on a dedicated project upgrade branch. Resolve reported conflicts in adapted start/delivery text, validate and integrate the upgrade, then restart agent sessions.
- Affected capabilities: Governed SDD `bounded-worktree-lifecycle` v5, `execution-command-gate` v4, `lifecycle-orchestration` v12, `review-remediation-record` v6, `task-worktree-boundary` v10, `task-worktree-integration` v7, `task-worktree-review-procedure` v13, and `task-blueprint` v18; Lean Delivery `bounded-worktree-lifecycle` v6; and `worktree-lifecycle` v5 in both modes. Workflow skills also carry the execution-boundary instructions.
- Managed paths: `PROJECT_WORKFLOW.md`, `docs/WORKTREE_LIFECYCLE.md`, `docs/LIFECYCLE_ORCHESTRATION.md`, `docs/PULL_REQUEST_POLICY.md`, `docs/REVIEW_RECORD_TEMPLATE.md`, `tasks/TASK_BLUEPRINT.md`, `docs/workflows/IMPLEMENTATION.md`, `docs/workflows/REVIEW.md`, `docs/workflows/REMEDIATION.md`, and `.codex/rules/meridian.rules`, as applicable to the selected workflow. Project-owned policy remains outside the managed changes.
- After prepare and worktree check, run `meridian execution start <TASK-ID> --project <task-worktree>` before substantive analysis, advisor consultation, or implementation. Only explicitly authorized Resume adds `--resume`, after status/diff inspection and sole-writer confirmation; it preserves the original start event.
- For Review-required Governed tasks, finish and commit implementation, validation evidence, and the final handoff before `meridian execution deliver <TASK-ID> --project <task-worktree>`. Delivery must be the last implementer write. Pending delivery/changes cannot launch review; the reviewer still performs its independent preflight. SPIKE and review-not-required closure retain their existing lifecycles.
- No manifest protocol upgrade or new historical-state import is required by this migration. `protocolVersion` remains 2; use Meridian 1.2.14 for the new commands. Existing task-state adoption requirements still apply to open legacy tasks without state.

## [1.2.13]

Template-changing release: migration `066-machine-task-state-adoption` advances `workflowBaselineVersion` to `1.2.13` and delivers command-owned task transitions and commit-bound review verdicts in managed procedures. Open legacy tasks can explicitly import tracked machine state. The manifest shape and `protocolVersion` 2 are unchanged.

### Added

- `upgrade --check` and `audit` report advisory locations and manual remedies for retired framework text left outside managed markers.
- `meridian task transition` creates schema-validated tracked task state and enforces Lean Delivery, Governed SDD, and SPIKE transition histories.
- `meridian review verdict` records commit-bound review verdicts and atomic task-state transitions, with owner approvals and free-form review bodies through `--body`.

### Changed

- `meridian worktree integrate stage` gates adopted projects on terminal task state and commit-bound approval before leasing or merging, projects queue status from that state, and blocks missing or stale reviews. Legacy projects retain the labeled prose fallback.
- The project console reads authoritative task status and review verdict from machine state, labels prose-only tasks as legacy, and shows invalid state as a per-task coded error. `meridian audit` reports queue and record status drift without modifying files.
- Open legacy tasks can explicitly import tracked machine state with queue, record, and review evidence. Managed procedures use `meridian task transition` and `meridian review verdict` for status and commit-bound verdicts; review headings are human-readable only. Migration 066 delivers the updated capabilities in 1.2.13.

### Upgrade notes

- Update the installed framework to v1.2.13, preview `meridian upgrade --check`, then run `meridian upgrade --apply` on a dedicated project upgrade branch. Validate and integrate the upgrade, then restart agent sessions. Prefer completing existing task worktrees before upgrading; they retain their previous workflow text.
- Affected capabilities: Governed SDD `audit-prompt` v4, `code-review-prompt` v3, `execution-command-gate` v3, `git-workflow` v14, `implementer-reviewer-handoff` v5, `lifecycle-orchestration` v11, `owner-acceptance-workflow` v4, `review-mode-boundary` v3, `review-remediation-record` v5, `roles` v4, `task-blueprint` v17, `task-lifecycle` v4, `task-worktree-integration` v6, and `task-worktree-review-procedure` v12; Lean Delivery `git-workflow` v13; and `worktree-lifecycle` v4 in both modes.
- Managed paths: `AGENTS.md`, `CLAUDE.md`, `PROJECT_WORKFLOW.md`, `docs/AUDIT_PROMPT_READ_ONLY.md`, `docs/CODE_REVIEW_PROMPT.md`, `docs/LIFECYCLE_ORCHESTRATION.md`, `docs/PULL_REQUEST_POLICY.md`, `docs/REVIEW_RECORD_TEMPLATE.md`, `docs/WORKTREE_LIFECYCLE.md`, `docs/workflows/IMPLEMENTATION.md`, `docs/workflows/LIFECYCLE.md`, `docs/workflows/REMEDIATION.md`, `docs/workflows/REVIEW.md`, and `tasks/TASK_BLUEPRINT.md`, as applicable to the selected workflow. Adapted status, verdict, review, and closure instructions inside managed regions are likely conflict areas; resolve reported upgrade conflicts without overwriting project-owned policy.
- Run `meridian task state import --project <path> --format json`, inspect the proposed files and their queue, record, and review evidence, then repeat with `--apply`. Resolve reported text disagreements through the workflow before applying. Existing state files and terminal legacy tasks are skipped; import does not invent historical transitions or past approvals. Commit the generated `.meridian/tasks/<TASK-ID>.json` files. If all legacy tasks are terminal, no import is required.
- Adopters on 1.2.9 or later should remove reported reasoning contract text from project-owned sections of `docs/EXECUTION_EVIDENCE_PROFILE.md` and `docs/CONTEXT_BUDGET_POLICY.md` by hand. Meridian preserves that text.
- No manifest protocol upgrade is required: `protocolVersion` remains 2. Use the v1.2.13 CLI for the new task-state and verdict commands; existing task IDs and historical records are not renamed or converted automatically.


## [1.2.12]

Template-changing release: migration `065-spike-blueprint-worktree-closure` advances `workflowBaselineVersion` to `1.2.12`. It aligns `task-blueprint` v16 with governed worktree closure and adds stale-base recovery, conservative queue archival, and the SPIKE validation-ledger exception to the managed lifecycle guides (`worktree-lifecycle` v3). The CLI adds `meridian worktree repair-base`, safer queue archival, SPIKE ledger integration, and console fixes. The manifest shape and `protocolVersion` 2 are unchanged.

### Fixed

- Retain open queue phases during archival by respecting heading levels and checking every nested task table. Report ambiguous sections and avoid assuming a fixed consumer queue path.
- Allow SPIKE tasks to integrate the canonical `.meridian/execution-evidence.json` ledger written by declared execution validation, preserving its bytes while continuing to reject neighboring paths, production code, and undeclared deliverables.
- Align the SPIKE blueprint and governed skills with dedicated task worktrees: a separate local throwaway probe branch is never merged or pushed, while the canonical task branch carries the deliverable and permitted lifecycle/evidence records through ordinary governed closure.
- Detect stale task bases after a proven commit-less fast-forward from `main`.
  Read-only worktree checks report `STALE_WORKTREE_BASE`; the explicit
  `meridian worktree repair-base` command preserves identity and timing,
  requires renewed validation evidence, and rejects unproven or unsafe cases.
- Count terminal console tasks with only C10 cleanup pending as Done, excluding
  them from Closing and Open while preserving the cleanup hint and exact resume
  command in the detail pane and `--once` output.
- Resolve uniquely matching task records after archival while queue links still
  point to their original task-root paths, preserving invalid-link errors.

### Documentation

- Document stale worktree base recovery and conservative queue-section archival
  in both managed lifecycle guides, and the canonical SPIKE validation ledger
  exception in the Governed SDD guide.

### Upgrade notes

- Affected capabilities: `task-blueprint` v16 (Governed SDD) and `worktree-lifecycle` v3 (both workflows). Managed paths: `tasks/TASK_BLUEPRINT.md` (Governed SDD) and `docs/WORKTREE_LIFECYCLE.md`.
- Required action: run `meridian upgrade --check`, then `meridian upgrade --apply` to receive migration `065-spike-blueprint-worktree-closure`.
- Likely conflict areas for adapted projects: adapted text inside the managed blocks of `tasks/TASK_BLUEPRINT.md` and `docs/WORKTREE_LIFECYCLE.md`; resolve in place and keep protected markers intact. Consumer-owned text outside the blocks is preserved. Upgrade does not rewrite historical task records, so align branch and closure instructions copied into non-terminal SPIKE records by hand.
- After `meridian worktree repair-base`, renew validation and record new evidence before closure.
- No minimum framework or `protocolVersion` change; Python 3.12 remains the minimum since 1.2.11.

## [1.2.11]

Template-changing release: migration `064-closure-text-uses-advance` advances `workflowBaselineVersion` to `1.2.11`. The managed `git-workflow` block now closes tasks through `meridian worktree advance` instead of listing the closure order, every stop in managed text and in the CLI carries a registered code, and Codex records unbacked `BLOCKED` reports through a `Stop` hook. `prepare --resume` no longer writes lifecycle state. Python 3.12 is the new minimum. The manifest shape and `protocolVersion` 2 are unchanged.

### Added

- The managed `.codex/hooks.json` registers a Codex `Stop` hook that runs `meridian hook stop-audit --host codex`, so a `BLOCKED <CODE>` report that no command emitted is recorded on Codex as it is on Claude Code. `meridian hook stop-audit` accepts `--host claude|codex` and defaults to `claude`.
- Every `unbacked_block` and `declared_block` journal line records its `host`; older lines without one are read as `claude`. `meridian report flow` reports both kinds per host.

### Changed

- Every remaining `BLOCKED` the CLI prints now carries a registered stop code: `COMMAND_REFUSED` and `OS_ACCESS_FAILED` for the generic catch-alls, `VALIDATION_ID_UNDECLARED`, `BUDGET_EXHAUSTED`, `HOST_IMPACT_DECLARATION_INVALID`, `HOST_IMPACT_EVIDENCE_MISSING`, `UPGRADE_BLOCKED`, and `ADOPTION_BLOCKED`. Investigation and budget argument errors use `EXECUTION_EVIDENCE_ARGUMENTS`, and a rejected integration decision uses `EVIDENCE_MISMATCH`. `meridian worktree check` now also prints `BLOCKED WRONG_WORKTREE` on a mismatch.
- Every managed-text line that tells an agent to stop now names a registered code. Workflow-unreadable and rule-conflict stops get the judgment codes `WORKFLOW_UNREADABLE` and `RULE_CONFLICT`; the Governed SDD documents also use `SCOPE_CHANGE_REQUIRED`, `CONTRACT_EXHAUSTED`, and `REVIEW_LOOP_EXHAUSTED`.
- `python3 scripts/check_repository.py` fails on a `BLOCKED` without a registered code in managed text or in the CLI.
- The managed `git-workflow` block (v13 in the Governed SDD `PROJECT_WORKFLOW.md`, v12 in the three Lean Delivery workflow files) no longer lists the closure order or the closure stop codes. It tells the agent to run `meridian worktree advance <TASK-ID>` from the primary checkout, perform exactly its `action_required`, rerun it with the results, and report its `BLOCKED` line when it stops. The single-step commands stay documented in `docs/WORKTREE_LIFECYCLE.md` for diagnosis and manual recovery.
- The shipped Codex rules allow `meridian worktree advance` in both modes, and `meridian codex doctor` probes it with the other lifecycle commands.
- The queue files that `meridian init` seeds into new projects now agree with
  closure ownership: task branches do not edit the queue, `integrate stage`
  sets `[x]` and archives closed rows, and the developer assigns the task
  (Governed SDD no longer tells agents to pick one). Existing projects are not
  changed; copy the new wording into `tasks/QUEUE.md` by hand if you want it.
- `meridian setup` now also adds `Bash(python3 scripts/run_tests.py --parallel)`
  to the Claude Code project allowlist. The entry matches only that exact
  command, so it has no effect in a project that has no `scripts/run_tests.py`.
- Python 3.12 is now the minimum supported version for Meridian maintenance commands and tests.

### Fixed

- Preserve every failing unittest diagnostic block in parallel test-runner reports.
- Keep `meridian worktree closure-status` read-only, including blocked lifecycle reports.
- `meridian worktree prepare --resume` no longer writes lifecycle state, so a worker that can only read the shared Git metadata can resume its task. A resume with missing lifecycle state now derives the base commit from Git and reports a repair command instead of failing, and a mismatched state file stops with `BLOCKED WRONG_WORKTREE`.

### Upgrade notes

- Affected capabilities: `git-workflow` v13 (Governed SDD) or v12 (Lean Delivery); `bounded-worktree-lifecycle` v5 and `codex-worktree-access` v4 (Lean Delivery); and, in Governed SDD, `code-review-prompt` v2, `codex-worktree-access` v4, `execution-evidence-profile` v5, `host-impact-routing` v2, `investigation-scope` v2, `lifecycle-orchestration` v10, `manual-verification-precondition` v4, `owner-acceptance-workflow` v3, `rejected-attempt-restart` v5, `review-remediation-record` v4, `reviewer-integrator-identity` v3, `spike-routing` v2, `task-blueprint` v15, `task-worktree-boundary` v9, `task-worktree-integration` v5, `task-worktree-remediation` v4, `task-worktree-review-procedure` v11, and `workflow-mode-lock` v2. Managed paths: `PROJECT_WORKFLOW.md`, `AGENTS.md`, `CLAUDE.md`, `tasks/TASK_BLUEPRINT.md`, `.codex/hooks.json`, `.codex/rules/meridian.rules`, `docs/CODE_REVIEW_PROMPT.md`, `docs/CONTEXT_BUDGET_POLICY.md`, `docs/EXECUTION_EVIDENCE_PROFILE.md`, `docs/LIFECYCLE_ORCHESTRATION.md`, `docs/OPERATOR_PROMPTS.md`, `docs/PULL_REQUEST_POLICY.md`, and `docs/workflows/{IMPLEMENTATION,LIFECYCLE,REMEDIATION,REVIEW}.md`.
- Required action: run `meridian upgrade --check`, then `meridian upgrade --apply` to receive migration `064-closure-text-uses-advance`. It replaces the managed `git-workflow` block with the `meridian worktree advance` closure rule, replaces managed text that carried a bare `BLOCKED` with registered codes, adds `advance` to `.codex/rules/meridian.rules`, and adds the Codex `Stop` entry to `.codex/hooks.json` while keeping the `PreToolUse` read guard. Run `meridian setup --apply` to add the `run_tests.py --parallel` allow entry to an existing project. Local edits outside the managed blocks and local rules are kept.
- Likely conflict areas for adapted projects: the `git-workflow` block of `PROJECT_WORKFLOW.md`, `AGENTS.md`, and `CLAUDE.md`; managed Governed SDD documents that named stops without a code; and locally edited `.codex/rules/meridian.rules` or `.codex/hooks.json`. Resolve in place and keep protected markers intact.
- Minimum requirement: `bin/meridian` and Meridian's maintenance commands now need Python 3.12 or later. No minimum framework or `protocolVersion` change.

## [1.2.10]

CLI-only release: this release introduces no migration.

### Added

- Every lifecycle command (`prepare`, `check`, `closure-status`, `evidence`,
  `integrate stage`, `integrate finalize`, `integrate abort`, and `cleanup`)
  now appends one line to a local journal at
  `<git-common-dir>/meridian-journal.jsonl`, recording its result and stop code
  without any path, command text, or message content. A failed journal write
  only prints a warning. See `docs/WORKTREE_LIFECYCLE.md`.
- `meridian report flow` reads the lifecycle journal and reports per-task lead
  time, stops by code and class, aborts, and `prepare --resume` runs, with
  origin shares from an optional `Origin` task header, targets declared in
  `.meridian/flow-targets.json`, and removal candidates among never-emitted
  tool stops. It is read-only. See `docs/WORKTREE_LIFECYCLE.md`.
- The lifecycle journal marks `prepare --resume` runs with `resume: true`.
- A Claude Code `Stop` hook runs `meridian hook stop-audit`, which finds
  `BLOCKED <CODE>` lines in the final assistant message and appends
  `unbacked_block` to the lifecycle journal when no `blocked` journal line backs
  the code, or `declared_block` for `command-exit` and `judgment` codes. It
  stores the registered code only, never message text, and always exits 0.
  `meridian report flow` counts the `unbacked_block` lines. See
  `docs/WORKTREE_LIFECYCLE.md`.
- `meridian worktree advance <TASK-ID>` drives task closure from the primary
  checkout. It records evidence from the supplied validation results (C5),
  stages the integration (C6), and cleans up once the push is proven (C10),
  then returns one JSON object with `step`, `action_required`, `commands`,
  `stop_code`, and `resume` when the next step needs validation, candidate
  validation (C7), a push (C9), or a decision. It never runs a supplied
  command and journals each step it performs. See `docs/WORKTREE_LIFECYCLE.md`.
- `meridian worktree advance` accepts `--candidate-command` and
  `--candidate-exit-code`, repeatable. At a staged integration it writes the
  candidate-bound evidence from those results and runs `integrate finalize`,
  then asks for the push. A failed or missing candidate command aborts the
  integration with `CANDIDATE_VALIDATION_FAILED` or
  `UNDECLARED_VALIDATION_COMMANDS`; a candidate tree that changed after stage
  stops with `EVIDENCE_MISMATCH`. It still never runs a supplied command. See
  `docs/WORKTREE_LIFECYCLE.md`.

### Changed

- `meridian worktree integrate stage` now reports under `warnings` in its JSON output each queue section that archival skips without error, naming the section heading and the reason, such as a heading level other than `###` or a table header that does not start with the expected columns. It also reports a Governed SDD section held open only by `INCONCLUSIVE` rows. A warning never blocks the stage, and which sections are archived does not change.

## [1.2.9]

Template-changing release: migration `063-retire-reasoning-budget-contract` advances `workflowBaselineVersion` to `1.2.9`. It retires the reasoning budget contract, clarifies that a local `main` ahead of `origin/main` does not block integration, and states the stop and denial rules of `docs/ADR_STOPS_AND_DENIALS.md` in the managed `git-workflow` block. The CLI adds the stop-code registry and coded closure, execution, and handoff stops. The manifest shape and `protocolVersion` 2 are unchanged.

### Added

- `scripts/run_tests.py --parallel [N]` runs the unit suite as N concurrent shard processes (default: the CPU count, at most 8) and prints one combined result with the full-suite coverage proof. Each shard gets a private temporary directory, output is printed in shard order, and a failing, erroring, or killed shard fails the run. `python3 -m unittest discover -s tests` remains the canonical command.
- `release.py publish` now also fast-forwards the remote `stable` branch to the release commit after the `main` and tag pushes, so a Claude Code marketplace declared with `"ref": "stable"` follows each release. It never forces the push, requires `.claude-plugin/plugin.json` to match the tag, and stops without moving `stable` when it is not an ancestor of the release commit. `release.py verify` checks, read-only, that `stable` points to the tag commit.
- `meridian self-check --check-latest` prints a `Plugin ref:` line for the marketplace ref in user settings: `stable`, the latest tag, an older tag with its remedy, or unknown. It never writes settings.
- `capabilities/stop-codes-v1.json` is the registry of closure stop codes for both workflows, with its schema in `schemas/stop-codes-v1.schema.json`. Each entry records its class (`tool`, `command-exit`, or `judgment`), workflows, step, emitter, whether a human decides, and a resume template. Every `tool` code names the test that proves its output line.
- `python3 scripts/check_repository.py` now checks the stop-code registry against the managed templates, this repository's managed copies, and the console's stop-code list. It fails, naming the file, line, and token, when a stop code that follows `BLOCKED` or appears in a stop-code list is not registered; when a `tool`-class code has no `test` or names a test that does not exist; and when a registered code appears in no managed text or CLI output.
- `meridian setup --apply` also adds `permissions.deny` prefix rules to the project `.claude/settings.local.json` for force, mirror, and delete pushes, `git tag`, `git rebase`, `git reset --hard`, `git cherry-pick`, `git branch -D`, and `git worktree remove --force`. Existing entries are kept, and the setup plan lists the rules it would add.

### Changed

- The Claude Code project allowlist now matches Codex for safe Meridian execution commands.
- `meridian worktree integrate stage` reports `MAIN_BEHIND_ORIGIN: local main is behind the already fetched origin/main` and names the local and the fetched `origin/main` commits. It is still raised only when local `main` is behind; an equal or ahead `main` is accepted.
- Closure stops detected by the CLI now print one line, `BLOCKED <CODE>: <detail>; resume: <command>`, through a single helper that accepts only registered codes: `INTEGRATION_CONFLICT`, `EVIDENCE_MISMATCH`, `CLEANUP_BLOCKED`, `PRIMARY_DIRTY`, `LEASE_HELD`, `MAIN_BEHIND_ORIGIN`, and `UNDECLARED_VALIDATION_COMMANDS`. The exit status stays `2` and the earlier detail text follows the code. `meridian worktree closure-status` takes its codes and resume commands from the registry; its JSON output is unchanged and its text output now adds a detail after the code.
- The managed `git-workflow` text in both workflows now states that a stop is valid only when a `BLOCKED <CODE>` line from a Meridian command, a non-zero exit of a required command, or a nameable unmet acceptance criterion backs it. An agent never satisfies a gate by writing false state and, when a gate contradicts another rule, stops and reports both rules. When a Meridian command accepted a state the text appears to forbid, the agent follows the command and records the difference under `Rule discrepancies:`, except for actions on the deny list.
- The prose list of closure stop codes is replaced by a reference to `capabilities/stop-codes-v1.json` and `meridian worktree closure-status`; the closure step order is unchanged.
- `docs/COMPLETION_REPORT_TEMPLATE.md` gains an optional `Rule discrepancies:` line. `meridian execution handoff-check` accepts a report with or without it.
- The Governed SDD execution and handoff gates (`execution preflight`, `contract`, `reconcile`, `evidence`, `handoff-check`, and `ready-check`) now stop with `BLOCKED <CODE>: <detail>; resume: <command>` through the stop-code registry. Each message names the rule, the field or source checked, the accepted values, and the value found.
- The Governed SDD task blueprint's `## Validation` guidance now states that every command proving an acceptance criterion or an `Evidence needed` item has its own declared validation ID, that one ID holds exactly one command, that output paths are fixed and task-scoped, and that commands use no `mktemp`, `$(...)`, or time-based paths. The wording changes no validation parsing, and existing tasks that declare fewer IDs are not an error.

### Removed

- The reasoning budget contract is retired from the Governed SDD templates: the `Reasoning` and `Reasoning justification` task fields, the exact-cap preflight, and the operator reasoning-level guidance. Agents cannot read their effective reasoning level, so the directive blocked every execution that carried it, and Meridian never enforced it.

### Fixed

- Let release publication verification call `gh api` without its unsupported `--repo` flag.
- Let `handoff-check` accept consumer-defined validation-skip descriptions instead of requiring a Meridian-specific test name.
- Budget reads no longer migrate or stage deletion of legacy `.meridian/budget.json` state.
- `PUSH_PENDING` in `capabilities/stop-codes-v1.json` now names the test that proves its output, as every `tool` code must.
- `handoff-check` accepts `Isolated exploration: none`, or a value that starts with `none` or `no` followed by text, when no investigation is recorded. Otherwise it states that `none` is expected and quotes the value found.
- `handoff-check` reports a required field written with text before the colon, such as `- Validation (commands):`, as a format problem that names the expected form `- <Field>: <value>`, instead of as a missing field.
- `execution preflight`, `ready-check`, `validate`, and `investigate` no longer block a Governed SDD remediation on a task branch. On the task's own branch they accept a queue row of `QUEUED` against a task record of `QUEUED`, `IN_PROGRESS`, `CHANGES_REQUESTED`, or `READY_FOR_REVIEW`, because a task branch never edits `tasks/QUEUE.md`. Other combinations still stop, and the message names the document the current actor may change.

### Documentation

- The README update procedure recommends `"ref": "stable"`, explains how to read the installed plugin version, and keeps exact tags for pinning and rollback.
- The managed `git-workflow` text, `docs/WORKTREE_LIFECYCLE.md`, and `docs/TASK_CLOSURE_DESIGN.md` now state that closure stages from a primary checkout whose `main` equals `origin/main` or is ahead of it with unpushed commits, which are pushed with the integration. Only a `main` behind the fetched `origin/main` stops with `MAIN_BEHIND_ORIGIN`.
- `docs/WORKTREE_LIFECYCLE.md` states the new text format of blocked `closure-status` results and names the stop-code registry.
- The README and the setup output state that these rules are defense in depth, that a reworded command can evade them, and that the managed denial text remains in force.

### Upgrade notes

- Affected capabilities: `git-workflow` v12 (Governed SDD) or v11 (Lean Delivery), `task-blueprint` v14, `execution-evidence-profile` v4, `lifecycle-orchestration` v9, and `execution-assets` v4; `reasoning-budget-contract` v1 is removed. Managed paths: `PROJECT_WORKFLOW.md`, `AGENTS.md`, `CLAUDE.md`, `tasks/TASK_BLUEPRINT.md`, `docs/CONTEXT_BUDGET_POLICY.md`, `docs/LIFECYCLE_ORCHESTRATION.md`, `docs/OPERATOR_PROMPTS.md`, `docs/PULL_REQUEST_POLICY.md`, `docs/EXECUTION_EVIDENCE_PROFILE.md`, and `docs/COMPLETION_REPORT_TEMPLATE.md`.
- Required action: run `meridian upgrade --check`, then `meridian upgrade --apply`. Run `meridian setup --apply` to add the new Claude Code execution allow entries and the `permissions.deny` rules to an existing project.
- `meridian upgrade --check` announces a tracked legacy `.meridian/budget.json`; `upgrade --apply` moves it to shared Git metadata, stages its deletion, and tells you to commit that deletion.
- Existing tasks that still carry `Reasoning` fields are not an error; a project that wants a reasoning policy writes its own outside the managed blocks.
- Task authors: declare a separate validation ID for each hash comparison, repeated capture, or other command that proves a criterion, so that `meridian execution validate` can run it without a permission prompt.
- Likely conflict areas for adapted projects: the `git-workflow` block of `PROJECT_WORKFLOW.md`, `AGENTS.md`, and `CLAUDE.md`, and the reasoning sections of `docs/CONTEXT_BUDGET_POLICY.md` and `tasks/TASK_BLUEPRINT.md`; resolve in place and keep protected markers intact.
- No minimum framework or `protocolVersion` change.

## [1.2.8]

Template-changing release: migration `062-primary-project-declaration-and-review-authority` advances `workflowBaselineVersion` to `1.2.8`. It updates `PROJECT_WORKFLOW.md` (`git-workflow` v10) and `docs/workflows/REVIEW.md` (`task-worktree-review-procedure` v10), and lists `docs/COMPLETION_REPORT_TEMPLATE.md` as a managed path. The manifest shape and `protocolVersion` 2 are unchanged.

### Fixed

- Remove retired inline marker blocks from project sections carried during a restructure upgrade.
- Warn before an upgrade preserves edits in a markerless managed copy that will fail the digest audit.
- Keep lifecycle-backed hook task-state lookups bounded and degrade queue briefings when their optional lookup times out.
- Resolve project declarations from the primary checkout and keep budget runtime state out of tracked project files.
- Mark the 1.2.8 release as template-changing through migration 062, so 1.2.7 projects receive the updated primary-project declaration and Review authority guidance.
- `meridian upgrade --check` no longer stops with `BLOCKED` on a project whose `capabilityProfiles` declare an older managed surface than the catalog. The plan shows one `PROFILE-SURFACE` row per affected capability, and `meridian upgrade` rewrites those declarations from the target catalog. A managed copy that drifted from its recorded digest still blocks the upgrade, and every other surface mismatch still fails validation.
- `scripts/check_repository.py` now fails when a capability's catalog surface gains a path that no migration of the next release lists in `managedPaths`.

### Upgrade notes

- Governed SDD upgrades add explicit post-approval Review authority for C6 through C10; legacy tracked `.meridian/budget.json` migrates on the next budget write.
- Projects that declare `capabilityProfiles` gain `docs/COMPLETION_REPORT_TEMPLATE.md` in their `execution-evidence` declaration; the file itself is already part of the managed baseline.
- Affected capabilities: `git-workflow` v10, `task-worktree-review-procedure` v10, and `execution-evidence` (profile surface). Managed paths: `PROJECT_WORKFLOW.md`, `docs/workflows/REVIEW.md`, `docs/COMPLETION_REPORT_TEMPLATE.md`.
- Required action: run `meridian upgrade --check`, then `meridian upgrade --apply`.
- Likely conflict areas for adapted projects: the `git-workflow` block of `PROJECT_WORKFLOW.md` and the review-procedure block of `docs/workflows/REVIEW.md`; resolve in place and keep protected markers intact.
- No minimum framework or `protocolVersion` change.

## [1.2.7]

Template-changing release: migration `061-governed-phase-reads` advances `workflowBaselineVersion` to `1.2.7`. It aligns the Governed SDD lifecycle text with the closure design and the CLI, adds the `.meridian/project.json` declaration, phase-based context loading, bounded router reads, and consumer capability profiles, and resolves the conformance defects reported by a Governed SDD consumer. The manifest shape and `protocolVersion` 2 are unchanged.

### Added

- Let `meridian setup` record an explicit opaque or milestone task-identity choice for new projects.
- Add a read-only `meridian task identity next` command for deterministic milestone task IDs.
- `meridian worktree prepare <TASK-ID> --resume` accepts an existing canonical worktree of that task that has uncommitted changes. It changes nothing, keeps `started_at` and `base_commit`, refuses when the task has no worktree or while an integration lease or staged merge names it, and still blocks every other mismatch. The result adds `resumed`, `dirty`, `changed_paths`, and `untracked_paths` (counts only); a dirty result has `next_action` `inspect-dirty`, after which `worktree check` reports `dirty-worktree` and no other error.
- Add `meridian context size` to report workflow-role startup read sets, estimated token ranges, and optional size-limit failures.
- Add `meridian usage report` for private, local-only summaries of Codex and Claude Code session token counters.
- Add a `phase-reads` managed block to the Governed SDD implementation, review, remediation, and status procedures that states, per document, whether it is read at start or at the phase that needs it, and teach `meridian context size` to report such documents as `deferred` outside the startup total.
- Add a `bounded-context-readers` managed block to the implementation, review, and remediation procedures that directs ADR and specification reads through `meridian context authority` and `meridian adr show` and queue reads through the queue briefing.
- The execution-evidence profile gains the `long-command-waits` v1 block: a command expected to take longer than one minute is started with a wait that covers its expected duration and is polled at most once afterwards, which removes the empty-poll loop Codex agents ran while the suite was executing. During implementation an agent runs only the tests of the modules the task touches and runs the full suite once, after the last code change, as the validation of record; the declared `REUSE`, `BOUNDED`, and `FULL` candidate validation is unchanged.
- Added the consumer-owned `.meridian/project.json` declaration and `meridian project show` for resolved project metadata.
- Added the `governed-sdd-consumer` and `lean-delivery-consumer` catalog profiles. `meridian profile bootstrap <id> --check` then `--apply` turns a legacy protocol v2 manifest's `UNVERIFIED` declaration row into a declared profile with installation evidence; host activation and verification stay `UNVERIFIED` until a probe exists. Catalog profiles may now declare `workflowModes`.
- `meridian audit` reports a `managed-copy-digest` row for each markerless managed copy: `FAIL` when its digest differs from `managedFiles`. Files with capability markers, `AGENTS.md`, `CLAUDE.md`, `docs/ARCHITECTURE_DECISIONS.md`, `docs/EXECUTION_EVIDENCE_PROFILE.md`, and the queue are never digest-checked.
- `docs/CODE_REVIEW_PROMPT.md` applies a project's `## Project review checklist` section and `audit-prompt` runs a project's `## Project-specific checks` section, each placed after the managed block.

### Changed

- Name the queue briefing and the bounded ADR readers in the minimal read-only status procedure.
- Aligned the Governed SDD lifecycle capability text with the closure design and the CLI: task branches never edit the queue, queue archive, or plan; the task record carries `IN_PROGRESS`, `READY_FOR_REVIEW`, and `CHANGES_REQUESTED`; the task branch is the `branch` value from `meridian worktree prepare`; and a task-branch push happens only to obtain `T1_CI`, at most once per review attempt, never by the reviewer, and not at all without CI.
- `Accept <TASK-ID>` now appends an owner `APPROVE` attempt to the review record, sets the task record to `ACCEPTED`, and continues at C6 under the `Proceed with` authority; a manual merge is never permitted.
- Managed text names resolved locations (`meridian locations`) and the reviewer author (`meridian project show --field reviewer-author`) instead of literal paths and placeholders, and the reviewer identity rule now lives in one block.
- `code-organization` v2 allows the project module map in the project's architecture documentation or in a `## Project module map` section after the managed block.
- Lean Delivery's `git-workflow` v9 carries only the task-branch name and push rules.
- Inline markers inside prose became standalone blocks: `code-review-prompt` v1 replaces the three inline markers in `docs/CODE_REVIEW_PROMPT.md`, `validation-scoping` v2 (complete sentences in the implementation procedure; unchanged text elsewhere), and `read-guard` v2 (the active task comes from the verified worktree and the router read set is exempt; both modes).
- `docs/WORKTREE_LIFECYCLE.md` is the whole-file `worktree-lifecycle` v1 capability in both modes, and the pull request policy's remote task-branch cleanup section is `remote-branch-cleanup` v1.
- `meridian profile bootstrap` refuses a markerless managed copy whose digest differs from the recorded one instead of recording the edited file.

### Removed

- Removed the unread `Project integration smoke command:` line from both `PROJECT_WORKFLOW.md` templates; `.meridian/candidate-validation.json` is the only candidate-validation declaration.
- Removed the unmarked duplicate of the reviewer identity rule from the Governed `docs/PULL_REQUEST_POLICY.md`.

### Fixed

- Verify published releases with supported GitHub CLI fields and the latest-release API.
- The console Resume for a task with a dirty worktree launched `Proceed with <ID>`, whose `prepare` refused the dirty worktree, so the agent stopped at once with `BLOCKED`. It now launches a directive that runs `prepare --resume`; a clean worktree, a first launch, `Review`, and `Address review` keep their ordinary directives.
- Detect managed-copy digest drift during the repository check and provide an explicit refresh command.
- Let `meridian worktree integrate stage` complete Governed queue rows with project-specific column layouts.
- Count cache-read and cache-creation tokens in the Claude Code input of `meridian usage report`, so startup, mean, peak, and `cache_ratio` match the Codex meaning of input.
- Governed integration now handles SPIKE rows safely and always requires candidate `git diff --check` evidence.
- Made read-guard router exemptions bounded by a declared ceiling and derived task activity from registered worktrees.

### Documentation

- Document the Claude Code settings-pinned marketplace refusal and ways to confirm the active Meridian plugin version.

### Upgrade notes

- Run `meridian upgrade --apply`. The change reaches Lean Delivery `bounded-worktree-lifecycle` v4 in `PROJECT_WORKFLOW.md`, Governed SDD `task-worktree-boundary` v8 in `docs/workflows/IMPLEMENTATION.md`, and `worktree-lifecycle` v2 in `docs/WORKTREE_LIFECYCLE.md` for both modes. Each adds wording that a Resume directive starts with `prepare --resume`, that `--resume` is allowed only for that directive, and that the agent reads `git status` and the diff before continuing. Project text outside the capability blocks is untouched.
- The shipped Codex rule already allows `meridian worktree prepare` by prefix, so `--resume` needs no rule change.
- Template-changing release 1.2.7 adds `phase-reads` v1 and `bounded-context-readers` v1 and bumps `minimal-read-only-status` to v2 in Governed SDD `docs/workflows/IMPLEMENTATION.md`, `docs/workflows/REVIEW.md`, `docs/workflows/REMEDIATION.md`, and `docs/CONTEXT_BUDGET_POLICY.md`. Run `meridian upgrade --apply`; adapted projects may conflict in those four files, and no minimum framework or `protocolVersion` change applies.
- Run `meridian upgrade --apply`. The change reaches `long-command-waits` v1 in `docs/EXECUTION_EVIDENCE_PROFILE.md` for both Lean Delivery and Governed SDD; the block is added after the existing Claude Code foreground-timeout rule, which is unchanged, and project text outside the block is preserved.
- Existing projects continue to use legacy workflow location prose until they add `.meridian/project.json`; the legacy resolver now warns on use.
- Run `meridian upgrade --apply`. The change reaches Governed SDD `git-workflow` v9, `roles` v3, `review-policy` v3, `task-lifecycle` v3, `execution-assets` v3, `document-precedence` v2, `review-mode-boundary` v2, `review-remediation-record` v3, `implementer-reviewer-handoff` v4, `reviewer-integrator-identity` v2, `task-worktree-boundary` v7, `task-worktree-review-procedure` v9, `task-worktree-integration` v4, `task-worktree-handoff` v5, `owner-acceptance-workflow` v2, `execution-command-gate` v2, `lifecycle-orchestration` v8, `rejected-attempt-restart` v4, `audit-prompt` v3, `task-blueprint` v13, and `code-organization` v2, plus Lean Delivery `git-workflow` v9, in `PROJECT_WORKFLOW.md`, `AGENTS.md`, `CLAUDE.md`, and the Governed `docs/` and `tasks/TASK_BLUEPRINT.md` files they list.
- Adapted projects are most likely to conflict in `PROJECT_WORKFLOW.md` (`git-workflow`, `roles`) and `docs/workflows/REVIEW.md`. Upgrade merges managed files three-way, so an untouched `Project integration smoke command: `none`` line is removed; a customized line is never dropped silently (it is kept or reported as a conflict), so move any real command into `.meridian/candidate-validation.json` and delete the line.
- Declare the project name and slug in `.meridian/project.json` so `meridian project show --field reviewer-author` can print the reviewer author for the acceptance commit.
- `meridian project show --field ci` defaults to `none`, and under the new push rule a task-branch push needs CI. A project that relies on `T1_CI` must declare `ci` in `.meridian/project.json`, otherwise the task-branch pushes stop.
- A `## Project module map` section placed after the `code-organization` block is preserved unchanged by upgrade.
- The unmarked prose of a project's own `tasks/QUEUE.md` is not managed; update its status-editing sentence to match the task-record rule by hand.
- Run `meridian upgrade --apply`. The change reaches Governed SDD `code-review-prompt` v1, `worktree-lifecycle` v1, `remote-branch-cleanup` v1, `validation-scoping` v2, `read-guard` v2, and `audit-prompt` v3, plus Lean Delivery `worktree-lifecycle` v1, `read-guard` v2, and `validation-scoping` v2, in `docs/CODE_REVIEW_PROMPT.md`, `docs/AUDIT_PROMPT_READ_ONLY.md`, `docs/CONTEXT_BUDGET_POLICY.md`, `docs/PULL_REQUEST_POLICY.md`, `docs/WORKTREE_LIFECYCLE.md`, `docs/workflows/IMPLEMENTATION.md`, and `PROJECT_WORKFLOW.md`.
- A project that edited prose around the retired `task-worktree-review` v4, `manual-verification-review-check` v1, or `ci-verified-validation` v1 inline markers in `docs/CODE_REVIEW_PROMPT.md` gets a `RESTRUCTURE` plan row. Upgrade writes the current file to `docs/CODE_REVIEW_PROMPT.md.meridian-pre-restructure.bak` (a numeric suffix is added when that name exists), installs the standalone block, and carries the project's own level-2 sections after it. Re-apply any project prose from the backup in a `## Project review checklist` section.
- Whole-file `worktree-lifecycle` v1 and `remote-branch-cleanup` v1 are protected regions. When the three-way merge conflicts inside text a project edited there, upgrade reports a conflict instead of adding a duplicate block; reconcile the edit by hand and put project text outside the block. A merge that applies cleanly around a project edit leaves the edited block, which `meridian audit` then reports as a protected-content `FAIL`. See `docs/CONSUMER_PROFILES.md` for project-owned sections and the consumer-profile procedure.
- A markerless managed copy edited by hand now fails `meridian audit`; restore the released text.

## [1.2.6]

Template-changing release: migrations `058-lean-closure-procedure`, `059-governed-closure-procedure`, and `060-unattended-closure-command-policy` advance `workflowBaselineVersion` to `1.2.6`. This release also ships the changes prepared for the unpublished versions `1.2.4` and `1.2.5`, which have no separate tag. The Lean Delivery and Governed SDD closure procedures, the Codex command policy, and project-declared candidate-validation commands arrive together.

### Added

- `meridian validation check` verifies a versioned, commit-and-tree-bound
  external validation evidence record without running its recorded command.
- `scripts/run_tests.py` runs the unittest suite in deterministic, disjoint
  shards and prints a full-suite SHA-256 coverage proof for each shard.

### Fixed

- Upgrades can now adopt an explicitly declared, newly managed framework file
  that already exists without a recorded baseline. A differing copy is backed
  up under a collision-safe adjacent name before the target template replaces
  it, and both the plan and apply output report the replacement and backup.
- `meridian worktree integrate stage` accepts the exact archive rename of a
  task record after validation while continuing to reject other task-record
  changes. This is a CLI-only fix.

### Changed

- `scripts/release.py publish` now validates the release state rather than a
  single `Release <version>` commit, so a migration task can prepare a
  template-changing release in its ordinary commits and publish it with the
  same typed-confirmation command as a CLI-only release.

### Added

- Repository validation now runs for pushed `task-*` branches and can produce
  exact-commit T1 CI evidence through `scripts/ci_evidence.py`.
- Release changelog fragments let parallel tasks record user-visible changes
  without concurrently editing `CHANGELOG.md`.
- Identify the running Meridian version and framework root in the project console, with an isolated single-choice agent launch panel.
- The project console now reports active-task cycle time and lifecycle gates.
- The Codex command policy allows `meridian worktree evidence` and `closure-status`, `git mv` for the task-record archive rename, the repository validation commands, and read-only inspection (`ls`, `cat`, `head`, `tail`, `wc`, `pwd`, `grep`). `meridian codex doctor` reports `archive-rename-policy`, `inspection-command-policy`, and `validation-command-policy`, and probes `evidence` and `closure-status` with the lifecycle commands.
- The Claude Code allowlist offered by `meridian setup` gains the equivalent entries, including `git mv tasks/`.
- The project console can resume interrupted Lean Delivery and Governed SDD tasks with explicit liveness and dirty-worktree confirmations.

### Changed

- Lean Delivery now treats `Proceed with <TASK-ID>` as standing authorization
  for the gated task lifecycle through integration, one `origin/main` push, and
  cleanup, with explicit exclusions for release, history-rewrite, conflict, and
  destructive operations.
- Governed SDD now treats `Proceed with <TASK-ID>` as standing authorization
  for the gated task lifecycle through integration, one `origin/main` push,
  and cleanup, while preserving explicit exclusions for release, history
  rewrites, conflicts, and destructive operations.
- A Governed `Review: REQUIRED` task stops at `REVIEW_REQUIRED` as a mandatory
  gate; after approval, the reviewer-integrator completes integration. A
  `Review: NOT_REQUIRED` task continues through cleanup without a reviewer.
- Reduce full-suite validation output and require foreground execution for long checks.
- Require candidate validation evidence to name the repository check for every integration decision and the unittest discovery suite for full validation.
- Forced `git mv` and every write-capable or program-executing form (`sed -i`, `rg --pre`, `find -exec`, `mv`) keep prompting. Codex prefixes match leading tokens only, so `git mv` cannot be limited to `tasks/done/`.
- The project console derives Governed SDD in-progress and review-pending state from the task record and shows its cycle time.

### Fixed

- `release.py publish` now waits for its matching GitHub workflow run, and the
  read-only `verify` command resumes publication verification after a tag exists.
- Make `meridian worktree integrate stage` complete Governed SDD queue rows without requiring `PROJECT_PLAN.md`, including approved required reviews and archived task links.
- The project console keeps a task listed as `CLOSING` until cleanup, in both workflows.
- Candidate validation now reads consumer-declared command fragments per integration outcome instead of assuming Meridian's own Python checks.

### Documentation

- Define the `REUSE`, `BOUNDED`, and `FULL` candidate-validation gates and the deterministic reuse proof. Lean Delivery projects now receive the defining `docs/WORKTREE_LIFECYCLE.md` as a managed file.

### Upgrade notes

- Run `meridian upgrade --apply` in each Lean Delivery project to install
  `git-workflow` v8 in `PROJECT_WORKFLOW.md`, `AGENTS.md`, and `CLAUDE.md`.
- The upgrade preserves consumer-owned text outside the managed capability
  blocks. Resolve any local edits inside those blocks deliberately.
- The new procedure leaves queue and plan status changes to `integrate stage`;
  restart open agent sessions after upgrading so they use the new closure rule.
- Run `meridian upgrade --apply` in each Governed SDD project to install
  `git-workflow` v8, `task-worktree-boundary` v6, and
  `task-worktree-review-procedure` v8.
- The upgrade preserves consumer-owned text outside managed capability blocks.
  Resolve local edits inside those blocks deliberately, then restart open
  agent sessions so they use the new closure procedure.
- Template-changing release: migration `060-unattended-closure-command-policy` updates the managed path `.codex/rules/meridian.rules` in both workflow modes. Run `meridian upgrade --apply`; project-local rules appended at the end of the file are preserved by the three-way merge.
- A project that edited the same block as the new rules may see a conflict in that file; resolve it deliberately and rerun the upgrade.
- Afterward run `meridian codex doctor` to confirm each new rule group is `ready`. The Claude Code allowlist is not delivered by the upgrade; it arrives through consented `meridian setup`.
- Lean Delivery projects now receive `docs/WORKTREE_LIFECYCLE.md` through `meridian upgrade --apply`. An unchanged or missing copy is refreshed automatically; a locally edited copy follows the normal three-way merge and may require deliberate conflict resolution.
- When that Lean lifecycle document already exists but has no 1.2.5 baseline,
  upgrade preserves the old copy as
  `docs/WORKTREE_LIFECYCLE.md.meridian-pre-adoption.bak` (or the next numbered
  free name) and replaces it with the 1.2.6 template.
- After `meridian upgrade --apply`, review `meridian setup --check` and explicitly declare candidate-validation fragments or choose `none`; the first integration of an undeclared project stops once before staging and reports a proposal.

## [1.2.3]

Template-changing release: migration `057-self-referential-handoff-commits`
advances `workflowBaselineVersion` to `1.1.55`.

### Changed

- In Governed SDD, the completion handoff now states how to record a commit
  that cannot name itself: a descriptive form by subject and branch, full SHAs
  for earlier commits in a lifecycle-only correction, and a correction commit
  followed by one push instead of amend or force-push. Reviewer preflight
  resolves a descriptive current task commit to the registered task branch
  `HEAD` and still blocks any value naming a different commit.

### Upgrade notes

- Run `meridian upgrade --apply` in each Governed SDD project to install
  `task-worktree-handoff` v4 in `docs/COMPLETION_REPORT_TEMPLATE.md` and
  `task-worktree-review-procedure` v7 in `docs/workflows/REVIEW.md`.
- Existing handoffs are not rewritten.
- Restart open agent sessions after upgrading so they read the new procedure.

## [1.2.2]

Template-changing release: migration `056-manual-governed-proceed-worktree`
advances `workflowBaselineVersion` to `1.1.54`.

### Changed

- In Governed SDD, a manually typed `Proceed with <TASK-ID>` now prepares and
  verifies the exact task worktree when a coordinator did not supply launch
  inputs. Coordinator-launched implementation, review, and remediation keep
  their existing registered-worktree rules.

### Upgrade notes

- Run `meridian upgrade --apply` in each Governed SDD project to install
  `bounded-worktree-lifecycle` v4 in `PROJECT_WORKFLOW.md` and
  `task-worktree-boundary` v5 in `docs/workflows/IMPLEMENTATION.md`.
- A locally edited `IMPLEMENTATION.md` can produce an upgrade conflict; resolve
  the manual `Proceed with` worktree-start rule deliberately rather than
  overwriting local policy.
- Restart open agent sessions after upgrading so they read the new procedure.

## [1.2.1]

CLI-only release: this release introduces no migration.

### Added

- `meridian setup --check` now plans, and `--apply` creates, the Codex skill
  links `meridian-lean-delivery` and `meridian-governed-sdd` in
  `~/.agents/skills`. It never overwrites an existing link or file, reports the
  `MERIDIAN_ROOT` and `PATH` lines to add to the shell profile without editing
  it, and warns about a stale copy in `~/.codex/skills`.
- `meridian codex doctor` reports two more read-only host checks:
  `skill-links` and `MERIDIAN_ROOT`.

### Fixed

- `scripts/release.py prepare` is accepted alongside the existing no-word
  preparation form, and its dry-run output now prints only the new release
  section.

### Documentation

- The README now documents the current repository layout, Codex doctor checks,
  and release preparation and publication commands.
- The `meridian-local` to `meridian` migration can leave
  `~/.claude/plugins/cache/meridian-local/` on disk; it is unused and can be
  deleted. The `v1.2.0` install evidence is recorded in
  `docs/HOST_CAPABILITY_CONTRACT.md`.

## [1.2.0]

CLI-only release: this release introduces no migration and leaves
`workflowBaselineVersion` at `1.1.53`.

Versions `1.1.51`, `1.1.52`, and `1.1.53` were never published as Git tags or
GitHub Releases. `1.2.0` is the first installable release since `v1.1.50` and
bundles their changes with those below. A project upgrading from `1.1.50`
receives migrations `053`, `054`, and `055` in one `meridian upgrade --apply`.
The `1.1.51` through `1.1.53` sections below stay as the record of those
changes.

### Added

- `meridian self-check --check-latest` performs an opt-in, read-only comparison
  with the latest public GitHub Release. It uses the standard library, a short
  timeout, no credentials, and no persistent state, and reports distinct exit
  codes for up-to-date, update-available, and unknown results.

### Changed

- The release script now enforces the adopter-facing release-notes contract: a
  `CHANGELOG.md` release section must start with `CLI-only release` or
  `Template-changing release`, the kind must agree with `baselineChanged` in
  `releases/<version>.json`, and a template-changing section must carry a
  non-empty `### Upgrade notes` subsection. Otherwise the release publishes
  nothing.
- The project console now starts Claude Code and Codex in a horizontal iTerm2
  split pane below the console instead of opening a tab. Repeated launches split
  the console pane again and reduce the space available to existing panes.
- The project console now reads the `Review:` field from a Governed SDD task
  record when the queue table has no `Review` column, offers `Review <ID>` for a
  `ready_for_review` task that declares `Review: REQUIRED`, and states why a
  review is withheld in the `Next action` line.
- **Breaking for existing Claude Code installs:** the marketplace is renamed
  from `meridian-local` to `meridian`, so the plugin id is now
  `meridian@meridian`. One-time migration: run
  `/plugin uninstall meridian@meridian-local`,
  `/plugin marketplace remove meridian-local`,
  `/plugin marketplace add biagiolibe/meridian#v<version>`, and
  `/plugin install meridian@meridian`.
- The README documents the pinned install (`#v<version>`) and the ordered
  update procedure. Moving a pin requires removing the marketplace, adding it
  at the new tag, and reinstalling the plugin.

### Upgrade notes

- **Existing Claude Code installs need a one-time marketplace migration.** The
  marketplace is now `meridian`, so the plugin id changes from
  `meridian@meridian-local` to `meridian@meridian`. Run:

  ```text
  /plugin uninstall meridian@meridian-local
  /plugin marketplace remove meridian-local
  /plugin marketplace add biagiolibe/meridian#v1.2.0
  /plugin install meridian@meridian
  ```

- Run `meridian upgrade --check`, then `meridian upgrade --apply`, in each
  project. From `1.1.50` this applies migrations `053`, `054`, and `055`.

## [1.1.53]

Template-changing release: migration `055-unified-worktree-root-and-setup`
advances `workflowBaselineVersion` to `1.1.53`.

### Added

- `meridian setup --check|--apply` plans and performs the bounded, once-per-
  machine worktree-root and Codex profile setup.

### Changed

- Worktree roots resolve consistently from an explicit option, environment,
  versioned user configuration, or `~/.meridian/worktrees`. Lifecycle and
  Codex commands no longer require `--worktree-root`.
- Start-of-turn and doctor diagnostics report a Codex profile that points at a
  different root. Existing worktrees remain in their old roots until normal
  explicit cleanup.

## [1.1.52]

Template-changing release: migration `054-machine-independent-worktree-handoff`
advances `workflowBaselineVersion` to `1.1.52`.

### Changed

- Completion handoffs no longer record an absolute task-worktree path, so
  tracked records resolve on every machine. They record `handoff_worktree`, the
  path relative to the worktree root, which `meridian worktree path`, `prepare`,
  and `check` now return. `check` accepts both that value and a legacy absolute
  value, so handoffs already written are not rewritten. Runtime uses of the
  absolute path are unchanged.
- `scripts/check_repository.py` rejects machine-specific home-directory paths
  in tracked text files.

## [1.1.51]

Template-changing release: migration `053-codex-profile-repair-guidance`
advances `workflowBaselineVersion` to `1.1.51`.

### Fixed

- `meridian codex configure` no longer strands an otherwise identical
  permission profile when a Codex app rewrite drops or moves Meridian's
  ownership comments. `--check` reports a named `repair-required` state with a
  unified diff of the exact bounded change; only explicit `--apply` writes it,
  after a new exclusive owner-only backup, and repeating it is a no-op.
  Divergent, partial, duplicated, or unusually serialized profiles stay
  `BLOCKED` with the diverging fields named. `meridian codex doctor` reports
  the condition as `profile-ownership`, separately from root access.
- Both workflows carry the same bounded recovery procedure
  (`codex-worktree-access` v2).

## [1.1.50]

CLI-only release: no template, workflow rule, or managed file changed, so it
ships no migration and `workflowBaselineVersion` stays at `1.1.49`
(`releases/1.1.50.json` records `baselineChanged: false`).

### Added

- `releases/<version>.json`, an append-only release ledger recording the
  release date, tag, protocol version, `workflowBaselineVersion`, and the
  migrations a release introduced. `scripts/check_repository.py` validates it
  and requires a record for the current `VERSION`.
- `meridian lock` and `meridian upgrade --apply` now reject a prerelease
  framework `VERSION` before it can become durable in a manifest, and
  `meridian --version` reports the framework version.
- Self-hosting host probes and a CI dogfooding gate that rejects missing,
  drifted, or unverified required capability state.

### Changed

- `meridian adopt` and `finalize-adoption` write `workflowBaselineVersion`
  alongside `frameworkVersion`, so an adopted project records the template
  baseline separately from the CLI release.
- `check_migrations()` now rejects only a migration that targets a version
  ahead of `VERSION`; the last migration may lag behind it, which is what lets
  a CLI-only release bump `VERSION` without a migration.
- The documentation describes the `frameworkVersion` /
  `workflowBaselineVersion` / `protocolVersion` split and the release
  procedure for CLI-only and template-changing releases.

## [1.1.49]

This section collects every release from 1.1.34 through 1.1.49, which were
never given individual headings; `migrations/*.json` records the exact
migration for each version and remains the authoritative detail.

### Added

- Migration `045-isolated-task-worktrees` makes a deterministic linked
  worktree the execution boundary for every task and adds parallel-safe
  serialized integration.

- Migration `046-integration-validation-evidence-reuse` reuses commit-bound
  task validation evidence during serialized worktree integration and replaces
  unconditional complete combined-tree validation with a deterministic bounded
  gate and conservative escalation rules.

- Migration `048-manifest-capability-profile-schema` introduces manifest
  protocol v2 with canonical `workflowMode` and validated capability-profile
  declarations backed by the versioned capability catalog.

- Migration `051-bounded-worktree-lifecycle` installs the host-neutral bounded
  worktree lifecycle, prepare-before-worker routing, candidate-bound
  integration evidence, and exact Codex command rules.

- Migration `052-install-meridian-self-hosting-surfaces` installs the
  workflow-neutral policy, evidence, Codex read-guard, and worktree-safety
  surfaces used by the Meridian self-hosting profile.

- Migration `049-task-identity-policy` adds the optional, closed
  `.meridian/task-identity.json` declaration and one host-neutral resolver for
  task, path, handoff, review, and budget identities. Projects without the
  declaration remain in backwards-compatible `opaque` mode; the migration
  does not create the declaration or rewrite project-owned task authorities.

- Migration `047-codex-worktree-access` adds repository-qualified task
  worktree paths, an explicit and atomic Codex permission-profile configurator,
  a host-capability doctor, and the same bounded command policy for Lean
  Delivery and Governed SDD. Existing legacy worktrees remain untouched.

- Governed-SDD now defines an authority-change restart procedure for rejected
  implementation attempts: an accepted design amendment precedes a distinct
  retry, while the rejected tip and its evidence remain retained.

- Governed-SDD upgrades now distribute `.codex/hooks.json`, registering a
  trusted-project Codex `PreToolUse` guard for Bash reads. The adapter blocks
  only recognised over-budget static reads; unknown syntax and internal errors
  allow safely. It reports denial through stderr and structured hook output.

- Governed-SDD upgrades now distribute `.codex/rules/meridian.rules`, a
  project-scoped Codex command-approval policy. Once the project's `.codex`
  layer is trusted, it allows the governed workflow's routine Git and narrow
  Meridian validation commands, forbids force-push forms, and leaves risky or
  state-changing commands to normal approval. Local appended rules survive the
  normal managed-file merge; Lean Delivery does not receive this file.

### Fixed

- Governed-SDD review now starts with a fail-closed verification of the
  completion handoff and registered task worktree before reading the task,
  implementation, or diff. Migration `050-review-worktree-preflight` removes
  the obsolete primary-checkout switching and fast-forward review procedure,
  preserves sequential worktree ownership, and requires sessions launched in
  the primary checkout to root every review operation in the verified task
  worktree.

- Codex's read guard now denies recognised over-budget absolute file reads
  outside the project root. Previously it attempted to render every denied
  path relative to the project, and an external path such as `/tmp/file`
  triggered the advisory-safe allow path instead.

- `meridian budget spend` (and `execution evidence` / `execution investigate`,
  which spend through it) now admits exactly `cap` recorded uses; the
  (`cap`+1)th is rejected with `BLOCKED`. Previously a cap of N admitted only
  N-1 uses, so `Diagnostic attempts: 3` allowed two attempts and a task
  override of `1` allowed none. `cap/cap` is now a valid persisted state, and
  the rejection message states how many of the allowed uses are already
  recorded. A rejected spend still leaves `.meridian/budget.json` unchanged.
  This is a CLI-only change: no template text changed, so there is no
  migration. The CLI change reaches every project immediately through
  `MERIDIAN_ROOT`, while an un-upgraded project's template docs may still say
  "reaching one requires `BLOCKED`"; that wording is ambiguous rather than
  wrong under the new boundary.

## [1.1.33]

### Changed

- Migration `036-explicit-claude-agents-pointer` replaces the fragile prose
  signature used to recognize project-owned `CLAUDE.md` pointers with the
  explicit `MERIDIAN:CLAUDE-AGENTS-POINTER v1` marker. Existing prose-based
  pointers remain compatible; the upgrader still verifies that `AGENTS.md`
  carries every shared capability and that the pointer has none of its own.

## [1.1.32]

### Added

- Migration `035-tech-design-alignment-prompt` adds a read-only operator
  prompt that aligns a tech-design chat to current constraints, active work,
  dependencies, risks, and evidence gaps before it answers project questions
  or scopes an explicitly requested change.

## [1.1.31]

### Changed

- Migration `034-operator-prompts-location-aware` makes the Governed-SDD
  operator cookbook resolve project-declared queue, task, and review-record
  locations instead of hardcoding template paths. It combines the overlapping
  named-change and next-phase design prompts, makes the bounded `SPIKE` route
  visible during design, and adds a read-only framework-upgrade inspection
  prompt that cannot accidentally invoke adoption or an applying upgrade.

## [1.1.23]

### Added

- Migration `026-bound-the-queue-read` (docs/AUDIT_TOKEN_EFFICIENCY.md F9):
  `hooks/queue-briefing.sh` now resolves a project's declared queue location
  (the `execution-assets` "Canonical locations" override, when present and
  unambiguous) instead of only ever looking at `tasks/QUEUE.md`, and for
  governed-SDD's table format classifies each `QUEUED` row as startable or
  blocked on an unmet dependency (`ANSWERED` satisfies a dependency the same
  as `ACCEPTED`, per `task-lifecycle` v2, without joining the `ACCEPTED`
  tally), reading `QUEUE_ARCHIVE.md` too when a dependency has been archived.
  `queue-briefing` v1 in `docs/CONTEXT_BUDGET_POLICY.md` points a session at
  this resolved summary as the normal path. The hook runs from
  `$CLAUDE_PLUGIN_ROOT`, not a per-project copy, so every project sees the
  new briefing output immediately regardless of its own locked `VERSION`;
  only the policy text explaining it arrives on upgrade.

## [1.1.22]

### Removed

- Migration `025-retire-role-scoped-agent-rules`: retires `role-scoped-agent-rules`
  v1 (docs/AUDIT_TOKEN_EFFICIENCY.md F5), the first real use of task 007's
  retirement path. Under Claude Code's `CLAUDE.md` auto-injection the file
  enters the session in full before the rule is ever read, so it saved
  nothing there; for `AGENTS.md`, the rule's own fallback clause ("read the
  whole file instead of guessing" when a heading is unclear) meant it
  degraded to the unoptimized behavior under exactly the conditions where a
  session is least sure what it is reading — a conditional saving that
  vanishes under uncertainty, at the cost of ~1.4 KB of always-loaded policy
  text. Pure deletion, no `supersededBy`: nothing replaces this rule.

## [1.1.21]

### Added

- Migration `024-evidence-tiers-and-routing`: makes `Manual verification:
  required` cost one sentence of justification instead of being free to
  declare. `evidence-tiers` v1 in `docs/CONTEXT_BUDGET_POLICY.md` names three
  stack-agnostic tiers — structural, derived value, perceptual — and states
  that only tier 3 justifies manual verification. `task-blueprint` v6 adds a
  mandatory `Manual verification rationale` field. `manual-verification-precondition`
  v3 checks that rationale first, before the probe: a missing or
  wrongly-tiered rationale returns `BLOCKED` asking for the task to be
  re-scoped, without running the probe at all.
  `manual-verification-review-check` v1 in `docs/CODE_REVIEW_PROMPT.md` has
  the reviewer confirm the rationale matches the evidence actually gathered.
  Bundled with task 011's fix (unmarked, since `docs/EXECUTION_EVIDENCE_PROFILE.md`
  carries no protected markers): a warning that a first-lines output bound
  must consume the whole stream (`awk 'NR<=N'` / `sed -n '1,Np'`), never
  `head -n N` / `sed 'Nq'`, which turns `pipefail` into an intermittent
  false-failure generator as output grows past the bound.

## [1.1.20]

### Added

- Migration `023-spike-task-class`: adds a `SPIKE` task class so an
  implementation task that cannot evaluate its own acceptance criteria
  without first resolving an unknown has a named, bounded place to route
  to, instead of investigating inside its own branch and budget.
  `task-lifecycle` v2 adds the `ANSWERED | INCONCLUSIVE` lifecycle and
  states that only `ANSWERED` satisfies a dependency. `review-policy` v2
  names `SPIKE` as a third case alongside `Review: REQUIRED`/`NOT_REQUIRED`,
  with its own self-administered close-out gate, rather than leaving it in
  conflict with the prior prohibition on `NOT_REQUIRED` for unresolved
  design questions. `task-blueprint` v5 adds the spike shape
  (`Class`/`Question`/`Budget`/`Deliverable`/`Branch`) inside the existing
  single marker. `spike-routing` v1 adds the routing rule as a numbered
  step inside AGENTS.md/CLAUDE.md's Implementation workflow, so it is
  reachable without a second capability bump.

## [1.1.19]

### Fixed

- Migration `022-executable-probe-precondition`: closes a composition defect
  between two individually defensible rules. `manual-verification-precondition`
  v1 only asked an implementer to confirm they "can" produce manual/visual
  evidence before implementation, and its deterministic-test escape hatch let
  a passing automated test demote a failed manual/visual check to a secondary
  concern with no floor under it — in the incident this traces to, a failed
  GPU screenshot probe was demoted rather than treated as a stop condition,
  and nothing then bounded the exploration that followed. v2 promotes
  wording already proven in a downstream consumer project: evidence
  availability is confirmed only after an end-to-end probe actually
  succeeds and produces the exact channel the task will record, with a
  `BLOCKED` return when none succeeds. The deterministic-test escape hatch
  now suspends only the requirement to *capture* manual/visual confirmation
  as the sole gate, never the requirement to stop on a probe already
  attempted and failed, and the forbidden recovery is named explicitly:
  never respond to a failed probe by exploring the local environment for an
  alternative.

## [1.1.18]

### Changed

- Migration `021-concrete-execution-budgets`: makes the execution-evidence
  profile's bounds concrete instead of nominal, in the two places it
  previously left them to prose or to an empty placeholder.

  The output bound moves from prose into the literal command string. A worker
  previously ran a bare validation command and was asked to report a "concise
  success-output form" afterwards, but that instruction can only govern how
  output is restated once it has already returned to the session and been
  billed in full. The profile now records each required check as the exact
  command executed, including its own output-bounding pipeline stage, with
  `set -o pipefail` (or `${PIPESTATUS[0]}`) mandatory so the pipeline reports
  the validation command's own exit status rather than the trailing
  formatter's.

  The empty `[policy]` placeholders become default caps a project inherits
  without configuring anything: 3 diagnostic attempts per failure, 2 evidence
  captures per acceptance criterion, and a newly declared 2 context
  expansions per task, each with a one-line definition of what counts as one.
  Every default is a cap, not a target — exhausting it requires `BLOCKED` —
  and raising one requires a recorded rationale in the same shape
  `Reasoning justification` already uses.

  `docs/CONTEXT_BUDGET_POLICY.md` is amended on both counts, and
  `tasks/TASK_BLUEPRINT.md` gains three optional per-task override fields for
  the same caps. The template still names no language, build tool, or test
  runner, and prescribes no bound value; per-stack worked examples live only
  in this repository's own `WORKFLOW_GUIDE.md`. This makes the bounds exist
  and makes them concrete; enforcing them at runtime is later work.

## [1.1.17]

### Added

- Migration `020-reasoning-budget-contract`: makes a task's `Reasoning`
  declaration an exact permitted worker-runtime cap rather than a minimum or
  a suggestion. It adds `low` for focused mechanical work, requires a written
  rationale for `high`, and requires explicit developer authorization for
  `xhigh`. Implementers and reviewers must use a fresh session configured at
  the declared value; a mismatch or an unconfirmable setting blocks before
  substantive work, and agents may never escalate effort automatically.
  Lifecycle coordinators retain the lowest available effort because they only
  inspect durable state and delegate substantive work.

## [1.1.16]

### Fixed

- Migration `019-marker-aware-capability-insertion`: framework upgrade now
  handles the safe case where a project moved intact protected marker blocks
  and a newer template adds a new protected capability. Rather than reporting
  a line-based merge conflict, it appends the new byte-identical block without
  changing project text. Altered or missing inherited protected blocks remain
  blocking conflicts.

## [1.1.15]

### Added

- Migration `018-execution-evidence-profile`: adds the
  `execution-evidence-profile` capability to Governed SDD. It separates
  stack-agnostic evidence discipline from project-specific commands: the
  protected context policy requires concise successful output, progressive
  diagnostics, complete per-hunk diff review, planned manual evidence, and no
  duplicate session context, while the new project-owned
  `docs/EXECUTION_EVIDENCE_PROFILE.md` records the actual commands, logs,
  capture channels, and runtime settings. Required validation, independent
  review, and manual acceptance evidence are unchanged.

## [1.1.14]

### Added

- Migration `017-manual-verification-precondition-and-record`: adds
  `manual-verification-precondition` and `manual-verification-record` to
  Governed SDD. Caught in real use: a task requiring manual/visual proof
  passed every automated check and only then discovered, mid-implementation,
  that the evidence itself was unavailable — forcing a wasted resumption
  session to finish what a precondition check would have caught for free.
  `manual-verification-precondition` (step 1 of `AGENTS.md`/`CLAUDE.md`'s
  Implementation workflow) makes the implementer confirm evidence
  availability *before* writing any code when the task declares `Manual
  verification: required`, returning `BLOCKED` immediately instead of
  discovering the gap later, and prefers a deterministic test as primary
  acceptance evidence over a GUI check when one exists (e.g. a geometry or
  layout assertion). `manual-verification-record` gives
  `docs/COMPLETION_REPORT_TEMPLATE.md` and `docs/REVIEW_RECORD_TEMPLATE.md` a
  dedicated field — a named screenshot, the view checked, and the result —
  so a reviewer can use it without reconstructing the session; the review
  record's own marker sits outside `review-remediation-record`'s existing
  marker to avoid the documented nesting limitation.

## [1.1.13]

### Added

- Migration `016-task-blueprint-manual-verification-v2`: bumps
  `task-blueprint` to `capabilityVersion: 2`, adding a `Manual verification:
  [none / required]` field immediately after `Review` — the declaration
  migration 017's precondition and record capabilities key off.

## [1.1.12]

### Added

- Migration `015-role-scoped-agent-rules`: adds the `role-scoped-agent-rules`
  capability to Governed SDD. `AGENTS.md`/`CLAUDE.md` states rules for every
  role in one file; this scopes how much of it a session actually needs to
  read. Every role reads a shared core (introductory rules through "Command
  triggers", plus "Owner-acceptance workflow"); an implementer additionally
  reads the implementation-side sections, a reviewer-integrator the
  review-side sections, and the orchestrator does not read the file at all
  beyond confirming its own trigger phrases (already true per this policy's
  existing "Lifecycle orchestration" section). Sections are matched by
  heading text with an explicit fallback to reading the whole file when a
  heading is missing or the mapping is unclear — this narrows a known-safe
  read, it does not license skipping unfamiliar content.

  This is the cheaper alternative to physically splitting `AGENTS.md`/
  `CLAUDE.md` by role, which was evaluated and set aside: relocating an
  existing capability marker to a new file would require a migration
  category the framework doesn't have yet (previous migrations only ever
  add or version a capability, never move it between files) and would orphan
  the operative prose a customized project has already written next to that
  marker in its current location (consumer project A and consumer project B both did this in
  their retrofit onto capability markers). A prompt-level reading rule gets
  most of the same benefit — implementer and reviewer sessions each skip
  roughly a quarter to a third of the file — with no migration risk and no
  retrofit cost on already-adopted projects. Physical splitting stays a
  future option once enough adopting projects exist to justify a one-time
  relocation migration.

## [1.1.11]

### Added

- Migration `014-minimal-read-only-status`: adds the
  `minimal-read-only-status` capability to Governed SDD. It distinguishes a
  lightweight read-only project-status report from a conformance audit,
  constraining the default reads to workflow mode, non-terminal queue state,
  direct dependency readiness, and Git state. Expanded reads require a stated
  evidence gap. The governed-SDD operator prompt and Codex/Claude Code skills
  now route explicit status requests through this profile.

- Fixed a bug in the Phase 3 cosmetic-vs-real conflict check (`upgrade`/
  `adopt`): the set of capabilities a conflicting file had to satisfy to be
  downgraded to `VERIFIED` was derived from each migration's `managedPaths`
  — every file that migration's diff *touches* — rather than from which
  capability markers the file's own template actually *carries*. A
  migration can mention a capability in several files' prose while marking
  it in only one (`migrations/011-whole-file-baseline-capabilities.json`
  pairs four capabilities with four different single-purpose files via
  parallel arrays); the old code required all four in every one of the
  four files, so none of them could ever verify. `capability_ids_for_file`
  is replaced by `capability_ids_in_template`, which reads the marker ids
  directly out of the framework's own template for that file — the same
  ground truth `audit` already uses. The satisfied-check itself is also
  tightened from "marker version present" to a byte-exact comparison of
  the local marker's content against the template's, closing a gap where a
  version-tagged marker with corrupted inner text was wrongly accepted.
  Caught while retrofitting a real, heavily customized project (consumer project A)
  onto capability markers: `meridian audit` passed all 31 markers while
  `meridian upgrade --check` still reported 5 files as blocking `CONFLICT`s
  — a contradiction between the two commands that shouldn't be possible
  since they check the same protected regions.
- `meridian audit --project <path> [--mode ...]`
  ([commands/meridian-audit.md](commands/meridian-audit.md)): a new,
  read-only command. Phase 4 of
  [migrations/CAPABILITY_MARKERS.md](migrations/CAPABILITY_MARKERS.md) —
  verifies every `MERIDIAN:BEGIN`/`END` protected region in a project's
  managed files still matches the framework's released text for that exact
  capability version, in that exact file (`PASS`/`FAIL`), and reports a
  project marker version the current template no longer carries as `SKIP`
  (a staleness question for `upgrade`, not a drift question for this
  command) rather than a false failure. Does not yet include the
  originally-proposed `ACCEPTED`-task/review-record consistency check from
  `QUALITY_COMPLIANCE_ROADMAP.md` Tier 2 — that remains a separate addition
  to this same command.
- Phase 3 of [migrations/CAPABILITY_MARKERS.md](migrations/CAPABILITY_MARKERS.md):
  `meridian upgrade`/`adopt` now tell a cosmetic merge conflict from a real
  one. When a file's three-way merge conflicts, and that file's *own*
  content already carries a satisfied capability marker for every migration
  that manages it, the conflict downgrades to a new `VERIFIED` plan action
  (file left untouched, does not block the upgrade) instead of a blocking
  `CONFLICT`. The check is scoped to the conflicting file's own text, not
  the whole project — an earlier version of this checked project-wide
  presence and produced a false positive (a `PROJECT_WORKFLOW.md` conflict
  wrongly downgraded because an unrelated capability happened to be
  satisfied elsewhere in the project), caught by the existing conflict
  regression tests before it shipped.
- Phase 2 of [migrations/CAPABILITY_MARKERS.md](migrations/CAPABILITY_MARKERS.md):
  `detect_capabilities()` is now version-aware — it reads each migration's
  `capability`/`capabilityVersion` fields and compares against the
  project's `MERIDIAN:BEGIN` marker version, so a future migration that
  *modifies* an existing capability (not just adds a new one) becomes
  detectable, with a distinct message for "no marker at all" versus "marker
  present but below the required version." A legacy fallback
  (`LEGACY_CAPABILITY_EVIDENCE`) keeps every project adopted before markers
  existed (migration 006) correctly detected at v1 via the old phrase
  check — caught by testing this against two real, already-adopted
  projects, which regressed to fully `MISSING` without it.
  `assisted_implementer_prompt` now surfaces a migration's `delta` field
  when present, so a capability version bump is scoped to the actual
  change instead of implying a from-scratch rewrite.
- `meridian upgrade --apply --owner-reconciled`: registers the target
  version and baseline snapshot without touching any managed file, for a
  project too customized for the automatic three-way merge to ever resolve
  cleanly (a permanently conflicting `AGENTS.md`/`CLAUDE.md`, not a one-off
  conflict) whose developer has already reconciled every managed file by
  hand. Mirrors `finalize-adoption --owner-accepted`'s escape-hatch shape.
  `adopt` already had a capability-aware path for a project with no manifest
  yet; `upgrade` had no equivalent for one that is already locked but too
  divergent for line-based merging.

Framework-CLI improvements to `bin/meridian` for capability-aware adoption.
These change tooling and documentation only — no generated-project managed
file changed, so no migration record or `VERSION` bump applies.

### Added

- `meridian adopt --assisted --check` now computes a single, durable
  `NEXT_ACTION` (`IMPLEMENT_MIGRATION` → `REVIEW_MIGRATION`/`ADDRESS_REVIEW`
  → `FINALIZE`, or `BLOCKED`) from detected capabilities and a
  machine-readable `.meridian/adoption-review.md` header
  (`Verdict:`/`Attempt:`), mapped onto the CLI's existing exit codes so a
  coordinator can drive the whole migration with no memory of its own — see
  [migrations/ASSISTED_ADOPTION.md](migrations/ASSISTED_ADOPTION.md).
- `--mode` and `--from` are auto-detected on `adopt` and `finalize-adoption`
  when unambiguous (mode from the project's `PROJECT_WORKFLOW.md` lock,
  version from the sole packaged baseline), falling back to an explicit
  error naming the flags needed.
- `--emit implementer|reviewer|orchestrator` extracts a single prompt block
  from `adopt --assisted --check`, without parsing the `_BEGIN`/`_END`
  markers, for a host or human that only needs one block.
- `finalize-adoption` now refuses to run unless `.meridian/adoption-review.md`
  records an unconditional `APPROVE` (no unchecked findings) for the current
  attempt, or an explicit `--owner-accepted` override is passed — mirroring
  the existing `Accept <TASK-ID>` owner-acceptance path.
- The two-consecutive-`CHANGES_REQUESTED` retry limit is now enforced by the
  CLI itself (`BLOCKED`), not left to a coordinator's memory of prior turns.
- `.meridian/baselines/<version>/` snapshots older than the manifest's
  current `frameworkVersion` are pruned automatically once `upgrade --apply`
  or `adopt --apply` completes, since only the current version's snapshot is
  ever read again.
- `skills/meridian-governed-sdd-claude-code/SKILL.md` and
  `skills/meridian-governed-sdd/SKILL.md` document how a coordinator dispatches
  the implementer and reviewer roles as genuinely independent sessions (Claude
  Code Task-tool subagents, or separate fresh chats where no subagent tool is
  available) driven by that loop.

## [1.1.10]

### Fixed

- Migration `013-language-policy-v2`: the `language-policy` marker (migration
  011) wrongly included the per-project `**Conversation language:**
  `[Conversation language]`` declaration inside its protected region.
  `commands/meridian-init.md` step 9 replaces that placeholder with the
  project's actual chosen language during initialization — so every real,
  correctly initialized project would have diverged from canon on that exact
  line and failed `meridian audit` on day one, not just consumer project A. Caught
  before shipping anywhere, while working out the consumer project A retrofit.
  Verified live: a project with the placeholder replaced (exactly what
  `/meridian-init` produces) now passes.

## [1.1.9]

### Added

- Migration `012-agents-claude-residual-capabilities`: backfills capability
  tracking for `AGENTS.md`/`CLAUDE.md`'s remaining independently-changeable
  sections — `command-triggers`, `review-mode-boundary`,
  `owner-acceptance-workflow`, `implementer-reviewer-handoff`,
  `reviewer-integrator-identity` — each at `v1`. `review-mode-boundary` is
  introduced already path-parameterized (referencing `PROJECT_WORKFLOW.md`'s
  canonical locations instead of a hardcoded `tasks/reviews/<TASK-ID>.md`),
  since a brand-new capability has no reason to ship with a defect a later
  migration would just have to fix again. `### Implementation workflow`'s
  steps 1-4 and 6-8 remain untracked: the marker grammar has no nesting, and
  step 5 already carries `validation-scoping`'s marker inside that same
  numbered section. This closes out the marker-retrofit sweep of every
  managed governed-SDD file except the two intentionally excluded ones
  (`docs/ARCHITECTURE_DECISIONS.md`, a project-owned scaffold, and
  `docs/OPERATOR_PROMPTS.md`, an explicitly non-normative cookbook).
  Verified live: a fresh vanilla project passes `meridian audit` on all 34
  marker occurrences.

## [1.1.8]

### Added

- Migration `011-whole-file-baseline-capabilities`: backfills capability
  tracking for the four remaining single-purpose managed files that had
  none — `LANGUAGE_POLICY.md`, `tasks/TASK_BLUEPRINT.md`,
  `docs/CODE_ORGANIZATION.md`, `docs/AUDIT_PROMPT_READ_ONLY.md` — each
  wrapped whole in one `v1` marker. Purely additive. Verified live: a fresh
  vanilla project passes `meridian audit` on all 24 marker occurrences
  across every migration with markers so far.

## [1.1.7]

### Added

- Migration `010-project-workflow-baseline-capabilities`: backfills capability
  tracking for `PROJECT_WORKFLOW.md` — the single most important managed file,
  since it carries the `GOVERNED_SDD` mode lock itself — which had none until
  now. Wraps its eight independent rule sections
  (`workflow-mode-lock`, `document-precedence`, `task-lifecycle`,
  `execution-assets`, `roles`, `review-policy`, `git-workflow`,
  `execution-discipline`) each in its own `v1` marker, introducing the
  `capabilities` list field to the migration schema alongside the existing
  singular `capability`/`capabilityVersion` fields, so one migration record
  can declare several independent, pre-existing capabilities at once instead
  of needing eight near-duplicate records. Purely additive: no section's
  content changed. Verified live: a fresh vanilla project passes `meridian
  audit` on all 20 marker occurrences across the framework's four
  migrations-with-markers so far.

## [1.1.6]

### Changed

- Migrations `008-review-remediation-record-v2` and
  `009-lifecycle-orchestration-v2`: the canonical text for both capabilities
  stops hardcoding `tasks/reviews/<TASK-ID>.md` inline, referencing a new
  "Canonical locations" declaration in `PROJECT_WORKFLOW.md`'s Execution
  assets section instead (default unchanged). Motivated by consumer project A: its
  own directory conventions (`docs/tasks/...`) were baked into the literal
  wording of the review-remediation-record and lifecycle-orchestration
  capabilities, so wrapping consumer project A's actual text in a marker would have
  been a false claim of byte-identical canon. Parameterizing the reference
  lets any project's own declared locations sit outside the protected
  region without changing the canonical text at all.
- **Real consequence, not a bug**: because this changes what "the current
  version" of these two capabilities' canonical text actually is, both
  capabilities require v2 now. The `LEGACY_CAPABILITY_EVIDENCE` fallback
  (added in migration 006/phase 2) only ever proves v1, by design — so a
  project relying on it, including the two real projects adopted so far
  (`consumer project B`, `consumer project A`), now correctly reports both capabilities `MISSING`
  (stale) rather than falsely `PRESENT`, and needs another assisted-adoption
  pass to reach `1.1.6`. Verified live, read-only, against both.

## [1.1.4]

### Added

- Migration `007-validation-capability-markers`: wraps `validation-scoping`
  (004) and `ci-verified-validation` (005) in the same
  `<!-- MERIDIAN:BEGIN capability=<id> v1 --> / <!-- MERIDIAN:END -->`
  markers migration 006 gave to 001/002 — bringing all four framework
  capabilities shipped so far under version-aware detection, cosmetic-vs-real
  conflict resolution, and `meridian audit` integrity checking. Purely
  additive: detection and verification code are unchanged, only the marker
  text and the `capability`/`capabilityVersion` fields backfilled onto 004
  and 005's own records. Also genericized a Rust-specific example
  (`cargo test/build/clippy`) in the validation-scope rule to a stack-agnostic
  one, and required `extract_marker_block`'s parser to accept a marker sitting
  inline mid-sentence (not just on its own line), since `validation-scoping`'s
  text in `AGENTS.md`/`CLAUDE.md` is one clause inside a larger numbered step,
  not a standalone section like 001/002's.

## [1.1.3]

### Added

- Versioned capability markers (Phase 1 of
  [migrations/CAPABILITY_MARKERS.md](migrations/CAPABILITY_MARKERS.md)):
  the review-remediation-record (001) and lifecycle-orchestration (002)
  capability text in `AGENTS.md`, `CLAUDE.md`,
  `docs/REVIEW_RECORD_TEMPLATE.md`, and `docs/LIFECYCLE_ORCHESTRATION.md` is
  now wrapped in `<!-- MERIDIAN:BEGIN capability=<id> v1 -->` /
  `<!-- MERIDIAN:END -->` markers. Purely additive in this migration —
  detection (`detect_capabilities()`) and verification are unchanged; the
  markers exist so later phases can compare a required capability version
  against what a project actually has, and tell a cosmetic merge conflict
  (the project already has the rule, worded its own way) from a real gap,
  instead of the phrase-only detection that failed to recognize a real,
  pre-token governed-SDD project twice this session.
- Migration `006-capability-markers`.

## [1.1.2]

### Added

- CI-first validation-evidence rule
  ([docs/PULL_REQUEST_POLICY.md](templates/workflows/governed-sdd/docs/PULL_REQUEST_POLICY.md)):
  a reviewer with a completed CI run for the exact task-branch commit that
  covers the task's validation surface uses that run as evidence instead of
  re-running the same checks locally — a real independent, tamper-evident
  source, unlike the implementer's own self-report. Without such a run, the
  reviewer performs its own validation scoped to the diff per
  `docs/CONTEXT_BUDGET_POLICY.md`, rather than trusting a bare "tests
  passed" claim or duplicating the implementer's full run wholesale.
- `docs/COMPLETION_REPORT_TEMPLATE.md`'s `Validation` field now requires the
  exact commands and exit status, or the CI check run, instead of a bare
  pass/fail assertion — evidence has to be falsifiable to be evidence.
- Migration `005-ci-verified-validation`.

## [1.1.1]

### Added

- Validation-scope rule
  ([docs/CONTEXT_BUDGET_POLICY.md](templates/workflows/governed-sdd/docs/CONTEXT_BUDGET_POLICY.md)):
  before running validation, classify the diff by surface
  (documentation/policy text vs. source/build) and run only the commands
  whose surface the diff actually touches. A documentation/policy-only change
  now explicitly skips the project's full build/test/lint suite and states so
  in the report, instead of running it defensively. A reviewer verifies the
  same scoping and flags disproportionate or missing validation as a finding.
  This closes a real, measured gap: a 7-file documentation-only migration to
  another project burned roughly 200K tokens across two review sessions,
  almost entirely from a full `cargo build`/`test`/`clippy` run that had
  nothing to validate.
- `meridian adopt --assisted`'s implementer and reviewer prompts now state the
  same scoping explicitly, since every framework-managed file is
  documentation/policy text by construction.
- Migration `004-validation-scoping`.

## [1.1.0]

### Added

- `bin/meridian` / `scripts/meridian.py`: a portable CLI that locks a
  generated project to its installed Meridian version
  (`.meridian/manifest.json` plus baseline snapshots) and performs a
  three-way merge for framework upgrades (`meridian upgrade --check/--apply`),
  applying nothing when any managed file conflicts.
- `meridian adopt --from <version> [--assisted]` for projects that predate the
  lockfile: a generic three-way merge against a packaged legacy baseline, or
  capability-aware detection of missing framework behavior for a project that
  has intentionally customized its workflow documents.
- `release-baselines/1.0.0/`: the immutable packaged Governed SDD template
  snapshot for Meridian 1.0.0, the merge base for adopting a pre-lockfile
  project.
- Migration `003-framework-updater` (this release).

## [1.0.2]

### Added

- `Run lifecycle <TASK-ID>` autonomous orchestration
  ([docs/LIFECYCLE_ORCHESTRATION.md](templates/workflows/governed-sdd/docs/LIFECYCLE_ORCHESTRATION.md)):
  a coordination-only role that starts distinct implementer and
  reviewer-integrator sessions, loops through requested-change remediation via
  the durable review record, and integrates only after approval and all
  repository/forge gates.
- Migration `002-lifecycle-orchestration`.

## [1.0.1]

### Added

- Durable review-remediation record
  (`docs/REVIEW_RECORD_TEMPLATE.md`, `tasks/reviews/<TASK-ID>.md`): on
  `CHANGES_REQUESTED`, the reviewer records prioritized, evidence-backed
  findings and returns the task to `IN_PROGRESS` instead of relying on chat
  output as the handoff. `Address review <TASK-ID>` resolves exactly the
  unchecked findings.
- Migration `001-review-remediation-record`.

## [1.0.0]

Initial packaged Governed SDD workflow: ADRs, dependency-gated atomic tasks,
`REQUIRED`/`NOT_REQUIRED` review policy, reviewer-integrator-led `main`
integration, and the Lean Delivery mode for low-risk work. Snapshotted verbatim
at [release-baselines/1.0.0/](release-baselines/1.0.0/) as the reference point
for adopting projects that predate `.meridian/manifest.json`.
