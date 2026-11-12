# ADR: Spec Kit interoperability

Status: Accepted

*Spike 295. Researched on 2026-11-12 against Spec Kit `v1.4.0` (published 2026-11-10).*

## Context

`docs/ADR_PRODUCT_DIRECTION.md`, decisions 1 and 3, position Cardine as the delivery
layer that works with the developer's spec tool. This ADR decides how a Spec Kit task
becomes a Cardine task record, and how Cardine ships as a Spec Kit extension.

Every external fact carries one of two marks:
- **documented**: read in Spec Kit's public repository, with its URL;
- **to verify**: inferred or not yet read; a work item confirms it before relying on it.

URLs are under `https://github.com/github/spec-kit` (blob/tree `main`) unless stated.

### Spec Kit facts

| # | Fact | Mark | Source |
|---|------|------|--------|
| 1 | Latest release at research time is `v1.4.0`. | documented | `https://api.github.com/repos/github/spec-kit/releases/latest` |
| 2 | Per feature, files live in `FEATURE_DIR`, for example `specs/[###-feature-name]/`. `tasks.md` reads `spec.md` and `plan.md` (required) plus optional `research.md`, `data-model.md`, `contracts/`, `quickstart.md`. | documented | `templates/tasks-template.md`, `templates/commands/tasks.md` |
| 3 | The constitution is `memory/constitution.md`. | documented | `templates/commands/tasks.md` |
| 4 | A task line is `- [ ] [TaskID] [P?] [Story?] Description with file path`. | documented | `templates/commands/tasks.md`, "Checklist Format" |
| 5 | `TaskID` is `T` plus a sequential number in execution order (`T001`). `[P]` marks a task that can run in parallel. `[US1]`, `[US2]` label tasks of a user-story phase only. | documented | same |
| 6 | Phases: 1 Setup, 2 Foundational (blocks all stories), 3+ one per user story in priority order, last Polish. Each story phase has `**Goal**` and `**Independent Test**` lines. | documented | `templates/tasks-template.md` |
| 7 | Dependencies between tasks are prose, for example `(depends on T012, T013)`, plus a dependencies section of story order. There is no machine field. | documented | `templates/tasks-template.md`; the "section" part is to verify |
| 8 | File paths appear inside the description. The template shows one path per task. A task without a path is considered wrong by the generator. | documented | `templates/commands/tasks.md` ("WRONG" examples) |
| 9 | The checkbox is flipped by the implement step. | to verify | not read: `templates/commands/implement.md` |
| 10 | `converge` reads `spec.md`, `plan.md` and `tasks.md`, and appends a `## Phase N: Convergence` section to `tasks.md`; when converged it leaves `tasks.md` byte-for-byte unchanged. | documented | `templates/commands/converge.md` |
| 11 | Hooks live in `.specify/extensions.yml` under keys such as `hooks.before_tasks`, `hooks.after_tasks`, `hooks.before_converge`, `hooks.after_converge`; each hook is `optional: true` (offered) or `false` (mandatory, run automatically). | documented | `templates/commands/tasks.md`, `templates/commands/converge.md` |
| 12 | The `tasks` command template carries YAML front matter (`description`, `handoffs`, `scripts`). | documented | `templates/commands/tasks.md` |

Fact 7 is the weakest point: the dependency syntax is prose that an agent writes, so the
import cannot rely on it.

### Extension facts

| # | Fact | Mark | Source |
|---|------|------|--------|
| 13 | An extension is a directory with `extension.yml` (required), `README.md`, `LICENSE`, optional `CHANGELOG.md`, `commands/*.md`, config templates. | documented | `docs/extensions/publishing.md` |
| 14 | Manifest: `schema_version: "1.0"`; `extension` (`id`, `name`, `version`, `description`, `author`, `repository`, `license`, `homepage`, optional `category`, `effect` of `read-only` or `read-write`); `requires.speckit_version` and `requires.tools`; `provides.commands` (`name`, `file`, `description`, `aliases`); `provides.config`; `hooks`; `tags`; `defaults`. | documented | `extensions/template/extension.yml` |
| 15 | Command names follow `speckit.{extension-id}.{command-name}`. The id matches `^[a-z][a-z0-9-]*$`; the description stays under 200 characters; the version is semantic. | documented | `extensions/template/extension.yml`, `docs/extensions/publishing.md` |
| 16 | A hook entry is `command`, `optional`, `prompt`, `description`, `condition`; several commands on one event use a list with `priority`. | documented | `extensions/template/extension.yml` |
| 17 | Install: `specify extension add <name>` from a catalog, or `specify extension add <name> --from <zip URL>` directly. `specify extension search` and `list` exist. | documented | `extensions/README.md` |
| 18 | Two catalogs: `extensions/catalog.json` (upstream default, empty by design) and `extensions/catalog.community.json` (community entries). `SPECKIT_CATALOG_URL` overrides the default. | documented | `extensions/README.md` |
| 19 | A community catalog entry has `name`, `id`, `description`, `author`, `version`, `download_url` (a tag zip), `sha256`, `repository`, `homepage`, `documentation`, `changelog`, `license`, `category`, `effect`, `requires`, `provides`. | documented | `extensions/catalog.community.json` |
| 20 | Listing in the community catalog: public GitHub repository, GitHub release with a semantic tag, tested on a real project, then an issue from the extension-submission template; a maintainer edits the catalog. Maintainers check form, not code. | documented | `extensions/README.md`; template at `https://github.com/github/spec-kit/issues/new?template=extension_submission.yml` |

## Decision

### 1. One Cardine task is a group of Spec Kit tasks

A Spec Kit line such as `T012 [P] [US1] Create User model in src/models/user.py` is one
file and minutes of work. A Cardine task is about one session and at most about ten
files, with its own review and landing. Importing one record per line would put a
review and a landing around a single file.

The unit is the **phase** of `tasks.md`: Setup, Foundational, each user story, Polish.
A phase that names more than ten distinct paths is split (see the mapping). No other
grouping is configurable in the first version.

### 2. Mapping, field by field

| Record field | Source in `tasks.md` | Rule |
|--------------|----------------------|------|
| ID | none | The next free Cardine id, assigned at import. |
| Title | phase heading | `Phase 3: User Story 1 - Title` becomes `User Story 1 - Title`. |
| Category, Priority | story priority `(Priority: P1)` | `Feature`; `P1` becomes `P1` and so on; absent becomes `Feature` and `P2`. |
| Origin | the import | `Origin: spec-kit` (see "Identity"). |
| Objective | the phase `**Goal**` line, else `**Purpose**` | Verbatim, shortened to the import's limit; a phase with neither is refused. |
| Acceptance criteria | `**Independent Test**` plus each task line | First criterion is the independent test. Then one `[ ]` per task, `<description> (T012)`. `[P]` and `[Story]` markers are dropped. |
| Expected code surface | paths named in the group's task lines | Every token that looks like a repository path; a directory path becomes `dir/**`. Paths that no line names are not invented. |
| Dependencies | phase order and `(depends on T...)` | Foundational blocks every story group; Setup blocks Foundational; a story group has no implied dependency on another story (fact 6). `depends on Tnnn` maps to the group holding `Tnnn`, once that group is imported. |
| Validation | not in `tasks.md` | Asked (see below). |
| Authority | `spec.md`, `plan.md` in `FEATURE_DIR` | Listed as `## Authority` when the project requires authority; always listed in Relevant Files. |
| Relevant Files | `spec.md`, `plan.md` | Read only. |

**What the import must ask.**
- The validation commands. Spec Kit tasks name no commands (fact 8 covers paths only).
  The import proposes the project's baseline commands (`cardine` already reads these
  from the project declaration), and `--validation ID=COMMAND` (repeatable) overrides
  them. Without either, the import refuses with the exact flag to add. A task never
  enters the queue with an empty Validation.
- The surface, when a group names no path (for example a Polish task "update docs").
  The import refuses that group and lists its lines; the developer adds paths in
  `tasks.md` or passes `--surface GROUP=PATH` (repeatable).
- Review and options: inherited from the project default; a flag per import
  (`--review required`) applies to all groups of one run.

**Size.**
- A group naming at most ten distinct paths becomes one record.
- A larger group is split at task boundaries into consecutive records of at most ten
  paths, in task order, each depending on the previous one unless every line of the
  later part is `[P]`. Titles get ` (part 2 of 3)`.
- A single task line that names more than ten paths cannot be split by lines. The
  import refuses it and says to split it in `tasks.md`. It never truncates a surface.
- A group of one task is imported as is; the import does not merge groups.

### 3. The command

```text
cardine task import <tasks.md> [--feature-dir DIR] [--check] [--only GROUP ...]
                    [--validation ID=COMMAND ...] [--surface GROUP=PATH ...]
                    [--review required|not_required] [--update] [--project .]
```

- `<tasks.md>`: the file to read. `--feature-dir` defaults to its directory; it locates
  `spec.md` and `plan.md`.
- **`--check`**: preview only. Prints, for each group, the title, the criteria count,
  the surface, the dependencies, and every refusal with its fix. Creates nothing and
  exits non-zero when anything would be refused. The same code builds the preview and
  the records, so the preview cannot differ from the result.
- **Creation** goes through the existing task registration (`cardine task new`), never
  by writing state files, so every gate that applies to a hand-written task applies
  here.
- **Identity.** Each record stores `Origin: spec-kit` and a line
  `Source: <path relative to project>#<group key>@<digest>`. The group key is the
  phase number plus a slug of its heading; the digest is a hash of the group's lines
  after trimming and dropping checkbox state. Matching is by key, not by position.
- **Rerun.**
  - Same key and digest: nothing happens; the line says `unchanged`.
  - A group not imported yet: imported.
  - Same key, new digest, record `queued`: reported as `changed`, with a diff of the
    criteria and surface. Applied only with `--update`, which rewrites the record and
    runs `cardine task contract update`.
  - Same key, new digest, record started or later: never touched. Reported as `drift`
    with the command that opens a new task for the delta. Reopening is a new task
    (`PROJECT_WORKFLOW.md`).
  - A key that disappeared: reported as `removed`; nothing is cancelled.
  - Changing a checkbox does not change the digest, so ticking boxes never reports
    drift.
- Cardine never edits `tasks.md`, except the optional checkbox write-back of the
  extension (decision 4).

### 4. The extension

A Spec Kit extension `cardine` (id `cardine`, category `integration`, effect
`read-write`), released from its own repository `spec-kit-cardine` with tag zips, as
facts 13 to 20 require. It adds no new engine behavior: it calls the CLI.

Commands (fact 15 naming):
- `speckit.cardine.import`: runs `cardine task import` on the current feature's
  `tasks.md`, first with `--check`, shows the preview, then imports after the developer
  agrees. Asks for validation commands the import refused for.
- `speckit.cardine.deliver`: for a task id the developer names, says
  `Proceed with <ID>` semantics, that is runs `cardine run <ID>` and follows its JSON.
  It never picks the next task by itself.
- `speckit.cardine.status`: prints `cardine status` for the imported tasks, by
  `Source` key.

Hooks (fact 11 and 16): `after_tasks` runs `speckit.cardine.import` with
`optional: true`. No mandatory hook: delivery stays an explicit developer act.

**What `converge` can read.** `converge` takes `spec.md`, `plan.md` and `tasks.md` as
its sole inputs (fact 10) and infers state from the code. Cardine can add evidence it
cannot infer: which groups landed, with what validation result. The safe form is a
generated, read-only file `FEATURE_DIR/cardine-state.md`, written by
`speckit.cardine.status` with, per group key: Cardine task id, state, landed commit,
and validation verdict. Whether `converge` reads a file that is not one of its three
inputs is **to verify** (work item 5); if not, the extension offers the file as an
optional `before_converge` hook prompt that asks the agent to read it. Write-back of
checkboxes (`- [x] T012`) for landed groups is optional, default off, and only flips
the checkbox of lines in landed groups, because `converge` leaves a converged
`tasks.md` byte-for-byte unchanged and any other edit would break that (fact 10).

### 5. Versioning and tolerance

- The parser accepts the line shape `- [ ] T<digits> [P] [US<digits>] text` with every
  marker optional, any checkbox state, and ignores lines it does not recognize inside a
  phase. It never fails on an unknown line; it reports `skipped: N lines` in the
  preview.
- Phases are recognized by `## ` headings with `Phase` or by a `User Story` heading;
  when no phase is found the whole file is one group and the preview says so.
- A fixture per supported Spec Kit minor lives in the tests. Supported at first:
  `1.4.x` (fact 1), recorded in the extension's `requires.speckit_version` as `>=1.4.0`.
  Earlier versions are **to verify** per work item 2; they are not claimed.
- The import records the Spec Kit version it was written against in its own output, not
  in the record. A format it cannot parse produces a refusal naming the first line it
  failed on, never a partial import.
- Because `tasks.md` is agent-written prose (fact 7), dependencies other than the phase
  order are best effort and always shown in the preview for confirmation.

## Amendment (2026-11-12)

The developer accepted this ADR with two changes.

1. **Validation.** The import never proposes the project's baseline commands as a
   record's Validation: the baseline already runs on every task, so repeating it adds
   time and no evidence. The import asks for a targeted command with
   `--validation ID=COMMAND`. Without one, it uses a default command that the project
   declares for imported tasks, if it declares one. Otherwise it refuses with the flag
   to add. The declaration key is decided by work item 2.
2. **Order.** Work items 1 to 3 (parser, mapping and preview, command) come first and
   are useful alone. Work items 4 to 6 (the extension package, the `converge` spike, and
   `cardine-state.md` with checkbox write-back) wait until the import has been used on
   a real project.

None of the work items is scheduled yet. They are planned when the developer decides.

## Consequences

- A developer specifies with Spec Kit and delivers with Cardine without retyping tasks.
  The grouping decision means a Cardine record is coarser than a Spec Kit line; the
  criteria keep the lines, so nothing is lost.
- Cardine depends on a format that Spec Kit does not specify formally. The tolerant
  parser, per-minor fixtures and the digest-based rerun contain that risk; a change
  upstream fails the preview, not a landing.
- The import adds no gate and relaxes none: records enter through `cardine task new`
  and carry the same options and validation requirements.
- Distribution through the community catalog is a pull request-free path for Cardine
  (an issue and a release), but maintainers do not review the code (fact 20), so the
  extension's trust rests on Cardine's own release process.
- Asking for validation commands adds a step at first import. Project baseline commands
  make it zero after that.
- Open verification items: facts 7 (dependencies section), 9 (checkbox flip), and the
  `converge` read of an extra file.

## Work items

Each is about ten files or fewer and is planned when its predecessors land.

1. **Task: `tasks.md` parser.** A module that reads a `tasks.md` into groups (key,
   heading, goal, independent test, task lines, paths, `[P]`, dependency mentions) with
   the tolerance rules of decision 5. Fixtures for `1.4.x`, including a `converge`
   appended phase and a file with no phases. Tests. (Closes facts 7 and 9 by reading
   `templates/commands/implement.md` and a generated sample.)
2. **Task: mapping and `--check`.** The record builder (fields, size split, refusals)
   and the preview, with no write. Tests for the ten-path split and the single-line
   refusal. Verifies support of Spec Kit versions earlier than `1.4.0`.
3. **Task: `cardine task import`.** Creation through `cardine task new`, the `Source`
   line, digest, rerun states (`unchanged`, `changed`, `drift`, `removed`), `--update`.
   Public-surface entry and documentation page.
4. **Task: extension package.** Directory `extensions/spec-kit/` (or its own repository)
   with `extension.yml`, three commands, the `after_tasks` hook, README, LICENSE,
   CHANGELOG. A static check that the manifest satisfies facts 14 and 15.
5. **Spike: `converge` and Cardine state.** Install Spec Kit in a throwaway project,
   run `converge` with `cardine-state.md` present, and record whether it reads a file
   beyond its three inputs; decide hook prompt versus no file. Needs the developer's
   machine and no write to GitHub.
6. **Task: `cardine-state.md` and checkbox write-back.** Generator for decision 4,
   write-back off by default, tests that a converged `tasks.md` stays byte-identical.
7. **Developer: publish.** Create the extension repository and release, test on a real
   project, open the extension-submission issue (fact 20). Cardine never opens it for
   the developer.
