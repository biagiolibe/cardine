# Code Organization Policy

<!-- CARDINE:BEGIN capability=code-organization v2 -->
This is advice for production code. It yields to the router, accepted ADRs, and the assigned task, and never widens scope, changes behavior, or authorizes a new abstraction. A reviewer checks it.

## Ownership

- Give every production type, rule, and fixture one owning module named for a stable domain concept.
- Keep a module to one cohesive responsibility; split on several owners, layers, or reasons to change, never to meet a line count.
- A later layer may use the public contract of an earlier one, never the reverse. Keep domain rules, infrastructure, fixtures, and presentation in separate modules.
- Put a shared type in the lowest layer that owns its meaning. No `utils`, `common`, or `misc` modules.

## Module map

Record the module map and its dependency direction in the architecture documentation or in a `## Project module map` section after this block.

## Roots and public API

- A root file (crate root, package `__init__`, module index) holds documentation, declarations, and explicit re-exports, not behavior. An entry point holds wiring and startup only.
- Default to the narrowest visibility.
- A root re-export is public API: change it only when the task authorizes it. Moving code keeps public paths.

## Tests

- Unit tests live with the module that owns the rule; cross-module tests live in the project's designated location.
- Shared fixtures have one owner.
- Moving tests keeps every case and assertion and exposes no internals for test convenience.
- An ADR invariant stays tested at the layer that enforces it.

## Plans and changes

- Name the owning module in the plan, and add behavior to an existing owner. A new module needs a stable new responsibility.
- Keep behavior changes and structural moves in separate tasks unless the task combines them. Do not relocate or reformat unrelated modules.
- If the work would reverse dependency direction, mix ownership, or need broad visibility, stop and report the missing architectural decision.
<!-- CARDINE:END -->
