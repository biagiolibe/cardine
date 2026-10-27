# Host integration — work item 9

## Scope and authority

This is the implementation plan for work item 9 of `ADR_CARDINE_1_0.md`,
decisions 7, 8, and 14 rules 2 and 4. It schedules no implementation here.
Work items 6 and 7 supply the single workflow, presets and status service;
work item 8 supplies the receipt-backed engine and role/session protocol.
Hours are estimates, not scope limits. Each row below is a separate task.

All tests, including host subprocess tests, use disposable homes, configuration
roots, repositories and worktree roots. Pass an isolated environment to child
processes; never borrow the real host configuration or authentication directory.
No row applies setup to the real home, changes this repository's frozen host
files, or creates `.cardine/` in this repository. Keep operating this repository
with installed Meridian 1.4.1 until work item 10. Product template changes are
tested in disposable consumer projects. Decision 14 rule 5 evaluations remain
after work item 9 and are not rows in this plan.

## Inventory and replacement ownership

Paths are product source paths unless prefixed with `~` or described as generated.
“Old name” includes embedded names and ownership markers, not just filenames.

| Shipped or written surface today | Owning module / entry point | Old name? | Target / disposition; row |
| --- | --- | --- | --- |
| `commands/meridian-init.md` | Plugin command; manual template-copy bootstrap | Yes | `commands/cardine-init.md`, thin route to `cardine init`; H2b |
| `commands/meridian-adopt.md`, `commands/meridian-upgrade.md` | Plugin adoption/upgrade commands; `templates/upgrade.py` | Yes | `commands/cardine-adopt.md`, `commands/cardine-upgrade.md`; H2c |
| `commands/meridian-task.md`, `commands/meridian-audit.md` | Plugin task/audit routes | Yes | `commands/cardine-task.md`, `commands/cardine-audit.md`; H2c |
| `skills/meridian-lean-delivery/SKILL.md`, `skills/meridian-governed-sdd/SKILL.md` | `hosts/skills.py`; Codex links | Yes | Exactly two shared Cardine skills, choice D1; H3a/H3b |
| `skills/meridian-lean-delivery-claude-code/SKILL.md`, `skills/meridian-governed-sdd-claude-code/SKILL.md` | Claude plugin skill variants | Yes | Remove variants after shared skills exist; H3b |
| `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` | Claude plugin distribution | Yes | Same host-required paths, plugin and marketplace identity `cardine`, installation `cardine@cardine`; H3c |
| `hooks/hooks.json` | Claude plugin hook registration | Yes | Frozen installation copy: leave intact until work item 10. Product plugin stops auto-registering these hooks; H3c |
| `hooks/queue-briefing.sh` | Shell queue/language/budget briefing | Yes | Frozen copy retained for installation only; new Python status-only briefing through user hook; H1a/H4c |
| `hooks/read-guard.sh` | Claude native Read guard | Yes | Frozen copy retained; one shared Python guard for both payloads; H1b/H4c |
| `hooks/stop-audit.sh` | Wrapper for `scripts/stop_audit.py` | No Cardine-incompatible basename; payload is diagnostic | Replace wrapper with direct Python module entry; H1c/H3c |
| `scripts/codex_read_guard.py`, `scripts/stop_audit.py` | `cli.py` hook dispatch | Codex guard retains installation references | Move product logic into `hosts/read_guard.py`, `hosts/stop_audit.py`; no parallel implementation; H1b/H1c |
| `src/cardine/hosts/briefing.py` | Shared status formatter, currently preserves non-queue caller bytes | Legacy queue headings in compatibility removal | Status-only formatter, no legacy shell pipeline; H1a |
| `templates/single/AGENTS.md`, `templates/single/CLAUDE.md` | Router templates; `templates/catalog.py` | No; still route by procedural documents | Shared entry routes to engine/role procedures, no hook installation instruction or old workflow route; H3d |
| `.claude/settings.local.json` in consumers | `hosts/claude.py`, setup | Current command entries use Cardine, but contain repository test commands | Replace only owned entries with product policy; preserve adopter entries; H5a |
| Claude allowlist and denylist constants | `hosts/claude.py` | Duplicate detection still recognizes old plugin name | Remove repository-specific tests, broad direct main push and unsafe lifecycle approvals; add role/path protection; H5a |
| `~/.codex/rules/default.rules` managed block | `hosts/codex.py`, setup | `MERIDIAN` block markers | Move owned policy to `~/.codex/rules/cardine.rules`; preserve unrelated default rules; H4a |
| Consumer `.codex/rules/meridian.rules` | Doctor expects this path; legacy distribution no longer in `templates/single/` | Yes | User `cardine.rules`; diagnose/remove only proven owned consumer duplicate during explicit migration; H4a/H4d |
| `~/.codex/config.toml`, exclusive backup files | `hosts/codex.py` | `meridian-worktrees`, managed markers and description | Cardine block, `cardine-worktrees` base permission profile, separate role profiles; preserve user TOML, restrictive uniquely named `.cardine-backup-*`; H4a/H5b |
| Consumer `.codex/hooks.json` | Legacy generated hook adapter; frozen copy in this repo | Invokes old CLI | User `~/.codex/hooks.json` registration, subject to runtime verification; no new consumer hook copies; H4c/H4d |
| `~/.agents/skills/meridian-lean-delivery`, `~/.agents/skills/meridian-governed-sdd` | `hosts/skills.py`, setup | Yes; also warns about `~/.codex/skills/meridian-*` copies | Two Cardine links; migrate only links proven owned, warn about foreign copies; H3b |
| Resolved private worktree root; user `config.json` | `hosts/setup.py`, `worktree/storage.py` | Legacy installations may use old roots | Cardine configuration under `$XDG_CONFIG_HOME/cardine/config.json` or `~/.config/cardine/config.json`; default `~/.cardine/worktrees`; retain explicit-root conflict checks; H4b |
| Consumer candidate-validation, project and task-identity declarations | `hosts/setup.py` | Current product paths selected by shared layout | `.cardine/candidate-validation.json`, `.cardine/project.json`, `.cardine/task-identity.json`; owned init/setup operation, no implicit conversion of this repo; H2a/H4b |
| Setup operation records, staged replacements and backups | `hosts/effects.py`, `lifecycle/file_operation.py` | Cardine operation infrastructure already present | Reuse operation-owned paths and replay; not new gate authorship evidence; H4b/H4c |
| `setup`, `codex configure`, `codex doctor`, probes | `hosts/setup.py`, `hosts/codex.py`, `cli.py` | Doctor still probes old worktree command and file | `cardine setup`, `cardine doctor --host claude|codex`; evaluate host decisions and invocation, retain compatibility only as a thin CLI alias if D4 chooses it; H4d/H5d |
| `CodexProfileAdapter`, `ClaudeProfileAdapter`, `HostTransport`, `RoleProfile` | `hosts/launch.py` (102) | No | Preserve protocol and request/session receipts; wire concrete verified transports with separate roles; H5c |

No other host asset is implied by a generic directory wildcard. Fixed native
filenames such as `AGENTS.md`, `CLAUDE.md`, `settings.json`, `config.toml`,
`hooks.json`, `plugin.json`, and `SKILL.md` remain native names. Every owned
identifier, hook command, marker, profile, link, slash command and plugin name
inside them uses Cardine. Use `CARDINE_ROOT` for explicit runtime discovery;
host-provided `CLAUDE_PLUGIN_ROOT` and `PLUGIN_ROOT` are native variables and
are not renamed. No new product hook invokes `bin/meridian`.

## Target

### Two skills and command routing

Exactly two host-neutral skill bodies ship. D1 leaves their semantic split
undecided, with complete names and routes for each option:

| D1 option | Skill 1 | Skill 2 | Routing consequence |
| --- | --- | --- | --- |
| A: preset pair | `cardine-lean`: lean init, assigned implementation/review/remediation, lifecycle and status | `cardine-governed`: governed equivalents and independent review requirement | Both select policy from the configured preset; mismatch is diagnosed, never changes configuration. Shared route text must not recreate two workflow engines. |
| B: operation pair | `cardine-project`: init/adopt/setup/upgrade, explicit audit and status | `cardine-delivery`: assigned implementation, review, remediation and lifecycle for both presets | Preset is a runtime input; project administration is separate from task execution. |

For either option, installation paths are `skills/<selected-name>/SKILL.md`
and `~/.agents/skills/<selected-name>` for Codex; Claude discovers the same two
source bodies through the Cardine plugin. No `-claude-code` copies remain.
`Proceed with` and `Address review` route to the assigned engine action;
`Review` routes to independent review; `Accept` and `Run lifecycle` route to
`docs/LIFECYCLE_ORCHESTRATION.md` and the engine's authorized next step, never
the absent `docs/workflows/LIFECYCLE.md`. Human acceptance uses the existing
authorized developer channel, never a role label in a prompt.

The five `cardine-*` slash commands remain thin discoverable entry points.
`cardine-init` invokes the CLI bootstrap instead of copying files. Init asks
for preset, conversation language, task identity and project validation choices
required by current declarations; it does not choose human policy defaults.
Init previews and applies only its authorized project; machine setup remains
a separate consented operation. No initial task or ADR is invented.

### User-level hooks, one implementation each

| Hook | Single Python implementation and command | Claude binding | Codex binding |
| --- | --- | --- | --- |
| Turn briefing | `hosts/briefing.py`; `cardine hook briefing --host <host>` | User `~/.claude/settings.json`, `UserPromptSubmit` | User `~/.codex/hooks.json`, corresponding turn event, verified by H4d |
| Read guard | `hosts/read_guard.py`; `cardine hook read-guard --host <host>` | User `PreToolUse`, native Read and recognized shell reads | User `PreToolUse`, recognized shell payloads |
| Stop audit | `hosts/stop_audit.py`; `cardine hook stop-audit --host <host>` | User `Stop` | User `Stop`, verified event/payload |
| Protected operation guard | `hosts/permissions.py`; `cardine hook permissions --host <host>` | User `PreToolUse` for writes and command execution | User `PreToolUse` plus native rules/profile restrictions |

Host payload decoding is an adapter inside each implementation, not a second
policy engine. Unknown tools/syntax are not evidence of permission enforcement.
Advisory briefing failure reports unavailable status without inventing counts;
outside a configured project it is silent. Denial hooks provide the host's
required structured output plus stderr/exit semantics proven by probes.
Unknown protected operations refuse a role session instead of silently falling
back to an unrestricted profile. D2 covers availability of Codex user events.

The briefing emits only the work item 7 status representation: configured
preset, validated totals, startable IDs, active tasks and diagnostics using
`tasks/status.py`. Reuse that service's rendering contract; formatting may
select its compact fields but may not derive eligibility, count queue rows,
resolve dependencies, infer status from archives or read prose as state.
Do not preserve caller language, budget, setup-advice or legacy queue blocks.
It performs no writes, including `status --write`, import, repair, journal or
receipt writes. Incomplete status remains visibly incomplete.

## Host permissions and evidence

Protect canonical `.cardine/tasks/` (including embedded `run.receipts`, hidden
`.<task>.intent.json` and staged task outputs), `.cardine/evidence/`, adjacent
`.<filename>.<operation>.<index>.stage` artifacts, Git common-directory
`cardine-operations/` and the temporary `cardine-operations/` host-operation
records resolved by `receipts.host_path`. Receipts are embedded in state today;
do not invent a separate `.cardine/receipts/` store. Enumerate actual paths from
the receipt/file-operation resolvers in H5a, including external worktree and
common-directory locations, before installing policy. Include every other
contract/evidence output trusted by gates. Deny direct writes, deletion,
rename, replacement and symlink
aliases through native edits and shell tools. The trusted Cardine operation may
write its own outputs through its issued channel; the agent cannot grant
itself that exception by spelling a command `cardine` or supplying JSON.

| Policy | Claude role sessions | Codex role sessions |
| --- | --- | --- |
| Native file writes | Native permission denies plus protected-operation hook on Edit/Write and equivalent tools; canonical path and destination checks | Restricted writable roots/path denies where supported, plus protected-operation hook for native and shell writers |
| Command deny policy | Native command denies plus semantic guard for chains, pipes, redirects, interpreters, wrappers and options | Native `execpolicy` forbidden rules plus semantic guard; prefix approval does not grant filesystem access |
| Developer-only operations | Deny developer acceptance/verdict recording, cancellation/authority change and direct main push outside the issued integration channel | Same; remove broad `review`, `task` and `worktree` allows where they bypass role/action checks |
| Implementer profile | `cardine-implementer`, task-scoped edits/delivery; no reviewer verdict, developer action or direct integration push | `cardine-implementer`, bounded task roots and same action restrictions |
| Reviewer profile | `cardine-reviewer`, read-only implementation surface, only issued review-result submission for exact task/commit | `cardine-reviewer`, read-only implementation surface and same bound submission |
| Integration privilege | Engine-owned operation capability, never either worker's general shell permission | Same; plain worker `git push origin main` is denied even when ordinary Git inspection is allowed |

Profiles are selected by the launch adapter from host-issued credentials, not
environment strings supplied by a worker. Retain 102's `profile`, `authorize`,
`authorize_operation`, `lookup`, `spawn` and `poll` contract. A request ID maps
to one session; terminal responses are retained only after its writer stops.
Missing, shared, unenforced or stale profiles refuse launch. No second checkout
or second reviewer is created while recovering an uncertain spawn.

Today the role protocol is tested with fake hosts; it does not establish live
host enforcement. The historical contract verifies particular older Read and
Codex shell profiles only. H4d/H5d must record host version, invocation mode,
configuration layer, installed/configured/trusted/effective states and probe
results anew. No future host behavior is asserted from those historical probes.

Doctor asks the host to evaluate positive and negative probe commands under
the selected installed profile, following the existing Codex
`execpolicy check` pattern. Evaluate the installed combined policy, not a
temporary rule string. Include direct main push, developer verdict,
implementer review submission, protected-path writes, reordered options,
chains, pipes, redirects, interpreter writes and symlink destinations; include
permitted inspection and task-source edits as false-deny controls. Rule parsing
only supports diagnosis. A live invocation against sentinel paths in the
disposable home proves hooks/trust and filesystem behavior separately from
command approval. No destructive probe targets a real repository or remote.
Claude requires an equivalent host decision probe or instrumented disposable
host session; if unavailable, report `unverified`, never infer enforcement by
reading settings. H5c cannot declare the profile enforced until H5d succeeds.

Within a verified host profile, these controls refuse observed prohibited
operations. General shell execution, alternate hosts, configuration changes and
same-user access limit the claim: an agent deliberately bypassing host rules
can rewrite same-user receipts. Digests detect inconsistency, not authorship.
No protected signer is introduced. Installation manifest, marker baselines and
capability evidence remain outside decision 14 rule 2's gate-authenticity
boundary until after 1.0. If a host cannot enforce a required boundary, it is
unsupported for engine role launches until D2/D3 is resolved; advisory reminders
cannot satisfy that gate.

## Deferred items — unique assignment

These are the six work item 9 rows from `PROJECT_PLAN.md`. Each has one owner;
later rows may consume its result but do not implement it again.

| Deferred requirement | Sole implementation row |
| --- | --- |
| Remove the budget lines from the per-turn queue briefing | H1a |
| Apostrophe in a title drops all queued tasks (`xargs: unterminated quote`); add regression | H1a |
| Add `cardine init`, replacing init slash-command copy steps | H2a (H2b only routes the completed command) |
| Remove this repository's scripts from the Claude allowlist and Codex probes; adopter validation stays project-owned | H4d |
| Defer `http.client`, `ssl`, `email` imports to self-update/release commands | H1d |
| Governed skills route `Accept` to absent `docs/workflows/LIFECYCLE.md` | H3a |

## Regression tests and fixtures

H1a/H4d run the work item 6 `test_single_workflow_briefing.py` cases through
both installed user-hook command bindings, not merely a direct formatter call.
Use `project_config_support.write_project_config` for lean and governed,
`task_state_support.write_task` and `task_contract_support.seal_state` for
receipt-covered states, and isolated hook payloads. Test preset independence
from queue shape; in-progress/in-review tasks never startable despite queued
prose; malformed/missing configuration; invalid states; and incomplete snapshots.
Retain the configuration/parity cases from `test_single_workflow_contract.py`
and `test_single_workflow_parity.py` as policy-level regressions.

For work item 7, run `test_task_status.py`, `test_task_status_gates.py`,
`test_status_render.py` and `test_status_legacy_boundary.py`, and repeat their
consumer-relevant cases through both hook bindings: closed phases with empty
queue but nonzero totals; queued task whose dependency is done; in-progress
task with done dependency; cancelled and terminal totals; forged/stale queue,
plan and review prose; missing product state without legacy-reader fallback;
changing inputs and incomplete snapshots. Compare shared status fields with
`cardine status --format json` from the same fixture. Hook calls must leave
fixture bytes unchanged. Status renderer write tests run separately and never
authorize a hook to write views.

Add titles `Developer's task`, quoted text, Unicode, shell metacharacters,
spaces and newlines; no shell splitting or `xargs` pipeline is allowed. Cover
custom declared paths, 300 tasks, zero tasks, subdirectory/deleted cwd,
unavailable CLI and malformed host payload. Retire old assertions that the
new product briefing prints language/budget text; retain frozen installation
fixtures separately in `installation_fixture.py`. Do not rename the installed
repository's hooks to make a product test pass.

Read-guard fixtures include native Claude Read and shell calls, and redacted
`tests/fixtures/codex_hook_payloads/{cat,sed,rg,chain}.json`; preserve external
401-line, ranged read, pipe/redirection, ambiguous parser and false-deny cases
from `test_read_guard.py` and `test_codex_read_guard.py`. Stop audit retains
`test_stop_audit.py` transcript/journal fixtures and reports unbacked stops as
diagnostics, never task state. Permissions/role tests extend
`test_run_host_roles.py` and `test_run_control.py` with real decision probes,
changed-input/foreign-owner negatives and every interruption boundary below.
Each implementation task also runs the applicable project baseline.

## Rows

File abbreviations are exact: `H=src/cardine/hosts/`, `T=tests/`,
`C=src/cardine/cli.py`, `S=src/cardine/shared/models.py`.
Braces expand to individual files; old/new rename endpoints both count.
Tests named in the tests column are executed; only files in the files column
are edited. Each row changes at most ten files in one or two areas. New files
are explicit, not permission to expand a directory. Any newly necessary file
requires splitting/replanning the row before implementation. D1–D4 are gates
only for rows that consume their unresolved choice.

For every writing row, inject failure before and after each listed durable
effect, rerun the same operation, and compare with a fresh install. Preserve
foreign paths, symlinks and changed user regions; never repair by overwriting
unknown ownership. Read-only checks may be repeated without mutation. Setup
apply uses SR1b's pinned plan/input digest and intent/staged/result protocol;
new host writers must join it, not add a second transaction mechanism.

| Row / hours | scope | files | tests | interruption boundaries | depends on |
| --- | --- | --- | --- | --- | --- |
| H1a / 3h | Status-only briefing; budget removal and apostrophe regression | `Hbriefing.py`, `Ttest_single_workflow_briefing.py`, new `Ttest_host_briefing.py` (3) | Work item 6/7 fixture matrix above on both payload adapters | Pure status read/output; interrupted output reruns without files or state changes | 115, SS7 |
| H1b / 3h | One Python read guard, two payload adapters | New `Hread_guard.py`, `scripts/codex_read_guard.py`, `C`, `Ttest_read_guard.py`, `Ttest_codex_read_guard.py` (5) | Native/shell/recorded payloads, external and ranged reads, false denies | Read/deny output only; no state write; wrapper delegates or is removed, no duplicated policy | H1a |
| H1c / 2h | Python stop audit and direct dispatch, retire product shell wrapper | New `Hstop_audit.py`, `scripts/stop_audit.py`, `hooks/stop-audit.sh`, `C`, `Ttest_stop_audit.py` (5) | Both host transcripts, backed/unbacked stops, duplicate invocation | Diagnostic append/replace and result publication: repeat once by event identity; never writes task state | H1b |
| H1d / 2h | Lazy heavy imports on release/update path; light hook entry dispatch | `C`, `src/cardine/release/update.py`, new `Ttest_cli_startup.py` (3) | Import trace excludes http/ssl/email for briefing; release/self-update behavior; report timing without machine-specific hard threshold | Import/dispatch has no durable effect; existing updater effects stay under SR1a | H1c |
| H2a / 3h | CLI init preview/apply, configured single-template bootstrap | `C`, new `src/cardine/templates/init.py`, `Ttest_template_commands.py`, new `Ttest_init.py` (4) | All required choices, generated status, existing/conflicting project, idempotent apply | Plan, each directory/file write, lock/baseline, empty views, final result; resume only identical owned outputs | H1d, TR2b |
| H2b / 1h | Rename init slash command and route to CLI | `commands/meridian-init.md`, `commands/cardine-init.md`, `Ttest_template_commands.py` (3) | No copy steps; argparse-valid route, setup remains separate | Packaging rename only; consumer init effects covered by H2a | H2a |
| H2c / 2h | Rename four remaining slash commands, bounded Cardine routes | `commands/meridian-{adopt,upgrade,task,audit}.md`, `commands/cardine-{adopt,upgrade,task,audit}.md`, `Ttest_template_commands.py` (9) | Route existence, no stale command paths; adopter overlays retained | Packaging renames; commands invoke existing operation protocol, no new install writer | H2b |
| H3a / 2h | Author exactly two selected skills; fix Accept route | Two selected new `skills/<name>/SKILL.md`, `Ttest_template_commands.py` (3) | D1 route matrix both presets/hosts; missing LIFECYCLE route absent | Static source writes only; no home installation | H2c, D1 |
| H3b / 2h | Remove four old skills, install two shared Codex links | Four old skill files in inventory, `Hskills.py`, `Hsetup.py`, `Ttest_host_worktree_setup.py`, `Ttest_host_repeatability.py` (8) | Two links only, stale copies, foreign link/directory, interrupted migration | Link-root create, each new link, each proven-owned old link removal, result; replay preserves foreign targets | H3a, SR1b |
| H3c / 2h | Cardine plugin metadata; remove product auto-hooks to avoid duplicate user hooks | `.claude-plugin/{plugin,marketplace}.json`, new `scripts/build_host_plugin.py`, `scripts/check_repository.py`, new `Ttest_host_distribution.py` (5) | Plugin resolves two skills/five commands; frozen hook manifest is not auto-loaded by packaged artifact | Package assembly after each copied file, publication of assembled directory and plugin enablement interrupted in disposable home; resume verifies identical owned files and no duplicate hook call | H3b, H1c |
| H3d / 2h | Router routes and managed-template registration | `templates/single/{AGENTS,CLAUDE}.md`, `src/cardine/templates/catalog.py`, `capabilities/marker-baselines.json`, `Ttest_template_router.py`, `Ttest_template_commands.py` (6) | Generated links/markers, host entry route, no stale procedural fallback | Template replace and baseline replace; regeneration converges preserving overlays | H3c, TR2b |
| H4a / 3h | Cardine Codex rules/profile naming and bounded owned migration | `Hcodex.py`, `Hsetup.py`, `S`, `Ttest_codex_user_rules.py`, `Ttest_host_codex_repair.py` (5) | Existing/foreign TOML and rules, ownership-marker loss, changed root | Backup creation, config replace, new rules write, owned old block removal, result; preserve changed user text | H3d, SR1b |
| H4b / 3h | Setup orchestration and Cardine paths, no real-home apply | `Hsetup.py`, `Heffects.py`, `Ttest_host_worktree_setup.py`, `Ttest_host_repeatability.py` (4) | Root/config/declarations, no-op, consent, symlink/changed plan negatives | Private root/mode, config create/remove, each declaration replace, intent/result; each replay pinned to original plan | H4a, H2a |
| H4c / 3h | User hook registration for both hosts, no project/plugin duplicates | New `Hhooks.py`, `Hsetup.py`, `Hclaude.py`, new `Ttest_host_hooks.py`, `Ttest_host_repeatability.py` (5) | Both user registries, foreign registrations, exactly one invocation per event | Backup, each registry replace, owned duplicate removal, activation/result; restart after changed definition, never fake trust | H4b, H3c, H1a–H1c, D2 |
| H4d / 3h | Unified doctor; remove adopter test-command assumptions from product policies and probes | `Hsetup.py`, `Hclaude.py`, `C`, `Ttest_host_codex_access.py`, `Ttest_host_worktree_setup.py`, new `Ttest_host_doctor.py` (6) | Host-evaluated decisions and live disposable hook invocation; adopter tests neither globally allowed nor required | Read-only probes; sentinel creation/removal only inside fixture; interrupted probe never records effective success | H4c, D4 |
| H5a / 3h | Protected-path/action policy and Claude implementer/reviewer restrictions | New `Hpermissions.py`, `Hclaude.py`, new `Ttest_host_permissions.py`, `Ttest_run_host_roles.py` (4) | Full path/action matrix including native tools, aliases, interpreters; inventory actual receipt paths | Policy-plan/write/verification via existing operation; incomplete guard denies role activation; no credential publication | H4d, RE4b, D3 |
| H5b / 3h | Codex native role policy/profile realization | `Hcodex.py`, `Hpermissions.py`, `Ttest_codex_rules.py`, `Ttest_host_permissions.py` (4) | Host decision table, bounded roots, shared/foreign profiles, direct main push denied | Each role block and rules replace, backup/result; no broad fallback if either profile incomplete | H5a |
| H5c / 3h | Concrete host transports wired to issued roles/session protocol | `Hlaunch.py`, new `Htransports.py`, `src/cardine/lifecycle/engine.py`, `Ttest_run_host_roles.py`, new `Ttest_host_transports.py` (5) | Both hosts, owner/action binding, lookup/spawn/poll, stopped writer, no second session | Existing before/after request, spawn, session and response receipt boundaries; reconcile same request on lost response | H5b, RE7a, D3 |
| H5d / 3h | Doctor runtime role proofs and host contract update | `Hsetup.py`, `Ttest_host_doctor.py`, `Ttest_host_transports.py`, `docs/HOST_CAPABILITY_CONTRACT.md`, `tests/test_no_meridian_identifiers.py` (5) | Disposable fresh sessions; all denies/false-deny controls; work item 6/7 hook regressions; identifier guard removes only retired work item 9 allowances | Probe/result persistence cannot promote an incomplete run; interrupted proof repeats against same config digest; role activation gated on actual effective proof | H5c, H4d |

H3c must ensure Claude's automatic `hooks/hooks.json` convention cannot load
the frozen manifest: assemble the distributable plugin without that file and
test the assembled artifact, rather than changing its frozen source. If the
current packaging path cannot omit it within H3c's file bound, split a packaging
row before implementation. Packaging never installs into this repository.

## Compatibility checks and conflicts

Checked against `RUN_ENGINE_PLAN.md`: RE4a/RE4b already own role/session and
verdict authority; H5 implements host transport and permissions, not a second
verdict engine. SR1b owns effect reconciliation; H4 extends its writer inventory.
TR1/TR2 own condensed procedures; H3 changes only host entry routing/registration.
RE3b owns observed host-impact facts; H5d supplies actual observations, not a
self-authored `enforced` boolean. Receipt layout enumeration follows RE1b/RE4a;
installation authenticity stays deferred. No engine-plan row is rescheduled.

The following contract conflicts require explicit revision in H5d; they are
not resolved by treating the existing prose as already implementing the target:

| Current `HOST_CAPABILITY_CONTRACT.md` statement | Work item 9 target / disposition |
| --- | --- |
| Codex briefing unsupported; Claude plugin hook supplies briefing | Two user-level adapters, one status service; keep unverified until event/trust proof; D2 |
| Claude needs no host configuration; setup chiefly configures Codex | Both hosts need user hook/policy setup, preview and consent; H4 |
| Project Codex rules/hooks and `meridian-worktrees` | User Cardine rules/hooks and distinct role profiles; retain historical observations labelled with their original profile |
| Prefix rules and prose deny list as defense in depth | Decision 14 requires effective role/path refusal for engine launches; advisory is insufficient; H5/D3 |
| Project allowlist text reported effective by planning | Doctor must obtain host decisions; installation and effective behavior are separate; H4d |

The work item 7 formatter preserves non-queue payload bytes today. H1a changes
the new product entry to status-only; frozen installation fixtures retain their
old behavior. This is a planned adapter change, not a change to status authority.
The installed lifecycle still requires task records/handoffs and integration
queue updates here; those coordination artifacts are outside the product-file
scope of task 116 and do not justify modifying frozen workflow files.

## Developer decisions — left undecided

- **D1: Which two skills ship?** Choose A (`cardine-lean`, `cardine-governed`)
  or B (`cardine-project`, `cardine-delivery`). A preserves preset discovery
  but risks duplicated routing; B shares delivery and separates administration
  but changes discoverability. Both use one engine and exactly two bodies.
- **D2: What if a supported Codex runtime lacks a user-level turn event or
  trusted user hook loader?** Require a verified minimum runtime, or use a
  Cardine-launched session adapter that injects the same Python output each
  turn. The former narrows supported versions; the latter makes unmanaged
  sessions unsupported. Project hook copies and a second briefing engine are
  excluded by the target. H4c awaits this choice/probe evidence.
- **D3: What if native host policy cannot enforce protected paths and role
  actions while allowing the required shell work?** Restrict engine roles to
  a verified guarded tool/session adapter, or declare that host profile
  unsupported for role launches. The first adds bounded transport work that
  must be split into file-sized tasks if H5 grows; the second limits host
  coverage and leaves that host acceptance unmet. Neither can claim enforcement
  from policy text. No separate-user signer is included.
- **D4: Keep `cardine codex doctor/configure` aliases?** Keep thin deprecated
  aliases to unified setup/doctor for one compatibility interval, or remove
  them with explicit migration diagnostics. Keeping them adds routing tests;
  removal requires consumers to update commands. No duplicate implementation.

These are planning questions, not requests to apply setup or select a skill
silently. Implementation tasks must carry the selected decisions in their
contracts before entering the dependent rows.
