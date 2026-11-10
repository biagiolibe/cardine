---
description: "Plan and convert a project to Cardine"
---

# Project adoption

Run `cardine adopt --project <path> --check` first and inspect its JSON plan and missing inputs. Supply the requested inputs, then use `--rehearse` to verify a disposable clone and `--apply` to convert the clean project. See `docs/ADOPT_COMMANDS.md` for the options and exit statuses.

```bash
cardine adopt --project . --check
```
