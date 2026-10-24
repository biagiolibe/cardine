# Contributing to Meridian

Thanks for helping improve Meridian.

Participation follows the [code of conduct](CODE_OF_CONDUCT.md). Report suspected
vulnerabilities privately using the [security policy](SECURITY.md).

## Cardine development package

This package skeleton is for editable development only. Do not publish this
state to PyPI: framework assets and non-editable installation are not yet
supported. `VERSION` remains the build-time version source at `1.4.0` until
the later compatibility-removal work item.

Use a temporary virtual environment (Python 3.12 or later):

```bash
python3 -m venv /tmp/cardine-dev-venv
/tmp/cardine-dev-venv/bin/python -m pip install --editable .
/tmp/cardine-dev-venv/bin/cardine --version
```

The `cardine` command runs this checkout's existing CLI, even if
`MERIDIAN_ROOT` names another checkout. The existing `bin/meridian` and
`scripts/meridian.py` entry points remain available. Do not install a task
worktree with user-level `pipx`: removing the worktree would break the command.

## Repository layout

```text
commands/                         Claude Code commands
hooks/                            Queue briefing hook
bin/                              Framework maintenance CLI
capabilities/                     Machine-readable framework capability catalog
docs/                             Architecture, workflow, and operator documentation
migrations/                       Versioned deterministic upgrade records
releases/                         Immutable release ledger records
schemas/                          JSON schemas for Meridian records
scripts/                          Repository validation and release tooling
skills/                           Codex and Claude Code workflow skills
tasks/                            Active task records, queue, and handoffs
templates/single/                 The one template set both presets install
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

Until Cardine 1.0, use the no-migration template rule under
[Managed copies of this repository](#managed-copies-of-this-repository).
The migration chain in `migrations/` starts empty at Cardine 1.0; see
[migrations/README.md](migrations/README.md) for the record format.

A migration that modifies framework-mandated prose already tracked as a
capability — not just adds a new managed file — must declare `capability`
and `capabilityVersion` in its migration record, wrap the affected text in
`<!-- MERIDIAN:BEGIN capability=<id> vN --> ... <!-- MERIDIAN:END -->`
markers if it doesn't already carry them, and describe the change in a
`delta` field scoped to what actually changed, not a from-scratch rewrite.
Presence-only, phrase-based detection cannot tell a modified capability
from an unmodified one, and breaks on a project whose wording has diverged
from the template. A migration that never introduces or changes a capability
(framework-CLI-only changes, for example) does not need these fields. Do not
add a migration merely to justify a version bump: a release that changes only
the CLI is a CLI-only release (see [Release procedure](#release-procedure))
and ships no migration.

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
seconds and `--parallel` (8 workers) about 52 seconds. The signal CI and the project's own
candidate validation use the parallel command; the release gate keeps the
sequential one.

For focused development runs, use:

```bash
python3 scripts/run_tests.py --parallel --last-failed
python3 scripts/run_tests.py --parallel --module test_run_tests
python3 scripts/run_tests.py --parallel --module tests/test_run_tests.py --module test_other.Example.test_value
```

Every full parallel run stores sorted failing and erroring test IDs in
`cardine-last-failed.txt` inside the current worktree's own Git directory.
A passing run empties the record. Clean-clone validation updates the originating
worktree's record. `--last-failed` reruns the recorded IDs and drops resolved
or removed tests; removed IDs are named and skipped. A missing, empty, or
entirely obsolete record runs nothing, exits 2, and prints the full command.
`--module` accepts a module, path, qualified class, or full test ID, and can
be repeated to select their union. Unknown names exit 2 with nearby modules.
Both options require `--parallel`, are mutually exclusive, and reject
`--clean-clone`. Partial summaries begin with `PARTIAL` and include the
selection, tests run, and full coverage total. They never count as validation;
a passing partial run prints `python3 scripts/run_tests.py --parallel
--clean-clone` as the next command. Failed full runs print the `--last-failed`
command instead.

The check validates JSON metadata, Bash syntax, required public-repository files, and links between the repository's Markdown documents.

A plain repository check never rewrites digests. See
[Managed copies of this repository](#managed-copies-of-this-repository) for how
to refresh them.

A task validates locally and in a clean clone, and no task waits for CI:

```bash
python3 scripts/run_tests.py --parallel --clean-clone
```

The command refuses a working tree with uncommitted changes. It clones the
committed `HEAD` with `git clone --depth 1 --no-local` into a temporary
directory, runs `python3 scripts/check_repository.py` and the parallel suite
there, removes the clone, and prints the commit, the coverage `total` and
`digest`, and the outcome. It sees only committed files and a shallow history,
as a CI checkout does.

CI runs the repository check and the suite on Linux for pull requests and
pushes to `main`, as a non-blocking signal. The release gate
(`.github/workflows/release.yml`) runs the repository check and the sequential
suite on Linux and macOS, and publishes the release only when both pass.
`scripts/ci_evidence.py` stays for projects that require CI evidence before
landing; this repository's tasks do not.

Changes under `bin/`, `migrations/`, `scripts/`, or `src/cardine/` run the
test suite with `python3 scripts/run_tests.py --parallel`, the command the signal CI runs.
Its coverage `total` and `digest` prove that every test ran, so a task does
not also run the sequential suite. The sequential suite runs in the release
gate, in row V01 of `docs/MODULE_SPLIT_PLAN.md`, and as the fallback when the
parallel run cannot start its workers:

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
python3 scripts/dev.py agent-evals --host claude --scenario main-ahead-integrates --runs 5
python3 scripts/dev.py agent-evals --host codex
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

## Development commands

Run maintainer tools from the repository checkout:

```bash
python3 scripts/dev.py profile doctor <profile-id> --project <consumer>
python3 scripts/dev.py report flow --project <consumer> --format json
python3 scripts/dev.py generate-entry-routers --template --check
python3 scripts/dev.py generate-entry-routers --project <consumer> --write
python3 scripts/dev.py agent-evals --help
```

The single generator replaces `generate-claude-md` and `generate-entry-routers`
in the user CLI. `--template` generates the single template set's shared
`CLAUDE.md` body; without it, the consumer's canonical router produces both entry files.
Use `--check` to detect drift without writing and `--write` to regenerate.
Profile and journal arguments and output retain their previous behavior.

## Managed copies of this repository

The installed Meridian owns this repository's `.meridian/` and managed copies:
`PROJECT_WORKFLOW.md`, `AGENTS.md`, `CLAUDE.md`, `LANGUAGE_POLICY.md`, `.codex/`,
the managed documents under `docs/`, and the managed hooks. Check installation
integrity locally with the installed Meridian:

```bash
meridian profile doctor meridian-self-hosting --project .
meridian audit --project . --mode lean-delivery --ci-profile meridian-self-hosting
```

Never edit `.meridian/` or managed copies by hand, rewrite their digests, or run
the checkout's `upgrade` on this repository. Restore an accidentally changed
managed copy from `main`. Product catalog, template, migration, and release
changes do not update this installed baseline. CI checks product code and
recorded managed digests; installation integrity is a local lifecycle check.

Until Cardine 1.0, no project runs Cardine. A template change bumps the
capability version, updates its `requiredVersion` in
`capabilities/markers-v1.json` to the version shipped by the Governed SDD
managed templates, and runs:

```bash
python3 scripts/check_repository.py --write-marker-baselines
```

Adoption detection reads only the Governed SDD templates and uses the first
marker in managed-file order. `requiredVersion` must equal that version; a
Lean-only bump therefore does not change it. `check_repository.py` enforces
this equality for every required, non-retired capability.

Commit the template, catalog, and `capabilities/marker-baselines.json`
together. Add no migration and do not bump `VERSION` for a template change.
The marker catalog is separate from `catalog-v1.json`, which describes
installation profiles. For a new marker, set `required: true`, `retired: false`,
and use its capability ID as the `adoptionRecord` label; existing labels are
retained for marker-catalog compatibility and do not require a new migration.
Mark a retired capability with `retired: true` and `required: false` in the
marker catalog. The catalog owns current requirements and retirements;
historical migration records are not the source of current template state.
This pre-1.0 rule takes precedence over the historical migration and release
procedures below.

Never run the checkout's `upgrade` on this repository. Its `.meridian/`
records belong to the installed Meridian, which runs this repository's
lifecycle. Task state files are written only by the installed Meridian
lifecycle commands, never by hand. The other records must not be edited to
accompany Cardine template changes. The installed Meridian is currently
1.4.1; 1.4.0 is the manifest's baseline. On 2026-10-18, the checkout's upgrade
rewrote digests of unchanged files and deleted `.meridian/baselines/1.4.0`.

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
  unsupported.
- A change to a template or migration must keep the proving test green.

Conversion of projects without Cardine and of existing Meridian projects returns with work item 10, using the single Cardine workflow. Until then, the CLI provides no conversion command.

## Pull requests

Explain the user-facing problem, the workflow behavior that changes, and how you validated it. When a change modifies a mode rule, identify every corresponding asset you updated—for example, the workflow document, `AGENTS.md`, `CLAUDE.md`, task template, queue template, commands, and skills.

Avoid unrelated formatting changes. They make workflow changes harder to audit.
