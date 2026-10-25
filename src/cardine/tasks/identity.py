"""Helpers extracted from the legacy CLI; see the module split plan."""

from __future__ import annotations

from cardine.shared.git import scoped_observation

from cardine.shared.git import _run_git

from cardine.shared.layout import names

from cardine.shared.errors import CardineError
from cardine.shared.git import primary_project_root
from cardine.shared.models import NUMERIC_TASK_ALIAS
from cardine.shared.models import ProjectLocations
from cardine.shared.models import ResolvedTaskIdentity
from cardine.shared.models import SAFE_PATH_COMPONENT
from cardine.shared.models import STRUCTURED_TASK_ID
from cardine.shared.models import TaskIdentityContext
from cardine.shared.models import TaskIdentityPolicy
from cardine.shared.project import _safe_project_path
from cardine.shared.project import read_project_declaration
from dataclasses import dataclass
from pathlib import Path
import json
import re
import sys
import unicodedata


def _safe_component(value: str, label: str) -> str:
    """Return one unambiguous, portable path component."""
    normalized = unicodedata.normalize("NFKC", value).strip().lower()
    if not normalized or normalized in {".", ".."}:
        raise CardineError(f"{label} is empty or traversing")
    if normalized != value.strip().lower() or not SAFE_PATH_COMPONENT.fullmatch(normalized):
        raise CardineError(f"{label} is not an unambiguous portable path component: {value!r}")
    return normalized


def canonical_task_id(value: str) -> str:
    normalized = value.strip().lower()
    match = re.fullmatch(r"(?:task-)?([0-9]+)", normalized)
    if match is None:
        raise CardineError(f"invalid task ID: {value!r}")
    number = match.group(1)
    if int(number) <= 0 or number != str(int(number)).zfill(len(number)):
        raise CardineError(f"ambiguous task ID: {value!r}")
    return f"task-{number}"


def task_identity_json(project_root: Path, identity: ResolvedTaskIdentity) -> dict[str, object]:
    """Render task identity without consulting mutable execution state."""
    return identity.as_json(project_root)


@scoped_observation
def resolve_project_locations(project_root: Path) -> ProjectLocations:
    """Read canonical locations exclusively from the project declaration."""
    from cardine.shared.snapshot_adapters import locations_adapter
    adapter = locations_adapter.get()
    if adapter is not None:
        return adapter(project_root)
    declaration = read_project_declaration(primary_project_root(project_root))
    if declaration is None:
        raise CardineError("missing project configuration: .cardine/project.json; run cardine setup --apply")
    locations = declaration.get("locations", {})
    def location(key, default):
        return _safe_project_path(locations.get(key, default), "locations." + key)
    return ProjectLocations(
        queue=location("queue", "tasks/QUEUE.md"),
        task_roots=tuple(_safe_project_path(value, "locations.taskRoots")
                         for value in locations.get("taskRoots", ["tasks"])),
        adr_log=location("adrLog", "docs/ARCHITECTURE_DECISIONS.md"),
        handoff_root=location("handoffRoot", "tasks/handoffs"),
        review_root=location("reviewRoot", "tasks/reviews"),
        plan=location("plan", "PROJECT_PLAN.md"),
    )


@dataclass(frozen=True)
class _TaskAuthority:
    canonical_id: str
    task_paths: tuple[Path, ...]
    queue_links: tuple[Path, ...]
    queue_records: int


def parse_task_identity_policy(declaration: object) -> TaskIdentityPolicy:
    """Validate the closed task-identity declaration schema."""
    if not isinstance(declaration, dict):
        raise CardineError("task identity declaration must be a JSON object")
    if set(declaration) != {"version", "mode"}:
        raise CardineError("task identity declaration accepts only version and mode")
    if type(declaration["version"]) is not int or declaration["version"] != 1:
        raise CardineError(f"unsupported task identity policy version: {declaration['version']!r}")
    if declaration["mode"] not in ("opaque", "milestone"):
        raise CardineError(f"unsupported task identity mode: {declaration['mode']!r}")
    return TaskIdentityPolicy(version=1, mode=str(declaration["mode"]))


def read_task_identity_policy(project_root: Path) -> TaskIdentityPolicy:
    declaration = read_project_declaration(project_root)
    if declaration is not None:
        return TaskIdentityPolicy(version=1, mode=declaration.get("taskIdentity", {}).get("mode", "opaque"))
    path = project_root / names().task_identity_path
    if not path.exists():
        return TaskIdentityPolicy(version=1, mode="opaque")
    if not path.is_file():
        raise CardineError(f"invalid task identity declaration: {path}")
    try:
        declaration = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise CardineError(f"invalid task identity declaration: {path}") from error
    return parse_task_identity_policy(declaration)


def _clean_queue_id(cell: str) -> tuple[str, str | None]:
    cell = cell.strip().strip("`")
    link = re.fullmatch(r"\[([^]]+)\]\(([^)]+)\)", cell)
    if link:
        return link.group(1).strip().strip("`"), link.group(2).strip()
    return cell, None


def _task_authorities(project_root: Path, locations: ProjectLocations, *, states: dict | None = None) -> dict[str, _TaskAuthority]:
    from cardine.tasks.contract_fields import snapshot_record_path
    # Stable filenames support records awaiting explicit creation/import and old
    # sparse snapshots. Registered recordPath always overrides filesystem discovery.
    task_paths = {}
    excluded = {"QUEUE.md", "QUEUE_ARCHIVE.md", "QUEUE_TEMPLATE.md", "TASK_BLUEPRINT.md"}
    for root in locations.task_roots:
        for path in (project_root / root).rglob("*.md"):
            if path.name in excluded or {"handoffs", "reviews"}.intersection(path.relative_to(project_root / root).parts):
                continue
            match = re.match(r"^(M[1-9][0-9]*-[A-Za-z][A-Za-z0-9_]*-[0-9]{3}|(?:TASK-)?[0-9]+)(?:-|$)", path.stem, re.I)
            canonical = match.group(1) if match else path.stem
            task_paths.setdefault(canonical, set()).add(path.resolve())
    if states is None:
        states = {}
        for path in sorted((project_root / names().tasks_path).glob("*.json")):
            try:
                states[path.stem] = json.loads(path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                # State readers report malformed state; identity never repairs it.
                continue
    for task_id, state in states.items():
        human = (state or {}).get("contract", {}) if isinstance(state, dict) else {}
        if "recordPath" in human:
            task_paths[task_id] = {snapshot_record_path(project_root, human)}
    return {canonical: _TaskAuthority(canonical, tuple(sorted(paths)), (), 0)
            for canonical, paths in task_paths.items()}


def _numeric_alias_key(value: str) -> str | None:
    match = NUMERIC_TASK_ALIAS.fullmatch(value)
    if match is None or int(match.group(1)) <= 0:
        return None
    return match.group(1)


def _authority_matches(authorities: dict[str, _TaskAuthority], supplied_id: str) -> list[str]:
    if supplied_id in authorities:
        return [supplied_id]
    structured = STRUCTURED_TASK_ID.fullmatch(supplied_id.upper())
    if structured:
        candidate = supplied_id.upper()
        return [candidate] if candidate in authorities else []
    numeric = _numeric_alias_key(supplied_id)
    if numeric is None:
        return []
    return [canonical for canonical in authorities if _numeric_alias_key(canonical) == numeric]


def _identity_names(canonical_id: str, kind: str) -> tuple[str, str, dict[str, object] | None]:
    """Derive branch and artifact names without spawning Git."""
    structured = STRUCTURED_TASK_ID.fullmatch(canonical_id)
    semantic: dict[str, object] | None = None
    if kind == "structured":
        if structured is None:
            raise CardineError(f"invalid structured task ID: {canonical_id!r}")
        semantic = {
            "milestone": int(structured.group("milestone")),
            "workstream": structured.group("workstream"),
            "ordinal": int(structured.group("ordinal")),
        }
        branch = canonical_id.lower()
    else:
        numeric = _numeric_alias_key(canonical_id)
        branch = f"task-{numeric}" if numeric is not None else canonical_id.lower()
    artifact = canonical_id
    normalized = unicodedata.normalize("NFKC", artifact)
    if normalized != artifact or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", artifact):
        raise CardineError(f"task ID is not a safe filesystem component: {canonical_id!r}")
    if artifact in (".", "..") or artifact.casefold() in {"con", "prn", "aux", "nul"} or artifact.endswith((".", ".lock")):
        raise CardineError(f"task ID is a reserved filesystem or Git component: {canonical_id!r}")
    return branch, artifact, semantic


def _check_branch_name(canonical_id: str, branch: str) -> None:
    checked = _run_git(None, 'check-ref-format', '--branch', branch, text=True)
    if checked.returncode != 0 or not SAFE_PATH_COMPONENT.fullmatch(branch):
        raise CardineError(f"task ID does not derive a safe Git branch: {canonical_id!r}")


def _identity_derivations(canonical_id: str, kind: str) -> tuple[str, str, dict[str, object] | None]:
    branch, artifact, semantic = _identity_names(canonical_id, kind)
    _check_branch_name(canonical_id, branch)
    return branch, artifact, semantic


@scoped_observation
def resolve_task_identity(
    project_root: Path,
    supplied_id: str,
    intent: str,
    *,
    check_queue_links: bool = True,
    context: TaskIdentityContext | None = None,
    allow_archived_queue_links: bool = False,
) -> ResolvedTaskIdentity:
    if intent not in ("existing", "new"):
        raise CardineError(f"unsupported task identity intent: {intent!r}")
    project_root = project_root.resolve()
    supplied = supplied_id.strip()
    if not supplied or supplied != supplied_id.strip() or any(separator in supplied for separator in ("/", "\\")):
        raise CardineError(f"invalid task ID: {supplied_id!r}")
    context = context or task_identity_context(project_root)
    policy = context.policy
    locations = context.locations
    authorities = context.authorities
    matches = _authority_matches(authorities, supplied)
    if len(matches) > 1:
        raise CardineError(f"ambiguous task identity {supplied_id!r}: {', '.join(sorted(matches))}")
    if intent == "existing" and not matches:
        raise CardineError(f"unknown task identity: {supplied_id!r}")

    if matches:
        canonical = matches[0]
    elif policy.mode == "milestone":
        canonical = supplied.upper()
        if STRUCTURED_TASK_ID.fullmatch(canonical) is None:
            raise CardineError("new milestone-mode tasks must use M<milestone>-<WORKSTREAM>-<ordinal>")
    else:
        canonical = supplied

    structured = STRUCTURED_TASK_ID.fullmatch(canonical)
    structured_casefold = STRUCTURED_TASK_ID.fullmatch(canonical.upper())
    if policy.mode == "milestone" and structured_casefold and structured is None:
        raise CardineError(f"authoritative structured task ID is not canonical uppercase: {canonical!r}")
    if policy.mode == "milestone" and structured:
        kind = "structured"
    elif policy.mode == "milestone":
        if not matches:
            raise CardineError(f"unknown legacy task identity: {supplied_id!r}")
        kind = "legacy-opaque"
    else:
        kind = "opaque"

    branch, artifact, semantic = _identity_derivations(canonical, kind)
    authority = authorities.get(canonical)
    if authority is not None:
        if len(authority.task_paths) > 1 or authority.queue_records > 1 or len(authority.queue_links) > 1:
            raise CardineError(f"ambiguous authoritative artifacts for task {canonical}")
        if check_queue_links:
            links = authority.queue_links
            if allow_archived_queue_links and len(authority.task_paths) == 1:
                record = authority.task_paths[0]
                links = tuple(
                    record if not link.exists() and record == link.parent / "done" / link.name else link
                    for link in links
                )
            linked_existing = tuple(path for path in links if path.is_file())
            if authority.queue_links and len(linked_existing) != len(authority.queue_links):
                raise CardineError(f"queue link for task {canonical} does not resolve to an existing task file")
            if linked_existing and not authority.task_paths:
                raise CardineError(f"queue and task authorities disagree for {canonical}")
            if authority.task_paths and linked_existing and authority.task_paths[0] != linked_existing[0]:
                raise CardineError(f"task and queue authorities disagree for {canonical}")
        paths = authority.task_paths
        if not paths:
            raise CardineError(f"task {canonical} has no authoritative task file")
        task_path = paths[0]
    else:
        task_path = (project_root / locations.task_roots[0] / f"{artifact}.md").resolve()

    for other_id in authorities:
        if other_id == canonical:
            continue
        try:
            other_kind = "structured" if policy.mode == "milestone" and STRUCTURED_TASK_ID.fullmatch(other_id) else "opaque"
            other_branch, other_artifact, _other_semantic = _identity_names(other_id, other_kind)
            if other_branch.casefold() != branch.casefold() and other_artifact.casefold() != artifact.casefold():
                continue
            # Only a colliding ID needs the Git ref check, so the subprocess cost
            # does not grow with the number of known tasks.
            _check_branch_name(other_id, other_branch)
        except CardineError:
            continue
        raise CardineError(f"task identity collision between {canonical!r} and {other_id!r}")

    return ResolvedTaskIdentity(
        policy_version=policy.version,
        mode=policy.mode,
        kind=kind,
        canonical_id=canonical,
        branch_name=branch,
        artifact_stem=artifact,
        semantic_tuple=semantic,
        task_path=task_path,
        queue_path=(project_root / locations.queue).resolve(),
        handoff_path=(project_root / locations.handoff_root / f"{artifact}.md").resolve(),
        review_path=(project_root / locations.review_root / f"{artifact}.md").resolve(),
    )


@scoped_observation
def task_identity_context(project_root: Path, *, states: dict | None = None) -> TaskIdentityContext:
    """Build the authoritative identity inputs once for a command."""
    project_root = project_root.resolve()
    policy = read_task_identity_policy(project_root)
    locations = resolve_project_locations(project_root)
    return TaskIdentityContext(policy, locations, _task_authorities(project_root, locations, states=states))


def next_milestone_task_identity(
    project_root: Path, milestone: str, workstream: str
) -> ResolvedTaskIdentity:
    """Resolve the next unused structured identity from the task authorities."""
    context = task_identity_context(project_root)
    if context.policy.mode != "milestone":
        raise CardineError("next task identity requires a milestone task-identity policy")
    if re.fullmatch(r"[1-9][0-9]*", milestone) is None:
        raise CardineError("invalid milestone: expected a positive integer without a leading zero")
    if re.fullmatch(r"[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*", workstream) is None:
        raise CardineError("invalid workstream: expected canonical uppercase task-ID grammar")

    project_root = project_root.resolve()
    authorities = context.authorities
    highest = 0
    for canonical_id in authorities:
        structured = STRUCTURED_TASK_ID.fullmatch(canonical_id)
        similar = STRUCTURED_TASK_ID.fullmatch(canonical_id.upper())
        if similar is None:
            continue
        if similar.group("milestone") != milestone or similar.group("workstream") != workstream:
            continue
        # Reuse the normal resolver to reject duplicate, mismatched, or
        # non-canonical authoritative records before deriving a new ordinal.
        resolved = resolve_task_identity(project_root, canonical_id, "existing", context=context)
        if structured is not None:
            highest = max(highest, int(structured.group("ordinal")))

    if highest >= 999:
        raise CardineError(f"next ordinal exceeds 999 for M{milestone}-{workstream}")
    return resolve_task_identity(
        project_root, f"M{milestone}-{workstream}-{highest + 1:03d}", "new", context=context
    )


def find_task_file(project_root: Path, task_id: str) -> Path:
    """Locate a task through the shared declaration-driven identity resolver."""
    return resolve_task_identity(project_root, task_id, "existing").task_path
