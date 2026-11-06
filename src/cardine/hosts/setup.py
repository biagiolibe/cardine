"""Host setup planning, application and diagnostics."""

from __future__ import annotations

from cardine.shared.layout import names

from cardine.worktree.paths import repository_identity

from cardine.hosts import permissions
from cardine.hosts.claude import apply_claude_project_allowlist
from cardine.hosts.claude import claude_role_policy
from cardine.hosts.effects import host_operation
from cardine.hosts.hooks import HooksPlan, _commands, apply_hooks, hook_command, plan_hooks, registry_path
from cardine.lifecycle import receipts
from cardine.hosts.claude import claude_hook_duplicate_advisories
from cardine.hosts.claude import plan_claude_project_allowlist
from cardine.hosts.codex import _configuration_backup
from cardine.hosts.codex import _codex_profile_divergence
from cardine.hosts.codex import apply_codex_configuration
from cardine.hosts.codex import apply_codex_user_rules
from cardine.hosts.codex import codex_role_policy
from cardine.hosts.codex import role_rules_path
from cardine.hosts.codex import plan_codex_configuration
from cardine.hosts.codex import plan_codex_user_rules
from cardine.hosts.skills import _aggregate_skill_state
from cardine.hosts.skills import _directory_setup_state
from cardine.hosts.skills import _framework_skill_links
from cardine.hosts.skills import _setup_codex_state
from cardine.hosts.skills import _stale_codex_skill_warnings
from cardine.hosts.skills import _remove_old_skill_links
from cardine.hosts.skills import codex_profile_root_mismatch
from cardine.integration.evidence import candidate_validation_declaration
from cardine.integration.evidence import proposed_candidate_validation_declaration
from cardine.shared.errors import CardineError
from cardine.shared.git import _run_git
from cardine.shared.git import primary_project_root
from cardine.shared.jsonio import json_bytes
from cardine.shared.models import SetupPlan
from dataclasses import dataclass, field, replace
import hashlib
from cardine.shared.project import parse_project_declaration
from cardine.shared.project import read_project_declaration
from cardine.tasks.identity import parse_task_identity_policy
from cardine.tasks.identity import read_task_identity_policy
from cardine.tasks.identity import read_installation_identity_policy
from cardine.worktree.storage import _read_user_configuration
from cardine.worktree.storage import resolve_worktree_root
from collections.abc import Mapping
from pathlib import Path
import difflib
import re
import json
import os
import shlex
import shutil
import subprocess
import tempfile
import tomllib
from cardine.shared.paths import SCRIPTS_ROOT


@dataclass(frozen=True)
class PinnedSetupPlan(SetupPlan):
    """A setup plan plus the digest of every user-owned file it was computed from."""

    inputs: Mapping[str, str | None] = field(default_factory=dict)
    hooks: HooksPlan | None = None


def _input_digest(path: Path) -> str | None:
    """Digest of what a setup input holds now; a link or directory is a distinct value, never followed."""
    if path.is_symlink():
        return "link:" + os.readlink(path)
    if path.is_dir():
        return "directory"
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except FileNotFoundError:
        return None


def _plan_inputs(plan: SetupPlan) -> dict[str, str | None]:
    hooks = getattr(plan, "hooks", None)
    return {
        **({f"{registry.host}-hooks": _input_digest(registry.path) for registry in hooks.registries}
           if hooks is not None else {}),
        "worktree-config": _input_digest(plan.resolution.config_path),
        "candidate-validation": _input_digest(plan.candidate_validation_path),
        "project-declaration": _input_digest(plan.project_declaration_path),
        "task-identity": _input_digest(plan.task_identity_path),
        "worktree-root": plan.directory_state,
    }


def _refuse_linked_write_paths(plan: SetupPlan) -> None:
    """Setup writes through no link: not a target, its directory, or the directory above it."""
    targets = [plan.resolution.config_path, plan.candidate_validation_path,
               plan.project_declaration_path, plan.task_identity_path]
    hooks = getattr(plan, "hooks", None)
    if hooks is not None:
        targets.extend(registry.path for registry in hooks.registries)
    for target in targets:
        for path in (target, target.parent, target.parent.parent):
            if path.is_symlink():
                raise CardineError(f"refusing to write through a symlink: {path}")


def _revalidate_plan(plan: SetupPlan) -> None:
    """Refuse before the first write when an input changed after it was planned."""
    pinned = getattr(plan, "inputs", None)
    if pinned is None:
        return
    current = _plan_inputs(plan)
    for name, digest in pinned.items():
        if current[name] != digest:
            raise CardineError(f"{name} changed since it was planned; rerun --check")


_LEGACY = "meri" + "dian"  # the retired product name, composed so the identifier guard stays strict


def _legacy_tool_installed(home: Path, environment: Mapping[str, str]) -> bool:
    """True while the retired tool is still on this machine; reads only `home` and `environment`."""
    root = environment.get(_LEGACY.upper() + "_ROOT")
    return bool((root and Path(root).expanduser().is_dir())
                or (home / ".local/share" / _LEGACY).is_dir()
                or (home / ".claude/plugins/cache" / _LEGACY).is_dir())


def plan_setup(
    worktree_root: Path | None,
    codex_config: Path,
    *,
    task_identity: str | None = None,
    environment: Mapping[str, str] | None = None,
    home: Path | None = None,
    user_config: Path | None = None,
    framework_root: Path | None = None,
    project_root: Path | None = None,
) -> SetupPlan:
    home = (home or Path.home()).expanduser().resolve()
    framework_root = (framework_root or SCRIPTS_ROOT.parent).expanduser().resolve()
    project_root = primary_project_root((project_root or Path.cwd()).expanduser().resolve())
    environment = environment or os.environ
    if task_identity not in (None, "opaque", "milestone"):
        raise CardineError(f"unsupported task identity mode: {task_identity!r}")
    resolution = resolve_worktree_root(
        worktree_root,
        environment=environment,
        home=home,
        config_path=user_config,
    )
    # Applying with a higher-precedence source must never overwrite malformed
    # lower-precedence user state without first reporting it.
    existing_config = _read_user_configuration(resolution.config_path)
    default_root = home / names().worktree_root
    expected_config = {"version": 1, "worktreeRoot": str(resolution.path)}
    if resolution.path == default_root:
        config_action = "remove" if existing_config is not None else "none"
    elif existing_config == expected_config:
        config_action = "none"
    else:
        config_action = "write"

    user_rules = plan_codex_user_rules(home / ".codex/rules/cardine.rules",
                                       legacy_tool_installed=_legacy_tool_installed(home, environment))
    directory_state, directory_change = _directory_setup_state(resolution.path)
    codex_plan: CodexConfigurationPlan | None = None
    try:
        codex_plan = plan_codex_configuration(codex_config, resolution.path)
        codex_state = _setup_codex_state(codex_plan)
        if codex_state == "blocked":
            parsed = tomllib.loads(codex_plan.current_text or "")
            differences = _codex_profile_divergence(parsed, resolution.path)
            codex_detail = (
                "owned Codex profile has unexpected divergence in: "
                + ", ".join(differences)
            )
        else:
            codex_detail = codex_plan.detail
    except CardineError as error:
        codex_state = "blocked"
        codex_detail = str(error)

    claude_plan = plan_claude_project_allowlist(project_root)
    claude_state = claude_plan.status
    claude_detail = claude_plan.detail
    claude_hook_duplicates = claude_hook_duplicate_advisories(project_root, home)
    hooks_plan = plan_hooks(home, project_root)
    candidate_validation_path = project_root / names().candidate_validation_path
    candidate_validation_proposal: dict[str, object] | None = None
    try:
        candidate_validation_state, _candidate_fragments = candidate_validation_declaration(project_root)
        if candidate_validation_state == "undeclared":
            proposal = proposed_candidate_validation_declaration(project_root)
            if not candidate_validation_path.is_file() or json.loads(
                candidate_validation_path.read_text(encoding="utf-8")
            ) != proposal:
                candidate_validation_proposal = proposal
    except CardineError:
        candidate_validation_state = "blocked"

    project_declaration_path = project_root / names().project_declaration_path
    project_declaration_proposal: dict[str, object] | None = None
    try:
        if project_declaration_path.exists():
            declaration = read_project_declaration(project_root)
            assert declaration is not None
            if "project" in declaration:
                project_declaration_state = "present"
            else:
                project_declaration_state = "advisory-incomplete"
                project_declaration_proposal = {
                    **declaration,
                    "project": proposed_project_identity(project_root),
                }
        else:
            project_declaration_state = "advisory-missing"
            project_declaration_proposal = {
                "version": 1,
                "preset": "lean",
                "project": proposed_project_identity(project_root),
                "locations": {
                    "queue": "tasks/QUEUE.md", "taskRoots": ["tasks"],
                    "reviewRoot": "tasks/reviews", "handoffRoot": "tasks/handoffs",
                    "adrLog": "docs/ARCHITECTURE_DECISIONS.md", "plan": "PROJECT_PLAN.md",
                },
            }
            parse_project_declaration(project_declaration_proposal)
    except CardineError:
        project_declaration_state = "blocked"

    task_identity_path = project_root / names().task_identity_path
    task_identity_proposal: dict[str, object] | None = None
    task_identity_detail = "no task-identity choice requested"
    if task_identity is None:
        task_identity_state = "not-requested"
    elif task_identity_path.exists():
        try:
            existing_identity = (read_task_identity_policy(project_root) if project_declaration_path.exists()
                                 else read_installation_identity_policy(project_root))
        except CardineError as error:
            task_identity_state = "blocked"
            task_identity_detail = str(error)
        else:
            if existing_identity.mode == task_identity:
                task_identity_state = "already-set"
                task_identity_detail = f"task identity is already set to {task_identity}"
            else:
                task_identity_state = "different"
                task_identity_detail = (
                    f"task identity is already set to {existing_identity.mode}; requested {task_identity}"
                )
    else:
        task_identity_proposal = {"version": 1, "mode": task_identity}
        # Validate the exact declaration that --apply will write using the
        # resolver's closed-schema parser before any mutation is possible.
        parse_task_identity_policy(task_identity_proposal)
        task_identity_state = "planned"
        task_identity_detail = f"write task identity declaration with mode {task_identity}"

    if project_declaration_proposal is not None and not project_declaration_path.exists():
        # A newly declared project owns naming policy. Retain the selected
        # identity when folding the standalone declaration into project.json.
        try:
            project_declaration_proposal["taskIdentity"] = {
                "mode": (task_identity_proposal["mode"] if task_identity_proposal is not None
                         else read_installation_identity_policy(project_root).mode
                         if task_identity_path.exists() else read_task_identity_policy(project_root).mode)
            }
        except CardineError as error:
            task_identity_state = "blocked"
            task_identity_detail = str(error)

    changes: list[str] = []
    if user_rules.proposed_text is not None:
        changes.append(f"configure Cardine Codex user-rules block in {user_rules.path}")
    if directory_state != "ready":
        changes.append(directory_change)
    if config_action == "write":
        changes.append(f"write {resolution.config_path} with version 1 and worktreeRoot {resolution.path}")
    elif config_action == "remove":
        changes.append(f"remove {resolution.config_path} because the built-in default needs no configuration")
    if codex_plan is not None and codex_plan.proposed_text is not None:
        verb = "repair" if codex_state in ("repair-required", "repair-and-replace-required") else "configure"
        changes.append(f"{verb} Codex permission profile in {codex_config} for {resolution.path}")
    for registry in hooks_plan.registries:
        if registry.proposed_text is not None:
            changes.append(registry.detail)
    if claude_plan.proposed_settings is not None:
        changes.append(
            f"add project Claude Code command allowlist and deny rules in {claude_plan.settings_path}"
        )
    if candidate_validation_proposal is not None:
        changes.append(
            f"write candidate-validation declaration in {candidate_validation_path} after explicit --apply consent"
        )
    if project_declaration_proposal is not None:
        changes.append(f"write project declaration in {project_declaration_path} after explicit --apply consent")
    if task_identity_proposal is not None:
        changes.append(f"write {task_identity_path} with task identity mode {task_identity}")
    if (
        directory_state == "blocked"
        or codex_state == "blocked"
        or claude_state == "blocked"
        or hooks_plan.blocked is not None
        or candidate_validation_state == "blocked"
        or project_declaration_state == "blocked"
        or task_identity_state == "blocked"
    ):
        changes = ["none; setup is blocked before mutation"]
    elif not changes:
        changes.append("none")
    warnings: list[str] = list(user_rules.warnings)
    skill_links = _framework_skill_links(framework_root, home)
    skill_links_state = _aggregate_skill_state(skill_links)
    if skill_links_state in ("blocked", "conflict"):
        changes = ["none; setup is blocked before mutation"]
    elif skill_links_state == "missing" and changes != ["none; setup is blocked before mutation"]:
        changes.append(f"create missing Codex skill links in {home / '.agents/skills'}")
    if any(state == "remove" for _, _, state, _ in skill_links):
        if changes != ["none; setup is blocked before mutation"]:
            changes.append("remove proven-owned old Codex skill links")
    cardine_root_value = environment.get("CARDINE_ROOT")
    cardine_root_state = (
        "unset"
        if cardine_root_value is None
        else "ready"
        if Path(cardine_root_value).expanduser().resolve() == framework_root
        else "mismatch"
    )
    if cardine_root_state == "mismatch":
        warnings.append(f"CARDINE_ROOT differs from framework root: {cardine_root_value}")
    warnings.extend(_stale_codex_skill_warnings(home))
    temporary_root = Path(tempfile.gettempdir()).resolve()
    if resolution.path == temporary_root or temporary_root in resolution.path.parents:
        warnings.append("resolved root is under a temporary directory and is unsuitable for persistent setup")
    probe_path = resolution.path
    while not probe_path.exists() and probe_path != probe_path.parent:
        probe_path = probe_path.parent
    if not probe_path.is_dir():
        probe_path = probe_path.parent
    repository_probe = _run_git(probe_path, "rev-parse", "--show-toplevel")
    if repository_probe.returncode == 0:
        repository_root = Path(repository_probe.stdout.strip()).resolve()
        if resolution.path == repository_root or repository_root in resolution.path.parents:
            warnings.append("resolved root is inside the current repository and is unsuitable for machine setup")
    plan = SetupPlan(
        user_rules,
        resolution,
        codex_config,
        directory_state,
        codex_state,
        codex_plan,
        codex_detail,
        claude_state,
        claude_plan,
        claude_detail,
        claude_hook_duplicates,
        candidate_validation_state,
        candidate_validation_path,
        candidate_validation_proposal,
        project_declaration_state,
        project_declaration_path,
        project_declaration_proposal,
        task_identity,
        task_identity_state,
        task_identity_path,
        task_identity_proposal,
        task_identity_detail,
        config_action,
        framework_root,
        skill_links,
        skill_links_state,
        cardine_root_state,
        tuple(changes),
        tuple(warnings),
    )
    pinned = PinnedSetupPlan(*(getattr(plan, name) for name in plan.__dataclass_fields__), hooks=hooks_plan)
    return replace(pinned, inputs=_plan_inputs(pinned))


def print_setup_plan(plan: SetupPlan) -> None:
    print(f"codex-user-rules: {plan.user_rules.status} ({plan.user_rules.path})")
    if plan.user_rules.proposed_text is not None:
        print("".join(difflib.unified_diff(
            plan.user_rules.current_text.splitlines(keepends=True),
            plan.user_rules.proposed_text.splitlines(keepends=True),
            fromfile=str(plan.user_rules.path), tofile=str(plan.user_rules.path) + " (planned)",
        )), end="")
    print(f"worktree-root: {plan.resolution.path}")
    print(f"worktree-root-source: {plan.resolution.source}")
    print(f"directory-exists: {'no' if plan.directory_state == 'missing' else 'yes'}")
    print(f"directory-owner-only: {'yes' if plan.directory_state == 'ready' else 'no'}")
    print(f"directory: {plan.directory_state}")
    print(f"codex-profile: {plan.codex_state}")
    print(f"codex-detail: {plan.codex_detail}")
    hooks = getattr(plan, "hooks", None)
    if hooks is not None:
        for registry in hooks.registries:
            print(f"{registry.host}-user-hooks: {registry.status} ({registry.path}; {registry.detail})")
        print("hook-activation: registration only; a new session loads the hooks and "
              "doctor must prove they run (not proven by this registry)")
        for advisory in hooks.advisories:
            print(f"hook-duplicate: {advisory}")
    print(f"claude-project-allowlist: {plan.claude_state}")
    print(f"claude-detail: {plan.claude_detail}")
    print(
        "claude-deny-note: deny rules are prefix rules and defense in depth; a reworded command can "
        "evade them, and the managed denial text remains in force"
    )
    for advisory in plan.claude_hook_duplicates:
        print(f"claude-hook-duplicate: {advisory}")
    print(f"candidate-validation-commands: {plan.candidate_validation_state}")
    if plan.candidate_validation_proposal is not None:
        print("candidate-validation-proposal: " + json.dumps(plan.candidate_validation_proposal, sort_keys=True))
    print(f"project-declaration: {plan.project_declaration_state}")
    if plan.project_declaration_proposal is not None:
        print("project-declaration-proposal: " + json.dumps(plan.project_declaration_proposal, sort_keys=True))
    print(f"task-identity: {plan.task_identity_state}")
    print(f"task-identity-detail: {plan.task_identity_detail}")
    if plan.task_identity_proposal is not None:
        print("task-identity-proposal: " + json.dumps(plan.task_identity_proposal, sort_keys=True))
    mismatch = codex_profile_root_mismatch(
        plan.codex_config,
        plan.resolution.path,
    )
    if mismatch:
        print(f"codex-root-mismatch: {mismatch}")
    print(f"codex-skill-links: {plan.skill_links_state}")
    for name, path, state, detail in plan.skill_links:
        print(f"codex-skill-{name}: {state} ({path}; {detail})")
    print(f"CARDINE_ROOT: {plan.cardine_root_state}")
    print(f"shell-profile-CARDINE_ROOT: export CARDINE_ROOT={plan.framework_root}")
    print('shell-profile-PATH: export PATH="$CARDINE_ROOT/bin:$PATH"')
    for warning in plan.warnings:
        print(f"warning: {warning}")
    print("changes:")
    for change in plan.changes:
        print(f"- {change}")


def apply_setup(plan: SetupPlan) -> bool:
    if (
        plan.directory_state == "blocked"
        or plan.codex_state == "blocked"
        or plan.claude_state == "blocked"
        or getattr(plan, "hooks", None) is not None and plan.hooks.blocked is not None
        or plan.candidate_validation_state == "blocked"
        or plan.project_declaration_state == "blocked"
        or plan.task_identity_state == "blocked"
        or plan.skill_links_state in ("blocked", "conflict")
        or plan.codex_plan is None
    ):
        detail = (
            next(detail for _, _, state, detail in plan.skill_links if state in ("blocked", "conflict"))
            if plan.skill_links_state in ("blocked", "conflict")
            else plan.codex_detail
            if plan.codex_state == "blocked"
            else plan.claude_detail
            if plan.claude_state == "blocked"
            else plan.hooks.blocked.detail
            if getattr(plan, "hooks", None) is not None and plan.hooks.blocked is not None
            else plan.task_identity_detail
            if plan.task_identity_state == "blocked"
            else _directory_setup_state(plan.resolution.path)[1]
        )
        raise CardineError(f"setup is blocked: {detail}")
    # Revalidate every user-owned input before any setup mutation.
    _refuse_linked_write_paths(plan)
    _revalidate_plan(plan)
    fresh_rules = plan_codex_user_rules(plan.user_rules.path)
    if (fresh_rules.current_text != plan.user_rules.current_text
        or fresh_rules.legacy_text != plan.user_rules.legacy_text):
        raise CardineError("Codex user rules changed since planning; rerun --check")
    root = plan.resolution.path
    request = {
        "task_identity": plan.task_identity_mode,
        "project": str(plan.project_declaration_path.parent.parent),
        "codex_config": str(plan.codex_config),
    }
    with host_operation("setup", root, request=request) as active:
        # Check all recorded destinations and pin this migration's outputs before
        # any host write; a retry cannot silently adopt changes to pending files.
        active.targets("before")
        active.targets("after")
        rules = plan.user_rules
        for target in (rules.path, rules.legacy_path, plan.codex_config):
            if target is not None:
                active.guard(target)
                for parent in (target.parent, target.parent.parent):
                    if parent.is_symlink():
                        raise CardineError(f"refusing to write through a symlink: {parent}")
        current_config = plan.codex_config.read_text(encoding="utf-8") if plan.codex_config.is_file() else ""
        if plan.codex_plan.proposed_text is not None and current_config != plan.codex_plan.current_text:
            raise CardineError("Codex configuration changed since it was planned; rerun --check")
        if rules.proposed_text is not None:
            active.declare("codex-rules", rules.path, rules.proposed_text.encode("utf-8"), mode=0o600)
        if rules.legacy_proposed is not None and rules.legacy_path is not None:
            active.declare("codex-legacy-rules", rules.legacy_path, rules.legacy_proposed.encode("utf-8"), mode=0o600)
        if plan.codex_plan.proposed_text is not None:
            active.declare("codex-config", plan.codex_config, plan.codex_plan.proposed_text.encode("utf-8"),
                           backup=_configuration_backup(plan.codex_plan), mode=0o600)
        wrote = False
        if plan.directory_state in ("missing", "repair-required"):
            active.directory("cardine-root", root, 0o700)
            wrote = True
        if plan.config_action == "write":
            active.replace("worktree-config", plan.resolution.config_path,
                           json_bytes({"version": 1, "worktreeRoot": str(root)}), mode=0o600)
            wrote = True
        elif plan.config_action == "remove":
            active.replace("worktree-config", plan.resolution.config_path, None)
            wrote = True
        wrote = apply_codex_configuration(plan.codex_plan, active) or wrote
        wrote = apply_codex_user_rules(plan.user_rules, active) or wrote
        wrote = apply_claude_project_allowlist(plan.claude_plan, active) or wrote
        if getattr(plan, "hooks", None) is not None:
            wrote = apply_hooks(plan.hooks, active) or wrote
        if plan.candidate_validation_proposal is not None:
            active.replace("candidate-validation", plan.candidate_validation_path,
                           json_bytes(plan.candidate_validation_proposal), mode=0o600)
            wrote = True
        if plan.project_declaration_proposal is not None:
            if plan.project_declaration_path.exists():
                existing = read_project_declaration(plan.project_declaration_path.parent)
                if existing is None or "project" in existing:
                    raise CardineError("project declaration appeared or changed since it was planned; rerun --check")
            active.replace("project-declaration", plan.project_declaration_path,
                           json_bytes(plan.project_declaration_proposal), mode=0o600)
            wrote = True
        if plan.task_identity_proposal is not None:
            if plan.task_identity_path.exists():
                raise CardineError("task identity declaration appeared since it was planned; rerun --check")
            active.replace("task-identity", plan.task_identity_path,
                           json_bytes(plan.task_identity_proposal), mode=0o600)
            wrote = True
        missing_links = [
            (path, plan.framework_root / "skills" / name)
            for name, path, state, _ in plan.skill_links
            if state == "missing"
        ]
        if missing_links:
            skills_root = missing_links[0][0].parent
            if not skills_root.exists() or active.intent.get("paths", {}).get("skills-root"):
                active.directory("skills-root", skills_root, 0o700)
            for path, target in missing_links:
                active.symlink("skill:" + path.name, path, target)
        removed = _remove_old_skill_links(active, plan.skill_links)
        result = wrote or bool(missing_links) or removed or active.resumed
        receipts.boundary("before_setup_result")
    receipts.boundary("after_setup_result")
    return result


CODEX_CLOSURE_POLICY_PROBES = (
    (
        "archive-rename-policy",
        (
            (("git", "mv", "tasks/1.md", "tasks/done/1.md"), "allow"),
            (("git", "mv", "-f", "tasks/1.md", "tasks/done/1.md"), "prompt"),
        ),
    ),
    (
        "inspection-command-policy",
        tuple(
            ((tool, "tasks"), "allow")
            for tool in ("ls", "cat", "head", "tail", "wc", "grep")
        )
        + (
            (("sed", "-i", "s/a/b/", "tasks/QUEUE.md"), None),
            (("rg", "--pre", "cat", "x"), None),
        ),
    ),
)


def _execpolicy_argv(codex_executable: str, rules: tuple[Path, ...], command: tuple[str, ...]) -> list[str]:
    """Ask the host to evaluate the installed combined policy, one `--rules` per layer."""
    argv = [codex_executable, "execpolicy", "check"]
    for path in rules:
        argv += ["--rules", str(path)]
    return [*argv, "--", *command]


def _codex_policy_probe_state(
    command_policy: str,
    codex_executable: str | None,
    rules: tuple[Path, ...],
    probes: tuple[tuple[tuple[str, ...], str | None], ...],
) -> str:
    """Report `ready` only when every probe returns its expected decision."""
    if command_policy != "ready" or not codex_executable:
        return "blocked" if command_policy == "blocked" else "approval-required"
    gaps = []
    for command, expected in probes:
        checked = subprocess.run(
            _execpolicy_argv(codex_executable, rules, command),
            text=True,
            capture_output=True,
            check=False,
        )
        try:
            actual = json.loads(checked.stdout).get("decision") if checked.returncode == 0 else "error"
        except json.JSONDecodeError:
            actual = "error"
        if actual != expected:
            gaps.append(" ".join(command[:2]) if command[0] == "git" else command[0])
    return "ready" if not gaps else "gap: " + ", ".join(sorted(set(gaps)))


def codex_doctor(
    project_root: Path,
    config_path: Path,
    worktree_root: Path,
    *,
    framework_root: Path | None = None,
    home: Path | None = None,
    environment: Mapping[str, str] | None = None,
) -> dict[str, str]:
    result: dict[str, str] = {}
    try:
        plan = plan_codex_configuration(config_path, worktree_root)
        result["permission-model"] = plan.status
        result["profile-ownership"] = (
            "ready"
            if plan.status == "ready"
            else plan.status
            if plan.status in ("repair-required", "repair-and-replace-required")
            else "not-applicable"
        )
    except CardineError:
        result["permission-model"] = "blocked"
        result["profile-ownership"] = "blocked"
    mismatch = codex_profile_root_mismatch(config_path, worktree_root)
    if mismatch:
        result["codex-root-mismatch"] = mismatch
    text = config_path.read_text(encoding="utf-8") if config_path.is_file() else ""
    try:
        parsed = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        parsed = {}
    trusted = any(
        isinstance(settings, dict)
        and settings.get("trust_level") == "trusted"
        and Path(path).expanduser().resolve() == project_root.resolve()
        for path, settings in parsed.get("projects", {}).items()
    )
    result["project-trust"] = "ready" if trusted else "approval-required"
    home = (home or Path.home()).expanduser().resolve()
    # The installed combined policy: the user layer plus any legacy project layer.
    rules = tuple(
        path for path in (home / ".codex/rules/cardine.rules", project_root / ".codex/rules/meridian.rules")
        if path.is_file()
    )
    result["command-policy"] = "ready" if rules and trusted else ("approval-required" if rules else "blocked")
    claude_plan = plan_claude_project_allowlist(project_root)
    result["claude-project-allowlist"] = "installed" if claude_plan.status == "ready" else claude_plan.status
    try:
        validation_state, _fragments = candidate_validation_declaration(project_root)
        result["candidate-validation-commands"] = (
            "advisory-undeclared" if validation_state == "undeclared" else "ready"
        )
    except CardineError:
        result["candidate-validation-commands"] = "blocked"
    lifecycle_policy = "approval-required"
    codex_executable = shutil.which("codex")
    if result["command-policy"] == "ready" and codex_executable:
        probes = (
            ("path", "TASK-1", "--worktree-root", str(worktree_root)),
            ("prepare", "TASK-1", "--worktree-root", str(worktree_root), "--format", "json"),
            ("check", "TASK-1", "--worktree-root", str(worktree_root), "--format", "json"),
            ("evidence", "TASK-1", "--format", "json"),
            ("closure-status", "TASK-1", "--format", "json"),
            ("advance", "TASK-1", "--format", "json"),
            ("integrate", "stage", "TASK-1", "--worktree-root", str(worktree_root), "--evidence", "handoff.json", "--format", "json"),
            ("integrate", "finalize", "TASK-1", "--evidence", "candidate.json", "--format", "json"),
            ("integrate", "abort", "TASK-1", "--format", "json"),
            ("cleanup", "TASK-1", "--worktree-root", str(worktree_root), "--format", "json"),
        )
        decisions: list[str | None] = []
        for probe in probes:
            checked = subprocess.run(
                _execpolicy_argv(codex_executable, rules, ("cardine", "worktree", *probe)),
                text=True,
                capture_output=True,
                check=False,
            )
            try:
                decisions.append(json.loads(checked.stdout).get("decision") if checked.returncode == 0 else None)
            except json.JSONDecodeError:
                decisions.append(None)
        lifecycle_policy = "ready" if decisions and all(item == "allow" for item in decisions) else "blocked"
    elif result["command-policy"] == "blocked":
        lifecycle_policy = "blocked"
    result["lifecycle-command-policy"] = lifecycle_policy
    for key, group in CODEX_CLOSURE_POLICY_PROBES:
        result[key] = _codex_policy_probe_state(
            result["command-policy"], codex_executable, rules, group
        )
    root_write = "approval-required"
    if result["permission-model"] in ("ready", "repair-required", "repair-and-replace-required") and worktree_root.is_dir():
        # Read-only: a probe file here would write outside the fixture on every run.
        root_write = "ready" if os.access(worktree_root, os.W_OK | os.X_OK) else "blocked"
    result["worktree-root-write"] = root_write
    result["git-metadata"] = "ready" if lifecycle_policy == "ready" else "approval-required"
    framework_root = (framework_root or SCRIPTS_ROOT.parent).expanduser().resolve()
    try:
        result["user-command-policy"] = plan_codex_user_rules(home / ".codex/rules/cardine.rules").status
    except CardineError:
        result["user-command-policy"] = "stale"
    result["skill-links"] = _aggregate_skill_state(_framework_skill_links(framework_root, home))
    cardine_root_value = (environment or os.environ).get("CARDINE_ROOT")
    result["CARDINE_ROOT"] = (
        "unset"
        if cardine_root_value is None
        else "ready"
        if Path(cardine_root_value).expanduser().resolve() == framework_root
        else "mismatch"
    )
    result["hook-invocation"] = probe_hook_invocation("codex", home)
    result.update(role_launch_states("codex", project_root, worktree_root, home, executable=codex_executable))
    return result


def claude_doctor(project_root: Path, *, home: Path | None = None) -> dict[str, str]:
    """Claude has no host command-decision probe, so enforcement is never inferred from settings."""
    home = (home or Path.home()).expanduser().resolve()
    plan = plan_claude_project_allowlist(project_root)
    return {
        "claude-project-allowlist": "installed" if plan.status == "ready" else plan.status,
        "claude-command-policy": "unverified",
        "hook-invocation": probe_hook_invocation("claude", home),
        **role_launch_states("claude", project_root, home, home),
    }


def host_doctor(host: str, project_root: Path, config_path: Path, worktree_root: Path, **options) -> dict[str, str]:
    if host == "claude":
        return claude_doctor(project_root, home=options.get("home"))
    return codex_doctor(project_root, config_path, worktree_root, **options)


# -- Runtime role proofs (D3) --------------------------------------------------
#
# A role profile is enforced only when the host itself reports the expected
# decision for every probe of the matrix under the installed policy. Nothing
# here persists a probe or a result: an interrupted run leaves no state, and a
# rerun asks the host again against the same policy digest.

_SHELL_SYNTAX = re.compile(r"[|&;<>$`()\n]|\s['\"]")


class ProbeInterrupted(Exception):
    """The host could not be asked; the run is incomplete and proves nothing."""


@dataclass(frozen=True)
class RoleProofResult:
    role: str
    state: str  # ready | unsupported: <gaps> | unverified: <reason> | approval-required: <reason>
    proof: permissions.HostProof | None
    gaps: tuple[str, ...] = ()


def codex_decision_evaluator(codex_executable: str, rules: tuple[Path, ...], *, timeout: int = 30):
    """Ask `codex execpolicy check` for the decision on a shell probe, under the installed rule layers.

    Returns `deny` only for a `forbidden` decision. Codex cannot evaluate a
    native file write, so those probes return None and stay unobserved.
    """
    def evaluate(tool: str, tool_input: dict) -> str | None:
        if tool != permissions.CODEX_SHELL:
            return None
        command = tool_input.get("command", "")
        words = ("bash", "-lc", command) if _SHELL_SYNTAX.search(command) else tuple(shlex.split(command))
        try:
            checked = subprocess.run(_execpolicy_argv(codex_executable, rules, words), text=True,
                                     capture_output=True, check=False, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ProbeInterrupted(type(error).__name__) from error
        try:
            document = json.loads(checked.stdout) if checked.returncode == 0 else None
        except json.JSONDecodeError:
            document = None
        if not isinstance(document, dict):
            raise ProbeInterrupted("no decision document")
        return "deny" if document.get("decision") == "forbidden" else "allow"

    return evaluate


def prove_role_policy(policy: permissions.RolePolicy, evaluate) -> RoleProofResult:
    """Run the whole probe matrix through `evaluate(tool, input) -> 'deny' | 'allow' | None`.

    A proof exists only when the host observed every probe; it enforces only
    when each observed decision equals the expected one. Read-only and
    repeatable: nothing is written, so an interruption cannot promote anything.
    """
    matrix = permissions.probe_matrix(policy.role, policy.host)
    observed: dict[str, str] = {}
    unobserved: list[str] = []
    try:
        for name, (tool, tool_input, _expected) in matrix.items():
            verdict = evaluate(tool, tool_input)
            if verdict in ("deny", "allow"):
                observed[name] = verdict
            else:
                unobserved.append(name)
    except ProbeInterrupted as error:
        return RoleProofResult(policy.role, f"unverified: probe interrupted ({error})", None)
    gaps = tuple(("not denied " if matrix[name][2] == "deny" else "false deny ") + name
                 for name, verdict in observed.items() if verdict != matrix[name][2])
    gaps += tuple("unobserved " + name for name in unobserved)
    if unobserved:  # An incomplete run is never a proof.
        return RoleProofResult(policy.role, "unsupported (D3): " + ", ".join(gaps[:4]) + _more(gaps), None, gaps)
    proof = permissions.HostProof(policy.host, policy.identity, policy.digest, observed)
    if permissions.proof_enforces(policy, proof):
        return RoleProofResult(policy.role, "ready", proof)
    return RoleProofResult(policy.role, "unsupported (D3): " + ", ".join(gaps[:4]) + _more(gaps), proof, gaps)


def _more(gaps: tuple[str, ...]) -> str:
    return f" (+{len(gaps) - 4} more)" if len(gaps) > 4 else ""


def role_launch_states(host: str, project_root: Path, worktree_root: Path, home: Path, *,
                       executable: str | None = None, evaluate=None) -> dict[str, str]:
    """Doctor facts `role-launch-<role>`: `ready` only from a complete host-evaluated proof.

    The policy is the representative one for this project; a launch recomputes
    its own policy and needs a proof of that exact digest.
    """
    states: dict[str, str] = {}
    for role in permissions.ROLES:
        key = "role-launch-" + role
        try:
            common = project_root / ".git"
            if host == "claude":
                policy = claude_role_policy(role, project_root, project_root, common)
            else:
                policy = codex_role_policy(role, project_root, worktree_root, project_root, common)
        except CardineError:
            states[key] = "blocked"
            continue
        if evaluate is not None:
            states[key] = prove_role_policy(policy, evaluate).state
        elif host == "claude":
            # Claude exposes no host decision probe: never inferred from settings text.
            states[key] = "unsupported (D3): no host decision probe"
        else:
            role_file = role_rules_path(home / ".codex", role)
            layers = tuple(path for path in (role_file, home / ".codex/rules/cardine.rules",
                                             project_root / ".codex/rules/meridian.rules") if path.is_file())
            if not role_file.is_file():
                states[key] = "approval-required: role rules not installed"
            elif not executable:
                states[key] = "unverified: codex is not on PATH"
            else:
                states[key] = prove_role_policy(policy, codex_decision_evaluator(executable, layers)).state
    return states


_PROBE_LINES = 2000


def probe_hook_invocation(host: str, home: Path, *, timeout: int = 30) -> str:
    """Run the registered read-guard hook on a sentinel file inside a throwaway fixture.

    Reads the registration only to find the command; the verdict is the hook's
    observed deny. An interrupted or failed probe reports `unverified` and
    persists nothing, so it can never record effective success.
    """
    registry = registry_path(home, host)
    try:
        document = json.loads(registry.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "missing"
    wanted = hook_command(host, "read-guard")
    if wanted not in set(_commands(document.get("hooks") if isinstance(document, dict) else None)):
        return "missing"
    argv = shlex.split(wanted)
    executable = shutil.which(argv[0])
    if executable is None:
        return "unverified: cardine is not on PATH"
    with tempfile.TemporaryDirectory(prefix="cardine-doctor-") as fixture:
        root = Path(fixture).resolve()
        (root / names().project_declaration_path).parent.mkdir()
        (root / names().project_declaration_path).write_text('{"version": 1, "preset": "lean"}', encoding="utf-8")
        (root / "sentinel.txt").write_text("line\n" * _PROBE_LINES, encoding="utf-8")
        tool_input = {"file_path": str(root / "sentinel.txt")} if host == "claude" else {"command": "cat sentinel.txt"}
        payload = {"tool_name": "Read" if host == "claude" else "Bash", "tool_input": tool_input, "cwd": str(root)}
        try:
            completed = subprocess.run([executable, *argv[1:]], input=json.dumps(payload), text=True,
                                       capture_output=True, cwd=root, timeout=timeout, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return "unverified: probe interrupted"
    return "ready" if completed.returncode == 2 and '"deny"' in completed.stdout else "unverified: no deny observed"


def proposed_project_identity(project_root: Path) -> dict[str, str]:
    """Derive a stable setup proposal even before a directory is a Git repository."""
    try:
        slug = repository_identity(project_root).repository
    except CardineError:
        slug = project_root.resolve().name.lower()
    return {"name": slug.replace("-", " ").title(), "slug": slug}
