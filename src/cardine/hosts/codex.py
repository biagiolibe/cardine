"""Helpers extracted from the legacy CLI; see the module split plan."""

from __future__ import annotations

from cardine.shared.errors import MeridianError
from cardine.shared.models import CODEX_MANAGED_BEGIN
from cardine.shared.models import CODEX_MANAGED_END
from cardine.shared.models import CODEX_PERMISSION_PROFILE
from cardine.shared.models import CodexConfigurationPlan
from cardine.shared.models import CodexUserRulesPlan
from cardine.stops.render import stop_error
from pathlib import Path
import ast
import copy
import difflib
import json
import os
import re
import tempfile
import tomllib


CODEX_USER_RULES = '''# MERIDIAN:BEGIN codex-user-rules v1
# Plain pushes to origin only. A flag placed after the refspec
# (`git push origin main --force`) is not caught by prefix rules; the GitHub
# ruleset on main and stable is the real guard against that form.
prefix_rule(pattern=["git", "push", "origin"], decision="allow")
prefix_rule(pattern=["git", "push", ["--force", "-f", "--force-with-lease", "--delete", "-d", "--mirror"]], decision="forbidden")
prefix_rule(pattern=["git", "push", "origin", ["--force", "-f", "--force-with-lease", "--delete", "-d", "--mirror"]], decision="forbidden")

# Meridian read-only and task-lifecycle commands. Commands that change machine
# or project configuration (setup/codex configure --apply, upgrade --apply,
# adopt, finalize-adoption, lock, generate-*) keep prompting.
prefix_rule(pattern=["meridian", ["--version", "self-check", "console", "audit", "profile", "locations", "project", "context", "adr", "budget", "report", "usage", "validation", "execution", "task", "review"]], decision="allow")
prefix_rule(pattern=["meridian", "worktree"], decision="allow")
prefix_rule(pattern=["meridian", "codex", ["doctor", "worktree-path"]], decision="allow")
prefix_rule(pattern=["meridian", ["upgrade", "setup"], "--check"], decision="allow")
prefix_rule(pattern=["meridian", "codex", "configure", "--check"], decision="allow")

# Read-only GitHub CLI. `gh api` stays unlisted: it can send writing requests.
prefix_rule(pattern=["gh", "release", ["list", "view"]], decision="allow")
prefix_rule(pattern=["gh", "run", ["list", "view", "watch"]], decision="allow")
prefix_rule(pattern=["gh", "pr", ["list", "view", "checks", "diff"]], decision="allow")
prefix_rule(pattern=["gh", "issue", ["list", "view"]], decision="allow")
prefix_rule(pattern=["gh", "repo", "view"], decision="allow")
prefix_rule(pattern=["gh", "auth", "status"], decision="allow")

# Git and system commands that do not discard work.
prefix_rule(pattern=["git", "write-tree"], decision="allow")
prefix_rule(pattern=["git", "fetch"], decision="allow")
prefix_rule(pattern=["git", "restore", "--staged"], decision="allow")
prefix_rule(pattern=["git", "rm"], decision="allow")
prefix_rule(pattern=["git", "rm", ["-f", "--force"]], decision="prompt")
prefix_rule(pattern=["ps"], decision="allow")
# MERIDIAN:END codex-user-rules
'''


def plan_codex_user_rules(path: Path) -> CodexUserRulesPlan:
    # Read bytes so CRLF and missing final newlines in foreign rules survive.
    text = path.read_bytes().decode("utf-8") if path.exists() else ""
    markers = list(re.finditer(r"(?m)^.*# MERIDIAN:(?:BEGIN|END) codex-user-rules[^\r\n]*", text))
    if markers:
        if (len(markers) != 2
            or not re.fullmatch(r"# MERIDIAN:BEGIN codex-user-rules v[0-9]+", markers[0].group())
            or markers[1].group() != "# MERIDIAN:END codex-user-rules"):
            raise stop_error("COMMAND_REFUSED", f"damaged Codex user-rules markers in {path}; repair the marker pair before setup")
        start, end = markers[0].start(), markers[1].end()
        if text[end:end + 2] == "\r\n":
            end += 2
        elif text[end:end + 1] == "\n":
            end += 1
        proposed = text[:start] + CODEX_USER_RULES + text[end:]
        status = "ready" if proposed == text else "stale"
    else:
        proposed = text + ("\n" if text and not text.endswith("\n") else "") + CODEX_USER_RULES
        status = "missing"
    warnings = []
    # Inspect literal calls without executing user-owned policy. AST parsing
    # handles multiline calls, comments, and either keyword order.
    try:
        calls = [node for node in ast.walk(ast.parse(text)) if isinstance(node, ast.Call)]
    except SyntaxError:
        calls = []
    lines = text.splitlines(keepends=True)
    for call in sorted(calls, key=lambda node: node.lineno):
        if not isinstance(call.func, ast.Name) or call.func.id != "prefix_rule":
            continue
        offset = sum(len(line) for line in lines[:call.lineno - 1])
        if markers and start <= offset < end:
            continue
        keywords = {item.arg: item.value for item in call.keywords}
        try:
            pattern = ast.literal_eval(keywords["pattern"])
            decision = ast.literal_eval(keywords["decision"])
        except (KeyError, ValueError, SyntaxError):
            continue
        if decision == "allow" and pattern in (["meridian"], ["git", "push"]):
            warnings.append(f"{path}:{call.lineno}: broad allow rule {pattern!r} permits commands outside Meridian's prompt coverage")
    return CodexUserRulesPlan(path, status, text, None if status == "ready" else proposed, tuple(warnings))


def apply_codex_user_rules(plan: CodexUserRulesPlan) -> bool:
    current = plan.path.read_bytes().decode("utf-8") if plan.path.exists() else ""
    if current != plan.current_text:
        raise MeridianError("Codex user rules changed since planning; rerun --check")
    if plan.proposed_text is None:
        return False
    plan.path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".meridian-rules-", dir=plan.path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(plan.proposed_text.encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, plan.path)
    finally:
        if os.path.exists(name):
            os.unlink(name)
    return True


def _toml_quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _codex_managed_block(worktree_root: Path) -> str:
    root = str(worktree_root.expanduser().resolve())
    return "\n".join(
        [
            CODEX_MANAGED_BEGIN,
            f'default_permissions = "{CODEX_PERMISSION_PROFILE}"',
            "",
            f"[permissions.{CODEX_PERMISSION_PROFILE}]",
            'description = "Workspace access plus Meridian-managed task worktrees."',
            'extends = ":workspace"',
            "",
            f"[permissions.{CODEX_PERMISSION_PROFILE}.workspace_roots]",
            f"{_toml_quote(root)} = true",
            CODEX_MANAGED_END,
        ]
    )


def _replace_codex_managed_block(text: str, block: str) -> str:
    start = text.find(CODEX_MANAGED_BEGIN)
    if start >= 0:
        end = text.find(CODEX_MANAGED_END, start) + len(CODEX_MANAGED_END)
        text = text[:start] + text[end:]

    table = re.search(r"(?m)^\s*\[", text)
    insertion = table.start() if table is not None else len(text)
    prefix = text[:insertion].rstrip("\n")
    suffix = text[insertion:].strip("\n")
    parts = [part for part in (prefix, block, suffix) if part]
    return "\n\n".join(parts) + "\n"


def _without_top_level_default_permissions(text: str) -> str:
    """Remove the root selection while leaving comments and profile tables intact."""
    lines = text.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if line.lstrip().startswith("["):
            break
        if re.match(r"^\s*default_permissions\s*=", line):
            del lines[index]
            break
    return "".join(lines)


def _codex_expected_profile(root: Path) -> dict[str, object]:
    return {
        "description": "Workspace access plus Meridian-managed task worktrees.",
        "extends": ":workspace",
        "workspace_roots": {str(root): True},
    }


def _codex_profile_divergence(parsed: dict[str, object], root: Path) -> list[str]:
    """Name every field where the parsed profile differs from the one expected profile."""
    permissions = parsed.get("permissions")
    profile = permissions.get(CODEX_PERMISSION_PROFILE) if isinstance(permissions, dict) else None
    if not isinstance(profile, dict):
        return ["profile shape"]
    expected = _codex_expected_profile(root)
    differences = [
        key for key in sorted(set(profile) | set(expected)) if profile.get(key) != expected.get(key)
    ]
    if parsed.get("default_permissions") != CODEX_PERMISSION_PROFILE:
        differences.append("default_permissions")
    return differences


def _codex_header_patterns() -> tuple[re.Pattern[str], re.Pattern[str]]:
    name = re.escape(CODEX_PERMISSION_PROFILE)
    quoted = rf'(?:{name}|"{name}")'
    return (
        re.compile(rf"^\s*\[\s*permissions\s*\.\s*{quoted}\s*\]\s*(?:#.*)?$"),
        re.compile(rf"^\s*\[\s*permissions\s*\.\s*{quoted}\s*\.\s*workspace_roots\s*\]\s*(?:#.*)?$"),
    )


def _codex_markers_intact(text: str) -> bool:
    """Return whether one ordered marker pair encloses every managed piece present.

    The root selection, the profile table, and its workspace_roots table must each
    be inside the span or absent; a piece left outside means the host moved part of
    the block and ownership can only be recovered semantically.
    """
    if text.count(CODEX_MANAGED_BEGIN) != 1 or text.count(CODEX_MANAGED_END) != 1:
        return False
    start = text.index(CODEX_MANAGED_BEGIN)
    end = text.index(CODEX_MANAGED_END)
    if start >= end:
        return False
    profile_header, roots_header = _codex_header_patterns()
    selection = re.compile(r"^\s*default_permissions\s*=")
    offset = 0
    in_table = False
    inside_profile = False
    for line in text.splitlines(keepends=True):
        bare = line.rstrip("\r\n")
        within = start <= offset < end
        if bare.lstrip().startswith("["):
            in_table = True
            if (profile_header.match(bare) or roots_header.match(bare)) and not within:
                return False
            inside_profile = inside_profile or (within and bool(profile_header.match(bare)))
        elif not in_table and selection.match(bare) and not within:
            return False
        offset += len(line)
    return inside_profile


def _without_codex_profile_text(text: str) -> str:
    """Remove ownership markers, the root selection, and the managed profile tables.

    Raises MeridianError unless each managed table header appears exactly once as a
    plain table header, so unusual serializations are never edited heuristically.
    """
    profile_header, roots_header = _codex_header_patterns()
    marker = re.compile(r"^\s*#\s*MERIDIAN:(?:BEGIN|END)\s+worktree-permissions\b.*$")
    lines = text.splitlines(keepends=True)
    if sum(1 for line in lines if profile_header.match(line.rstrip("\r\n"))) != 1 or sum(
        1 for line in lines if roots_header.match(line.rstrip("\r\n"))
    ) != 1:
        raise MeridianError(
            f"Codex permission profile {CODEX_PERMISSION_PROFILE!r} is not serialized as exactly one plain "
            "profile table and one workspace_roots table; reconcile it manually"
        )
    kept: list[str] = []
    skipping = False
    for line in lines:
        bare = line.rstrip("\r\n")
        if bare.lstrip().startswith("["):
            skipping = bool(profile_header.match(bare) or roots_header.match(bare))
            if skipping:
                continue
        if skipping or marker.match(bare):
            continue
        kept.append(line)
    return _without_top_level_default_permissions("".join(kept))


def _plan_codex_ownership_repair(
    config_path: Path, text: str, parsed: dict[str, object], root: Path
) -> CodexConfigurationPlan:
    """Plan an ownership-metadata repair, or raise unless the profile is an exact semantic match."""
    differences = _codex_profile_divergence(parsed, root)
    if differences:
        raise MeridianError(
            f"Codex permission profile {CODEX_PERMISSION_PROFILE!r} exists without intact Meridian ownership "
            f"markers and differs from the expected profile in: {', '.join(differences)}; reconcile it manually"
        )
    stripped = _without_codex_profile_text(text)
    proposed = _replace_codex_managed_block(stripped, _codex_managed_block(root))
    try:
        reparsed = tomllib.loads(proposed)
    except tomllib.TOMLDecodeError as error:
        raise MeridianError(f"proposed Codex ownership repair would be invalid: {error}") from error
    if reparsed != parsed:
        raise MeridianError(
            "Codex ownership repair would change effective configuration beyond Meridian's markers; "
            "reconcile it manually"
        )
    return CodexConfigurationPlan(
        "repair-required",
        config_path,
        root,
        "permission-profile",
        proposed,
        "ownership-metadata-repair: the effective profile is identical; explicit --apply restores only "
        "Meridian's ownership markers and block position",
        text,
    )


def _plan_codex_ownership_repair_and_root_replacement(
    config_path: Path, text: str, parsed: dict[str, object], root: Path
) -> CodexConfigurationPlan | None:
    """Plan the one safe combined recovery, or return None for a normal refusal.

    Lost comments are not ownership evidence.  The profile's exact Meridian
    shape is, but only when it contains one enabled root that differs from the
    requested root.  Keep this predicate deliberately narrower than parsed
    divergence so foreign grants and unusual shapes cannot be adopted.
    """
    permissions = parsed.get("permissions")
    profile = permissions.get(CODEX_PERMISSION_PROFILE) if isinstance(permissions, dict) else None
    expected = _codex_expected_profile(root)
    if (
        parsed.get("default_permissions") != CODEX_PERMISSION_PROFILE
        or not isinstance(profile, dict)
        or set(profile) != set(expected)
        or profile.get("description") != expected["description"]
        or profile.get("extends") != expected["extends"]
    ):
        return None
    roots = profile.get("workspace_roots")
    if not isinstance(roots, dict) or len(roots) != 1 or list(roots.values()) != [True]:
        return None
    if roots == expected["workspace_roots"]:
        return None

    stripped = _without_codex_profile_text(text)
    proposed = _replace_codex_managed_block(stripped, _codex_managed_block(root))
    try:
        reparsed = tomllib.loads(proposed)
    except tomllib.TOMLDecodeError as error:
        raise MeridianError(f"proposed Codex repair and root replacement would be invalid: {error}") from error
    expected_parsed = copy.deepcopy(parsed)
    expected_parsed["permissions"][CODEX_PERMISSION_PROFILE]["workspace_roots"] = expected["workspace_roots"]  # type: ignore[index]
    if reparsed != expected_parsed:
        raise MeridianError(
            "Codex repair and root replacement would change effective configuration beyond the one root value; "
            "reconcile it manually"
        )
    return CodexConfigurationPlan(
        "repair-and-replace-required",
        config_path,
        root,
        "permission-profile",
        proposed,
        "ownership-metadata-repair-and-root-replacement: explicit --apply restores Meridian's ownership "
        "metadata and replaces the one configured worktree root",
        text,
    )


def plan_codex_configuration(
    config_path: Path,
    worktree_root: Path,
    requirements_path: Path | None = None,
) -> CodexConfigurationPlan:
    root = worktree_root.expanduser().resolve()
    if root == Path(root.anchor) or root == Path.home().resolve():
        raise MeridianError("worktree root must not authorize the filesystem root or the user's home")
    text = config_path.read_text(encoding="utf-8") if config_path.is_file() else ""
    try:
        parsed = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise MeridianError(f"malformed Codex TOML at {config_path}: {error}") from error
    if "sandbox_mode" in parsed or "sandbox_workspace_write" in parsed:
        raise MeridianError("legacy Codex sandbox settings conflict with permission profiles")
    if requirements_path is not None and requirements_path.is_file():
        try:
            requirements = tomllib.loads(requirements_path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as error:
            raise MeridianError(f"malformed managed Codex requirements at {requirements_path}: {error}") from error
        allowed = requirements.get("allowed_permission_profiles")
        if isinstance(allowed, dict) and allowed.get(CODEX_PERMISSION_PROFILE) is not True:
            raise MeridianError(
                f"managed Codex requirements do not allow permission profile {CODEX_PERMISSION_PROFILE!r}"
            )
    existing_profile = parsed.get("permissions", {}).get(CODEX_PERMISSION_PROFILE)
    managed_present = CODEX_MANAGED_BEGIN in text or CODEX_MANAGED_END in text
    if existing_profile is not None and not _codex_markers_intact(text):
        replacement = _plan_codex_ownership_repair_and_root_replacement(config_path, text, parsed, root)
        if replacement is not None:
            return replacement
        return _plan_codex_ownership_repair(config_path, text, parsed, root)
    if managed_present and not _codex_markers_intact(text):
        raise MeridianError("Codex configuration contains an incomplete or damaged Meridian-managed block")
    base_text = text
    if "default_permissions" in parsed and not managed_present:
        base_text = _without_top_level_default_permissions(text)
    proposed = _replace_codex_managed_block(base_text, _codex_managed_block(root))
    try:
        tomllib.loads(proposed)
    except tomllib.TOMLDecodeError as error:
        raise MeridianError(f"proposed Codex configuration would be invalid: {error}") from error
    current_model = "permission-profile" if "default_permissions" in parsed or "permissions" in parsed else "unconfigured"
    if proposed == text:
        return CodexConfigurationPlan("ready", config_path, root, current_model, None, "requested profile is already effective")
    return CodexConfigurationPlan("approval-required", config_path, root, current_model, proposed, "explicit --apply is required", text)


def print_codex_configuration_plan(plan: CodexConfigurationPlan) -> None:
    print(f"status: {plan.status}")
    print(f"config: {plan.config_path}")
    print(f"permission-model: {plan.current_model}")
    print(f"worktree-root: {plan.worktree_root}")
    print(f"detail: {plan.detail}")
    if plan.status in ("repair-required", "repair-and-replace-required") and plan.proposed_text is not None and plan.current_text is not None:
        suffix = "effective configuration is unchanged" if plan.status == "repair-required" else "repairs ownership metadata and replaces the worktree root"
        print(f"proposed-change (unified diff; {suffix}):")
        print(
            "".join(
                difflib.unified_diff(
                    plan.current_text.splitlines(keepends=True),
                    plan.proposed_text.splitlines(keepends=True),
                    fromfile=f"{plan.config_path.name} (current)",
                    tofile=f"{plan.config_path.name} (repaired)",
                )
            ),
            end="",
        )
    elif plan.proposed_text is not None:
        print("proposed-change:")
        print(_codex_managed_block(plan.worktree_root))


def _write_exclusive_backup(path: Path, backup: Path) -> None:
    """Copy the current bytes to a new owner-only file, never replacing an existing backup."""
    descriptor = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(path.read_bytes())
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        try:
            backup.unlink()
        except OSError:
            pass
        raise


def _unused_repair_backup(path: Path) -> Path:
    candidate = path.with_name(path.name + ".meridian-repair.bak")
    index = 0
    while candidate.exists() or candidate.is_symlink():
        index += 1
        candidate = path.with_name(f"{path.name}.meridian-repair.{index}.bak")
    return candidate


def apply_codex_configuration(plan: CodexConfigurationPlan) -> bool:
    if plan.proposed_text is None:
        return False
    path = plan.config_path
    path.parent.mkdir(parents=True, exist_ok=True)
    if plan.status in ("repair-required", "repair-and-replace-required"):
        if not path.is_file() or path.read_text(encoding="utf-8") != plan.current_text:
            raise MeridianError("Codex configuration changed since it was planned; rerun --check")
        _write_exclusive_backup(path, _unused_repair_backup(path))
    else:
        backup = path.with_name(path.name + ".meridian.bak")
        if path.exists() and not backup.exists():
            _write_exclusive_backup(path, backup)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.chmod(temporary, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(plan.proposed_text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise
    return True
