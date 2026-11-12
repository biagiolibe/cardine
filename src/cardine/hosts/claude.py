"""Helpers extracted from the legacy CLI; see the module split plan."""

from __future__ import annotations

from cardine.shared.errors import CardineError
from cardine.hosts import permissions
from cardine.hosts.effects import changed, host_operation
from cardine.lifecycle.file_operation import Operation
from cardine.shared.jsonio import json_bytes
from cardine.shared.models import ClaudeConfigurationPlan
from pathlib import Path
import copy
import json


def claude_plugin_state(home: Path, framework_root: Path | None) -> str:
    """The installed Cardine plugin against this CLI; read only, and never proof of activation."""
    if framework_root is None:
        return plugin_state_for(home, None)
    from cardine.release.version import read_version
    return plugin_state_for(home, read_version(framework_root))


def plugin_state_for(home: Path, cli: str | None) -> str:
    """`absent`, `match`, `mismatch...` against version `cli`, or `installed ...` without one."""
    registry = home / ".claude/plugins/installed_plugins.json"
    try:
        entries = json.loads(registry.read_text(encoding="utf-8"))["plugins"]["cardine@cardine"]
        versions = sorted({entry["version"] for entry in entries})
    except (OSError, ValueError, KeyError, TypeError):
        return "absent"
    if not versions:
        return "absent"
    if cli is None:
        return "installed " + ", ".join(versions)
    stale = [version for version in versions if version != cli]
    if not stale:
        return "match"
    return f"mismatch: plugin {', '.join(stale)}, CLI {cli}; reinstall the plugin at tag v{cli}"


def plugin_alignment_commands(state: str, version: str) -> list[list[str]]:
    """The ordered Claude commands that align the plugin with `version`; none on a match."""
    if state == "match":
        return []
    commands = [["claude", "plugin", "marketplace", "add", f"biagiolibe/cardine#v{version}"],
                ["claude", "plugin", "install", "cardine@cardine"]]
    if state.startswith("mismatch"):
        commands.insert(0, ["claude", "plugin", "marketplace", "remove", "cardine"])
    return commands


def align_claude_plugin(home: Path, version: str, *, runner=None, which=None, out=print) -> str:
    """Align the Claude plugin with `version`; returns match, aligned, or printed (no claude on PATH)."""
    import shlex
    import shutil
    import subprocess
    state = plugin_state_for(home, version)
    commands = plugin_alignment_commands(state, version)
    if not commands:
        out("claude-plugin: match")
        return "match"
    if (shutil.which if which is None else which)("claude") is None:
        out("claude-plugin: claude is not on PATH; run these commands:")
        for command in commands:
            out("  " + shlex.join(command))
        return "printed"
    run = runner or (lambda argv: subprocess.run(argv, check=False).returncode)
    for command in commands:
        code = run(command)
        if code:
            raise CardineError(f"{shlex.join(command)} failed with exit {code}; fix the cause and rerun to converge")
    out(f"claude-plugin: aligned to v{version}")
    return "aligned"


CLAUDE_PROJECT_ALLOWLIST = (
    "Bash(git status:*)",
    "Bash(git diff:*)",
    "Bash(git log:*)",
    "Bash(git show:*)",
    "Bash(git rev-parse:*)",
    "Bash(git merge-base:*)",
    "Bash(git branch --show-current)",
    "Bash(git add:*)",
    "Bash(git switch:*)",
    "Bash(git commit -m:*)",
    "Bash(git merge --ff-only:*)",
    "Bash(git worktree list:*)",
    "Bash(cardine worktree path:*)",
    "Bash(cardine worktree prepare:*)",
    "Bash(cardine worktree check:*)",
    "Bash(cardine worktree evidence:*)",
    "Bash(cardine worktree closure-status:*)",
    "Bash(cardine worktree advance:*)",
    "Bash(cardine worktree cleanup:*)",
    "Bash(cardine worktree integrate stage:*)",
    "Bash(cardine worktree integrate finalize:*)",
    "Bash(cardine worktree integrate abort:*)",
    "Bash(cardine execution start:*)",
    "Bash(cardine execution deliver:*)",
    "Bash(cardine execution validate:*)",
    "Bash(cardine execution ready-check:*)",
    "Bash(cardine execution preflight:*)",
    "Bash(cardine execution contract:*)",
    "Bash(git mv tasks/:*)",
    "Bash(set -o pipefail)",
    "Bash(ls:*)",
    "Bash(cat:*)",
    "Bash(head:*)",
    "Bash(tail:*)",
    "Bash(wc:*)",
    "Bash(pwd)",
    "Bash(grep:*)",
)


# Prefix rules are defense in depth: a reworded command can evade them, so the
# managed denial text stays in force (docs/ADR_STOPS_AND_DENIALS.md, Decision 5).
# Claude Code applies an `Edit(...)` rule to every built-in file-editing tool.
CLAUDE_EDIT_RULE_TOOL = "Edit"

CLAUDE_PROJECT_DENYLIST = (
    "Bash(git push --force:*)",
    "Bash(git push -f:*)",
    "Bash(git push --force-with-lease:*)",
    "Bash(git push --mirror:*)",
    "Bash(git push --delete:*)",
    "Bash(git tag:*)",
    "Bash(git rebase:*)",
    "Bash(git reset --hard:*)",
    "Bash(git cherry-pick:*)",
    "Bash(git branch -D:*)",
    "Bash(git worktree remove --force:*)",
    # Protected paths: relative to the project root. One `Edit` rule covers every
    # built-in tool that edits files; Claude Code warns on the other tool names.
    *(f"{CLAUDE_EDIT_RULE_TOOL}(/{path})" for path in permissions.relative_protected()),
)

# Earlier versions also wrote these exact rules. `Edit(...)` above covers the same
# tools, so removing them never widens access; setup removes only these strings.
OBSOLETE_DENY_ENTRIES = tuple(
    f"{tool}(/{path})" for path in permissions.relative_protected()
    for tool in permissions.NATIVE_WRITE_TOOLS if tool != CLAUDE_EDIT_RULE_TOOL
)

# A previous Cardine version pre-approved this exact entry. A user can also write it, so
# ownership is unprovable: setup keeps it and reports it instead of removing it.
LEGACY_ALLOW_ENTRIES = ("Bash(git push origin main)",)


def plan_claude_project_allowlist(project_root: Path) -> ClaudeConfigurationPlan:
    """Plan one explicit, project-local Claude Code command allowlist update."""
    settings_path = project_root.expanduser().resolve() / ".claude/settings.local.json"
    if settings_path.exists() and not settings_path.is_file():
        return ClaudeConfigurationPlan(
            "blocked", settings_path, None, "Claude settings path is not a regular file"
        )
    current_text = settings_path.read_text(encoding="utf-8") if settings_path.is_file() else ""
    try:
        settings = json.loads(current_text) if current_text else {}
    except json.JSONDecodeError as error:
        return ClaudeConfigurationPlan(
            "blocked", settings_path, None, f"malformed Claude settings: {error}", current_text
        )
    if not isinstance(settings, dict):
        return ClaudeConfigurationPlan(
            "blocked", settings_path, None, "Claude settings must contain a JSON object", current_text
        )
    permissions = settings.get("permissions", {})
    if not isinstance(permissions, dict):
        return ClaudeConfigurationPlan(
            "blocked", settings_path, None, "Claude settings permissions must contain an object", current_text
        )
    allow = permissions.get("allow", [])
    if not isinstance(allow, list) or not all(isinstance(item, str) for item in allow):
        return ClaudeConfigurationPlan(
            "blocked", settings_path, None, "Claude settings permissions.allow must contain strings", current_text
        )
    deny = permissions.get("deny", [])
    if not isinstance(deny, list) or not all(isinstance(item, str) for item in deny):
        return ClaudeConfigurationPlan(
            "blocked", settings_path, None, "Claude settings permissions.deny must contain strings", current_text
        )
    legacy = [item for item in LEGACY_ALLOW_ENTRIES if item in allow]
    legacy_note = ("; kept entries of unprovable ownership, remove by hand if unwanted: " + ", ".join(legacy)
                   if legacy else "")
    missing = [item for item in CLAUDE_PROJECT_ALLOWLIST if item not in allow]
    missing_deny = [item for item in CLAUDE_PROJECT_DENYLIST if item not in deny]
    obsolete = [item for item in deny if item in OBSOLETE_DENY_ENTRIES]
    if not missing and not missing_deny and not obsolete:
        return ClaudeConfigurationPlan(
            "ready",
            settings_path,
            None,
            "project command allowlist and deny rules are already installed; installation is not host enforcement"
            + legacy_note,
            current_text,
        )
    proposed = copy.deepcopy(settings)
    proposed_permissions = copy.deepcopy(permissions)
    if missing:
        proposed_permissions["allow"] = [*allow, *missing]
    if missing_deny or obsolete:
        proposed_permissions["deny"] = [*(item for item in deny if item not in OBSOLETE_DENY_ENTRIES), *missing_deny]
    proposed["permissions"] = proposed_permissions
    detail = "explicit --apply adds the missing project command allowlist entries"
    if missing_deny:
        detail = (
            ("explicit --apply adds the missing project command allowlist entries and "
             if missing else "explicit --apply adds the missing ")
            + "deny rules: "
            + ", ".join(missing_deny)
            + "; prefix rules are defense in depth, a reworded command can evade them,"
            + " and the managed denial text remains in force"
        )
    if obsolete:
        detail += "; removes deny rules that Claude Code reports as never matching: " + ", ".join(obsolete)
    detail += legacy_note
    return ClaudeConfigurationPlan("approval-required", settings_path, proposed, detail, current_text)


def apply_claude_project_allowlist(plan: ClaudeConfigurationPlan, operation: Operation | None = None) -> bool:
    if plan.status == "blocked":
        raise CardineError(f"Claude project allowlist is blocked: {plan.detail}")
    with host_operation("claude-allowlist", plan.settings_path, operation) as active:
        if plan.proposed_settings is None:
            return changed(active, False)
        current_text = plan.settings_path.read_text(encoding="utf-8") if plan.settings_path.is_file() else ""
        if current_text != plan.current_text:
            raise CardineError("Claude settings changed since they were planned; rerun --check")
        active.replace("claude-allowlist", plan.settings_path, json_bytes(plan.proposed_settings), mode=0o600)
        return True


CLAUDE_REVIEWER_TOOLS = ("Read", "Grep", "Glob")  # read-only: nothing writes or runs commands


def _edit_rule(tool: str, root: Path) -> str:
    return f"{tool}(/{root.as_posix()})"  # `//path` is an absolute path in Claude rule syntax


def claude_role_policy(role: str, project_root: Path, worktree: Path, common_dir: Path) -> permissions.RolePolicy:
    """Deterministic settings for one role session, from the shared protected-path and action matrix.

    The launch adapter passes this fragment to the role session. It contains
    rules only: no credential, token, or environment value is ever rendered.
    """
    if role not in permissions.ROLES:
        raise CardineError(f"unknown Claude role: {role}")
    if role == "reviewer":
        # No write or command tool exists in the session, so no deny rule is needed.
        settings = {"tools": list(CLAUDE_REVIEWER_TOOLS), "strict_mcp": True, "session_persistence": False,
                    "answer_schema": "review-answer-v1"}
        return permissions.RolePolicy("claude", role, f"cardine-{role}", settings,
                                      permissions.policy_digest("claude", role, settings))
    roots = permissions.protected_roots((project_root, worktree), common_dir)
    deny = [_edit_rule(CLAUDE_EDIT_RULE_TOOL, path) for root in roots for path in (root, root / "**")]
    deny += [f"Bash(cardine {' '.join(action)}:*)" for action in permissions.DEVELOPER_ONLY + permissions.INTEGRATION]
    deny += ["Bash(git push origin main:*)", "Bash(git push origin HEAD:main:*)",
             "Bash(git push origin +main:*)", "Bash(git push origin HEAD:refs/heads/main:*)",
             "Bash(git push origin master:*)", "Bash(git push origin HEAD:master:*)"]
    deny.append("Bash(cardine review verdict:*)")
    settings = {"permissions": {"deny": list(dict.fromkeys(deny))}}
    return permissions.RolePolicy("claude", role, f"cardine-{role}", settings,
                                  permissions.policy_digest("claude", role, settings))


def claude_role_profile(policy: permissions.RolePolicy, proof: permissions.HostProof | None):
    """`enforced` comes only from a complete host-evaluated proof of this exact policy.

    Claude has no host decision probe yet, so doctor reports `unverified` and
    the proof is None: the profile stays unenforced and the launch adapter
    refuses the role (D3), whatever the installed settings say.
    """
    from cardine.hosts.launch import RoleProfile  # lazy: launch pulls in the lifecycle engine
    return RoleProfile(policy.identity, policy.role, permissions.proof_enforces(policy, proof))


def _claude_settings(project_root: Path, home: Path) -> list[tuple[Path, object]]:
    paths = (home / ".claude/settings.json", project_root / ".claude/settings.json",
             project_root / ".claude/settings.local.json")
    parsed: list[tuple[Path, object]] = []
    for path in paths:
        if not path.is_file():
            continue
        try:
            parsed.append((path, json.loads(path.read_text(encoding="utf-8"))))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
    return parsed


def _legacy_plugin_enabled(parsed: list[tuple[Path, object]]) -> list[Path]:
    """Files that decide an effective `true` for a legacy plugin id.

    Claude Code combines `enabledPlugins` key by key: for each plugin id the
    highest-precedence file that names it wins (local > project > user), and
    `parsed` is ordered user, project, local.
    """
    decided: dict[str, tuple[Path, bool]] = {}
    for path, settings in parsed:
        plugins = settings.get("enabledPlugins") if isinstance(settings, dict) else None
        if not isinstance(plugins, dict):
            continue
        for name, enabled in plugins.items():
            if "meridian" in str(name).lower() and isinstance(enabled, bool):
                decided[str(name)] = (path, enabled)
    return list(dict.fromkeys(path for path, enabled in decided.values() if enabled))


def claude_legacy_plugin_advisories(project_root: Path, home: Path) -> tuple[str, ...]:
    """The enabled legacy plugin registers its own hooks next to the user registration; advisory only."""
    return tuple(f"{path}: the enabled legacy plugin registers its own hooks and runs them "
                 "next to the user-level Cardine hooks; disable it for one invocation per event"
                 for path in _legacy_plugin_enabled(_claude_settings(project_root, home)))


def claude_hook_duplicate_advisories(project_root: Path, home: Path) -> tuple[str, ...]:
    """Report direct hook registrations when the Cardine Claude plugin is enabled.

    This is deliberately advisory and read-only: setup writes only its own
    user-level registrations (`hosts/hooks.py`), so a hand-written duplicate
    in a project or plugin must remain the user's choice to remove.
    """
    parsed = _claude_settings(project_root, home)
    if not _legacy_plugin_enabled(parsed):
        return ()
    advisories: list[str] = []
    for path, settings in parsed:
        rendered = json.dumps(settings, sort_keys=True) if isinstance(settings, (dict, list)) else ""
        for command in ("queue-briefing.sh", "read-guard.sh"):
            if command in rendered:
                advisories.append(f"{path}: direct {command} registration duplicates the enabled Cardine plugin")
    return tuple(advisories)
