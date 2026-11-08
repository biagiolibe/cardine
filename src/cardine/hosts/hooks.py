"""User-level hook registration for Claude Code and Codex.

Each host gets one Cardine entry per event in its user registry and nothing in
any project or plugin. Registration is not activation: a host loads its hooks
when a session starts, and only a probe (`doctor`) can show that it did. This
module never writes trust or approval state and never reads a registry to
claim a hook is in force.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
import json
import re
import shlex
import sys

from cardine.hosts.claude import claude_legacy_plugin_advisories
from cardine.hosts.effects import changed
from cardine.lifecycle.file_operation import Operation
from cardine.shared.errors import CardineError

# event -> (matcher, command suffix, timeout). Matchers follow the payloads the
# shared read guard decodes: Claude's native Read tool, Codex's shell tool.
_HOOKS = {
    "claude": {
        "UserPromptSubmit": (None, "briefing", 5),
        "PreToolUse": ("Read", "read-guard", 5),
        "Stop": (None, "stop-audit", 5),
    },
    "codex": {
        "UserPromptSubmit": (None, "briefing", 5),
        "PreToolUse": ("Bash", "read-guard", 10),
        "Stop": (None, "stop-audit", 5),
    },
}
# Any binary name: the legacy CLI used the same subcommands.
FOREIGN_HOOK = re.compile(r"\bhook (?:briefing|read-guard|stop-audit)\b.*--host\b")


@dataclass(frozen=True)
class HookRegistryPlan:
    host: str
    path: Path
    status: str  # ready | missing | update | blocked
    detail: str
    current_text: str
    proposed_text: str | None
    duplicates: int = 0


@dataclass(frozen=True)
class HooksPlan:
    claude: HookRegistryPlan
    codex: HookRegistryPlan
    advisories: tuple[str, ...] = ()

    @property
    def registries(self) -> tuple[HookRegistryPlan, HookRegistryPlan]:
        return (self.claude, self.codex)

    @property
    def blocked(self) -> HookRegistryPlan | None:
        return next((plan for plan in self.registries if plan.status == "blocked"), None)


def launcher() -> tuple[str, ...]:
    """The interpreter and launcher of the running Cardine checkout.

    Hosts started from a desktop app run hooks without the developer's interactive
    shell PATH, where neither `cardine` nor a recent `python3` resolves. Absolute
    paths make the registered command independent of that PATH.
    """
    script = Path(__file__).resolve().parents[3] / "bin" / "cardine"
    return (sys.executable, str(script)) if script.is_file() else ("cardine",)


def hook_command(host: str, name: str) -> str:
    return " ".join(shlex.quote(part) for part in launcher()) + f" hook {name} --host {host}"


def owns(command: str, host: str, name: str) -> bool:
    """A Cardine registration of this hook, whatever launcher path it names."""
    try:
        argv = shlex.split(command)
    except ValueError:
        return False
    return len(argv) >= 5 and argv[-4:] == ["hook", name, "--host", host] and Path(argv[-5]).name == "cardine"


def _owned_anywhere(command: str) -> bool:
    return any(owns(command, host, name) for host, events in _HOOKS.items() for _m, name, _t in events.values())


def _group(host: str, event: str) -> dict[str, object]:
    matcher, name, timeout = _HOOKS[host][event]
    group: dict[str, object] = {} if matcher is None else {"matcher": matcher}
    group["hooks"] = [{"type": "command", "command": hook_command(host, name), "timeout": timeout}]
    return group


def registry_path(home: Path, host: str) -> Path:
    return home / (".claude/settings.json" if host == "claude" else ".codex/hooks.json")


def _blocked(host: str, path: Path, detail: str, text: str = "") -> HookRegistryPlan:
    return HookRegistryPlan(host, path, "blocked", detail, text, None)


def _merged(groups: list, host: str, name: str, desired: dict) -> tuple[list, int]:
    """Replace every owned hook with one desired group; return it and how many owned hooks existed."""
    result: list = []
    seen = 0
    insert_at: int | None = None
    for group in groups:
        entries = group.get("hooks") if isinstance(group, dict) else None
        if isinstance(entries, list):
            kept = [entry for entry in entries
                    if not (isinstance(entry, dict) and isinstance(entry.get("command"), str)
                            and owns(entry["command"], host, name))]
            if len(kept) != len(entries):
                seen += len(entries) - len(kept)
                insert_at = len(result) if insert_at is None else insert_at
                if kept:
                    result.append({**group, "hooks": kept})
                continue
        result.append(group)
    result.insert(len(result) if insert_at is None else insert_at, desired)
    return result, seen


def _plan_registry(host: str, path: Path) -> HookRegistryPlan:
    if path.is_symlink() or (path.exists() and not path.is_file()):
        return _blocked(host, path, f"{path} is not a regular file")
    try:
        text = path.read_bytes().decode("utf-8") if path.exists() else ""
        document = json.loads(text) if text.strip() else {}
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        return _blocked(host, path, f"{path} is not readable JSON: {error}")
    if not isinstance(document, dict) or not isinstance(document.get("hooks", {}), dict):
        return _blocked(host, path, f"{path} must hold an object with an object `hooks` value", text)
    registered = dict(document.get("hooks", {}))
    duplicates = 0
    altered = False
    for event in _HOOKS[host]:
        groups = registered.get(event, [])
        if not isinstance(groups, list):
            return _blocked(host, path, f"{path} hooks.{event} must be a list", text)
        merged, seen = _merged(groups, host, _HOOKS[host][event][1], _group(host, event))
        duplicates += max(seen - 1, 0)
        if merged != groups:
            registered[event] = merged
            altered = True
    if not altered:
        return HookRegistryPlan(host, path, "ready", "one Cardine entry per event is registered", text, None)
    proposed = json.dumps({**document, "hooks": registered}, indent=2, ensure_ascii=False) + "\n"
    status = "update" if path.exists() else "missing"
    detail = f"register Cardine {host} hooks in {path}"
    if duplicates:
        detail += f"; remove {duplicates} owned duplicate registration(s)"
    return HookRegistryPlan(host, path, status, detail, text, proposed, duplicates)


def _commands(value: object) -> Iterator[str]:
    if isinstance(value, dict):
        command = value.get("command")
        if isinstance(command, str):
            yield command
        for item in value.values():
            yield from _commands(item)
    elif isinstance(value, list):
        for item in value:
            yield from _commands(item)


def _foreign_advisories(home: Path, project_root: Path) -> tuple[str, ...]:
    """Other registrations of a Cardine or legacy hook command; reported, never rewritten."""
    candidates = (
        (registry_path(home, "claude"), "user"), (registry_path(home, "codex"), "user"),
        (project_root / ".claude/settings.json", "project"), (project_root / ".claude/settings.local.json", "project"),
        (project_root / ".codex/hooks.json", "project"),
    )
    found: list[str] = []
    for path, scope in candidates:
        try:
            document = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        for command in _commands(document.get("hooks") if isinstance(document, dict) else None):
            if FOREIGN_HOOK.search(command) and (scope == "project" or not _owned_anywhere(command)):
                found.append(f"{path}: {command!r} may invoke a hook twice next to the user registration; "
                             "remove it if it is yours")
    return (*found, *claude_legacy_plugin_advisories(project_root, home))


def plan_hooks(home: Path, project_root: Path) -> HooksPlan:
    return HooksPlan(
        _plan_registry("claude", registry_path(home, "claude")),
        _plan_registry("codex", registry_path(home, "codex")),
        _foreign_advisories(home, project_root),
    )


def _unused_backup(path: Path) -> Path:
    candidate = path.with_name(path.name + ".cardine.bak")
    index = 0
    while candidate.exists() or candidate.is_symlink():
        index += 1
        candidate = path.with_name(f"{path.name}.cardine.{index}.bak")
    return candidate


def apply_hooks(plan: HooksPlan, active: Operation) -> bool:
    """Back up and replace each changed registry inside the caller's setup operation."""
    wrote = False
    for registry in plan.registries:
        if registry.proposed_text is None:
            continue
        active.guard(registry.path)
        current = registry.path.read_bytes().decode("utf-8") if registry.path.is_file() else ""
        if current != registry.current_text:
            raise CardineError(f"{registry.path} changed since it was planned; rerun --check")
        existing = registry.path.is_file()
        active.replace(f"{registry.host}-hooks", registry.path, registry.proposed_text.encode("utf-8"),
                       backup=_unused_backup(registry.path) if existing else None,
                       mode=registry.path.stat().st_mode & 0o777 if existing else 0o600)
        wrote = True
    return changed(active, wrote)
