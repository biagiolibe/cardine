# Consumer profiles and project-owned sections

Cardine protects framework-managed regions delimited by `CARDINE:BEGIN` and
`CARDINE:END` markers. Project-owned sections belong outside these regions.
`cardine upgrade` preserves project sections and `cardine audit` checks managed
regions for drift. Some managed copies have no markers and are checked by
digest instead. Project configuration in `.cardine/project.json` remains
project-owned. See [project declaration](PROJECT_DECLARATION.md).

The `lean` and `governed` presets select defaults for one lifecycle. Task
options can override those defaults. Use `cardine project show` to inspect the
resolved declaration and `cardine audit` to inspect the installed framework.
