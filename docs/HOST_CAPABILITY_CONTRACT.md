# Host Capability Contract

Status: Design baseline. This document records host-specific evidence and
release expectations; it does not itself create a task, change a template, or
claim that an unimplemented control is enforced.

## Purpose

Meridian has one workflow policy, but Claude Code and Codex reach that policy
through different instruction files, plugin/skill distribution paths, tools,
approval systems, and trust models. A workflow rule is not an effective
constraint merely because its prose exists in both host-facing assets.

Every claim about a host-dependent capability therefore identifies a concrete
host profile and one of these states:

| State | Meaning |
|---|---|
| `enforced` | The host invokes a verified adapter that prevents the prohibited action. |
| `advisory` | The host receives guidance or a reminder, but can still bypass it. |
| `unsupported` | Meridian intentionally provides no adapter for this host profile. |
| `unverified` | An adapter, claim, or runtime path exists but lacks the required evidence. |

An installed file is not evidence that a capability is active. For a
host-managed adapter, distinguish `installed`, `configured`, `trusted`, and
`effective`; only the last state supports an `enforced` claim.

## Host profiles

The contract applies to a versioned profile, not an umbrella product name.
At minimum, release evidence names the host, host version, invocation mode,
and relevant configuration layer.

| Profile | Distribution path | Notes |
|---|---|---|
| Claude Code plugin session | Claude plugin, `CLAUDE.md`, slash commands, plugin hooks | Plugin lifecycle and the native `Read` tool are distinct from Codex shell execution. |
| Codex project session | `AGENTS.md`, optional Codex skill, project `.codex/` files | Project hooks and rules require the project's Codex configuration layer to be trusted. |
| Codex plugin session | Codex plugin hook/configuration plus `AGENTS.md` | Plugin hooks also require trust; `PLUGIN_ROOT` is available and `CLAUDE_PLUGIN_ROOT` remains a compatibility variable. |
| Host-neutral CLI | `bin/meridian` and managed project files | The CLI may be common, but PATH, current directory, sandbox, and approval behavior remain host-specific. |

## Capability matrix

| Capability | Claude Code profile | Codex project profile | Required evidence before an enforcement claim |
|---|---|---|---|
| Workflow router and language policy | `CLAUDE.md` supplies the route and policy. | `AGENTS.md` supplies the route and policy; a skill is an optional reusable layer. | Fresh-session evidence of the auto-loaded entry point, route selection, and policy salience. Byte equality alone is insufficient. |
| Managed entry-point integrity | Template/generator tests preserve expected `CLAUDE.md` content. | Template/generator tests preserve expected `AGENTS.md` content. | Static generator and audit tests plus one host-session route fixture per release that changes routing. |
| Queue and language briefing | `UserPromptSubmit` hook is an advisory salience aid. | No equivalent adapter is distributed. | Claude: plugin-hook invocation fixture. Codex: retain `unsupported` unless a trusted adapter and probe are shipped. |
| Authority excerpts and execution budgets | Available through the Meridian CLI when the plugin root resolves it. | Available through the Meridian CLI when `MERIDIAN_ROOT`/PATH and cwd resolve it. | Per-profile bootstrap/doctor check proving the exact command can be found and executed from a project subdirectory. |
| Large-file read guard | Existing plugin hook targets the native `Read` tool; unit tests cover its policy semantics. | The governed-SDD `.codex/hooks.json` adapter intercepts recognised Bash reads after project-hook trust. | Native payload fixture and real hook invocation for Claude; recorded Codex payload, parser table, denial fixture, trust proof, and no false-deny regression for Codex. |
| Command approval policy | No Meridian-managed, project-scoped equivalent is currently shipped. | `templates/workflows/governed-sdd/.codex/rules/meridian.rules` is distributed on upgrade, but it is effective only after project-layer trust. | A decision table evaluated by the host plus a real trusted-project chain test. Approval evidence does not prove sandbox access. |
| Trust activation | Must be observed for the installed plugin/hook definition. | Local rules/hooks are inactive until the project layer and current hook definition are trusted. | An activation check that distinguishes missing, untrusted, trusted, and effective states. |
| Shell and chained commands | Host-specific behavior must not be inferred from rule text. | Codex CLI 0.155.1 trusted-project probe: an all-allowed `&&` chain ran without a prompt; a force-push chain was refused; an unmatched later `git rebase` segment still ran. Governed sessions must issue one command per call. | A fixture for simple command, chain, pipe, redirection, and unsupported syntax, with the expected allow/deny behavior recorded per host. |
| Sandbox and Git operations | Permission and filesystem outcomes depend on the runtime environment. | Approval rules cannot override filesystem sandboxing, network restrictions, or Git worktree restrictions. | A host-specific preflight that reports whether the intended Git/filesystem operation is executable, needs approval, or is unavailable. |
| Review isolation | Task-tool or a fresh independent session may provide isolation. | A separate thread/subagent may provide isolation when available; otherwise use a fresh chat. | The skill must state the current adapter and fallback without assuming a host limitation that has not been verified for the current version. |
| Upgrade and adoption entry point | Claude commands use `CLAUDE_PLUGIN_ROOT`. | Codex guidance uses `MERIDIAN_ROOT`/CLI discovery. | One clean project upgrade/adoption check from each host profile that the release claims to support. |

## Verified Claude Code read-guard probe

On 2026-09-20, a temporary Meridian-shaped repository with a 401-line target
file was used with Claude Code `2.1.278`, model `claude-sonnet-5`, and the
Meridian plugin loaded directly through `--plugin-dir`.

| Question | Result |
|---|---|
| Does the Meridian plugin load? | Yes. Claude reported the Meridian plugin and its hooks in the session metadata. |
| Does `PreToolUse:Read` fire for a native Read? | Yes. |
| Is an unranged over-threshold Read prevented? | Yes. The hook exited `2`, returned its structured deny output, and the tool result was classified as a non-execution permission rule. |
| Does the model receive an actionable reason? | Yes. It reported that the 401-line read was blocked by the 400-line threshold. |

This verifies the existing Claude read guard for this direct-plugin CLI profile.
It does not by itself prove that a marketplace-installed plugin, another Claude
runtime, or a different tool path loads the same hook definition.

## Verified Claude Code marketplace install probe

On 2026-09-30, Claude Code `2.1.285` was run with an isolated
`CLAUDE_CONFIG_DIR` against the real tags `v1.1.49` and `v1.1.50` of
`biagiolibe/meridian`. Both tags predate the marketplace rename, so the
marketplace in this probe was named `meridian-local`; the name `meridian`
(`meridian@meridian`) is covered by the `v1.2.0` migration below.

| Question | Result |
|---|---|
| Does `claude plugin marketplace add biagiolibe/meridian#v1.1.49` pin to the tag? | Yes. The marketplace source was recorded as `biagiolibe/meridian@v1.1.49`. |
| Does `claude plugin install` from the pinned marketplace install that tag? | Yes. The plugin reported version `1.1.49`, with the tagged commit in `installed_plugins.json`. |
| Can the marketplace be re-added at a different tag? | No. Claude Code refused: the source differs from the one declared in settings. |
| Does `claude plugin marketplace remove` keep the installed plugin? | No. The plugin was uninstalled with it. |
| Does remove, add at `#v1.1.50`, then install move the plugin? | Yes. The plugin reported version `1.1.50`; the `1.1.49` cache entry remained on disk. |
| Does `claude plugin update` move a pinned plugin to a newer tag? | No. It reported the plugin already at the latest version for the pinned tag. |
| Does `bin/meridian` exist in the installed plugin cache and run? | Yes. The cached `bin/meridian` of `1.1.50` ran and printed its usage. |

### Migration to the published tag `v1.2.0`

On 2026-10-01, Claude Code `2.1.287` was used for the developer's real
user-scope installation, not an isolated `CLAUDE_CONFIG_DIR`. The migration
commands were entered in the interactive `/plugin` interface, starting from the
`meridian@meridian-local` install. Paths below are relative to `~/.claude`.

| Question | Result | Evidence |
|---|---|---|
| Does `/plugin marketplace add biagiolibe/meridian#v1.2.0` register the marketplace `meridian` pinned to the tag? | Yes. Source `github`, repo `biagiolibe/meridian`, `ref: v1.2.0`; no `meridian-local` entry remained. | `plugins/known_marketplaces.json` |
| Does `/plugin install meridian@meridian` install `1.2.0` at the tagged commit? | Yes. Version `1.2.0`, `gitCommitSha` `9a5bba7501cf8c7cf4c289998c71d96e8c4e7906`, equal to the commit of `v1.2.0`. | `plugins/installed_plugins.json`; `git ls-remote origin refs/tags/v1.2.0` |
| Is the old install replaced without a manual `settings.json` edit? | Yes. No `meridian@meridian-local` entry or `enabledPlugins` key remained, and `meridian@meridian` was enabled. | `plugins/installed_plugins.json`; `settings.json` |
| Does the cache hold a runnable `bin/meridian` for `1.2.0`? | Yes. `plugins/cache/meridian/meridian/1.2.0/bin/meridian self-check` ran and printed its usage. | Cache directory; command output |
| Does the `/plugin` detail view list the commands, skills, and hooks of `1.2.0`? | Yes, as observed by the developer in the interactive interface. | Developer observation |

Observed side effect, not a defect: the migration left
`plugins/cache/meridian-local/` (holding `1.0.0`) on disk. Claude Code did not
remove it, and it is safe to delete.

Still unverified: `/plugin marketplace update meridian` for an unpinned
marketplace moving to a newer release, and `${CLAUDE_PLUGIN_ROOT}` expansion
inside a live Claude session. The installed `hooks/hooks.json` references
`${CLAUDE_PLUGIN_ROOT}`, but no direct evidence that its hook command ran from
the installed plugin in a new session has been recorded, and the `/plugin`
detail view alone is not accepted as proof. The probes do not cover Codex, and
everything about Codex remains unverified.

## Verified Codex hook probe

On 2026-09-20, a scratch Git repository was used with Codex CLI 0.155.1 and a
trusted project-local `.codex/hooks.json` logging hook.

| Question | Result |
|---|---|
| Does `PreToolUse` fire for the shell path? | Yes. |
| What tool name is exposed? | `Bash`. |
| Where is the command? | `tool_input.command`. |
| Are multiline input and `&&` preserved? | Yes; both arrive in the one command string. |
| Can a hook block the entire invocation? | Yes. A hook emitting a reason on stderr and exiting `2` blocked both sides of an `&&` chain before either ran. |
| Is JSON alone sufficient with exit `2`? | No in this probe: Codex reported that no blocking reason had been written to stderr and the chain ran. |
| Does trust matter after a hook change? | Yes. Changing the hook definition required a new manual trust review before it ran. |

This established task 041's probe classification A for this profile. The
subsequent implementation added the parser, exemptions, managed distribution,
and redacted fixtures; other Codex runtimes remain unverified.

Task 041 subsequently recorded redacted individual `sed`, chain, `cat`, and
`rg` payload fixtures. The trusted definition is stored in
`~/.codex/config.toml` under `hooks.state`, keyed as
`<project>/.codex/hooks.json:pre_tool_use:0:0`; changing it requires another
manual `/hooks` review. The hook process had the project cwd, `MERIDIAN_ROOT`,
and a PATH containing `MERIDIAN_ROOT/bin` (but no `PLUGIN_ROOT`). Its deny
probe confirmed that stderr plus exit `2` blocks the whole chain and conveys
the reason; structured JSON is supplementary.

On 2026-09-20, a trusted consumer project A project session denied both a 2,520-line
project file and `cat /private/tmp/meridian-read-guard-probe.txt > /dev/null`
for an external 401-line file before execution. Together with task 042's
external-path regression fixture, this is enforcement evidence for the named
trusted Codex project-session profile, not for a Codex plugin session or every
future Codex runtime.

## Verified Codex skills install probe

On 2026-10-01, Codex CLI 0.159.2 ran `codex exec` (read-only sandbox) with a
scratch `HOME`, `CODEX_HOME` pointing at the real `~/.codex` for
authentication, and a clone of `v1.1.50` whose two skill directories were
symlinked into `$HOME/.agents/skills`.

| Question | Result |
|---|---|
| Does Codex load user skills from `$HOME/.agents/skills`? | Yes. `meridian-lean-delivery` and `meridian-governed-sdd` were listed from that path. |
| Does it follow directory symlinks? | Yes; each `SKILL.md` was reported under the symlinked path. |
| Is `~/.codex/skills` also scanned? | Yes. A pre-existing `meridian-governed-sdd` there was listed alongside the `.agents` one. Only `meridian-lean-delivery`, present solely under `.agents/skills`, isolates the new path. |
| Does `MERIDIAN_ROOT` reach the session shell? | Yes. `echo "$MERIDIAN_ROOT"` printed the tagged clone. |
| Does `$MERIDIAN_ROOT/bin/meridian` run there? | Not in this probe. The shell resolved `/usr/bin/python3` 3.9.6, and the launcher failed on `import tomllib`; the same launcher printed `1.1.50` in an ordinary shell with Python 3.14. The scratch `HOME` had no shell profile, so that is the suspected cause, but it was not isolated and stays `unverified`. |

Still unverified: the launcher under a Codex shell with a Python 3.12+
`PATH`, skill auto-selection (the probe listed skills, it did not invoke
`$meridian-lean-delivery`), the real-home path without a scratch `HOME`, other
Codex versions, and Codex plugin sessions.

## Required host-impact gate

Before a task changes a workflow rule, hook, command, generated instruction,
skill, permission policy, or CLI bootstrap path, its task record must state:

1. **Policy outcome** — the host-independent behavior being protected.
2. **Affected profiles** — each host/runtime/version/invocation mode affected,
   plus profiles explicitly out of scope.
3. **Adapter state** — `enforced`, `advisory`, `unsupported`, or `unverified`
   before and after the change.
4. **Activation preconditions** — installation, trust, PATH, cwd, sandbox,
   permissions, and any user action required.
5. **Evidence plan** — static fixture, host execution fixture, and required
   manual observation. A host claim without a matching evidence item remains
   `unverified`.
6. **Fallback** — the safe behavior and user-visible message if the adapter
   cannot run or cannot determine the host payload.

The implementation and review report must repeat the profiles actually
verified. A repository test may prove parser or template semantics, but cannot
by itself promote a host integration to `enforced`.

## Machine setup and worktree-root resolution

Every `meridian worktree` and `meridian codex` command resolves one root in
this order: explicit `--worktree-root`, `MERIDIAN_WORKTREE_ROOT`, the version-1
user configuration, then `~/.meridian/worktrees`. The user configuration is
`$XDG_CONFIG_HOME/meridian/config.json`, falling back to
`~/.config/meridian/config.json`, and its only keys are `version` and
`worktreeRoot`. It is absent when the built-in default is used. An explicit
value that differs from the environment is blocked with both sources named.
The filesystem root and the user's home are always rejected. A temporary or
repository-local explicit root is visible in the setup plan and should be
used only for bounded testing or legacy cleanup, never as machine setup.

`meridian setup --check` is the read-only machine preflight. It reports the
resolved path and source, whether the directory exists with current-user
ownership and mode `0700`, the Codex profile state (`unconfigured`, `ready`,
`repair-required`, `repair-and-replace-required`, `different-root`, or `blocked`), and every bounded change
that `--apply` would make. `meridian setup --apply` is the only write path: it
creates or repairs the private root, writes the user configuration only for a
non-default root, and delegates the Codex edit to the existing bounded planner
and backup behavior. Repeating it is a no-op. An intact Meridian-owned profile
for another root is `different-root` and may be replaced after consent. A
damaged profile with the exact Meridian description, parent, selection, and
one enabled old root is `repair-and-replace-required`; `--apply` repairs its
ownership metadata and replaces that root in one backed-up change. Every other
damaged shape is `blocked`, names the diverging fields, and is never
overwritten silently.

The normal flow is:

1. Install Meridian and put `meridian` on `PATH`.
2. Once per machine, run `meridian setup --check`, review the plan, run
   `meridian setup --apply`, and restart Codex. Claude Code needs no host
   configuration.
3. For a new project, run `meridian init`; lifecycle commands resolve the
   machine root without a project setting.
4. For an existing project, run `meridian upgrade --check` and then the
   consented `--apply` to receive the migrated workflow text.
5. Finish an existing worktree where it is. Clean it only after integration
   with `meridian worktree cleanup --worktree-root <old-root>`; Meridian never
   moves or deletes worktrees automatically.

## Codex task-worktree permission profile

Meridian supports one Codex permission model for shared task worktrees: the
beta permission-profile model. `meridian codex configure --check` resolves the
machine root, parses the user configuration, and prints the exact
managed profile block without writing it. `--apply` is the only write path. It
creates a restrictive backup before the first changed write and atomically
replaces the configuration while retaining unrelated text and comments.

The managed `meridian-worktrees` profile extends Codex's bounded `:workspace`
profile and adds only the selected shared root. It never enables network
access, grants the home directory, or grants unrestricted filesystem access.
Legacy `sandbox_mode`/`sandbox_workspace_write`, malformed TOML, an existing
foreign profile of the same name, and managed restrictions are conflicts, not
inputs to merge. See the official Codex permission-profile and sandbox
documentation: <https://learn.chatgpt.com/docs/permissions> and
<https://learn.chatgpt.com/docs/agent-approvals-security>.

### Recovery when ownership comments are lost

The comment markers around the managed block are ownership metadata, not the
source of truth: a conforming TOML writer, including a Codex app update, may
move, normalize, or drop them. Meridian therefore classifies the profile from
the parsed configuration. The state is `repair-required` only when
`default_permissions` selects `meridian-worktrees` and that profile is exactly
`description`, `extends = ":workspace"`, and a `workspace_roots` table holding
only the requested root set to `true`. The Meridian-specific description plus
the exact root, parent, and selection are the semantic evidence; no comment is
required. `repair-and-replace-required` uses the same exact shape but has one
enabled root different from the requested root. It repairs the markers and
replaces that one root together; this is not evidence that any other profile
shape is Meridian-owned.

`--check` prints a unified diff of the bounded change and writes nothing.
Explicit `--apply` is the only write path: it verifies the file is unchanged
since planning, writes a new exclusive owner-only backup
(`config.toml.meridian-repair.bak`, then `.1`, `.2`, ...), and replaces the file
atomically. The repaired file must parse to exactly the same configuration as
before, or, for `repair-and-replace-required`, to that same document with only
the one root value replaced. Unrelated keys, comments, tables, and application
settings are preserved, and repeating the repair is a no-op. Because the profile tables
move into the managed block, a repair may reorder them relative to unrelated
tables; comments inside those two tables are not carried over.

Anything else stays `BLOCKED`, is never adopted or overwritten, and names the
diverging fields: a different root, parent, description, or default selection;
extra grants or roots; a partial match; duplicate tables; inline or dotted
serializations Meridian cannot edit exactly; and legacy sandbox settings.
Intact markers around a profile for another root keep the ordinary managed
replacement path.

Repair proves only that the configuration file is effective. It does not prove
that a running session reloaded the profile or that the host enforces it; start
a fresh session and probe before relying on it.

### Unattended-closure command policy

The Codex rules allow `meridian worktree evidence` and `closure-status`, `git mv`,
the repository validation commands (`python3 scripts/check_repository.py`,
`python3 -m unittest discover -s tests`, `set -o pipefail`), and read-only
inspection (`ls`, `cat`, `head`, `tail`, `wc`, `pwd`, `grep`). Each group is a
separate doctor fact: `archive-rename-policy`, `inspection-command-policy`, and
`validation-command-policy`, reported as `ready` or `gap: <command>`.

Execpolicy prefixes match only leading literal tokens, and the most restrictive
matching decision wins. A command with no matching rule returns no decision and
keeps Codex's normal approval flow. Consequences:

- `git mv` cannot be limited to the `tasks/done/` destination. The rule allows
  any rename inside the task worktree; the residual risk is a misplaced tracked
  file, which `integrate stage` rejects because it accepts only the exact
  archive rename of the task record. Forced moves (`-f`, `--force`) prompt.
  The Claude Code entry `Bash(git mv tasks/:*)` scopes the source only.
- Intentional approval points, left without a rule because a dangerous option
  can follow safe leading tokens: `sed` (`-i`, `w`, `e`), `rg` (`--pre`, `-z`),
  `find` (`-exec`, `-delete`, `-fprint`), `git grep -O`, `mv`,
  `git fetch`, `git push origin task-<ID>`, `meridian validation check`, and
  `python3 scripts/run_tests.py`.
- The test and check commands execute project code by design; the rule does
  not widen what the sandbox permits.

Delivery: Codex rules arrive through `meridian upgrade --check` and `--apply`
(managed file `.codex/rules/meridian.rules`); the Claude Code allowlist arrives
through consented `meridian setup`, which is additive.

`meridian codex doctor` reports project trust, the selected permission model,
effective worktree-root write access, command-policy availability, and Git
metadata separately. It also reports `profile-ownership` (`ready`,
`repair-required`, `repair-and-replace-required`, `blocked`, or `not-applicable`) as its own line, independent
of root access, and a single `codex-root-mismatch` line when the profile and
resolved roots differ. Static configuration is not host-execution evidence.
`.git` and the resolved common Git directory remain protected independently;
project execpolicy rules control approval decisions but cannot widen the
filesystem sandbox.

## Host-neutral worktree lifecycle

`meridian worktree path|prepare|check|integrate|cleanup` is the canonical
lifecycle surface for Codex, Claude Code, and direct-terminal use. Codex rules
may allow only those action prefixes; Claude uses its own permission adapter.
The commands validate the current canonical project, task identity, configured
root, repository-qualified path, branch, state, lease ownership, and evidence
before changing Git metadata. They never execute project-controlled commands.

Orchestration prepares the checkout before starting any worker and passes the
returned existing path as a launch input. A worker immediately runs read-only
`check` from that exact directory. A host facility that creates a second
checkout, including a Claude automatic worktree, is not an equivalent adapter;
if the host cannot attach a fresh context to the prepared directory, the
lifecycle is `BLOCKED` and both checkouts are retained. `meridian codex
worktree-path` remains a deprecated path-only alias for one migration window.

## Decision rules

- Prefer a common policy with narrow host adapters over a common parser that
  assumes identical tools or payloads.
- Prefer a false allow to a false deny for advisory shell parsing unless the
  protected operation is independently unsafe; false denials stall legitimate
  work and invite workarounds.
- Treat approval, trust, sandbox access, and execution success as separate
  facts. No one fact implies another.
- Do not add host-specific prose to generic workflow policy when an adapter,
  a profile row, or a fallback statement expresses the requirement more
  precisely.
- Do not describe a capability as cross-host parity until its expected outcome
  has been demonstrated in every profile named by the claim.

## Open evidence

| Item | Current state | Needed evidence |
|---|---|---|
| Claude plugin read-guard activation | `enforced` for the tested direct-plugin Claude Code 2.1.278 profile. | Marketplace-installed plugin activation and any other Claude runtime remain unverified. |
| Codex command approval policy | `enforced` for the Codex CLI 0.155.1 trusted project profile. | Other Codex versions and plugin sessions remain unverified; governed sessions issue one command per invocation. |
| Codex read guard | `enforced` for the trusted consumer project A Codex project-session profile, including the recorded external absolute-path read. | Other Codex versions and plugin sessions remain unverified. |
| Router auto-load parity | `unverified` as a release-wide claim. | Fresh-session evidence for the actual entry point and route-specific initial reads on both profiles. |
| Codex review-isolation adapter | `unverified`; existing skill language may be stale. | Versioned check of available subagent/thread capability and a documented fresh-chat fallback. |
| Codex tagged-checkout launcher | Skills directory, symlink following, and `MERIDIAN_ROOT` propagation verified on Codex CLI 0.159.2; `bin/meridian` launch is `unverified`. | Run the launcher in a Codex session whose shell resolves Python 3.12+. |
| Host-neutral CLI bootstrap | `unverified` across profiles. | Subdirectory PATH/cwd checks for authority, upgrade, adoption, and hook entry points. |

## Non-goals

This contract does not introduce a new task lifecycle, make Codex and Claude
mechanically identical, distribute rules or hooks, change the current template
set, or replace a task-specific acceptance criterion. It is the design record
used to scope those changes safely.
