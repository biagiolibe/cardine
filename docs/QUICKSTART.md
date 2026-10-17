# Adopter quick start

Install the latest stable release, initialize a project, and close one small
Lean Delivery task. The `stable` ref follows published releases; use an exact
`v<version>` tag from [Releases](https://github.com/biagiolibe/meridian/releases)
when you need a fixed pin. The [clean-install report](CLEAN_INSTALL_VERIFICATION.md)
records the historical release it tested. See the
[public surface classification](PUBLIC_SURFACE.md) for compatibility promises.

## Prerequisites

- macOS or Linux; see the [platform matrix](PLATFORM_SUPPORT.md).
- Python 3.12+ and Git on the shell PATH used by your agent. Check with
  `python3 --version` and `git --version` inside that host as well as your terminal.
  Also check `zsh -lc 'python3 --version'` (or `bash -lc 'python3 --version'`
  for bash): on macOS a PATH without Homebrew can select system Python 3.9.
- An installed, authenticated Claude Code or Codex host. Meridian supplies
  workflow instructions; install and sign into the host separately.
- Network access for installation, release discovery, and a remote push.
  Use a persistent installation directory, not a temporary test home.
- Git author identity (`git config user.name` and `git config user.email`),
  a clean project checkout on `main`, and a writable `origin` for full closure.
  Set your identity before making the first commit.

On Homebrew macOS, if the selected Python is too old:

```bash
brew install python@3.12
export PATH="$(brew --prefix python@3.12)/libexec/bin:$PATH"
python3 --version
```

Persist the resolved Python directory (for example,
`/opt/homebrew/opt/python@3.12/libexec/bin`) in PATH before the Meridian
exports below in the same shell startup files. Use the resolved path so
startup does not depend on finding `brew` in a non-interactive shell.
Then restart your host.

## Install the CLI for every host

Install one release checkout for terminal commands and every agent host.
Choose the persistent canonical path below, which must not already exist:

```bash
git clone --branch stable https://github.com/biagiolibe/meridian ~/.local/share/meridian
export MERIDIAN_ROOT="$HOME/.local/share/meridian"
export PATH="$MERIDIAN_ROOT/bin:$PATH"
```

Use `--branch v<version>` instead of `--branch stable` to pin a release at
the same path. Persist both exports in the startup files that your terminal
and agent host load. For zsh, use `~/.zshenv`: non-interactive `zsh -c` and
`zsh -lc` do not read `~/.zshrc`. For bash, use `~/.profile` (or
`~/.bash_profile` when present) plus `~/.bashrc`; non-interactive `bash -c`
inherits exported variables, or reads a file explicitly selected by
`BASH_ENV`. Restart the terminal and host after persisting the exports.

Verify the resolved CLI, Python, and exact release tag:

```bash
command -v meridian
meridian --version
cat "$MERIDIAN_ROOT/VERSION"
git -C "$MERIDIAN_ROOT" describe --tags --exact-match
zsh -lc 'command -v meridian'
zsh -lc 'python3 --version'
```

For bash, replace `zsh -lc` with `bash -lc`. The non-interactive CLI check
must print the checkout's `bin/meridian`, and Python must be 3.12 or newer.
The CLI version, `VERSION`, and tag must agree. The checkout changes only
when you explicitly update it; see the
[framework update instructions](HOW_TO_UPGRADE.md#1-update-the-framework-first).

## Connect Claude Code

In Claude Code, add the stable marketplace and install its plugin:

```text
/plugin marketplace add biagiolibe/meridian#stable
/plugin install meridian@meridian
```

Open `/plugin` and confirm Meridian is enabled at the same release as the
checkout. Keep the plugin and checkout at the same release when updating or
pinning a tag. Plugin commands use `${CLAUDE_PLUGIN_ROOT}/bin/meridian`;
terminal commands use the checkout CLI installed above. Continue with
initialization below.

## Connect Codex

Use the checkout installed above; no second clone is needed. From your project,
preview the skill links and Codex permission profile:

```bash
meridian setup --check
```

Review the exact diff, then explicitly consent before applying:

```bash
meridian setup --apply
```

Restart Codex afterwards. Setup creates user skill links under
`~/.agents/skills`; inspect older `~/.codex/skills` copies yourself to avoid
loading stale instructions. Initialization and the project-specific setup
review below cover workflow and task identity choices.

## Initialize and choose a workflow

Open the target project directory in your host. In Claude Code run:

```text
/meridian-init
```

For Codex, there is no `meridian init` CLI subcommand. Ask Codex:

```text
Initialize this project by following $MERIDIAN_ROOT/commands/meridian-init.md
as instructions. Resolve the environment variable to the installed checkout;
use that checkout wherever the instructions name CLAUDE_PLUGIN_ROOT.
Ask me for the choices and confirmations the instructions require.
```

Choose the project name, conversation language, workflow mode, and task
identity when asked. Choose **lean-delivery** for this first reversible task;
**governed-sdd** adds architectural authority, dependency and review gates.
Choose **opaque** identity to use the numeric `001` example below, or
**milestone** for `M<milestone>-<WORKSTREAM>-<ordinal>` IDs (then use the ID
returned by the identity command throughout). These are explicit user choices.
Repository artifacts remain English in either conversation language.

The initializer copies the base templates and mode overlay, fills project
details, and runs `meridian lock --project . --mode lean-delivery`. Confirm
`PROJECT_WORKFLOW.md` declares `LEAN_DELIVERY`, `AGENTS.md` and `CLAUDE.md`
exist, and `.meridian/manifest.json` was generated. Do not edit the manifest
manually. Fill `TECH_DESIGN.md` and the project's actual validation commands
before assigning implementation. Existing workflow files require a displayed
diff and your decision before replacement.

### Review setup once

From the project, review the initializer's setup plan. If it has not already
been shown, run it with your selected identity:

```bash
meridian setup --check --task-identity opaque
```

This can propose the worktree directory (default `~/.meridian/worktrees`),
Codex user permission profile and skill links, project-local Claude settings,
and project declarations. It is broader than linking skills. After reviewing
the exact diff and explicitly consenting, apply once:

```bash
meridian setup --apply --task-identity opaque
```

Use your chosen identity instead of `opaque` if different. Restart Codex after
apply; Claude Code requires no Codex host profile. A warning about a temporary
root is expected in a disposable verification harness, but use a persistent
root for real work.

In the restarted Codex session, from the project run:

```bash
meridian codex doctor
git status --short
git worktree list --porcelain
```

Doctor exit 0 means diagnostics ran, even if individual states are `blocked`
or `approval-required`. On first use, project trust, command policies, and Git
metadata can still need attention. Review and trust the project through your
host, inspect the reported fields, then verify actual worktree access: after
`prepare` below, run `check`, `git status --short`, and a reversible write/delete
of a scratch file in that exact task worktree from Codex. Verify the expected
routine commands run under the loaded profile. Configuration alone does not
prove effective session permissions; do not bypass a denied operation.
See [permission diagnostics](AGENT_OPERATIONS.md#codex-command-approvals-in-governed-sdd)
for the additional Governed-SDD rules checks.

Before committing, add `.claude/settings.local.json` to the consumer project's
`.gitignore` and confirm `git check-ignore .claude/settings.local.json` prints
the path. Setup-generated settings are local; verify this entry even when
using an older base ignore template.

For either host, finish the version check with:

```bash
meridian self-check --check-latest
```

`Installed` should match your pin. Exit 0 is `UP_TO_DATE`; exit 10 is
`UPDATE_AVAILABLE` (a valid older pin). Exit 11 is `UNKNOWN`, for example when
DNS, offline access, or rate limits prevent release discovery. It does not
prove an installed-version mismatch. A tagged Codex checkout may report
`Plugin ref: unknown` because it has no Claude marketplace entry.

## Close a first Lean Delivery task

Use a documentation-only change, such as adding a short purpose paragraph to
your project's README. Follow the [reproducible Lean Delivery walkthrough](examples/LEAN_DELIVERY_WALKTHROUGH.md)
for executable commands, checked file excerpts, and a local bare origin.
The steps below outline the lifecycle.
Use an existing writable remote here. Never apply the documentation-only
validation example below to source or runtime changes.

1. **Create the task before assigning it.** In Claude Code run
   `/meridian-task`; in Codex invoke `$meridian-lean-delivery` and ask it to
   create the task following the local workflow and task blueprint. Specify
   the paragraph, measurable acceptance criteria, affected file, and validation
   (`git diff --check` plus human inspection of the requested text). Reconcile
   the template's initial `001` queue row rather than adding a duplicate.
   Before execution, check that the task file has explicit metadata such as
   `> **ID**: \`001\``, a matching queue row and a recognized plan entry:

   ```text
   - `[ ]` 001 — Add the project purpose paragraph.
   ```

2. **Declare candidate checks before the first task.** Review
   `.meridian/candidate-validation.json`; setup may leave it `undeclared`.
   For this documentation-only consumer, the minimal declaration is:

   ```json
   {
     "version": 1,
     "state": "declared",
     "outcomes": {
       "REUSE": ["git diff --check"],
       "BOUNDED": ["git diff --check"],
       "FULL": ["git diff --check"]
     }
   }
   ```

   For an application, declare the real repository, bounded, and full-suite
   gates instead; see [candidate validation](WORKTREE_LIFECYCLE.md#candidate-validation-by-integration-outcome).
   Commit the initialized project, task/queue/plan, ignore entry, and policy
   on `main`, then push the baseline to `origin` before delegation.

3. **Assign only that task.** Send `Proceed with 001` to your agent from the
   primary checkout. The local workflow authorizes implementation, validation,
   closure, one plain push of the integration to `main`, and cleanup when gates
   pass. It does not authorize tags, releases, force pushes, or other tasks.
   The agent first runs:

   ```bash
   meridian worktree prepare 001 --project <primary-checkout> --format json
   ```

   It uses the returned branch and absolute worktree path. In that worktree,
   before substantive work, it runs:

   ```bash
   meridian worktree check 001 --project <primary-checkout> --format json
   meridian execution start 001 --project .
   ```

   Expect a ready, clean check. Lean start can return `state: null` and
   `started: false`; no machine state is added just to claim progress.

4. **Implement, verify, and record completion in the task worktree.** The
   agent checks the actual paragraph and runs the task's validation. After
   success it commits the implementation, records exact results and validated
   task/base commits in `tasks/handoffs/001.md`, and marks the task's acceptance
   criteria. If closure requires machine state, it uses
   `meridian task transition 001 DONE`; it never edits status fields by hand.
   It runs `mkdir -p tasks/done` before archiving the exact task record there
   and commits the completion records. An empty directory from initialization
   may not exist in a linked Git worktree. Queue and plan edits belong to
   integration, not the task branch.

5. **Integrate from the primary checkout.** After validation and the completion
   commit, the agent supplies only results it actually obtained:

   ```bash
   meridian worktree advance 001 --project . --accepted --validation-command "git diff --check" --validation-exit-code 0 --format json
   ```

   `advance` records evidence and stages integration, including queue/plan
   completion. It never executes validation itself. When `action_required`
   is `run-candidate-validation`, run every returned command on the staged
   candidate in the primary checkout. For the minimal policy above, run
   `git diff --check` and inspect the merged paragraph, then report the result:

   ```bash
   meridian worktree advance 001 --project . --accepted --candidate-command "git diff --check" --candidate-exit-code 0 --format json
   ```

   Follow the returned action exactly. Successful finalization returns `push`:

   ```bash
   git push origin main
   meridian worktree advance 001 --project . --accepted --format json
   ```

   The last call performs cleanup and should return `action_required: none`.
   If a gate prints `BLOCKED <CODE>`, preserve the result and follow its resume
   command; never report a failed gate as success. For diagnosis use the
   [single-step lifecycle reference](WORKTREE_LIFECYCLE.md#commands).

6. **Check closure.** `git status --short` is empty, `HEAD` matches
   `origin/main`, the task's queue/plan records show completion (a fully closed
   queue section may be archived), and `git worktree list --porcelain` no
   longer lists its worktree. `git branch --list task-001` should be empty.
   `meridian worktree cleanup 001 --project . --format json` is an idempotent
   diagnostic if cleanup already ran.

## Where to go next

- [Lean Delivery guide](../WORKFLOW_GUIDE.md) and your project's mode lock.
- [Agent operations](AGENT_OPERATIONS.md): console, permission rules, read guard,
  and local usage reports.
- [Upgrade guide](HOW_TO_UPGRADE.md) when choosing a newer release pin.
- [Clean-install evidence and limitations](CLEAN_INSTALL_VERIFICATION.md):
  the shell lifecycle was exercised; interactive marketplace/init and effective
  restarted host permissions remain unverified. This guide is not new evidence
  that those interactive steps passed.
- [Contributing](../CONTRIBUTING.md) for framework maintenance and releases.
