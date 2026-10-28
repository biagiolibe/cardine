---
description: "Verify protected capability-marker regions were not edited outside cardine upgrade"
---

Run a deterministic, read-only integrity check on a Cardine project's
`CARDINE:BEGIN`/`CARDINE:END` capability markers recorded in
[the capability catalog](../capabilities/catalog-v1.json).

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/cardine" audit --project .
```

The CLI validates `.cardine/project.json` and uses the single distribution.
Repeating this read-only command must not write project or home files.
Host activation remains UNVERIFIED unless a host evaluates a probe or makes an
observed decision; static marker integrity is not proof of effective enforcement.

Read the per-capability results and the aggregate summary. `PASS` means the
checked content or installation matches its declared baseline. `FAIL` reports
a mismatch; do not repair protected regions by hand. `ADVISORY`, `UNVERIFIED`,
`NOT_APPLICABLE`, and marker-version `SKIP` results retain their reported
meaning; an absent marker or an unverified host is not proof of enforcement.
Exit code 0 passes, 1 retains advisory or unverified results, and 2 fails.
Report the exact results. For stale framework content, inspect the existing
`cardine upgrade --check` plan and preserve adopter overlays; this command
never applies an upgrade or writes host configuration.
