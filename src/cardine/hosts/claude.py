"""Helpers extracted from the legacy CLI; see the module split plan."""

from __future__ import annotations

from cardine.shared.errors import CardineError
from cardine.shared.jsonio import _write_json_atomic
from cardine.shared.models import ClaudeConfigurationPlan
from pathlib import Path
import copy
import json


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
    "Bash(git push origin main)",
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
    "Bash(cardine execution handoff-check:*)",
    "Bash(cardine execution preflight:*)",
    "Bash(cardine execution contract:*)",
    "Bash(python3 scripts/check_repository.py)",
    "Bash(python3 scripts/run_tests.py --parallel)",
    "Bash(python3 -m unittest discover -s tests)",
    "Bash(python3 -m unittest discover -s tests -q)",
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
)


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
    missing = [item for item in CLAUDE_PROJECT_ALLOWLIST if item not in allow]
    missing_deny = [item for item in CLAUDE_PROJECT_DENYLIST if item not in deny]
    if not missing and not missing_deny:
        return ClaudeConfigurationPlan(
            "ready",
            settings_path,
            None,
            "project command allowlist and deny rules are already effective",
            current_text,
        )
    proposed = copy.deepcopy(settings)
    proposed_permissions = copy.deepcopy(permissions)
    if missing:
        proposed_permissions["allow"] = [*allow, *missing]
    if missing_deny:
        proposed_permissions["deny"] = [*deny, *missing_deny]
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
    return ClaudeConfigurationPlan("approval-required", settings_path, proposed, detail, current_text)


def apply_claude_project_allowlist(plan: ClaudeConfigurationPlan) -> bool:
    if plan.status == "blocked":
        raise CardineError(f"Claude project allowlist is blocked: {plan.detail}")
    if plan.proposed_settings is None:
        return False
    current_text = plan.settings_path.read_text(encoding="utf-8") if plan.settings_path.is_file() else ""
    if current_text != plan.current_text:
        raise CardineError("Claude settings changed since they were planned; rerun --check")
    _write_json_atomic(plan.settings_path, plan.proposed_settings)
    return True


def claude_hook_duplicate_advisories(project_root: Path, home: Path) -> tuple[str, ...]:
    """Report direct hook registrations when the Cardine Claude plugin is enabled.

    This is deliberately advisory and read-only: Cardine never writes Claude
    hook registrations, so a hand-written duplicate must remain the user's
    choice to remove.
    """
    paths = (home / ".claude/settings.json", project_root / ".claude/settings.json",
             project_root / ".claude/settings.local.json")
    parsed: list[tuple[Path, object]] = []
    for path in paths:
        if not path.is_file():
            continue
        try:
            parsed.append((path, json.loads(path.read_text(encoding="utf-8"))))
        except (OSError, json.JSONDecodeError):
            continue
    plugin_enabled = any(
        isinstance(settings, dict)
        and isinstance(settings.get("enabledPlugins"), dict)
        and any("meridian" in str(name).lower() and enabled is True
                for name, enabled in settings["enabledPlugins"].items())
        for _path, settings in parsed
    )
    if not plugin_enabled:
        return ()
    advisories: list[str] = []
    for path, settings in parsed:
        rendered = json.dumps(settings, sort_keys=True) if isinstance(settings, (dict, list)) else ""
        for command in ("queue-briefing.sh", "read-guard.sh"):
            if command in rendered:
                advisories.append(f"{path}: direct {command} registration duplicates the enabled Cardine plugin")
    return tuple(advisories)
