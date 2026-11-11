---
description: "Plan and convert a project to Cardine"
---

# Project adoption

`cardine init` chooses adoption for an existing project; prefer `/cardine-init`. Use
`cardine adopt` directly only for automation that needs its flags: run
`cardine adopt --project <path> --check` first and inspect its JSON plan and missing
inputs, supply the requested inputs, then use `--rehearse` to verify a disposable
clone and `--apply` to convert the clean project. See `docs/ADOPT_COMMANDS.md` for the
options and exit statuses.

```bash
cardine adopt --project . --check
```
