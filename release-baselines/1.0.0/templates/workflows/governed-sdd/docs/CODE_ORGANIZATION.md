# Code Organization Policy

## Status and precedence

This is the normative source-organization policy for production code. It is subordinate to `AGENTS.md`/`CLAUDE.md`, accepted ADRs, specifications, and the assigned atomic task. It organizes an authorized implementation; it never expands scope, changes behavior, or authorizes a new abstraction.

## Ownership and cohesion

Every production type, rule, system, and fixture has one owning module named for a stable domain concept or application responsibility.

- A module should represent one cohesive responsibility, not merely reduce line count.
- Different architectural layers belong in different modules. A later layer may consume the public contract of an earlier layer; an earlier layer must not depend on a later layer.
- Domain rules, framework/infrastructure integration, fixed fixtures, and presentation do not share an owning module.
- Shared types belong to the lowest stable layer that owns their meaning. Do not create generic `utils`, `common`, or `misc` dumping grounds.
- Prefer a small cohesive module with several related items over one file per type or function.

File length is a diagnostic signal, not an acceptance limit. Split when a file accumulates multiple owners, layers, change reasons, or test domains; do not split mechanically to satisfy a line-count target.

## Project module map

Record this project's actual layered module map — and its dependency direction — in `[Project Name]`'s own architecture documentation (for example `docs/ARCHITECTURE_DECISIONS.md` or `TECH_DESIGN.md`), not in this file. This file states the ownership rules; the project states which modules exist and how they depend on each other. Keep domain-specific architecture out of Meridian's generic workflow assets.

## Crate/package roots and public API

- A root entry file (crate root, package `__init__`, module index) contains documentation, module declarations, and explicit root re-exports. It does not own behavior.
- An application/process entry point contains wiring and startup only. It does not own systems, fixtures, formatting, or tests beyond bootstrap-specific coverage.
- Use the narrowest visibility by default. Use package/internal visibility only for intentional intra-package collaboration and public visibility only for an external contract.
- A root re-export is public API. Add, remove, or rename one only when the assigned task explicitly authorizes the API change.
- Moving code between modules must preserve existing public paths unless the governing task explicitly changes them.
- Avoid wildcard public re-exports; enumerate the intended public surface.

## Tests

- Unit tests live with the module that owns the rule or contract.
- Tests spanning public modules live in the project's designated cross-module test location.
- Shared test fixtures have one explicit test-support owner.
- Moving tests must not remove cases, weaken assertions, or expose production internals solely for test convenience.
- Invariants declared by an ADR or specification (determinism, ownership, atomicity, layer separation, causal provenance, or similar) remain tested at the layer where each invariant is enforced.

## Task and review discipline

- Before editing production code, name the owning module in the implementation plan.
- Add behavior to the existing owner when one exists. A new module requires a stable new responsibility, not convenience during one task.
- Keep behavior changes and structural movement in separate atomic tasks unless the assigned task explicitly combines them.
- Do not relocate, rename, or reformat unrelated modules while implementing a feature or fix.
- If the requested behavior would reverse dependency direction, mix ownership categories, or require broad visibility, stop and report the missing architectural decision instead of creating an opportunistic abstraction.

Review verifies module ownership, dependency direction, visibility, root API stability, test placement, and diff scope. Organization-only tasks additionally verify behavior preservation with the repository baseline checks.
