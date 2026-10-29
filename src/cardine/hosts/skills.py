"""Helpers extracted from the legacy CLI; see the module split plan."""

from __future__ import annotations

from cardine.hosts.codex import _codex_expected_profile
from cardine.hosts.codex import _codex_markers_intact
from cardine.shared.git import _run_git
from cardine.shared.models import CODEX_PERMISSION_PROFILE
from cardine.shared.models import CodexConfigurationPlan
from cardine.shared.errors import CardineError
from pathlib import Path
import os
import stat
import tomllib


def _directory_setup_state(root: Path) -> tuple[str, str]:
    if not root.exists():
        return "missing", f"create {root} with mode 0700"
    if not root.is_dir():
        return "blocked", f"worktree root exists but is not a directory: {root}"
    details = root.stat()
    if hasattr(os, "getuid") and details.st_uid != os.getuid():
        return "blocked", f"worktree root is not owned by the current user: {root}"
    mode = stat.S_IMODE(details.st_mode)
    if mode != 0o700:
        return "repair-required", f"set mode 0700 on {root} (currently {mode:04o})"
    return "ready", "no directory change"


CODEX_SKILL_NAMES = ("cardine-project", "cardine-delivery")
OLD_SKILL_NAMES = (
    "meridian-lean-delivery", "meridian-governed-sdd",
    "meridian-lean-delivery-claude-code", "meridian-governed-sdd-claude-code",
)


def _safe_skill_parent(path: Path) -> bool:
    return all(not parent.is_symlink() and (not parent.exists() or parent.is_dir())
               for parent in path.parents)


def _owned_old_link(path: Path, target: Path) -> bool:
    return (_safe_skill_parent(path) and path.is_symlink()
            and os.path.abspath(path.parent / os.readlink(path)) == str(target))


def _remove_old_skill_links(active, links) -> bool:
    active._check()
    records = active.intent.get("old_skill_links", {})
    for value, target in records.items():
        _old_link_absent(Path(value), Path(target))
    for _, path, state, target in links:
        if state == "remove" and str(path) not in records:
            records[str(path)] = target
            active.intent["old_skill_links"] = records
            active._save()
    for value, target in records.items():
        path = Path(value)

        label = "/".join(path.parts[-3:])
        active.effect("remove-skill:" + label, path.unlink,
                      lambda: _old_link_absent(path, Path(target)))
    if records:
        active.effect("skill-migration-result", lambda: None,
                      lambda: all(_old_link_absent(Path(value), Path(target))
                                  for value, target in records.items()))
    return bool(records)


def _old_link_absent(path: Path, target: Path) -> bool:
    if not _safe_skill_parent(path):
        raise CardineError(f"skill parent changed: {path}")
    if not path.exists() and not path.is_symlink():
        return True
    if not _owned_old_link(path, target):
        raise CardineError(f"old skill link changed: {path}")
    return False


def _framework_skill_links(framework_root: Path, home: Path) -> tuple[tuple[str, Path, str, str], ...]:
    target_root = (framework_root / "skills").resolve()
    checkout = _run_git(framework_root, "rev-parse", "--show-toplevel")
    if checkout.returncode != 0 or Path(checkout.stdout.strip()).resolve() != framework_root.resolve():
        reason = "framework root is not the root of a Git checkout"
        return tuple((name, home / ".agents/skills" / name, "skipped", reason) for name in CODEX_SKILL_NAMES)
    missing_assets = [name for name in CODEX_SKILL_NAMES if not (target_root / name / "SKILL.md").is_file()]
    if missing_assets:
        reason = "framework checkout does not contain " + ", ".join(
            f"skills/{name}/SKILL.md" for name in missing_assets
        )
        return tuple((name, home / ".agents/skills" / name, "skipped", reason) for name in CODEX_SKILL_NAMES)
    links: list[tuple[str, Path, str, str]] = []
    for name in CODEX_SKILL_NAMES:
        path = home / ".agents/skills" / name
        target = target_root / name
        if not _safe_skill_parent(path):
            state, detail = "blocked", "skill parent is a symlink or a non-directory"
        elif path.is_symlink():
            observed = os.readlink(path)
            state = "ready" if path.resolve() == target else "conflict"
            detail = str(target) if state == "ready" else f"points to {observed} (expected {target})"
        elif path.exists():
            state = "blocked"
            detail = f"path exists as {('directory' if path.is_dir() else 'regular file')}"
        else:
            state = "missing"
            detail = f"create symlink to {target}"
        links.append((name, path, state, detail))
    for directory in (".agents/skills", ".codex/skills"):
        for name in OLD_SKILL_NAMES:
            path, target = home / directory / name, target_root / name
            if _owned_old_link(path, target):
                links.append((name, path, "remove", str(target)))
    return tuple(links)


def _aggregate_skill_state(links: tuple[tuple[str, Path, str, str], ...]) -> str:
    states = {state for _, _, state, _ in links}
    if "blocked" in states:
        return "blocked"
    if "conflict" in states:
        return "conflict"
    if states == {"skipped"}:
        return "skipped"
    if states & {"missing", "remove"}:
        return "missing"
    return "ready"


def _stale_codex_skill_warnings(home: Path) -> list[str]:
    return [
        f"stale Codex skill copy: {path}"
        for directory in (".codex/skills", ".agents/skills")
        for path in sorted((home / directory).glob("meridian-*"))
    ]


def _setup_codex_state(plan: CodexConfigurationPlan) -> str:
    if plan.status in ("ready", "repair-required", "repair-and-replace-required"):
        return plan.status
    text = plan.current_text or ""
    try:
        parsed = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return "blocked"
    permissions = parsed.get("permissions")
    existing = permissions.get(CODEX_PERMISSION_PROFILE) if isinstance(permissions, dict) else None
    if isinstance(existing, dict) and _codex_markers_intact(text):
        expected = _codex_expected_profile(plan.worktree_root)
        differing = [key for key in sorted(set(existing) | set(expected)) if existing.get(key) != expected.get(key)]
        roots = existing.get("workspace_roots")
        enabled_roots = (
            [value for value, allowed in roots.items() if allowed is True]
            if isinstance(roots, dict)
            else []
        )
        if differing == ["workspace_roots"] and len(enabled_roots) == 1:
            return "different-root"
        return "blocked"
    return "unconfigured"


def codex_profile_root_mismatch(config_path: Path, resolved_root: Path) -> str | None:
    if not config_path.is_file():
        return None
    try:
        parsed = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return None
    permissions = parsed.get("permissions")
    profile = permissions.get(CODEX_PERMISSION_PROFILE) if isinstance(permissions, dict) else None
    roots = profile.get("workspace_roots") if isinstance(profile, dict) else None
    if not isinstance(roots, dict):
        return None
    enabled = [Path(value).expanduser().resolve() for value, allowed in roots.items() if allowed is True]
    if len(enabled) == 1 and enabled[0] != resolved_root:
        return f"profile={enabled[0]} resolved={resolved_root}"
    return None
