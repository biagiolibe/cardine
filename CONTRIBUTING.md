# Contributing to Cardine

Thanks for helping improve Cardine. Participation follows the [code of conduct](CODE_OF_CONDUCT.md); report suspected vulnerabilities using the [security policy](SECURITY.md).

## Development setup

Cardine requires Python 3.12 or later. Install from a clone:

```bash
git clone https://github.com/biagiolibe/cardine ~/src/cardine
pipx install --editable ~/src/cardine
cardine --version
```

For development in a task worktree, use a temporary virtual environment instead of installing the worktree with user-level pipx. Removing an installed worktree would break that installation.

```bash
python3 -m venv /tmp/cardine-dev-venv
/tmp/cardine-dev-venv/bin/python -m pip install --editable .
/tmp/cardine-dev-venv/bin/cardine --version
```

## Scope and language

Cardine provides one task lifecycle with `lean` and `governed` presets. Keep generic workflow assets free of project-specific rules. Repository text, including documentation, code, tests, and commit messages, is English; see [LANGUAGE_POLICY.md](LANGUAGE_POLICY.md).

## Before opening a change

Read the relevant templates and implementation, keep the change focused, and preserve corresponding Codex and Claude Code assets when changing workflow rules. Explain the problem, behavior change, and validation in the pull request.

## Validation

Follow the assigned task's validation contract and [PROJECT_WORKFLOW.md](PROJECT_WORKFLOW.md). The repository check is:

```bash
python3 scripts/check_repository.py
```

For focused development tests, select affected modules:

```bash
python3 scripts/run_tests.py --parallel --module test_check_repository
```

## Managed copies

Cardine manages the project's workflow files and task state. Use the lifecycle commands rather than editing task state by hand. See [PROJECT_WORKFLOW.md](PROJECT_WORKFLOW.md) and [migrations/README.md](migrations/README.md).

## Release procedure

## Changelog fragments

When a task makes a user-visible change, add exactly one fragment named
`changelog.d/<TASK-ID>.md`; add none when there is no user-visible change. A
fragment contains only the headings and bullets described in
[changelog.d/README.md](changelog.d/README.md). Do not edit the shared
`[Unreleased]` section for new work.

`python3 scripts/release.py prepare` validates and groups fragments in a fixed
heading and file-name order, consumes them in its release commit, and continues
to render an existing non-empty `[Unreleased]` body first during the migration.
Use `python3 scripts/release.py changelog render --version X.Y.Z` to inspect
the rendered body, or add `--write` to put it in `[Unreleased]` and consume the
fragments without making a Git commit. For an already-prepared template-changing
release, add `--prepared` to inspect or update the existing `## [X.Y.Z]` section
instead. This preserves its release kind line, merges subsection content in the
same heading and file-name order, and keeps a single `### Upgrade notes` heading.
With no pending fragments, `--prepared --write` leaves the file unchanged.

For a **CLI-only release**, `python3 scripts/release.py prepare --bump patch`
(or `--bump minor`, `--bump major`, or `--version X.Y.Z`) is the repeatable
local preparation command. It derives the release kind from migrations, writes
the version, ledger, and changelog files, runs the release checks, and makes one
local release commit. It never fetches, pushes, creates a tag, or compares
manifests. Use `--dry-run` to inspect its derived result first. The manual
procedure below remains valid; in particular, the manifest comparison remains a
manual step.

When changing the release version, update both `VERSION` and the `version`
field in `.claude-plugin/plugin.json`; the repository check requires them to
match.

Every release adds a `releases/<version>.json` record (see
[releases/README.md](releases/README.md)); `python3 scripts/check_repository.py`
requires one for the current `VERSION`. Then choose the release kind:

- **CLI-only release**: no template, workflow rule, or managed file changed.
  Bump `VERSION` and add the ledger record with `baselineChanged: false` and an
  empty `migrations` list. Add no migration; `workflowBaselineVersion` stays at
  the newest existing migration's target.
- **Template-changing release**: add a migration whose `to` equals the new
  `VERSION`, and list its id in the ledger record with `baselineChanged: true`.
  This is what advances `workflowBaselineVersion`.

Every `CHANGELOG.md` release section states its kind in its first line: begin a
CLI-only section with `CLI-only release` and a template-changing section with
`Template-changing release`. The line must agree with the ledger's
`baselineChanged`, and a template-changing section must also have a non-empty
`### Upgrade notes` subsection listing the affected capabilities and managed
paths, the required action (`upgrade --apply`), likely conflict areas for
adapted projects, and any minimum framework or `protocolVersion` change. The
release script enforces both rules.

Every retirement migration must register its distinctive seeded phrases, affected
files, retirement version, and manual remedy in `capabilities/retired-text-v1.json`
in the same task. Keep the registry valid against
`schemas/retired-text-v1.schema.json`; only project-owned text is advisory.

The last migration may lag behind `VERSION` but must never target a version
ahead of it.

For a **template-changing release**, the task that adds the migration must also
bump `VERSION`, `.claude-plugin/plugin.json`, the release ledger, and the
changelog in its ordinary commits. Do not run `prepare`: it recognizes this
already-prepared state and directs you to publish when no fragments remain.
If later tasks add fragments, both `prepare` and `publish` stop and name the
pending files. Run `python3 scripts/release.py changelog render --version X.Y.Z
--prepared --write` for the current `VERSION`, review the merged section, and
commit `CHANGELOG.md` together with the consumed fragment removals before
publishing. For either path, on `main`,
publish with `python3 scripts/release.py publish --confirm v<VERSION>`. The
confirmation must exactly match the current `VERSION`; the command prints every
commit to push, the ledger kind, and any migration ids before it pushes `main`,
creates and pushes the tag, then fast-forwards the remote branch `stable` to the release
commit with `git push origin <release-commit>:refs/heads/stable` (creating it on
the first release). It first checks that the commit's `.claude-plugin/plugin.json`
version equals the tag, and it stops, leaving `main` and the tag as published,
if `stable` is not an ancestor of the release commit. When `gh` is available, it polls every five seconds
for up to two minutes for the `Publish release` push run whose SHA matches the
tag, then watches and verifies it. Release verification uses `gh release view`
only with fields supported by current GitHub CLI versions and checks the latest
tag through `gh api`. Use `--no-wait` only when you will verify the
printed workflow and release URLs manually. If the run is not observed before
the timeout, the successful pushes remain unchanged and the command prints the
exact `gh run list`, `gh release view`, and read-only
`python3 scripts/release.py verify --version X.Y.Z` commands to resume.
`verify` requires the tag on `origin`, checks that remote `stable` points to
the tag commit, and performs the same polling, workflow,
release, and self-check verification without creating, moving, deleting, or
pushing anything. The release command never force pushes, deletes, or moves a
tag. If the workflow fails, the tag remains in place and no GitHub Release was
published: inspect the run, fix the cause, and move the tag only if no release
exists for it. The
`.github/workflows/release.yml` workflow runs `scripts/prepare_release.py`, which
fails unless the tag equals `v` plus `VERSION`, `releases/<VERSION>.json` exists
with a matching `gitTag`, `.claude-plugin/plugin.json` matches `VERSION`, and
`CHANGELOG.md` has a `## [<VERSION>]` section whose kind line and Upgrade notes
satisfy the rules above. It then runs the repository check
and the unit tests, and creates the GitHub Release whose body is that changelog
section plus a link to `releases/<VERSION>.json`. Do not create the release by
hand.

Before releasing, compare the manifest written by the new CLI with the prior
release. Bump `PROTOCOL_VERSION` only when the manifest shape or semantics
change in a way that an older CLI cannot safely read. Backward-compatible
additions, including fields with a safe legacy fallback, do not require a
protocol bump. When a bump is required, add compatibility tests that prove the
older protocol remains readable and the newer protocol is rejected by the
current reader with upgrade guidance.

## Support policy

See the [README](README.md) for installation and the [design decisions](docs/ADR_CARDINE_1_0.md) for the release plan.

## Pull requests

Describe the user-facing problem, the behavior that changes, and how you validated it. Avoid unrelated formatting changes.
