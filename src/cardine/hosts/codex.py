"""Helpers extracted from the legacy CLI; see the module split plan."""

from __future__ import annotations

from cardine.hosts import permissions
from cardine.hosts.effects import changed, host_operation
from cardine.lifecycle.file_operation import Operation
from cardine.shared import atomic
from cardine.shared.errors import CardineError
from cardine.shared.models import CODEX_MANAGED_BEGIN
from cardine.shared.models import CODEX_MANAGED_END
from cardine.shared.models import CODEX_PERMISSION_PROFILE
from cardine.shared.models import CodexConfigurationPlan
from cardine.shared.models import CodexUserRulesPlan
from cardine.stops.render import stop_error
from dataclasses import dataclass
from pathlib import Path
import ast
import copy
import difflib
import json
import re
import tomllib


LEGACY_CODEX_USER_RULES = '''# MERIDIAN:BEGIN codex-user-rules v1
# Plain pushes to origin only. A flag placed after the refspec
# (`git push origin main --force`) is not caught by prefix rules; the GitHub
# ruleset on main and stable is the real guard against that form.
prefix_rule(pattern=["git", "push", "origin"], decision="allow")
prefix_rule(pattern=["git", "push", ["--force", "-f", "--force-with-lease", "--delete", "-d", "--mirror"]], decision="forbidden")
prefix_rule(pattern=["git", "push", "origin", ["--force", "-f", "--force-with-lease", "--delete", "-d", "--mirror"]], decision="forbidden")

# Cardine read-only and task-lifecycle commands. Commands that change machine
# or project configuration (setup/codex configure --apply, upgrade --apply,
# lock, generate-*) keep prompting.
prefix_rule(pattern=["cardine", ["--version", "self-check", "console", "audit", "profile", "locations", "project", "context", "adr", "report", "usage", "validation", "execution", "task", "review"]], decision="allow")
prefix_rule(pattern=["cardine", "worktree"], decision="allow")
prefix_rule(pattern=["cardine", "codex", ["doctor", "worktree-path"]], decision="allow")
prefix_rule(pattern=["cardine", ["upgrade", "setup"], "--check"], decision="allow")
prefix_rule(pattern=["cardine", "codex", "configure", "--check"], decision="allow")

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


CODEX_USER_RULES = LEGACY_CODEX_USER_RULES.replace('# MERIDIAN:', '# CARDINE:')
PREVIOUS_CODEX_USER_RULES = CODEX_USER_RULES
CODEX_USER_RULES = (PREVIOUS_CODEX_USER_RULES.replace('codex-user-rules v1', 'codex-user-rules v2')
                    .replace('"execution", "task", "review"', '"execution", "task", "review", "run", "status"'))


def plan_codex_user_rules(path: Path, *, legacy_tool_installed: bool = False) -> CodexUserRulesPlan:
    # Read bytes so CRLF and missing final newlines in foreign rules survive.
    text = path.read_bytes().decode("utf-8") if path.exists() else ""
    markers = list(re.finditer(r"(?m)^.*# CARDINE:(?:BEGIN|END) codex-user-rules[^\r\n]*", text))
    if markers:
        if (len(markers) != 2
            or not re.fullmatch(r"# CARDINE:BEGIN codex-user-rules v[0-9]+", markers[0].group())
            or markers[1].group() != "# CARDINE:END codex-user-rules"):
            raise stop_error("COMMAND_REFUSED", f"damaged Codex user-rules markers in {path}; repair the marker pair before setup")
        start, end = markers[0].start(), markers[1].end()
        if text[end:end + 2] == "\r\n":
            end += 2
        elif text[end:end + 1] == "\n":
            end += 1
        if text[start:end] == PREVIOUS_CODEX_USER_RULES:
            proposed = text[:start] + CODEX_USER_RULES + text[end:]
            status = "stale"
        elif text[start:end] == CODEX_USER_RULES:
            proposed = text
            status = "ready"
        else:
            raise CardineError(f"Codex user-rules block in {path} has changed; reconcile it manually")
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
        if decision == "allow" and pattern in (["cardine"], ["git", "push"]):
            warnings.append(f"{path}:{call.lineno}: broad allow rule {pattern!r} permits commands outside Cardine's prompt coverage")
    legacy_path = path.with_name("default.rules") if path.name == "cardine.rules" else None
    legacy_text = legacy_path.read_bytes().decode("utf-8") if legacy_path and legacy_path.exists() else ""
    legacy_proposed = None
    if legacy_path and legacy_text.count(LEGACY_CODEX_USER_RULES) == 1 and legacy_text.count("# MERIDIAN:BEGIN codex-user-rules") == 1 and legacy_text.count("# MERIDIAN:END codex-user-rules") == 1:
        if legacy_tool_installed:
            # The retired tool still reads this block; removing it would change its policy.
            warnings.append(f"{legacy_path}: the known legacy rules block is kept byte-identical while the legacy tool stays installed")
        else:
            legacy_proposed = legacy_text.replace(LEGACY_CODEX_USER_RULES, "", 1)
    elif legacy_path and "# MERIDIAN:" in legacy_text and "codex-user-rules" in legacy_text:
        warnings.append(f"{legacy_path}: legacy rules differ from the known owned block; preserved")
    return CodexUserRulesPlan(path, status, text, None if status == "ready" else proposed,
                              tuple(warnings), legacy_path, legacy_text, legacy_proposed)


def apply_codex_user_rules(plan: CodexUserRulesPlan, operation: Operation | None = None) -> bool:
    with host_operation("codex-rules", plan.path, operation) as active:
        active.guard(plan.path)
        if plan.legacy_path is not None:
            active.guard(plan.legacy_path)
            current_legacy = plan.legacy_path.read_bytes().decode("utf-8") if plan.legacy_path.exists() else ""
            if current_legacy != plan.legacy_text:
                raise CardineError("legacy Codex user rules changed since planning; rerun --check")
        current = plan.path.read_bytes().decode("utf-8") if plan.path.exists() else ""
        if current != plan.current_text:
            raise CardineError("Codex user rules changed since planning; rerun --check")
        wrote = False
        if plan.proposed_text is not None:
            active.replace("codex-rules", plan.path, plan.proposed_text.encode("utf-8"), mode=0o600)
            wrote = True
        if plan.legacy_proposed is not None and plan.legacy_path is not None:
            current_legacy = plan.legacy_path.read_bytes().decode("utf-8") if plan.legacy_path.exists() else ""
            if current_legacy != plan.legacy_text:
                raise CardineError("legacy Codex user rules changed since planning; rerun --check")
            active.replace("codex-legacy-rules", plan.legacy_path, plan.legacy_proposed.encode("utf-8"), mode=0o600)
            wrote = True
        return changed(active, wrote)


def _toml_quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _codex_managed_block(worktree_root: Path, legacy_root: Path | None = None) -> str:
    root = str(worktree_root.expanduser().resolve())
    return "\n".join(
        [
            CODEX_MANAGED_BEGIN,
            f'default_permissions = "{CODEX_PERMISSION_PROFILE}"',
            "",
            f"[permissions.{CODEX_PERMISSION_PROFILE}]",
            'description = "Workspace access plus Cardine-managed task worktrees."',
            'extends = ":workspace"',
            "",
            f"[permissions.{CODEX_PERMISSION_PROFILE}.workspace_roots]",
            *[f"{_toml_quote(value)} = true" for value in dict.fromkeys(
                [root] + ([str(legacy_root.resolve())] if legacy_root is not None else []))],
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


def _codex_expected_profile(root: Path, legacy_root: Path | None = None) -> dict[str, object]:
    return {
        "description": "Workspace access plus Cardine-managed task worktrees.",
        "extends": ":workspace",
        "workspace_roots": {str(path): True for path in (root, legacy_root) if path is not None},
    }


def _codex_profile_divergence(parsed: dict[str, object], root: Path, legacy_root: Path | None = None) -> list[str]:
    """Name every field where the parsed profile differs from the one expected profile."""
    permissions = parsed.get("permissions")
    profile = permissions.get(CODEX_PERMISSION_PROFILE) if isinstance(permissions, dict) else None
    if not isinstance(profile, dict):
        return ["profile shape"]
    expected = _codex_expected_profile(root, legacy_root)
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

    Raises CardineError unless each managed table header appears exactly once as a
    plain table header, so unusual serializations are never edited heuristically.
    """
    profile_header, roots_header = _codex_header_patterns()
    marker = re.compile(r"^\s*#\s*CARDINE:(?:BEGIN|END)\s+worktree-permissions\b.*$")
    lines = text.splitlines(keepends=True)
    if sum(1 for line in lines if profile_header.match(line.rstrip("\r\n"))) != 1 or sum(
        1 for line in lines if roots_header.match(line.rstrip("\r\n"))
    ) != 1:
        raise CardineError(
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
        if skipping and bare.lstrip().startswith("#") and not marker.match(bare):
            raise CardineError("Codex profile contains comments of unknown ownership; reconcile it manually")
        if skipping or marker.match(bare):
            continue
        kept.append(line)
    return _without_top_level_default_permissions("".join(kept))


def _plan_codex_ownership_repair(
    config_path: Path, text: str, parsed: dict[str, object], root: Path, legacy_root: Path | None = None
) -> CodexConfigurationPlan:
    """Plan an ownership-metadata repair, or raise unless the profile is an exact semantic match."""
    differences = _codex_profile_divergence(parsed, root, legacy_root)
    if differences:
        raise CardineError(
            f"Codex permission profile {CODEX_PERMISSION_PROFILE!r} exists without intact Cardine ownership "
            f"markers and differs from the expected profile in: {', '.join(differences)}; reconcile it manually"
        )
    stripped = _without_codex_profile_text(text)
    proposed = _replace_codex_managed_block(stripped, _codex_managed_block(root, legacy_root))
    try:
        reparsed = tomllib.loads(proposed)
    except tomllib.TOMLDecodeError as error:
        raise CardineError(f"proposed Codex ownership repair would be invalid: {error}") from error
    if reparsed != parsed:
        raise CardineError(
            "Codex ownership repair would change effective configuration beyond Cardine's markers; "
            "reconcile it manually"
        )
    return CodexConfigurationPlan(
        "repair-required",
        config_path,
        root,
        "permission-profile",
        proposed,
        "ownership-metadata-repair: the effective profile is identical; explicit --apply restores only "
        "Cardine's ownership markers and block position",
        text,
    )


def _plan_codex_ownership_repair_and_root_replacement(
    config_path: Path, text: str, parsed: dict[str, object], root: Path, legacy_root: Path | None = None
) -> CodexConfigurationPlan | None:
    """Plan the one safe combined recovery, or return None for a normal refusal.

    Lost comments are not ownership evidence.  The profile's exact Cardine
    shape is, but only when it contains one enabled root that differs from the
    requested root.  Keep this predicate deliberately narrower than parsed
    divergence so foreign grants and unusual shapes cannot be adopted.
    """
    permissions = parsed.get("permissions")
    profile = permissions.get(CODEX_PERMISSION_PROFILE) if isinstance(permissions, dict) else None
    expected = _codex_expected_profile(root, legacy_root)
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
    proposed = _replace_codex_managed_block(stripped, _codex_managed_block(root, legacy_root))
    try:
        reparsed = tomllib.loads(proposed)
    except tomllib.TOMLDecodeError as error:
        raise CardineError(f"proposed Codex repair and root replacement would be invalid: {error}") from error
    expected_parsed = copy.deepcopy(parsed)
    expected_parsed["permissions"][CODEX_PERMISSION_PROFILE]["workspace_roots"] = expected["workspace_roots"]  # type: ignore[index]
    if reparsed != expected_parsed:
        raise CardineError(
            "Codex repair and root replacement would change effective configuration beyond the one root value; "
            "reconcile it manually"
        )
    return CodexConfigurationPlan(
        "repair-and-replace-required",
        config_path,
        root,
        "permission-profile",
        proposed,
        "ownership-metadata-repair-and-root-replacement: explicit --apply restores Cardine's ownership "
        "metadata and replaces the one configured worktree root",
        text,
    )


def plan_codex_configuration(
    config_path: Path,
    worktree_root: Path,
    requirements_path: Path | None = None,
    *, legacy_root: Path | None = None, legacy_installed: bool = False,
) -> CodexConfigurationPlan:
    root = worktree_root.expanduser().resolve()
    expected_legacy = legacy_root if legacy_installed else None
    if root == Path(root.anchor) or root == Path.home().resolve():
        raise CardineError("worktree root must not authorize the filesystem root or the user's home")
    text = config_path.read_text(encoding="utf-8") if config_path.is_file() else ""
    if requirements_path is not None and requirements_path.is_file():
        try:
            requirements = tomllib.loads(requirements_path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as error:
            raise CardineError(f"malformed managed Codex requirements at {requirements_path}: {error}") from error
        allowed = requirements.get("allowed_permission_profiles")
        if isinstance(allowed, dict) and allowed.get(CODEX_PERMISSION_PROFILE) is not True:
            raise CardineError(f"managed Codex requirements do not allow permission profile {CODEX_PERMISSION_PROFILE!r}")
    legacy_begin = "# MERIDIAN:BEGIN worktree-permissions v1"
    legacy_end = "# MERIDIAN:END worktree-permissions"
    if legacy_begin in text and CODEX_MANAGED_BEGIN in text:
        def span(begin: str, end: str) -> str:
            if text.count(begin) != 1 or text.count(end) != 1 or text.find(end) < text.find(begin):
                raise CardineError("both profiles have damaged ownership markers; reconcile them manually")
            return text[text.index(begin):text.index(end) + len(end)]
        old = span(legacy_begin, legacy_end)
        current = span(CODEX_MANAGED_BEGIN, CODEX_MANAGED_END)
        try:
            old_parsed, current_parsed = tomllib.loads(old), tomllib.loads(current)
            old_roots = old_parsed["permissions"]["meri" + "dian-worktrees"]["workspace_roots"]
            current_roots = current_parsed["permissions"][CODEX_PERMISSION_PROFILE]["workspace_roots"]
            old_root = Path(next(iter(old_roots)))
            current_paths = list(current_roots)
            known_old = (_codex_managed_block(old_root).replace(CODEX_MANAGED_BEGIN, legacy_begin)
                         .replace(CODEX_MANAGED_END, legacy_end).replace(CODEX_PERMISSION_PROFILE, "meri" + "dian-worktrees")
                         .replace("Cardine-managed", "Meridian-managed"))
            known_current = _codex_managed_block(Path(current_paths[0]), Path(current_paths[1]) if len(current_paths) == 2 else None)
            if (len(old_roots) != 1 or old_roots[str(old_root)] is not True
                or (legacy_root is not None and old_root != legacy_root)
                or len(current_paths) not in (1, 2) or current != known_current or old != known_old
                or (len(current_paths) == 2 and set(current_paths) != {str(root), str(legacy_root)})):
                raise ValueError("unknown profile")
            proposed = text.replace(current, "", 1).replace(old, _codex_managed_block(root, expected_legacy), 1)
            proposed_parsed = tomllib.loads(proposed)
            if "sandbox_mode" in proposed_parsed or "sandbox_workspace_write" in proposed_parsed:
                raise ValueError("legacy sandbox settings")
        except (KeyError, IndexError, TypeError, ValueError, StopIteration, tomllib.TOMLDecodeError) as error:
            raise CardineError("both profiles are not known owned blocks; reconcile them manually") from error
        return CodexConfigurationPlan("approval-required", config_path, root, "permission-profile", proposed,
                                      "remove the known legacy profile and restore the Cardine profile", text)
    try:
        parsed = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise CardineError(f"malformed Codex TOML at {config_path}: {error}") from error
    if "sandbox_mode" in parsed or "sandbox_workspace_write" in parsed:
        raise CardineError("legacy Codex sandbox settings conflict with permission profiles")
    permissions = parsed.get("permissions", {})
    if not isinstance(permissions, dict):
        raise CardineError("Codex permissions must be a table")
    existing_profile = permissions.get(CODEX_PERMISSION_PROFILE)
    legacy_name = "meridian-worktrees"
    legacy_begin = "# MERIDIAN:BEGIN worktree-permissions v1"
    legacy_end = "# MERIDIAN:END worktree-permissions"
    legacy_profile = permissions.get(legacy_name)
    if legacy_profile is not None or legacy_begin in text or legacy_end in text:
        if existing_profile is not None or CODEX_MANAGED_BEGIN in text or CODEX_MANAGED_END in text:
            raise CardineError("both legacy and Cardine permission profiles exist; reconcile them manually")
        roots = legacy_profile.get("workspace_roots") if isinstance(legacy_profile, dict) else None
        if not isinstance(roots, dict) or len(roots) != 1 or list(roots.values()) != [True]:
            raise CardineError("legacy Codex profile has unknown ownership or changed roots; reconcile it manually")
        block_root = Path(next(iter(roots)))
        if legacy_root is not None and block_root != legacy_root:
            raise CardineError("legacy Codex profile root differs from the resolved root; reconcile it manually")
        legacy_block = (_codex_managed_block(block_root)
                        .replace(CODEX_MANAGED_BEGIN, legacy_begin)
                        .replace(CODEX_MANAGED_END, legacy_end)
                        .replace(CODEX_PERMISSION_PROFILE, legacy_name)
                        .replace("Cardine-managed", "Meridian-managed"))
        if text.count(legacy_block) != 1 or parsed.get("default_permissions") != legacy_name:
            raise CardineError("legacy Codex profile has changed or lost ownership markers; reconcile it manually")
        proposed = text.replace(legacy_block, _codex_managed_block(root, expected_legacy), 1)
        try:
            tomllib.loads(proposed)
        except tomllib.TOMLDecodeError as error:
            raise CardineError(f"proposed Codex migration would be invalid: {error}") from error
        return CodexConfigurationPlan("approval-required", config_path, root, "permission-profile",
                                      proposed, "migrate the owned Meridian profile", text)
    managed_present = CODEX_MANAGED_BEGIN in text or CODEX_MANAGED_END in text
    if existing_profile is not None and not _codex_markers_intact(text):
        replacement = _plan_codex_ownership_repair_and_root_replacement(config_path, text, parsed, root, expected_legacy)
        if replacement is not None:
            return replacement
        return _plan_codex_ownership_repair(config_path, text, parsed, root, expected_legacy)
    if managed_present and not _codex_markers_intact(text):
        raise CardineError("Codex configuration contains an incomplete or damaged Cardine-managed block")
    if existing_profile is not None and managed_present:
        roots = existing_profile.get("workspace_roots") if isinstance(existing_profile, dict) else None
        enabled = [name for name, value in roots.items() if value is True] if isinstance(roots, dict) else []
        allowed = {str(root)} | ({str(legacy_root)} if legacy_root is not None else set())
        if len(enabled) not in (1, 2) or (len(enabled) == 2 and set(enabled) != allowed):
            raise CardineError("Cardine Codex profile has changed; reconcile it manually")
        old_block = _codex_managed_block(Path(enabled[0]), Path(enabled[1]) if len(enabled) == 2 else None)
        if text.count(old_block) != 1:
            raise CardineError("Cardine Codex profile block has changed; reconcile it manually")
        if old_block == _codex_managed_block(root, expected_legacy) and set(roots) == set(enabled):
            return CodexConfigurationPlan("ready", config_path, root, "permission-profile", None,
                                          "requested profile is already effective")
    base_text = text
    if "default_permissions" in parsed and not managed_present:
        base_text = _without_top_level_default_permissions(text)
    proposed = _replace_codex_managed_block(base_text, _codex_managed_block(root, expected_legacy))
    try:
        tomllib.loads(proposed)
    except tomllib.TOMLDecodeError as error:
        raise CardineError(f"proposed Codex configuration would be invalid: {error}") from error
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
        print(plan.proposed_text, end="" if plan.proposed_text.endswith("\n") else "\n")


def _write_exclusive_backup(path: Path, backup: Path) -> None:
    """Copy the current bytes to a new owner-only file, never replacing an existing backup."""
    atomic.create_exclusive(backup, path.read_bytes())


def _unused_repair_backup(path: Path) -> Path:
    candidate = path.with_name(path.name + ".cardine-repair.bak")
    index = 0
    while candidate.exists() or candidate.is_symlink():
        index += 1
        candidate = path.with_name(f"{path.name}.cardine-repair.{index}.bak")
    return candidate


def _configuration_backup(plan: CodexConfigurationPlan) -> Path | None:
    path = plan.config_path
    if not path.exists():
        return None
    if plan.status in ("repair-required", "repair-and-replace-required"):
        return _unused_repair_backup(path)
    backup = path.with_name(path.name + ".cardine.bak")
    return backup if not backup.exists() and not backup.is_symlink() else _unused_repair_backup(path)


def apply_codex_configuration(plan: CodexConfigurationPlan, operation: Operation | None = None) -> bool:
    path = plan.config_path
    with host_operation("codex-config", path, operation) as active:
        if plan.proposed_text is None:
            return changed(active, False)
        repair = plan.status in ("repair-required", "repair-and-replace-required")
        actual = path.read_text(encoding="utf-8") if path.is_file() else ""
        if (repair and not path.is_file()) or actual != plan.current_text:
            raise CardineError("Codex configuration changed since it was planned; rerun --check")
        backup = _configuration_backup(plan)
        active.replace("codex-config", path, plan.proposed_text.encode("utf-8"), backup=backup, mode=0o600)
        return True


# -- Role policy and profiles ---------------------------------------------------
#
# The two role profiles are separate from the shared `cardine-worktrees` base
# profile and never replace it or `default_permissions`. Only keys the host
# contract documents are written (`description`, `extends`, `workspace_roots`);
# protected paths and role actions are carried by the policy and its digest, so
# only a host-evaluated proof of that digest can make a role profile enforced (D3).
# Role rules live in a Cardine-owned directory that Codex does not load by
# itself: Codex rule files are global, so a `forbidden` rule there would also
# bind the coordinator that `Proceed with` authorizes to push `main`. The launch
# adapter hands the file to the role session.

ROLE_RULES_DIRECTORY = "cardine-roles"
_FORBIDDEN_FLAGS = ["--force", "-f", "--force-with-lease", "--delete", "-d", "--mirror"]
_REVIEWER_GIT = ["push", "add", "commit", "merge", "rebase", "reset", "checkout"]


@dataclass(frozen=True)
class CodexRolePlan:
    status: str  # ready | approval-required | blocked
    config_path: Path
    detail: str
    config_text: str
    proposed_config: str | None
    rules: tuple  # ((role, path, current_text, proposed_text | None), ...)

    @property
    def writes(self) -> bool:
        return self.proposed_config is not None or any(item[3] is not None for item in self.rules)


def _role_identity(role: str) -> str:
    if role not in permissions.ROLES:
        raise CardineError(f"unknown Codex role: {role}")
    return f"cardine-{role}"


def _role_markers(role: str) -> tuple[str, str]:
    return f"# CARDINE:BEGIN role-permissions-{role} v1", f"# CARDINE:END role-permissions-{role}"


def _rules_markers(role: str) -> tuple[str, str]:
    return f"# CARDINE:BEGIN codex-role-rules-{role} v1", f"# CARDINE:END codex-role-rules-{role}"


def _bounded_root(worktree_root: Path) -> Path:
    root = Path(worktree_root).expanduser().resolve()
    if root == Path(root.anchor) or root == Path.home().resolve():
        raise CardineError("worktree root must not authorize the filesystem root or the user's home")
    return root


def _role_profile_table(role: str, root: Path) -> dict:
    return {"description": f"Cardine {role} role inside the managed task worktrees.",
            "extends": ":workspace", "workspace_roots": {str(root): True}}


def _role_block(role: str, root: Path) -> str:
    begin, end = _role_markers(role)
    name = _role_identity(role)
    table = _role_profile_table(role, root)
    return "\n".join([begin, f"[permissions.{name}]", f"description = {_toml_quote(table['description'])}",
                      'extends = ":workspace"', "", f"[permissions.{name}.workspace_roots]",
                      f"{_toml_quote(str(root))} = true", end])


def _rule(pattern: list) -> str:
    return f'prefix_rule(pattern={json.dumps(pattern)}, decision="forbidden")'


def role_rule_lines(role: str) -> tuple[str, ...]:
    """Command rules of one role, from the shared action matrix. Prefix rules are advisory text."""
    _role_identity(role)
    rules = [_rule(["git", "push", "origin", target]) for branch in permissions.PROTECTED_BRANCHES
             for target in (branch, f"+{branch}", f"HEAD:{branch}", f"HEAD:refs/heads/{branch}")]
    rules += [_rule(["git", "push", _FORBIDDEN_FLAGS]), _rule(["git", "push", "origin", _FORBIDDEN_FLAGS])]
    actions = list(permissions.DEVELOPER_ONLY + permissions.INTEGRATION)
    if role == "implementer":
        actions.append(permissions.VERDICT)
    else:
        actions += list(permissions.REVIEWER_DENIED)
        rules.append(_rule(["git", _REVIEWER_GIT]))
    rules += [_rule(["cardine", *action]) for action in actions]
    return tuple(dict.fromkeys(rules))


def _role_rules_text(role: str) -> str:
    begin, end = _rules_markers(role)
    return "\n".join([begin, *role_rule_lines(role), end]) + "\n"


def role_rules_path(codex_home: Path, role: str) -> Path:
    _role_identity(role)
    return Path(codex_home) / ROLE_RULES_DIRECTORY / f"{role}.rules"


def codex_role_policy(role: str, project_root: Path, worktree_root: Path, worktree: Path,
                      common_dir: Path) -> permissions.RolePolicy:
    """Deterministic role policy: bounded profile, command rules, and every protected path.

    Holds rules and paths only; no credential, token, or environment value.
    """
    identity = _role_identity(role)
    root = _bounded_root(worktree_root)
    roots = permissions.protected_roots((project_root, worktree), common_dir)
    settings = {"profile": {"name": identity, **_role_profile_table(role, root)},
                "rules": list(role_rule_lines(role)),
                "protected_paths": [str(path) for path in roots]}
    return permissions.RolePolicy("codex", role, identity, settings,
                                  permissions.policy_digest("codex", role, settings))


def codex_role_profile(policy: permissions.RolePolicy, proof: permissions.HostProof | None):
    """`enforced` only from a complete host proof of this exact policy; Codex has no probe yet (D3)."""
    from cardine.hosts.launch import RoleProfile  # lazy: launch pulls in the lifecycle engine
    return RoleProfile(policy.identity, policy.role, policy.host == "codex" and permissions.proof_enforces(policy, proof))


def codex_role_profiles(plan: CodexRolePlan, policies: dict, proofs: dict) -> dict:
    """Both role profiles, or neither: an incomplete installation falls back to nothing broader."""
    from cardine.hosts.launch import RoleProfile
    complete = (plan.status == "ready" and set(policies) == set(permissions.ROLES)
                and all(permissions.proof_enforces(policies[role], proofs.get(role)) for role in permissions.ROLES))
    return {role: RoleProfile(policies[role].identity, role, complete) for role in policies}


def _role_span(text: str, role: str) -> tuple[int, int] | None:
    begin, end = _role_markers(role)
    if text.count(begin) != text.count(end) or text.count(begin) > 1:
        raise CardineError(f"damaged Cardine role markers for {role} in the Codex configuration; reconcile them manually")
    if begin not in text:
        return None
    start, stop = text.index(begin), text.index(end)
    if start > stop:
        raise CardineError(f"damaged Cardine role markers for {role} in the Codex configuration; reconcile them manually")
    return start, stop + len(end)


def _plan_role_config(text: str, role: str, root: Path) -> str:
    """The configuration text with this role's owned block present and current, or CardineError."""
    name = _role_identity(role)
    permission_tables = tomllib.loads(text).get("permissions", {})
    profile = permission_tables.get(name) if isinstance(permission_tables, dict) else None
    span = _role_span(text, role)
    block = _role_block(role, root)
    if span is None:
        if profile is not None:
            raise CardineError(f"Codex permission profile {name!r} exists without Cardine ownership; it is foreign and preserved")
        return text + ("\n" if text and not text.endswith("\n") else "") + ("\n" if text.strip() else "") + block + "\n"
    roots = profile.get("workspace_roots") if isinstance(profile, dict) else None
    enabled = [key for key, value in roots.items() if value is True] if isinstance(roots, dict) else []
    if len(enabled) != 1 or len(roots) != 1 or text[span[0]:span[1]] != _role_block(role, Path(enabled[0])):
        raise CardineError(f"Cardine role block for {role} has changed or is incomplete; reconcile it manually")
    return text[:span[0]] + block + text[span[1]:]


def _plan_role_rules(codex_home: Path, role: str) -> tuple:
    path = role_rules_path(codex_home, role)
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise CardineError(f"Codex role rules path {path} is not a regular file; preserved")
    current = path.read_bytes().decode("utf-8") if path.exists() else ""
    wanted = _role_rules_text(role)
    begin, end = _rules_markers(role)
    if current and current != wanted and not (
            current.startswith(begin + "\n") and current.endswith(end + "\n") and current.count("CARDINE:") == 2):
        raise CardineError(f"Codex role rules {path} are foreign or damaged; reconcile them manually")
    return role, path, current, None if current == wanted else wanted


def plan_codex_role_policies(config_path: Path, codex_home: Path, worktree_root: Path) -> CodexRolePlan:
    """Read-only plan for both role blocks and both role rule files; never writes.

    Either profile being foreign, damaged, or incomplete blocks the whole plan.
    """
    config_path = Path(config_path)
    text = config_path.read_text(encoding="utf-8") if config_path.is_file() else ""
    try:
        root = _bounded_root(worktree_root)
        try:
            proposed = text
            for role in permissions.ROLES:
                proposed = _plan_role_config(proposed, role, root)
        except tomllib.TOMLDecodeError as error:
            raise CardineError(f"malformed Codex TOML at {config_path}: {error}") from error
        rules = tuple(_plan_role_rules(codex_home, role) for role in permissions.ROLES)
    except CardineError as error:
        return CodexRolePlan("blocked", config_path, str(error), text, None, ())
    if proposed == text and all(item[3] is None for item in rules):
        return CodexRolePlan("ready", config_path, "both role profiles and rules are current", text, None, rules)
    return CodexRolePlan("approval-required", config_path, "explicit --apply is required", text,
                         None if proposed == text else proposed, rules)


def _unused_backup(path: Path) -> Path:
    index = 0
    while True:
        index += 1
        candidate = path.with_name(f"{path.name}.cardine-backup-{index}")
        if not candidate.exists() and not candidate.is_symlink():
            return candidate


def apply_codex_role_policies(plan: CodexRolePlan, operation: Operation | None = None) -> bool:
    """Replace both role blocks and both rule files in one receipt-covered operation, with backups."""
    if plan.status == "blocked":
        raise CardineError(f"Codex role policy is blocked: {plan.detail}")
    with host_operation("codex-roles", plan.config_path, operation) as active:
        if not plan.writes:
            return changed(active, False)
        path = plan.config_path
        if (path.read_text(encoding="utf-8") if path.is_file() else "") != plan.config_text:
            raise CardineError("Codex configuration changed since it was planned; rerun --check")
        for _role, rules_path, current, _proposed in plan.rules:
            active.guard(rules_path)
            if (rules_path.read_bytes().decode("utf-8") if rules_path.exists() else "") != current:
                raise CardineError("Codex role rules changed since they were planned; rerun --check")
        if plan.proposed_config is not None:
            active.replace("codex-roles-config", path, plan.proposed_config.encode("utf-8"),
                           backup=_unused_backup(path) if path.exists() else None, mode=0o600)
        for role, rules_path, current, proposed in plan.rules:
            if proposed is not None:
                active.replace(f"codex-roles-rules-{role}", rules_path, proposed.encode("utf-8"),
                               backup=_unused_backup(rules_path) if current else None, mode=0o600)
        return True
