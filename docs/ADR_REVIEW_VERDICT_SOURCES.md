# ADR: Sources of a review verdict

Status: Accepted

## Context

A consumer on the governed preset found that the only way to record a verdict
is the developer's terminal, and nothing in the templates says so.

Facts at v0.9.2, read from the code:

- `cardine review verdict` without `--owner` requires `--request-id`: the
  identity of a reviewer session that Cardine launched and recorded under
  `run.hostLaunches` (`src/cardine/review/verdict.py`).
- No host adapter launches sessions. `src/cardine/hosts/launch.py` states "No
  adapter is installed by default", and `cardine doctor` reports
  `role-launch-reviewer: unsupported (D3)` on both hosts
  (`docs/HOST_CAPABILITY_CONTRACT.md`, row D3).
- So every governed verdict is an owner verdict. `cardine run` already prints
  `cardine review verdict <ID> APPROVE --owner …`.
- `templates/single/PROJECT_WORKFLOW.md` (block `review-policy v2`) and
  `templates/single/docs/workflows/REVIEW.md` (block
  `task-worktree-review-procedure v4`) still describe a reviewer session that
  records its own verdict with `--request-id`. That text cannot be followed.
- The review projection already records `approved_by` (`owner` or `reviewer`)
  and `source='local'`.
- The project declaration accepts `landingMode: "direct"` only, and knows a CI
  provider (`github`) whose required checks the engine polls before landing
  (`docs/PROJECT_DECLARATION.md`).
- `docs/ADR_CARDINE_1_0.md` decision 14, rule 2, says the engine launches the
  implementer and the reviewer with distinct host profiles. Its 2026-11-03
  "Developer channel" amendment makes the developer record verdicts while hosts
  cannot prove their role profiles.

Developer decisions of 2026-11-11, taken as given:

- Review must be possible beyond the owner, and the direction leads toward pull
  requests and teams with manual review.
- Rejected: an unverified reviewer verdict that any session may record (it
  removes "nobody approves their own work"), and refusing a verdict from the
  implementer's host session id (a local heuristic that does not reach a
  teammate on a forge).
- The model is: a verdict comes from a source that proves the approver's
  identity.

### External facts

Each fact is marked **documented** (with its URL) or **probe** (to verify by
a read-only probe before the work item that relies on it ships). This spike
fetched no page and made no host or GitHub call; "documented" means the cited
page states it, and each work item that depends on one re-reads the page when
it starts. Nothing here was run against a paid agent.

| # | Fact | Mark |
|---|------|------|
| G1 | A pull request review has `id`, `user.login`, `state` (`APPROVED`, `CHANGES_REQUESTED`, `COMMENTED`, `DISMISSED`, `PENDING`) and `commit_id`, the commit the review was made on. https://docs.github.com/en/rest/pulls/reviews | documented, re-read 2026-11-12: fields yes, state values and `commit_id` meaning not stated; see docs/FORGE_PROBE.md |
| G2 | The author of a pull request cannot approve it. https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/reviewing-changes-in-pull-requests/about-pull-request-reviews | verified by probe, see docs/FORGE_PROBE.md |
| G3 | A dismissed review keeps its record with state `DISMISSED`; a repository can dismiss approvals automatically when new commits are pushed. https://docs.github.com/en/rest/pulls/reviews and https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches | documented, re-read 2026-11-12: automatic dismissal yes, `DISMISSED` record not stated; see docs/FORGE_PROBE.md |
| G4 | A pull request can exist for a branch that is later landed outside GitHub (a direct merge and push of `main`); GitHub marks it merged or closed from the pushed history. | verified by probe, see docs/FORGE_PROBE.md |
| G5 | A review by the account of the token that opened the pull request, when the repository is private and has one collaborator, is refused. The author rule holds for a token-owned account the same way as for a person. | verified by probe, see docs/FORGE_PROBE.md |
| G6 | `gh api` with the developer's existing login can read reviews without a write scope. | verified by probe, see docs/FORGE_PROBE.md |
| C1 | Claude Code runs non-interactively with `claude -p`, restricts tools with `--allowedTools` / `--disallowedTools`, and returns structured output with `--output-format json`. https://code.claude.com/docs/en/cli-reference | documented |
| C2 | Claude Code `permissions.deny` rules are honored in headless mode and can deny `Bash(cardine review verdict:*)` and edit tools. https://code.claude.com/docs/en/permissions | documented |
| C3 | A headless child cannot widen its own permissions; a deny rule from a settings file passed with `--settings` wins over an allow. | probe |
| X1 | Codex runs non-interactively with `codex exec`, with `--sandbox read-only` and a JSON event stream. https://developers.openai.com/codex/cli/reference | documented |
| X2 | A read-only Codex sandbox also blocks a `cardine review verdict` call that writes under the task worktree or `.cardine`. | probe |

## Decision

Cardine accepts a verdict from three sources. Every verdict records which
source produced it. They are built in this order: **owner** (exists, text
corrected first), **forge**, then **launched reviewer**. The coordinator's
recommendation is confirmed, for three reasons:

1. The forge source proves identity with a system Cardine does not control and
   the agent cannot edit, so it needs no host enforcement (D3) at all. The
   launched reviewer needs both hosts to prove their role profiles, which
   `cardine doctor` cannot show today.
2. It is the only source that reaches a teammate, which is the stated
   direction.
3. It needs only a read-only client. It adds no process launching, no
   permission rules, and no paid call.

### 1. The sources

| | owner | forge | launched reviewer |
|---|---|---|---|
| Proof of identity | the developer at an interactive terminal who confirms the task and commit (decision 14 amendment of 2026-11-03) | a GitHub account, authenticated by GitHub, other than the pull request author (G2) | a host session that Cardine started with an enforced reviewer profile and recorded under `run.hostLaunches` |
| `approved_by` | `owner` | `forge` | `reviewer` |
| `source` | `local` | `github` | `launched` |
| Reviewed commit | `HEAD` of the task branch when recorded | the review's `commit_id` (G1), which must equal the task branch `HEAD` | the `source` bound in the launch request, which must equal `HEAD` |
| Also recorded | none | pull request number, review id, approver login, review state | request id, host, profile identity, session id |
| Declared limit | presence, not authenticity; same-user limit of decision 14 | Cardine trusts GitHub's account identity and the token it reads with; it does not detect one person controlling two accounts, or an agent holding a second account's token. Cardine never presents a forge verdict as proof of a person, only of an account | the same-user limit of decision 14: a receipt is written as the developer's user, and an agent that bypasses host permissions can forge the launch record. D3 must show enforcement first |

The review projection adds `source` values `github` and `launched` next to
today's `local`, and a `forge` object (number, review id, login) present only
for the forge source. Existing projections stay valid.

### 2. Which sources satisfy `review: required`

Every source that is supported satisfies `review: required`. A project may
restrict them with one key in `.cardine/project.json`:
`review.sources`, a nonempty list drawn from `owner`, `forge`, `launched`.
The default is `["owner"]` for projects that exist when the key ships, so no
project changes behavior silently, and `["owner", "forge", "launched"]` for
new projects once all three exist. `["forge"]` forbids owner verdicts: a team
that wants every approval on the forge says so, and `cardine review verdict
--owner` then refuses with a stop that names the key. Cancel and abort stay
owner commands. The schema change is a work item, not part of this ADR.

### 3. The forge source

**Landing.** Reading an approval does not need `landingMode: "pull-request"`.
Landing stays `direct`: the engine merges and pushes `main` as today. The
engine only needs the task branch to exist on the remote and a pull request
whose head is that branch. `cardine run` pushes the task branch and opens the
pull request when the project selects the forge source and the task reaches
`in_review`; both are writes the project's CI settings already permit for the
branch, and neither is a force push. A pull request that is not merged by
GitHub is closed by the engine after direct landing, with a comment naming the
landed commit (G4 to be probed). A true pull-request landing mode is a later,
separate decision and is not required by this ADR.

**Reading the verdict.** Cardine reads the reviews of the task's pull request
(read-only, G1, G6) and applies these rules, in this order:

1. Ignore reviews in state `COMMENTED` or `PENDING`. They carry findings for
   people and never a verdict.
2. Ignore reviews whose `commit_id` is not the task branch `HEAD`. A head that
   moved after approval makes the approval stale: the result is the existing
   `REVIEW_NOT_APPROVED` with cause `stale`, and the task waits for a new
   review of the new head.
3. For each reviewer take the latest remaining review. A `DISMISSED` review is
   treated as absent, so a dismissed approval no longer approves and a
   dismissed request for changes no longer blocks (G3).
4. Ignore a review whose author login equals the pull request author login or
   the login of the account that pushed the branch.
5. If any reviewer's latest review is `CHANGES_REQUESTED`, the verdict is
   `CHANGES_REQUESTED`, with that review's body as the review body.
   Otherwise, if at least one is `APPROVED`, the verdict is `APPROVE`.
   Otherwise there is no verdict yet and `cardine run` returns `waiting`.

Cardine records the verdict itself through the same single write path as the
owner verdict, so the receipt, budget and history rules do not change. The
command is `cardine review verdict <ID> --from-forge`; `cardine run` calls it
while waiting.

### 4. The launched reviewer

A launch adapter is required before this source works. Each host must enforce,
and `cardine doctor` must prove, all of:

- **No edits.** The child's tool policy denies file writes and `git`
  mutations. Claude Code: deny rules for edit tools and `Bash(git:*)`
  mutations (C2). Codex: read-only sandbox (X1, X2).
- **No verdict by the child.** The child's policy denies
  `cardine review verdict` and `cardine run`. Cardine collects the child's
  output itself and records the verdict in the parent process, so the child
  never holds the ability to write one (X2, C3).
- **Distinct profile.** The reviewer profile differs from the implementer's and
  is enforced (D3).
- **Fresh process.** The reviewer is a new process with no resumed session of
  the implementer.

**Start and collect.** Cardine starts the child with the host's non-interactive
mode: `claude -p … --output-format json --settings <deny file>` (C1) or
`codex exec --sandbox read-only --json` (X1). The prompt names the task, the
reviewed commit and the output form: a verdict and findings. Cardine reads the
final message, validates its form, and records the verdict with source
`launched`. The launch request is idempotent by request id, as
`HostTransport.spawn` already requires.

**Doctor proof.** `role-launch-reviewer` is `ready` only when doctor shows, by
a read-only probe that makes no model call, that the effective policy denies
the edit tools and the two Cardine commands above for the reviewer profile.
Otherwise it keeps reporting `unsupported (D3)` with the gaps.

**Flags.** C1, C2, X1 are documented; C3 and X2 are to verify by probe before
the adapter work item starts. A probe that cannot be run without a model call
stays `unverified`, and the host stays unsupported.

### 5. Mixed review

An agent reviewer may post its findings in the pull request as a `COMMENTED`
review or as comments. They are explanation for people, ignored by rule 1 of
the forge reading, and not a verdict. A person approves with an `APPROVED`
review; that is the verdict. If a project allows `launched` and `forge`, a
verdict from either source is valid; if a project restricts the sources, only
the allowed ones count.

Two consecutive `CHANGES_REQUESTED` rounds end in `REVIEW_LOOP_EXHAUSTED`
whatever the source: the rule reads the `review_history` of the task state
(`src/cardine/lifecycle/control.py`), and every source appends to it. A mix
(one round from the forge, one launched) counts the same.

### 6. Ordering

See Work items.

## Consequences

- A team can review on GitHub, and the record shows who approved and which
  commit, without any host enforcement.
- Cardine keeps the single write path for verdicts, so receipts and the loop
  budget are unaffected.
- The forge source adds one remote dependency and a network read during
  review; a missing token or a private repository without access returns a
  recoverable `waiting`, not a false verdict.
- The forge source is only as strong as GitHub accounts; the declared limit
  above says so, and the docs must not say "reviewed by a person".
- The launched reviewer stays unavailable until the hosts can prove their role
  profiles. Decision 14 rule 2 remains the target for that source and is
  amended, not changed, by a note pointing here.
- Until the template correction ships, the managed review text keeps pointing
  at an unusable command. That is the first work item for that reason.
- Not decided here: the PR landing mode, the schema change, any stop code, any
  template text.

## Work items

Each is small enough for a task of about ten files. Items 1 to 3 may ship
alone; item 1 needs nothing else.

1. **Template correction.** Rewrite `review-policy` and
   `task-worktree-review-procedure` in `templates/single/` to describe the
   owner procedure that exists (`cardine run` prints the command, the
   developer records it), and the sources as advice. Update the capability
   marker versions and baselines.
2. **Declaration key and projection fields.** Add `review.sources` to the
   project schema and `docs/PROJECT_DECLARATION.md`, refuse an owner verdict
   when the key excludes it, and extend the review projection with the `github`
   and `launched` source values and the optional `forge` object.
3. **Forge probe.** A read-only probe of G4, G5, G6 against a scratch
   repository, recorded in `docs/`, and a small read-only GitHub client in
   `src/cardine/` with fixtures for the reading rules.
4. **Forge verdict.** `cardine review verdict --from-forge`, applying the
   reading rules of the Decision, with tests for stale head, dismissal,
   author exclusion and mixed `COMMENTED` findings.
5. **Run integration.** `cardine run` pushes the task branch, opens the pull
   request, returns `waiting` until a verdict exists, and closes the pull
   request after direct landing. Doctor reports the forge source status.
6. **Launch adapter, first host.** Claude Code: deny-rule settings file, probe of C3,
   doctor proof of `role-launch-reviewer`, `HostTransport` implementation.
7. **Launch adapter, second host.** Codex, after probe X2.
8. **Optional: pull-request landing mode.** A separate ADR first; this ADR
   does not require it.

## Amendment (2026-11-12): launched reviewer first, without write capability

Developer decision of 2026-11-12. Two facts changed the order of work:

- The forge probe (`docs/FORGE_PROBE.md`) confirmed G5. The account that opens
  a pull request cannot approve it. `cardine run` opens it with the developer's
  own token, so a solo developer needs a second person for every forge
  verdict. A bot account whose token sits on the same machine as the
  implementer agent proves nothing beyond the same-user limit.
- The role policies of `src/cardine/hosts/permissions.py` are deny-lists over
  a session that may write. No host can prove them complete: Claude has no
  decision probe without a model call, and Codex cannot observe native writes.
  So `role-launch-reviewer` can never become `ready` under section 4 as
  written.

The launched reviewer therefore changes as follows, and is built before the
forge source.

1. **No write capability, instead of denied commands.** The reviewer process
   has no way to write:
   - Codex runs `codex exec --sandbox read-only --ephemeral`, so the operating
     system sandbox refuses every write;
   - Claude Code runs `claude -p --tools "Read,Grep,Glob"`, so no tool that
     writes or runs commands exists in the session.

   Cardine passes the task diff and the measured evidence in the prompt. The
   tests have already run on CI before review (task 278).
2. **Cardine records the verdict from the child's output.** The child returns
   a structured final answer, `{verdict, findings}`, through `--output-schema`
   (Codex) or `--json-schema` (Claude). Cardine reads it in the parent process
   and records the verdict through the single write path, with
   `approved_by: reviewer` and `source: launched`. No credential to write a
   verdict is ever issued to a child. `cardine review verdict --request-id` is
   removed, so no session can claim a launched verdict.
3. **Only the reviewer profile must be enforced.** The implementer is the
   developer's ordinary agent session. It cannot produce a launched verdict,
   by point 2. The declared limit of decision 14 still applies: an agent of the
   same user can forge files on disk, and receipts detect changes but are not
   signatures.
4. **Doctor proof.**
   - Codex: `codex sandbox` runs a real write attempt under the reviewer's
     sandbox, without a model call, and the attempt must fail.
   - Claude Code: the restriction is structural, because Cardine passes the
     flags itself. Doctor checks that the installed CLI supports them. A
     one-time probe with a model call, run by the developer, confirms that
     `--tools` removes the write tools in headless mode.

Work items 6 and 7 are replaced by, in order:
- the launched verdict core;
- the Codex reviewer adapter;
- the Claude Code reviewer adapter;
- `cardine run` integration.

Work items 3 to 5 (forge) follow them.
