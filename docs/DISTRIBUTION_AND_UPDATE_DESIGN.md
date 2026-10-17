# Distribution and Update Channel Design

Status: decided by task 049, with the project console CLI surface added by task
075. The command remains part of the tagged repository tree; no separate
package or publishing channel is introduced.

## Problem

Today an adopter installs Meridian by cloning `main` and registering the clone
as a **local** marketplace (`meridian-local`, `source: "./"`), or by symlinking
skills for Codex. Nothing says how to install a specific release, learn that a
newer one exists, or move a checkout forward safely before running
`meridian upgrade`. The upgrade CLI is only correct once the adopter already
holds the newer framework files.

The version and ledger mechanics already exist and this design reuses them
unchanged: the three version axes (`frameworkVersion`, `workflowBaselineVersion`,
`protocolVersion`), the append-only `releases/<version>.json` ledger, the
contiguous `migrations/` chain, `release-baselines/`, and the `v<version>` Git
tags (`v1.1.49` and `v1.1.50` already exist; `v1.1.51` is not cut yet).

## Platform facts the design relies on

From the official Claude Code documentation
(<https://code.claude.com/docs/en/plugins/host-marketplace> and
<https://code.claude.com/docs/en/plugins/create-marketplace>):

- A Git repository containing `.claude-plugin/marketplace.json` is added with
  `/plugin marketplace add owner/repo`; a `#<ref>` suffix pins a branch or tag
  (`your-org/your-marketplace#stable`).
- For a Git-hosted marketplace Claude Code clones the whole tree, so a
  relative `source` such as `"./"` keeps working.
- An installed plugin is a cached copy. It is refreshed only when its computed
  version changes (`plugin.json` `version` first, then the marketplace entry).
  Meridian bumps `plugin.json` `version` with every release (task 046).
- Background auto-update is off by default and is controlled by the user or an
  administrator, not by `marketplace.json`. Without it users run
  `/plugin marketplace update <name>` or `claude plugin update <plugin>@<name>`.
- The marketplace `name` is part of the install id and of the `enabledPlugins`
  key, so it cannot change without migrating existing installs.

From the Codex documentation (<https://learn.chatgpt.com/docs/build-skills>):

- Skills are directories scanned from `.agents/skills` (repository) and
  `$HOME/.agents/skills` (user). OpenAI recommends plugins for wider
  distribution. The documentation states no versioning or update mechanism for
  skills.

`docs/HOST_CAPABILITY_CONTRACT.md` records that marketplace-installed Claude
plugin activation and Codex plugin sessions are **unverified**. Every claim
below that depends on installed-plugin behavior is therefore verified
empirically by the implementing task before it is documented as supported.

## Decision 1 — Distribution channels

Meridian is distributed as **one Git repository, consumed two ways**. The
release artifact is the tagged repository tree; there is no second build
artifact.

| Channel | What the adopter installs | Status |
|---------|---------------------------|--------|
| Claude Code marketplace, GitHub-hosted | `/plugin marketplace add biagiolibe/meridian#v<version>` then `/plugin install meridian@meridian`. The plugin cache holds the tagged tree, so `${CLAUDE_PLUGIN_ROOT}/bin/meridian` is the CLI. | Primary |
| Codex skills from a tagged checkout | A clone at `v<version>`, `MERIDIAN_ROOT` pointing to it, and the two skill directories symlinked into `$HOME/.agents/skills`. | Supported, manual |

Marketplace rename: the current marketplace name `meridian-local` describes a
local-directory install and would be wrong on a public catalog. The
marketplace `name` becomes `meridian` (install id `meridian@meridian`). This
is a breaking change for anyone who already installed `meridian@meridian-local`;
the implementing task must state the one-time migration (remove the old
marketplace, add the new one) in the README and CHANGELOG.

Rejected alternatives:

- **Python package (PyPI).** The CLI is a stdlib script that resolves
  templates, migrations, and baselines relative to the framework root, plus
  Claude hooks and skills. Packaging it means a second copy of every asset and
  a second version source that could drift from `VERSION`. It also adds a
  publication account and supply-chain surface for a benefit the two host
  channels already cover. Revisit only if adopters appear who use neither
  Claude Code nor Codex.
- **Codex plugin.** Recommended by OpenAI for distribution, but Meridian has no
  verified Codex plugin profile (see the host contract). Adding one now would
  ship an unproven adapter. Revisit after a Codex plugin probe exists.
- **Unpinned `main` as the adopter default.** `main` contains unreleased
  work; adopters must land on a ledger-recorded release.
- **Submission to a third-party or official marketplace directory.** Out of
  scope and outward-facing; it requires a separate developer decision.

### Project console command

The read-only project console is exposed as `meridian console`. It is resolved
from the installed Meridian framework root and operates on the current working
project by default:

```text
meridian console
meridian console --project /path/to/project --interval 5
```

This is a local terminal view with automatic refresh; it does not control
agents, write project state, or require a service. Claude Code receives the
command from `${CLAUDE_PLUGIN_ROOT}/bin/meridian`. Codex adopters use the
`bin/meridian` launcher from their tagged checkout with `MERIDIAN_ROOT` set to
that checkout. The command is therefore versioned and updated together with
the tagged Meridian tree.

## Decision 2 — Version pinning

The pin is the Git tag `v<version>`, which the ledger already records as
`gitTag`.

- Claude Code: add the marketplace at the tag, `#v<version>`.
- Codex: `git clone --branch v<version>` (or check out the tag) and point
  `MERIDIAN_ROOT` at it.
- An adopter stays on that release until they deliberately move the pin. No
  channel moves an adopter automatically.
- For the `extraKnownMarketplaces` settings-pinned refusal and active-version
  checks, see [Updating Meridian](HOW_TO_UPGRADE.md#updating-meridian).

Rejected: a moving `stable` branch fast-forwarded by the release workflow. It
would give tag-following updates through `#stable`, but it requires the
release workflow to push a branch and adds a second ref to keep consistent
with the tag. Reconsider after task 050 has proven the tag-driven release.

## Decision 3 — Update discovery

Two layers, both optional for the adopter and neither a requirement for
`meridian upgrade`.

1. **Documentation and GitHub Releases (baseline).** Each release has a
   GitHub Release (task 050) whose body is its `CHANGELOG.md` section. Adopters
   learn of releases through the repository's Releases feed ("Watch" >
   "Releases only"). This works with no Meridian code.
2. **`meridian self-check --check-latest` (opt-in command).** A read-only
   command that prints the installed framework version and compares it with the
   latest GitHub Release (`releases/latest` of the repository). Contract:
   - Network access happens only when this flag is given. `upgrade`, `adopt`,
     hooks, and every other command stay fully offline.
   - Standard library only, short timeout, no credentials, no telemetry, and no
     cache or state file (no new persistence format).
   - Offline, rate-limited, or malformed response: report status `UNKNOWN`
     with the reason and a documented exit code distinct from "update
     available"; never raise a failure that blocks other work.
   - It reports the release kind (CLI-only or template-changing) taken from
     the release body's kind line defined in Decision 5.

Rejected: startup or hook-time update notification (network on every session,
violates the offline default), and a polling background job (persistence and a
new trust surface).

Risk flag: `--check-latest` adds a network dependency and a new public CLI
surface. Meridian remains on its repository-local Lean Delivery lifecycle.
Task 066 therefore requires a fresh-session, read-only review after
implementation and validation and before the normal Lean completion and
integration steps. The task stays in progress until that review returns
`APPROVE`; this adds a risk-proportionate gate without importing Governed SDD
states, roles, or acceptance commits.

## Decision 4 — Update procedure

Ordered adopter steps from "a new release exists" to "project upgraded". The
framework is always updated **before** the project, because the project's
manifest is only readable by a CLI at least as new as its `protocolVersion`.

1. Read the release notes (Decision 5) and note the release kind.
2. Move the pin: for Claude Code, remove the marketplace, add it again at
   the new tag, and reinstall the plugin (removal uninstalls it, and re-adding
   at a different ref is refused; verified in task 065), or use
   `/plugin marketplace update meridian` when it was added without a pin; for
   Codex, fetch and check out the new tag.
3. From the project, run `meridian upgrade --check`.
4. On a clean plan, apply it on a dedicated branch with
   `meridian upgrade --apply`, validate the project, and commit the diff.
   On conflicts, resolve the bounded conflict and rerun; never hand-edit
   `.meridian/manifest.json`.

A migration may explicitly adopt a framework-owned path that becomes managed
after consumers may already hold it. The clean plan names that adoption. If the
existing file differs from the target template, both check and apply name the
collision-safe adjacent backup that apply writes before replacement. Paths not
declared for adoption retain the normal missing-baseline conflict.

What each version axis tells the adopter:

| Signal | Meaning | Adopter action |
|--------|---------|----------------|
| Only `frameworkVersion` moved (`baselineChanged: false`) | CLI-only release; no managed file changed. | Update the framework; `upgrade --check` shows no managed-file changes. |
| `workflowBaselineVersion` moved (`baselineChanged: true`) | Template-changing release with a migration. | Update the framework, then `upgrade --apply` performs the migration plan. |
| `protocolVersion` newer than the project manifest's | The CLI reads and writes a newer manifest shape; the older manifest stays readable. | No extra step beyond `upgrade`. |
| Project manifest `protocolVersion` newer than the CLI's | The project was upgraded by a newer framework. | The CLI refuses with guidance (task 048); update the framework first. |

The adopter confirms the move by comparing the installed framework version
(the tag without its `v`) with the project's `frameworkVersion` in
`.meridian/manifest.json` after `upgrade --apply`, rather than trusting the
plugin manager alone.

Pre-manifest projects follow the existing `meridian adopt` path; this design
does not change it.

## Decision 5 — Adopter-facing release notes

Both locations, with `CHANGELOG.md` as the single source and the GitHub Release
body generated from it (task 050 already specifies that generation plus a link
to `releases/<version>.json`).

Every release section states its kind in its first line, matching the ledger:

- **CLI-only** — "CLI-only release: no template, workflow rule, or managed
  file changed" (existing wording). No adopter action beyond the update.
- **Template-changing** — the existing first line naming the migration ids and
  the new `workflowBaselineVersion`, plus an **Upgrade notes** subsection that
  lists: the affected capabilities and managed paths an adopter will see in
  `upgrade --check`, the required action (`upgrade --apply`), likely
  conflict areas for adapted projects, and any minimum framework version or
  `protocolVersion` change.

Host approval policy has two delivery paths. Codex rules in the managed file
`.codex/rules/meridian.rules` arrive through `meridian upgrade --check` and
`--apply`; the Claude Code allowlist arrives only through consented, additive
`meridian setup`, because it lives in a user-local settings file.

A mechanical check that the section's first line agrees with
`baselineChanged` and that a template-changing section has an Upgrade notes
subsection belongs in the release-notes follow-up task.

## Decision 6 — Support policy

Consistent with `migrations/`, `release-baselines/`, and the append-only
ledger:

- **Upgrade window.** Every published release from `v1.1.49` (the oldest
  release published as a tag) forward is upgradable to the newest release in a
  single `upgrade --apply`, proved by
  `test_oldest_published_release_upgrades_to_current_in_one_apply`. Migrations
  and packaged baselines are never removed while this policy holds.
  Amended by task 068: the original `1.0.0` window does not hold, because a
  pristine `1.0.0` project adopts with conflicts at migrations `037` and `038`
  (task 090, cancelled on 2026-10-03: the narrower window stays). Projects older than
  `v1.1.49` use `meridian adopt` best-effort.
- **Skipping releases** is supported; adopters need not step through
  intermediate releases.
- **Fixes land only in the newest release.** There are no backport branches; a
  correction ships as a new release, as the ledger rules already require.
- **Unsupported:** downgrades, manifests whose installed baseline is not
  recorded (use `meridian adopt`), and unreleased `main`.
- **Changing the window** (dropping the oldest baseline) requires a
  CHANGELOG-announced release and a migration or `adopt` path for affected
  projects; it is not done implicitly.

## Follow-up implementation tasks

All are added to `tasks/QUEUE.md` and `PROJECT_PLAN.md` as `[ ]`.

| ID | Objective | Depends on | Notes |
|----|-----------|------------|-------|
| 065 | Rename the marketplace to `meridian`, rewrite the README install and update sections around `#v<version>`, verify pinned add, plugin update, and CLI path resolution from an installed plugin, and document the `meridian-local` migration. | 049 | Outward-facing docs; first published tag needed to fully verify. |
| 066 | Add `meridian self-check --check-latest` per Decision 3. | 049, 050, 065 | Network dependency and public CLI surface: require an independent read-only review before Lean completion and integration. |
| 067 | Enforce the release-notes contract: `CHANGELOG.md` kind line agrees with the ledger and a template-changing section has Upgrade notes; feed the same into the GitHub Release body. | 049, 050 | Extends the task 050 script. |
| 068 | Document and test the support policy: one upgrade test spanning the oldest packaged baseline to current, and README/CONTRIBUTING statements of the window. | 049 | No CLI behavior change expected. |
| 069 | Document Codex install from a tagged checkout, verify the user skills directory and `MERIDIAN_ROOT` resolution, and record the result in the host capability contract. | 049 | Keeps Codex plugin distribution deferred. |

## Out of scope

Publishing to any marketplace directory or package index, creating tags or
releases, and any code change. Those follow from the tasks above and, where
outward-facing, need a separate developer decision.
