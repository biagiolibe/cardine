---
description: "Plan and complete a capability-aware Meridian adoption"
---

Adopt an existing Meridian project that predates `.meridian/manifest.json`
without forcing generic template merges over local workflow customizations.

Run the single planning command — omit `--mode` and `--from` and the CLI
detects them from the project's `PROJECT_WORKFLOW.md` mode lock and the sole
packaged baseline for that mode; pass them explicitly only when detection is
ambiguous and the command says so:

```bash
${CLAUDE_PLUGIN_ROOT}/bin/meridian adopt --project . --assisted --check
```

Read its first `NEXT_ACTION <value>` line and exit code; this pair is the
entire coordination contract, computed fresh from the project's detected
capabilities and `.meridian/adoption-review.md` on every run — nothing needs
to be remembered between invocations:

- **`NEXT_ACTION IMPLEMENT_MIGRATION` or `ADDRESS_REVIEW` (exit 3):** start a
  fresh implementer for the named missing capability. In Claude Code, start it
  as an independent Task-tool subagent — do not implement it in the current
  session — and send it the exact text between `IMPLEMENTER_PROMPT_BEGIN` and
  `IMPLEMENTER_PROMPT_END`. Then loop back to the planning command.
- **`NEXT_ACTION REVIEW_MIGRATION` or the next pass of `ADDRESS_REVIEW` (exit
  3):** start a second, distinct Task-tool subagent that did not implement the
  migration and send it the text between `REVIEWER_PROMPT_BEGIN` and
  `REVIEWER_PROMPT_END`. It commits its verdict to
  `.meridian/adoption-review.md`. Then loop back to the planning command.
- **`NEXT_ACTION FINALIZE` (exit 0, `READY_TO_FINALIZE`):** the reviewer that
  approved the migration runs `finalize-adoption` (below), inspects the
  manifest/baseline diff, and commits it with the approved migration.
- **Exit 2 (`BLOCKED`):** stop and report the exact printed reason — this
  covers two consecutive `CHANGES_REQUESTED` verdicts, a malformed review
  record, or an ambiguous mode/version detection. Do not retry automatically.

Do this as a genuine coordinator loop, not a one-shot report: after each
subagent finishes, immediately rerun the planning command and act on its new
`NEXT_ACTION` until it reports `FINALIZE` or `BLOCKED`. Pass only the emitted
prompt text and the record path between sessions — never the coordinating
session's own reasoning or a copy of one subagent's transcript into another.
To pull one prompt block on its own (for a shell script, or a host with no
subagent tool), append `--emit implementer` or `--emit reviewer` to the same
`--assisted --check` command instead of parsing the `_BEGIN`/`_END` markers.

**Fallback when this host cannot start independent subagents or chats:** run
the same planning command yourself, open a new chat window for each role, and
paste the relevant emitted block verbatim — the record on disk keeps the loop
consistent across manually started sessions, so nothing is lost by doing this
by hand. A human may follow the same prompts directly instead of an agent.

After `APPROVE`, register the framework baseline:

```bash
${CLAUDE_PLUGIN_ROOT}/bin/meridian finalize-adoption --project .
```

`finalize-adoption` also detects `--mode` when omitted. It refuses to run
unless every required capability is present and `.meridian/adoption-review.md`
records an unconditional `APPROVE` with no unchecked findings. A developer who
personally reviewed the migration may pass `--owner-accepted` to skip that
review-record gate instead — mirroring the project's own `Accept <TASK-ID>`
owner-acceptance path — but this is a deliberate, explicit substitute for
independent review, not a default.

Review and commit the resulting manifest and baseline snapshot together with
the approved migration. If a capability cannot be implemented without changing
authority or project-specific workflow intent, return `BLOCKED` with the exact
conflict.
