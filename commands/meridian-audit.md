---
description: "Verify protected capability-marker regions were not edited outside meridian upgrade"
---

Run a deterministic, read-only integrity check on a governed-SDD project's
`MERIDIAN:BEGIN`/`MERIDIAN:END` capability markers — see
[migrations/CAPABILITY_MARKERS.md](../migrations/CAPABILITY_MARKERS.md).

```bash
${CLAUDE_PLUGIN_ROOT}/bin/meridian audit --project . --mode governed-sdd
```

`--mode` is detected from the project's `PROJECT_WORKFLOW.md` mode lock when
omitted. The command changes nothing; it reports one of three outcomes per
marker found:

- `PASS` — the protected content between the markers matches the framework's
  released text for that exact capability version, in that exact file.
- `FAIL` — it does not. The protected region was edited outside
  `meridian upgrade`/`adopt`, or the marker's version is wrong for what the
  text actually says. Exit code `2`.
- `SKIP` — the project's marker names a version the current framework
  template no longer carries in that file (typically because the project is
  behind — run `meridian upgrade --check` first). This is a staleness
  question for `upgrade`, not an integrity failure for this command.

This audits only the capability-marker mechanism from `CAPABILITY_MARKERS.md`.
It does not (yet) perform the broader deterministic conformance checks
described in `QUALITY_COMPLIANCE_ROADMAP.md` (for example, verifying that
every `ACCEPTED` task has a matching `APPROVE` verdict in its review record)
— those remain a documentation-only prose audit
(`docs/AUDIT_PROMPT_READ_ONLY.md`) until they are added to this same command.

A project with no capability markers at all (predates migration 006, or has
never adopted a marked capability) reports "No capability markers found to
audit" and exits `0` — that is not the same as passing; it means there is
nothing yet for this command to check.
