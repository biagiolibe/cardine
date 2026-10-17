# Task 113 — Add the validation evidence record and a read-only verifier

> **ID**: `113`
> **Category**: Feature
> **Priority**: 🟡 P2
> **Estimate**: ~2h
> **Assigned to**: unassigned
> **Session**: Task 101 validation could not finish in the agent host

## Objective

When a required validation cannot finish in the agent host, Meridian has no
verifiable form of evidence for a run made elsewhere and no names for the states
in between. Add one JSON evidence record, a schema for it, and a read-only
command that checks a record against the repository, so that a validation run
outside the agent host can be accepted without trusting a sentence. The command
never runs a test or any project command.

## Acceptance Criteria

- [ ] `schemas/validation-evidence-v1.schema.json` defines the record. Common
  fields: `version`, `task_id`, `status`, `level`, `commit`, `tree`, `command`
  (an array of strings), `exit_code`, `tests_run`, and `produced_at`.
- [ ] `status` is one of `running`, `unavailable`, `failed`, or `passed`.
  A `running` record carries `started_at` and a `log` path. An `unavailable`
  record carries a `reason` (for example `host_timeout`). The other two carry
  `exit_code`.
- [ ] `level` is one of `T1_CI`, `T2_SHARDED`, or `T3_ATTESTED`, with these
  level-specific fields: `T1_CI` has `ci` (`run_id`, `run_url`, `workflow`,
  `conclusion`, `head_sha`); `T2_SHARDED` has `shards` (each with `index`,
  `count`, `exit_code`, `tests_run`) plus `total` and `digest`; `T3_ATTESTED`
  has `attested_by` (always `developer`), `attested_on` (ISO date), and a non-empty
  `statement`.
- [ ] `meridian validation check <record.json> --project <primary> [--commit
  <sha>] --format json` is read-only and reports one of `VALIDATION_RUNNING`,
  `VALIDATION_UNAVAILABLE`, `VALIDATION_FAILED`, or `VALIDATION_PASSED` with the
  level and a list of reasons. It uses distinct exit codes for passed, running or
  unavailable, and failed or invalid.
- [ ] `VALIDATION_PASSED` requires all of: the record validates against the
  schema; `commit` exists and equals the given commit (default: the task branch
  tip); `tree` equals that commit's tree as Git reports it; `exit_code` is 0;
  `tests_run` is above 0; and the level-specific proof holds. For `T1_CI`:
  `conclusion` is `success` and `head_sha` equals `commit`. For `T2_SHARDED`:
  indexes `1..count` are all present once, every shard exited 0, the shard
  `tests_run` values sum to `total`, and every shard carries the same `digest`
  and `total`. For `T3_ATTESTED`: `attested_by`, `attested_on`, and `statement`
  are present; the result reports the level as `T3_ATTESTED` so a handoff can
  label it.
- [ ] A record for a different commit, a mismatching tree, a missing or
  duplicate shard, a differing digest, a zero test count, a non-zero exit, an
  unknown level or status, or an attestation without a date is not
  `VALIDATION_PASSED`, and the reason names the failing field.
- [ ] The command runs no test, shell, hook, or project command, makes no
  network call, and writes nothing. Git is used only for read-only plumbing. A
  test with a recording double for subprocess calls asserts this.
- [ ] The command follows the existing `meridian execution` and `meridian
  worktree` conventions for argument names, JSON output, and error handling, and
  is listed in `meridian --help`.
- [ ] The README or `docs/WORKTREE_LIFECYCLE.md` documents the record, the three
  levels, the four states, and what each level does and does not prove. It states
  that the record is an attestation bound to a commit and a tree, not an
  unforgeable proof.
- [ ] `CHANGELOG.md` records the command under `[Unreleased]`.
- [ ] `python3 scripts/check_repository.py` and the unit tests pass.

## Relevant Files

| File | Role |
|------|------|
| `schemas/validation-evidence-v1.schema.json` | New schema. |
| `scripts/meridian.py` | New `validation` command and verifier. |
| `tests/test_meridian_cli.py` | New verifier tests, or a new `tests/test_validation_evidence.py`. |
| `docs/WORKTREE_LIFECYCLE.md` | Evidence documentation. |
| `CHANGELOG.md` | `[Unreleased]` entry. |

## Technical Context

- `integrate stage` already takes a stage evidence JSON, and candidate
  validation evidence is a separate JSON bound to `candidate_tree`. This record
  is for the task validation that precedes stage and is meant to be referenced
  by the handoff; it does not replace either existing format.
- `scripts/run_tests.py` (Task 112) prints `total` and `digest`, which the
  `T2_SHARDED` proof checks. CI evidence for `T1_CI` is captured by Task 114.
- The command is additive, read-only, and follows existing patterns. If it turns
  out to need a manifest or `PROTOCOL_VERSION` change, stop and report, because
  the workflow would then call for Governed SDD.
- Task 108 adds a `Validation skips` handoff field. How a handoff references this
  record is Task 109 and 110's rule text; this task does not edit workflow
  templates or the handoff checker.

## Validation

- `python3 scripts/check_repository.py`
- `python3 -m unittest discover -s tests`
- Evidence tier: schema validity, state decisions, exit codes, and the absence of
  writes, network, and project commands are program-computed and asserted.

## Out of scope

Running tests (Task 112), fetching CI results (Task 114), the handoff field and
its check (Tasks 108 to 110), `meridian worktree closure-status` reporting
(Task 101), and any cryptographic signing.

## Dependencies

- **Depends on**: 112
- **Blocks**: 114, 108, 109
