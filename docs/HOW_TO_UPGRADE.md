# How to upgrade a project

This guide upgrades one Meridian-managed project to the release you have
installed, using `scripts/upgrade_project.sh`. The script wraps the manual
[Updating Meridian](#updating-meridian) and
[Framework upgrades](#framework-upgrades) procedures below. It runs on
a dedicated branch and never merges, pushes, tags, or deletes anything.

## 1. Update the framework first

A project can only be upgraded to a release the framework already has.
Every host uses the canonical CLI checkout at `~/.local/share/meridian`
(`$MERIDIAN_ROOT`); see the [installation steps](QUICKSTART.md#install-the-cli-for-every-host).
Update that checkout first. Claude Code users also update the plugin below:
both copies must stay at the same release. Terminal commands use the checkout CLI.

- **Claude Code** (marketplace declared with `"ref": "stable"`):

  ```text
  /plugin marketplace update meridian
  ```

- **Local framework checkout** (Experimental): run `meridian self-update
  --check` to inspect the current and target versions, release notes, template
  impact, and Git operation. Then run `meridian self-update --apply`.
  The command uses the checkout containing the running CLI, ignoring
  `MERIDIAN_ROOT` and `--framework-root`. It fast-forwards `stable` or switches
  a detached release checkout to the latest tag. For a pinned target or
  rollback, use `--to v<version>` on a detached release checkout; on `stable`,
  first switch explicitly with `git switch --detach v<version>`.
  Dirty trees, development branches, and divergent `stable` are refused.
  A plan never changes checkout refs or files. Offline release lookup exits 11
  with the latest release unknown; registered refusals exit 2.
  Apply verifies the target tag and `VERSION`. Restart running Codex and
  Claude Code sessions afterwards. For template-changing releases, run
  `meridian upgrade --check` in each project.

Read the release section in `CHANGELOG.md` before upgrading projects. A
template-changing release lists the affected files and likely conflicts under
`Upgrade notes`.

## 2. Pick the framework root

Pass the framework with `--meridian-root`. It must be a released version:

- the canonical checkout at `$MERIDIAN_ROOT` (`~/.local/share/meridian`),
  whose `HEAD` is exactly the tag `v<version>`; or
- as an alternative for `--meridian-root`, the installed Claude Code plugin,
  for example `~/.claude/plugins/cache/meridian/meridian/<version>`.

The script refuses a checkout that is not at the release tag, because upgrading
from unreleased `main` is not supported. `--allow-untagged` overrides this for
framework development only.

The examples below use:

```bash
export FW="$MERIDIAN_ROOT"
```

## 3. Prepare the project

The script checks these itself and stops if one fails:

- the project has `.meridian/manifest.json`;
- it is the primary checkout, on `main`, with a clean working tree;
- `main` is not behind `origin/main`;
- the branch `meridian-upgrade-<version>` does not exist yet.

Prefer upgrading when no task worktree is open. An open worktree keeps the old
workflow text until its task is integrated; the script prints a note when it
finds one.

## 4. Preview

Without `--apply` nothing is changed:

```bash
scripts/upgrade_project.sh /path/to/project --meridian-root "$FW"
```

It prints the `meridian upgrade --check` plan, the `meridian setup --check`
plan, and the queue usage-text diff. A blocked upgrade plan stops here; resolve
the listed conflicts before continuing.

## 5. Apply

Add `--apply` and the project's own validation commands, one `--validate` per
command:

```bash
scripts/upgrade_project.sh /path/to/project --meridian-root "$FW" --apply \
  --validate "<format check>" --validate "<build>" --validate "<tests>"
```

The script then:

1. creates the branch `meridian-upgrade-<version>`;
2. runs `meridian upgrade --apply`;
3. runs `meridian setup --apply`;
4. aligns the queue usage text with `scripts/align_queue.py`;
5. runs `meridian audit` and stops on any `FAIL` row (`UNVERIFIED` and
   `ADVISORY` rows do not stop it);
6. checks that the manifest `frameworkVersion` is the new version;
7. runs each `--validate` command in the project;
8. commits on the branch, leaving `.claude/settings.local.json` uncommitted.

If a step fails after the branch exists, nothing is committed and the script
prints the commands that discard the attempt and return to `main`.

## 6. Review, integrate, and publish

The script ends by printing these steps; run them yourself:

```bash
git -C /path/to/project diff main..meridian-upgrade-<version>
git -C /path/to/project switch main
git -C /path/to/project merge --ff-only meridian-upgrade-<version>
git -C /path/to/project push origin main
git -C /path/to/project branch -d meridian-upgrade-<version>
```

Then restart open Claude Code or Codex sessions in the project so they reload
the updated workflow text and settings.

## Options

| Option | Effect |
|--------|--------|
| `--apply` | Perform the upgrade; without it the run is a preview. |
| `--validate "<cmd>"` | Run a project validation command before committing; repeatable. |
| `--meridian-root <path>` | Framework to upgrade from; defaults to the `meridian` on `PATH`. |
| `--branch <name>` | Branch name instead of `meridian-upgrade-<version>`. |
| `--skip-setup` | Do not run `meridian setup`; it may also change machine-level settings such as the Codex profile and skill links. |
| `--skip-queue` | Do not align the queue usage text. |
| `--allow-untagged` | Accept a framework checkout that is not at its release tag. |

## Aligning only the queue

The queue is not a managed file, so `meridian upgrade` never changes it. To
align its usage text without upgrading, run the aligner directly. It finds the
queue through `meridian locations`, so a queue outside `tasks/QUEUE.md` (for
example `docs/TASK_QUEUE.md`) is handled:

```bash
python3 scripts/align_queue.py /path/to/project --meridian "$FW/bin/meridian"
python3 scripts/align_queue.py /path/to/project --meridian "$FW/bin/meridian" --apply
```

It never stages or commits, and a second run reports `no change`.

## Recovering a manual upgrade

If `meridian upgrade --apply` was already run by hand on `main` and left
uncommitted changes, the script refuses the dirty tree. Finish by hand instead:

```bash
git -C /path/to/project switch -c meridian-upgrade-<version>
python3 scripts/align_queue.py /path/to/project --meridian "$FW/bin/meridian" --apply
"$FW/bin/meridian" audit --project /path/to/project
```

Run the project's validation, commit on the branch, and continue with step 6.

## Updating Meridian

Update the framework before the project: a project manifest can only be read by
a CLI at least as new as its `protocolVersion`.

To upgrade a project in one guided run, see the
[guided procedure](#1-update-the-framework-first); the steps below are the
manual procedure it wraps.

1. Read the release notes on the Releases page or in [CHANGELOG.md](../CHANGELOG.md). The first
   line of each section says whether the release is CLI-only or
   template-changing.
   Optionally run `meridian self-check --check-latest` to compare the installed
   framework with the latest public GitHub Release. This is the only Meridian
   command that performs an update-discovery network request; it uses no
   credentials and writes no cache or state. Exit `0` means `UP_TO_DATE`, exit
   `10` means `UPDATE_AVAILABLE`, and exit `11` means `UNKNOWN` because the
   request was offline, rate-limited, or malformed. These informational results
   never block `upgrade` or other Meridian work.
2. Update the canonical checkout (`~/.local/share/meridian`) using the
   self-update procedure above, then move the Claude Code plugin pin to the
   same release if you use that host. Re-adding a marketplace at a different
   ref is refused, and removing a marketplace also uninstalls its plugins, so
   reinstall afterwards:

   ```text
   /plugin marketplace remove meridian
   /plugin marketplace add biagiolibe/meridian#v<new-version>
   /plugin install meridian@meridian
   ```

   If the marketplace was declared in `extraKnownMarketplaces` in user or
   managed settings, adding the new pin can instead fail with
   `Cannot add marketplace "meridian": its source doesn't match its extraKnownMarketplaces entry in user or managed settings`.
   That settings entry still names a different source or ref. Change its `ref`
   to the new tag, or remove the entry, then run `/plugin marketplace update
   meridian` or use the remove, add, and install sequence above. The entry may
   be in user settings or managed settings; a developer cannot change a managed
   entry, so its owner must update or remove it.

   A marketplace added without a pin can instead be refreshed with
   `/plugin marketplace update meridian`.

   To stop moving the pin by hand, set the entry's `ref` to `"stable"` once. The
   `stable` branch is advanced by each release's `publish` to the commit of its
   `v<version>` tag, so later releases need only `/plugin marketplace update
   meridian`. This documentation does not claim that Claude Code refreshes a
   third-party marketplace on its own. Exact tags remain the way to pin a
   version or roll back: set `ref` back to `v<version>`.

   To read the installed plugin version, use `/plugin`, read the `version` and
   `gitCommitSha` recorded for `meridian@meridian` in
   `~/.claude/plugins/installed_plugins.json`, or run `meridian self-check
   --check-latest`, which also prints a `Plugin ref:` line for the `ref` it can
   read from `extraKnownMarketplaces.meridian.source.ref` in user settings
   (`stable`, a current tag, an older tag with its remedy, or `unknown`). It
   never writes settings.
3. From the project, run `meridian upgrade --check`.
4. On a clean plan, apply it in a dedicated branch, validate the project, and
   commit the diff (see [Framework upgrades](#framework-upgrades)). Never
   hand-edit `.meridian/manifest.json`.

Confirm the move by comparing the installed framework version with the
project's `frameworkVersion` in `.meridian/manifest.json` after
`upgrade --apply`, rather than trusting the plugin manager alone.

To confirm the version Claude Code has actively installed, use these checks in
order:

1. In Claude Code, open `/plugin` and inspect the Meridian entry. This most
   directly shows the enabled plugin and its version. The interactive view was
   previously observed in a real user installation; the earlier installation verification checked the
   equivalent `claude plugin list` command in that installation.
2. Read `~/.claude/plugins/installed_plugins.json` and find the `version` in
   the `meridian@meridian` record. This identifies the active installed version
   and its install path.
3. Run `meridian self-check --check-latest`. With a successful network lookup,
   its `Installed`, `Latest`, and `Status` lines compare the installed framework
   with the newest release. During that earlier installation verification, the command ran from the
   active install but its lookup was blocked by DNS, so the `Latest` line
   remained unverified.

The plugin cache can retain older version folders. Those folders are not proof
that an older version is active; use the installed-plugin record or the plugin
list instead.

## Migrating from `meridian-local`

Earlier instructions registered a local clone as the `meridian-local`
marketplace. The marketplace is now named `meridian`, so the install id changes
from `meridian@meridian-local` to `meridian@meridian`. Migrate once:

```text
/plugin uninstall meridian@meridian-local
/plugin marketplace remove meridian-local
/plugin marketplace add biagiolibe/meridian#v<version>
/plugin install meridian@meridian
```

The migration can leave `~/.claude/plugins/cache/meridian-local/` on disk. It is
not used any more and can be deleted.

## Framework upgrades

Meridian-generated projects lock their installed workflow baseline in
`.meridian/manifest.json`. This makes framework changes deterministic rather
than dependent on a manual prompt.

The manifest tracks three independent version axes:

- `frameworkVersion` is the Meridian release version (the CLI and plugin). It
  moves with every release.
- `workflowBaselineVersion` is the version of the governed template baseline a
  project has installed. It is derived from the migrations and moves only when
  a release ships one, so it may lag behind `frameworkVersion`.
- `protocolVersion` is the manifest shape the CLI reads and writes. It moves
  only when an older CLI could not safely read the manifest.

A CLI-only release changes `frameworkVersion` but ships no migration: the
baseline stays where it was, and `upgrade --check` reports no managed-file
changes. A template-changing release adds a migration, which advances
`workflowBaselineVersion` to that release's version and produces the plan that
`upgrade --apply` performs. Each release is recorded in `releases/<version>.json`.

Check an upgrade from the installed Meridian source:

```bash
${MERIDIAN_ROOT}/bin/meridian upgrade --project /path/to/project --check
```

When the plan has no conflicts, apply it in a dedicated branch, validate the
project, and commit the resulting diff:

```bash
${MERIDIAN_ROOT}/bin/meridian upgrade --project /path/to/project --apply
```

The CLI performs a three-way merge between the installed baseline, the local
project file, and the new framework template. It applies no changes when a
managed file conflicts; resolve that bounded conflict in a dedicated upgrade
change and rerun the command. Do not edit `.meridian/manifest.json` or its
baseline snapshots by hand.

For a project created before framework locking was available, use the packaged
baseline that matches its installed Meridian version. For example, a compatible
`1.0.0` Governed SDD project can safely preview its migration with:

```bash
${MERIDIAN_ROOT}/bin/meridian adopt --project /path/to/project \
  --mode governed-sdd --from 1.0.0 --check
```

`adopt --apply` writes the manifest only after a clean plan. It refuses to
guess an unrecorded baseline; add an explicit snapshot before supporting a
different legacy version.

If an established project has intentionally adapted workflow documents, use
capability-aware adoption instead of forcing template merges:

```bash
${MERIDIAN_ROOT}/bin/meridian adopt --project /path/to/project --assisted --check
```

`--mode` and `--from` are detected automatically when unambiguous. The command
recomputes a single `NEXT_ACTION` (`IMPLEMENT_MIGRATION`, `REVIEW_MIGRATION`,
`ADDRESS_REVIEW`, `FINALIZE`, or `BLOCKED`) from the project's detected
capabilities and `.meridian/adoption-review.md` on every run, mapped onto the
CLI's exit codes (`3` for agent work required, `0` when ready to finalize, `2`
when blocked) — so an orchestrator, human, or the packaged Claude Code skill
can drive the whole migration by repeatedly running the same command and
acting on its `NEXT_ACTION`, dispatching the emitted implementer and reviewer
prompts to independent sessions (Task-tool subagents in Claude Code, separate
fresh chats otherwise) without ever copying context between them. Run
`meridian finalize-adoption` only after the reviewer records an unconditional
`APPROVE`; a developer who personally reviewed the migration may pass
`--owner-accepted` instead. See [assisted adoption](../commands/meridian-adopt.md).

### Support policy

- **Upgrade window.** Every published release from `v1.1.49` forward upgrades
  to the newest release in a single `upgrade --apply`. `v1.1.49` is the oldest
  release published as a tag, and the test suite proves this path.
- **Skipping releases** is supported; step through intermediate releases only
  if you prefer to.
- **Fixes land only in the newest release.** There are no backport branches; a
  correction ships as a new release.
- **Not supported:** downgrades, manifests whose installed baseline is not
  recorded (use `meridian adopt`), and unreleased `main`.
- **Projects older than `v1.1.49`**, including the packaged `1.0.0` baseline,
  are adopted with `meridian adopt` on a best-effort basis. A pristine `1.0.0`
  project currently adopts with conflicts against the newest release.
