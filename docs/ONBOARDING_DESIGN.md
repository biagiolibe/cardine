# Onboarding Design

Status: proposal, 2026-11-11. Nothing here is decided until the developer accepts it.
Accepted parts become tasks; parts marked *needs ADR amendment* also amend
`docs/ADR_CARDINE_1_0.md`.

## Problem

Cardine promises that an agent follows one command and a person only decides. Its
onboarding asks the opposite: the person runs most steps by hand and makes choices
the tool could make.

For a Claude Code user with an existing project, the path to the first task in
`docs/QUICKSTART.md` (v0.9.1) is:

| Phase | Commands | Decisions asked |
| --- | --- | --- |
| CLI | `git clone --branch v0.9.1`, `pipx install --editable`, `cardine --version` | where the runtime clone lives |
| Plugin | `claude plugin marketplace add biagiolibe/cardine#v0.9.1`, `claude plugin install cardine@cardine` | — |
| Configuration | a hand-written validation JSON, `adopt --check`, `--rehearse`, `--apply`, each with the same seven flags | name, slug, preset, language, task identity, `REUSE`/`BOUNDED`/`FULL` lists |
| Publication | `git add <each-intended-path>`, `git diff --cached`, `git commit`, `git push` | which paths to stage |
| Host | `setup --check`, `setup --apply`, `doctor` (Codex: restart first) | — |

That is about sixteen commands and six or seven decisions before the first task. The
version is pinned by hand in three places: the clone tag, the marketplace ref, and the
documentation URL, which points at `main`.

## Verified facts

These were checked against the code on `main` at `06bbe89`.

1. **A Git-tag install does not work yet.** `pyproject.toml` packages only
   `src/cardine`. A wheel built from `main` contains the `cardine` package and nothing
   else. The runtime resolves its framework root as the parent of the installed
   scripts (`cli.py`, `--framework-root` default) and reads `migrations/`, `skills/`,
   `scripts/` and `VERSION` from it. A non-editable install therefore has no framework
   root. The editable install from a clone is the only working form, and it is the
   reason the clone exists.
2. **ADR decision 9 already settles distribution.** pipx is the primary installer and
   uv the alternative. The sources are PyPI, a Git tag, or an editable clone for
   development. Templates and skills ship as package data. `cardine self-update` detects
   the installer, and `cardine doctor` checks that the plugin and the CLI match. The
   2026-11-08 amendment kept 0.9 on a clone, so the gap between decision 9 and today is
   intentional but has to close before 1.0.
3. **`adopt --apply` rehearses on its own.** `apply_rehearsed_adoption` runs the
   rehearsal when no receipt matches the current plan and source. The separate
   `--rehearse` step in the quick start is optional; the three-step ceremony is a
   documentation choice, not a CLI requirement.
4. **`setup --task-identity` cannot change an existing choice.** It records the choice
   only when the declaration has none. Changing task identity or language after `init`
   or `adopt` is not supported today.
5. **`cardine guide` exists** (task 243). It is read-only: it explains the bootstrap
   inputs and steps in prose, so the person still runs them.
6. **`docs/DISTRIBUTION_AND_UPDATE_DESIGN.md` is a Meridian-era document.** It rejects
   PyPI and makes the tagged repository tree the only artifact, which contradicts ADR
   decision 9.

## Goal

From nothing to the first task in three steps for a person, with every decision
offered with a default:

```bash
pipx install cardine          # or: pipx install git+https://github.com/biagiolibe/cardine@v<version>
cd my-project && cardine init
```

The third step is the request to the agent: «Proceed with 001». Upgrading is
`cardine self-update`, which updates the CLI and the plugin and names the checkouts that
need `cardine authorize`.

The flags, the JSON output, and the check-then-apply protocol stay as they are for
agents and CI. Agents never get a prompt.

## Proposals

Each proposal is labelled as one of:
- *implements ADR 9*;
- *needs ADR amendment*;
- *docs only*.

### P1. Ship the framework assets as package data — *implements ADR 9*

Move or include `migrations/`, `skills/`, `scripts/project_console.py`, `VERSION` and the
other assets the runtime reads into the wheel, then resolve the framework root from the
installed package. After this change:
- `pipx install git+https://github.com/biagiolibe/cardine@v0.9.x` works;
- PyPI publication for 1.0 needs nothing more from packaging;
- the editable clone remains for development only.

The runtime clone, `~/src/cardine-runtime`, disappears from the user path.

Verification is a real install from the built wheel in a disposable `HOME`, followed by
`init` and one landed task. This closes an item that the README lists as not yet proven:
installation from a released package.

### P2. Detect the test command and default the rest — *needs ADR amendment*

`init` and `adopt` accept `--test "<command>"` as the common case. With `--test`:
- Cardine builds the validation declaration itself, with `baseline` and the `BOUNDED`
  and `FULL` candidate lists set to that command;
- `--validation <json>` remains for full control.

Without `--test` or `--validation`, the preview proposes a command detected from the
project: `pyproject.toml` or `setup.cfg` give pytest or unittest, `package.json` gives
`scripts.test`, a `Makefile` gives a `test` target. The project is written only after a
confirmation. Other defaults:
- name from the directory, slug derived from it;
- preset `lean`;
- task identity `opaque`;
- language English.

Each default is shown in the preview.

### P3. One interactive entry point for people — *needs ADR amendment*

`cardine init` with no mode flag on an interactive terminal:
1. detects whether the project needs `init` or `adopt`;
2. shows the defaults of P2 and lets the person change them;
3. prints the plan;
4. asks one confirmation;
5. applies, with the rehearsal inside apply as today.

Off a TTY, or with `--check`/`--apply`, behaviour and output are unchanged. `cardine
guide` stays as the read-only explanation; this is the same flow, performed instead of
described.

### P4. Commit and publish the configuration — *needs ADR amendment*

After apply, the interactive flow shows the exact paths it wrote and the commit it will
create, then asks one confirmation. On a yes it commits only those paths and pushes
`main`. It never stages other files. A refused push leaves the commit in place and
prints the fix, as landing does today. With the flags, nothing changes: agents still
stage and publish under the project's permissions.

### P5. Install the Claude Code plugin from setup — *needs ADR amendment*

`cardine setup --apply` installs the plugin pinned to the running CLI's version, so the
CLI and the plugin can no longer diverge:
- when the plugin is absent, it runs `claude plugin marketplace add
  biagiolibe/cardine#v<version>` and `claude plugin install cardine@cardine`;
- when the plugin is at another version, it removes the marketplace and adds it again,
  because adding it again at a different ref is refused;
- when the `claude` command is not on `PATH`, it prints the two commands instead.

This is a host change that uses the network, so it stays inside `setup --apply`, which
only the developer runs, and `setup --check` shows it first. The same step can run at
the end of P3, under the same single confirmation.

### P6. One upgrade command — *implements ADR 9*

`cardine self-update --apply` detects the installer and upgrades the CLI. It then
updates the plugin as in P5, and lists the checkouts whose runtime acceptance is now
stale with the exact `cardine authorize --apply` command for each. Authorization stays a
separate step on the developer's terminal (ADR decision 14); the change is that the tool
names it at the right moment instead of a document.

### P7. Rewrite the user documents — *docs only*

`docs/QUICKSTART.md` becomes a short guide:
- install, `init`, first task;
- one path for an agent and one for the terminal;
- no role vocabulary in the main path;
- the new-project scaffolding (`PYTHONDONTWRITEBYTECODE`, the `__pycache__` ignore)
  moves to an appendix or goes away.

The other documents follow:
- The README keeps one install block and moves `Install` before `Status and evidence`.
  Its empty `First 5 minutes` section is removed.
- `docs/HOW_TO_UPGRADE.md` describes P6 and agrees with the README: today its clone has
  no tag and a different path.
- `docs/DISTRIBUTION_AND_UPDATE_DESIGN.md` gets a superseded notice that points to ADR
  decision 9, or moves to the maintainer archive.

Until P1 to P6 land, a first version of P7 can already drop the optional `--rehearse`
step and the repeated flags.

### P8. Allow changing early choices later — *needs ADR amendment*

A way to change task identity and language after configuration, so a new user is not
asked about them up front. This needs a design of its own: task identity is frozen into
every existing task contract.

## Task cut

| Order | Task | Proposals | Depends on |
| --- | --- | --- | --- |
| 1 | Package data and an installed-package framework root; verify an install from a built wheel | P1 | — |
| 2 | Install and upgrade documents for the Git-tag install; superseded notice | P7 (part), P1 docs | 1 |
| 3 | `--test` and a detected test command, with defaults shown in the preview | P2 | ADR amendment |
| 4 | Interactive `init` with one confirmation, and optional publication of the configuration | P3, P4 | 3 |
| 5 | Plugin installed by `setup`; `self-update` that updates the plugin and names stale checkouts | P5, P6 | 1 |
| 6 | Short quick start and README | P7 | 2, 4, 5 |

Tasks 1 and 2 can ship as 0.9.2 without any ADR change. Tasks 3 to 5 change the public
surface (`docs/PUBLIC_SURFACE.md`) and need the ADR amendments named above.

## Open decisions for the developer

1. **Scope for 1.0.** Do P2 to P5 ship in 1.0, or only P1, P6 and P7, with the rest in
   1.1? ADR decision 10 gates 1.0 on lifecycle cases, not on onboarding, but 1.0 is the
   first public release, and its onboarding is what new users meet.
2. **Publication by `init` (P4).** Is one confirmation enough for Cardine to commit and
   push the configuration, or does publication stay with the person or the agent?
3. **Plugin installation by `setup` (P5).** May `setup --apply` call `claude plugin`,
   or does it only print the commands?
4. **Test-command detection (P2).** Which ecosystems are detected in the first version?
   Python and Node are proposed. Should detection be dropped in favour of `--test` only?
5. **P8.** Plan it now, or keep the up-front questions with better defaults?

## Out of scope

- The lifecycle (`cardine run`) and its stops.
- Codex plugin distribution, which is still unverified.
- PyPI publication itself, which belongs to the release script (ADR decision 10, item 12).
