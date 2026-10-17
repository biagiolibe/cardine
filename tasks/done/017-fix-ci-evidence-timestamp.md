# Task 017 — Record wall-clock time and the real CI command in CI evidence

> **ID**: `017`
> **Category**: Bugfix
> **Priority**: 🟡 P2
> **Estimate**: ~1h
> **Assigned to**: unassigned
> **Session**: Cardine split validation review, 2026-10-17
> **Origin**: friction

## Objective

Make the `T1_CI` evidence that `scripts/ci_evidence.py` writes describe when
it was produced and what CI ran. Every split task since 006 records this
evidence before integration (ADR decision 11, CI before landing in `direct`
mode). Task 008's record says `"produced_at": "1970-01-07T07:37:25.496245Z"`,
and every record claims a command and a test count that CI never ran.

## Acceptance Criteria

- [x] `produced_at` is the UTC wall-clock time at which the record is
  written, in the `YYYY-MM-DDTHH:MM:SSZ` form that other Meridian evidence
  uses.
- [x] The polling deadline keeps using a monotonic clock. The wall clock and
  the deadline clock are separate injectable parameters of `run`, so a test
  can fix each one.
- [x] `command` records the command that the `Validate repository` workflow
  runs for the test suite, `python3 scripts/run_tests.py --parallel`, read
  from one constant that a test compares with `.github/workflows/validate.yml`.
  The record no longer claims `python3 -m unittest discover -s tests`.
- [x] `tests_run` is no longer the constant `1`. Either it records a count
  that the CI run proves, or the record states that the count is unknown in a
  form that `validation_evidence_reasons` in `scripts/meridian.py` and
  `schemas/validation-evidence-v1.schema.json` accept. The handoff names the
  choice.
- [x] Tests in `tests/test_ci_evidence.py` prove the timestamp with a fixed
  wall clock that differs from the monotonic clock, and prove the command
  constant matches the workflow.
- [x] Existing T1 records under `.git/meridian-worktrees/` and
  `tasks/handoffs/` are not rewritten.
- [x] Every command under Validation passes.

## Relevant Files

| File | Role |
|------|------|
| `scripts/ci_evidence.py` | Writes the T1 record. |
| `tests/test_ci_evidence.py` | Record and polling tests. |
| `.github/workflows/validate.yml` | The CI command the record must name. |
| `scripts/meridian.py` (`validation_evidence_reasons`) | Verifier of the record shape. |
| `schemas/validation-evidence-v1.schema.json` | Record schema. |

## Technical Context

- **Current behavior**: `run` takes `clock=time.monotonic` for its polling
  deadline and passes the same `clock` to `write_record`, which formats it
  with `datetime.fromtimestamp(now(), timezone.utc)`. Monotonic time counts
  seconds since boot, so a machine up for six days writes a January 1970
  date. The tests inject `clock=lambda: 0` and never assert `produced_at`.
- `write_record` hardcodes `"command": ["python3", "-m", "unittest",
  "discover", "-s", "tests"]` and `"tests_run": 1`, while `validate.yml`
  runs `python3 scripts/run_tests.py --parallel`.
- **Desired behavior**: the record states the real production time and the
  real CI command.
- The verifier checks only that `produced_at` is a non-empty string, so no
  consumer depends on the wrong value.

## Out of scope

Other evidence levels, CI workflow changes, and the module split.

## Dependencies

- **Depends on**: none
- **Blocks**: none

## Validation

- `python3 scripts/check_repository.py`
- `python3 scripts/run_tests.py --parallel`
- `python3 -m unittest tests.test_ci_evidence tests.test_validation_evidence -v`
- `git diff --check`

## Completion

Implemented in `d3cde4ca3934cd19e78127fd6283515b30937202`.
`tests_run: null` explicitly represents an unknown CI count; the schema and
verifier allow it only for T1_CI. T2_SHARDED and T3_ATTESTED retain integer
counts. Existing historical records were not rewritten. See
`tasks/handoffs/017.md` for validation evidence.
