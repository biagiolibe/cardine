# Project Execution Evidence Profile

This Meridian profile is configured for the repository's Python checks and
Git-based delivery workflow. Task-specific checks remain mandatory.

## Context and diagnostics

- Reuse unchanged sources and successful results from the active session.
- Locate a large-file range before reading it; the threshold is 400 lines.
- Allow at most two context expansions and three diagnostic hypotheses per
  failure. Stop with `BLOCKED CONTRACT_EXHAUSTED` when the task contract is exhausted.
- Start with the failing check's ordinary bounded output, then run the
  narrowest test method or file-specific diagnostic. Use verbose output or a
  full trace only when those levels cannot identify the cause.

## Validation output

Run the repository checks with producer-status-preserving bounds:

```bash
set -o pipefail
python3 scripts/check_repository.py 2>&1 | tail -n 200
python3 -m unittest discover -s tests -q 2>&1 | tail -n 40
git diff --check 2>&1 | tail -n 200
```

Record each literal command, its exit status, and the material final lines.
Run every validation command of record as its own command with its own exit
status. Never join it with `&&` or `;` to exploratory reads (`sed`, `cat`,
`rg`, or `ls`) or to another validation command whose individual status must
be reported. Reads may be batched with other reads.
Run a command expected to take longer than one minute in the foreground with a
timeout of up to 600 seconds, or in a persistent terminal session; never
detach it and poll for completion.

<!-- MERIDIAN:BEGIN capability=long-command-waits v1 -->
Long commands and suite runs:

- Start a command expected to take longer than one minute with a wait long
  enough to cover its expected duration in the same call. Poll an already
  running command at most once, and only after that wait has expired; never
  loop on empty polls, because each one re-sends the whole context.
- Codex returns control from a command session when the requested wait ends,
  not when the command ends, so ask for a wait that covers the expected
  duration in the call that starts the command. If the host caps the wait below
  that duration, use the cap once and then one further wait, not repeated short
  polls. Observed on codex-cli 0.160.0: a command cell starts with
  `yield_time_ms` and `max_output_tokens`, and a still-running cell is resumed
  with `wait` (`cell_id`, `yield_time_ms`, `max_tokens`). A wait of 60000 ms
  was honored in full; no larger value was exercised, so the maximum is not
  stated here.
- During implementation, run only the tests of the modules the task touches.
  Run the full suite once, after the last code change, as the validation of
  record, and rerun it only when code changed since. This does not change the
  declared candidate validation (`REUSE`, `BOUNDED`, `FULL`) in
  `docs/WORKTREE_LIFECYCLE.md`.
<!-- MERIDIAN:END -->

The full suite of this repository takes about two minutes, measured on
2026-10-03; treat this as a measurement that can change.

## Diff and manual evidence

- Before and after material edits, use `git status --short` and
  `git diff --stat`; inspect every changed hunk with `git diff -- <path>`.
- Prefer unit, integration, schema, hash, and command-output checks. This task
  has no perceptual acceptance criterion, so no manual capture is required.

## Runtime configuration

Faster execution is allowed only when it preserves required evidence.
