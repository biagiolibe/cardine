# Contributing to Meridian

Thanks for helping improve Meridian.

Participation follows the [code of conduct](CODE_OF_CONDUCT.md). Report suspected
vulnerabilities privately using the [security policy](SECURITY.md).

## Repository layout

```text
commands/                         Claude Code commands
hooks/                            Queue briefing hook
bin/                              Framework maintenance CLI
capabilities/                     Machine-readable framework capability catalog
docs/                             Architecture, workflow, and operator documentation
migrations/                       Versioned deterministic upgrade records
release-baselines/                Archived release baseline templates
releases/                         Immutable release ledger records
schemas/                          JSON schemas for Meridian records
scripts/                          Repository validation and release tooling
skills/                           Codex and Claude Code workflow skills
tasks/                            Active task records, queue, and handoffs
templates/base/                   Shared stack-agnostic templates
templates/workflows/lean-delivery/ Lean Delivery overlay
templates/workflows/governed-sdd/ Governed-SDD overlay
tests/                            Unit tests
.github/workflows/                GitHub Actions workflows
WORKFLOW_GUIDE.md                 Lean Delivery workflow reference
CONTRIBUTING.md                   Contribution guidance and validation
```

## Scope

Meridian is a stack-agnostic workflow for agentic software development. Keep generic workflow assets free of product, language, framework, and hosting-specific rules. Project-specific architecture belongs in generated projects, not in this repository's templates.

## Language invariant

Meridian repository text is English-only. Keep documentation, source code, comments, identifiers, user-facing strings, tests, configuration text, and commit messages in English. The only configurable language is the agent-developer conversation language, persisted in generated projects through `LANGUAGE_POLICY.md`; an individual prompt in another language does not change it.

When changing this behavior, keep the base and governed-SDD language-policy templates identical. For a workflow-rule change, update the corresponding Codex and Claude Code instruction and skill assets for that mode.

## Migrations and capability markers

A migration that modifies framework-mandated prose already tracked as a
capability — not just adds a new managed file — must declare `capability`
and `capabilityVersion` in its migration record, wrap the affected text in
`<!-- MERIDIAN:BEGIN capability=<id> vN --> ... <!-- MERIDIAN:END -->`
markers if it doesn't already carry them, and describe the change in a
`delta` field scoped to what actually changed, not a from-scratch rewrite.
See [migrations/CAPABILITY_MARKERS.md](migrations/CAPABILITY_MARKERS.md) for
why: presence-only, phrase-based detection cannot tell a modified capability
from an unmodified one, and breaks on a project whose wording predates the
exact phrase or has diverged from the template. A migration that never
introduces or changes a capability (framework-CLI-only changes, for example)
does not need these fields. Do not add a migration merely to justify a version
bump: a release that changes only the CLI is a CLI-only release (see
[Release procedure](#release-procedure)) and ships no migration.

Retrofit markers into an older migration's content opportunistically, on its
next real change, rather than as a dedicated migration with no other
purpose — migrations 003, 004, and 005 do not carry markers yet for exactly
this reason.

## Before opening a change

1. Read the relevant template, command, hook, or skill end to end.
2. Keep a change focused on one behavior or document set.
3. Preserve parity between the Codex and Claude Code skills for the workflow mode being changed.
4. Do not change generated-project behavior accidentally while editing explanatory documentation.

## Validation

Use Python 3.12 or later for Meridian development and validation. Check the
interpreter selected by your shell with `python3 --version` before running the
commands below.

Run the repository checks before proposing a change:

```bash
python3 scripts/check_repository.py
```

When the full test suite exceeds the host command limit, run its deterministic
test shards instead. The measured default is 8 shards:

```bash
python3 scripts/run_tests.py --list
python3 scripts/run_tests.py --shard 1/8
python3 scripts/run_tests.py --shard 2/8
python3 scripts/run_tests.py --shard 3/8
python3 scripts/run_tests.py --shard 4/8
python3 scripts/run_tests.py --shard 5/8
python3 scripts/run_tests.py --shard 6/8
python3 scripts/run_tests.py --shard 7/8
python3 scripts/run_tests.py --shard 8/8
```

`--list` prints the full-suite `total` and SHA-256 `digest`; each shard prints
the same coverage fields together with its selected count. A sharded run is
complete only when every shard for the chosen count ran against the same tree
and reported the same `total` and `digest`. `python3 -m unittest discover -s
tests` is the release gate (`release.yml` runs it) and the fallback for a host
where the parallel run cannot start its workers.

To run the shards concurrently and get one combined result, use the standard
validation command for this repository:

```bash
python3 scripts/run_tests.py --parallel      # CPU count, at most 8 workers
python3 scripts/run_tests.py --parallel 4    # explicit count; 1 is a sequential run
```

`--parallel N` runs N shards as separate processes, each with a private
`TMPDIR` and a `MERIDIAN_TEST_SHARD` variable, captures their output, and prints
it in shard order. A passing run prints two lines: the totals with wall time and
the same `total`/`digest` proof as `--list`, plus the number of tests the shards
selected. A failing, erroring, killed, or mismatched shard exits non-zero, and
the failing shards print first, limited to their last 60 lines. On the
reference machine (10 cores, 752 tests) the sequential run took about 277
seconds and `--parallel` (8 workers) about 52 seconds. CI and the project's own
candidate validation use the parallel command; the release gate keeps the
sequential one.

The check validates JSON metadata, Bash syntax, required public-repository files, and links between the repository's Markdown documents.

A plain repository check never rewrites digests. See
[Managed copies of this repository](#managed-copies-of-this-repository) for how
to refresh them.

CI runs the same validation suite on pull requests, pushes to `main`, and
pushes to `task-*` branches. Runs are on Linux, so macOS-only tests are skipped.
Push a task branch before expecting a CI run, then use
`python3 scripts/ci_evidence.py --commit <sha> --task <TASK-ID> --output <path>`
to capture a successful exact-commit run as T1 CI evidence. Add `--wait SECONDS`
to poll for a new run. Until Task 115 records whether task-branch pushes are
covered by standing authorization, a missing run remains `unavailable`; do not
work around it by pushing the branch.

For changes under `bin/`, `migrations/`, or `scripts/meridian.py`, also run the
sequential suite:

```bash
python3 -m unittest discover -s tests -v
```

The AppleScript compile test proves its iTerm2 payload compiles only where
`osacompile` can resolve the iTerm2 scripting dictionary. If it is skipped
because the dictionary is unavailable, record it as a skip in the task handoff;
before a release, a maintainer must run the full suite outside the agent sandbox.

For a change to a template or workflow rule, also manually trace the affected path from initialization through task creation, implementation, review, acceptance, and a framework-upgrade plan. The templates are the product.

### Agent evaluations

`unittest` proves that the CLI and the managed text agree; it cannot prove that
an agent reading the managed text behaves correctly. `scripts/run_agent_evals.py`
runs a real agent on a scripted fixture and grades the outcome from the
lifecycle journal and the final Git state, never from the agent's text:

```bash
python3 scripts/run_agent_evals.py --host claude --scenario main-ahead-integrates --runs 5
python3 scripts/run_agent_evals.py --host codex
```

Each scenario in `evals/scenarios/<name>/` holds `setup.sh` (builds a fixture
repository with Meridian installed and a local bare `origin`), `prompt.txt` (the
developer directive), and `expect.json` (`kind` `safety` or `progress`,
`journal_must_contain`, `git` assertions, and `must_not` conditions). The runner
repeats each scenario `--runs` times (default 5) in a fresh temporary directory,
prints one line per run and a pass count per scenario, and keeps a failing
fixture and the agent output for inspection. `--keep` keeps every fixture.

- **Cost**: every run is a full agent session that drives a task from `prepare`
  to `cleanup`, so expect minutes and a real token spend per run (`--runs 5` of
  one scenario is five sessions). `--max-budget-usd` caps one Claude Code run.
- **When to run it**: it is an optional, on-demand tool, never a release or
  integration gate. Run it when a change warrants it, for example after
  changing stop, denial, or closure rules in managed text, or to reproduce an
  agent behavior regression. It is outside `unittest` and CI, because runs are
  non-deterministic and billed. Only the grader and the safety guards have unit
  tests (`tests/test_agent_evals.py`).
- **Safety**: the runner builds fixtures in a fresh temporary directory outside
  any Git repository, refuses a fixture whose `origin` is not a local path inside
  that directory, points `MERIDIAN_WORKTREE_ROOT` and the global Git
  configuration at the fixture, and never touches your project or its remote.
  It isolates the host's user settings where the host allows it and prints what
  it could not isolate; the agent still runs as you, with your host sign-in.
  Codex runs under `workspace-write` with the temporary root as its workspace
  (the fixture, its origin, and an isolated `HOME` all live there), because the
  sandbox keeps `.git` read-only inside the workspace repository itself;
  `CODEX_HOME` stays real for the sign-in, and the prompt names the fixture
  directory.
- **Exit status**: `0` every scenario met its threshold, `1` a threshold was
  missed, `2` a usage or fixture error, and `3` when the host CLI or its
  credentials are missing. Status `3` never reports a pass.

Scenario kinds and thresholds:

| Kind | Threshold | Scenarios |
|------|-----------|-----------|
| `safety` | Every run passes (5 of 5). | `dirty-primary-stops`, `push-rejected-no-force`, `tag-request-refused`, `branch-keeps-off-governance` |
| `progress` | At least 4 of 5 runs pass. | `main-ahead-integrates`, `governed-remediation-completes` |

A scenario's result line ends with `threshold MET` or `threshold MISSED`.
Every scenario's `journal_must_contain` holds a record that any real run
produces, so a host that crashes at once cannot pass a scenario that grades only
the absence of a forbidden action. `setup.sh` records the facts the grader needs
(the base commit, the refs on `origin`, the dirty files' hashes) in
`<fixture>.eval-meta.json`, outside the repository.

A run is advisory. Treat a missed `safety` threshold as a finding to
investigate in the managed text or the CLI before relying on the change; no
release, commit message, or lifecycle step requires a run or its pass counts.

## Managed copies of this repository

This repository installs Meridian on itself. Its root `PROJECT_WORKFLOW.md`,
`AGENTS.md`, `CLAUDE.md`, `LANGUAGE_POLICY.md`, `.codex/` files, and the managed
documents under `docs/` are copies of the Lean Delivery templates, and
`.meridian/manifest.json` records the release and baseline they were installed
from. Never edit the manifest or `.meridian/baselines/` by hand; `meridian
upgrade` writes them.

A task that changes a managed template ships a migration and bumps `VERSION`
(see the release procedure below). In that same task, bring this repository's
copies to the new release with the checkout's own CLI:

```bash
bin/meridian upgrade --project . --check
bin/meridian upgrade --project . --apply
python3 scripts/check_repository.py --write-managed-digests
```

Do not retype the template change into a copy by hand. Run the last command
after `--apply` and review the manifest diff: `--apply` records the digest of
each template, but this repository's copies keep repository-specific text (the
project title, purpose, and local Codex rules), so the refresh records the
digest of each copy, recomputes the profiles' installation evidence from the
files, and restores a declared managed-copy surface that the upgrade's managed
list omits. Run it before `--apply` too when you have already edited a copy, so
that the recorded digests match the files the upgrade starts from.

`--apply` changes nothing while the plan has a `CONFLICT`. Resolve each one in
the copy, keeping this repository's intended text: where the copy only
paraphrases the template, take the template's text for that region; where it
carries repository-specific text, leave at least one unchanged baseline line
between it and the lines the template changed, because adjacent edits conflict.
Rerun `--check` until it reports no conflict. A managed document that has no
baseline yet and differs from the template is planned as `ADOPT-REPLACE`, which
would discard the copy: reduce the file to the template text, apply, then
restore the repository's own sections after the managed block.

Use `--write-managed-digests` on its own only for a deliberate edit to a managed
copy that follows no template change, such as repository-specific text outside
a capability block. Such an edit ships no migration and does not move the
manifest's release.

The repository check fails when the manifest's `workflowBaselineVersion` is
older than the newest migration's `to` that is not ahead of `VERSION`; run the
commands above to fix it.

## Versioning and deprecation

The stable compatibility promise starts at **1.3.0**. See the
[public surface](docs/PUBLIC_SURFACE.md) for command tiers and stable registries.
Choose versions by compatibility, independently of whether a release is CLI-only:

- **Patch**: fixes only, no new stable surface, no migration, and
  `baselineChanged: false`.
- **Minor**: additive stable surface, experimental changes, or template changes
  whose migrations apply through `meridian upgrade --apply`. Adopter action is
  limited to resolving conflicts in adapted managed text.
- **Major**: removing or renaming stable commands, flags or JSON fields;
  changing exit-status or stop-code meanings; removing stop codes; incompatible
  schema versions; a manifest `protocolVersion` refused by an older CLI;
  narrowing the support upgrade window; or any change requiring adopter action
  beyond `upgrade --apply`.

Deprecate stable surfaces in a minor release: list each under `Deprecated` in
its changelog and print a warning on stderr when it is used. Remove it only in
the next major release, under `Removed`. Experimental surfaces may be removed
in a minor release under `Changed`, explicitly marked experimental.

`release.py prepare` refuses patch releases with new migrations or fragment
subsections `Added`, `Deprecated`, or `Removed`, and minor releases with
`Removed`. Explicit `--version X.Y.Z` follows the same checks. These checks
cannot prove that an `Added` bullet is additive or a `Changed` bullet is
compatible: authors and reviewers remain responsible for that classification.

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

The support window is defined by Decision 6 in
`docs/DISTRIBUTION_AND_UPDATE_DESIGN.md` and stated for adopters in the README:

- Every published release from `v1.1.49` forward upgrades to the newest release
  in a single `upgrade --apply`, and releases may be skipped.
  `test_oldest_published_release_upgrades_to_current_in_one_apply` proves this
  from the snapshot in `tests/fixtures/release-1.1.49-governed-sdd.tar.gz`.
- Fixes land only in the newest release; do not add backport branches.
- Downgrades, manifests with an unrecorded baseline, and unreleased `main` are
  unsupported. Projects older than `v1.1.49` use `meridian adopt` best-effort.
- Never remove a migration or packaged baseline, or change the window, without a
  CHANGELOG-announced release and a migration or `adopt` path for affected
  projects. A change to a template or migration must keep the proving test green.

## Pull requests

Explain the user-facing problem, the workflow behavior that changes, and how you validated it. When a change modifies a mode rule, identify every corresponding asset you updated—for example, the workflow document, `AGENTS.md`, `CLAUDE.md`, task template, queue template, commands, and skills.

Avoid unrelated formatting changes. They make workflow changes harder to audit.
