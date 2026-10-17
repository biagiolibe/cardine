# [Project Name]

[Brief project description in one or two sentences.]

## Getting Started

```bash
# [commands to build, run, and test the project]
```

[If the toolchain is pinned (for example, rust-toolchain.toml, .nvmrc, or pyproject.toml), mention it here.]

## Repository & Claude Code Configuration

Notes for reproducing the development setup on another machine.

**Toolchain**
- [pinned language/runtime and version]
- Key dependencies: [list]

**Claude Code — repository files (tracked in Git)**
- `CLAUDE.md` — project conventions, invariants, and Meridian workflow.
- `LANGUAGE_POLICY.md` — persisted conversation-language preference and English-only repository-text policy.
- `.claudeignore` — keeps build artifacts and non-source files out of Claude context.
- `.gitignore` — excludes build output, OS cruft, and editor configuration.

**Claude Code — session settings (not saved in the repository; configure per machine/session)**
- Model: **[model name]**
- Advisor: **[advisor name]**
- Effort level: **[level]**

Set them again with `/model`, `/advisor`, and `/effort` after cloning on a new machine.

**Not tracked in Git (local to the machine)**
- `.claude/settings.local.json` — local permission allowlist; regenerated through approval prompts.
- `.vscode/` / `.idea/` — editor-specific configuration.

---

*Last updated: [Date]*
