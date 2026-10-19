"""Helpers extracted from the legacy CLI; see the module split plan."""

from __future__ import annotations

from cardine.shared.layout import names

from cardine.shared.errors import MeridianError
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
from cardine.shared.text import read_task_field
from cardine.shared import project as shared_project
from dataclasses import dataclass
from pathlib import Path
import json
import re
import subprocess
import sys
import unicodedata


def _safe_component(value: str, label: str) -> str:
    """Return one unambiguous, portable path component."""
    normalized = unicodedata.normalize("NFKC", value).strip().lower()
    if not normalized or normalized in {".", ".."}:
        raise MeridianError(f"{label} is empty or traversing")
    if normalized != value.strip().lower() or not SAFE_PATH_COMPONENT.fullmatch(normalized):
        raise MeridianError(f"{label} is not an unambiguous portable path component: {value!r}")
    return normalized


def canonical_task_id(value: str) -> str:
    normalized = value.strip().lower()
    match = re.fullmatch(r"(?:task-)?([0-9]+)", normalized)
    if match is None:
        raise MeridianError(f"invalid task ID: {value!r}")
    number = match.group(1)
    if int(number) <= 0 or number != str(int(number)).zfill(len(number)):
        raise MeridianError(f"ambiguous task ID: {value!r}")
    return f"task-{number}"


def task_identity_json(project_root: Path, identity: ResolvedTaskIdentity) -> dict[str, object]:
    """Render task identity without consulting mutable execution state."""
    return identity.as_json(project_root)


def resolve_project_locations(project_root: Path) -> ProjectLocations:
    """Resolve project customizations declared after execution-assets.

    The same resolver backs the CLI and the hook, avoiding separate default
    paths for a project's queue and its nested task records.
    """
    project_root = primary_project_root(project_root)
    declaration = read_project_declaration(project_root)
    workflow = project_root / "PROJECT_WORKFLOW.md"
    zone = ""
    block_zone = ""
    if workflow.is_file():
        workflow_text = workflow.read_text(encoding="utf-8")
        block_match = re.search(
            r"<!-- MERIDIAN:BEGIN capability=execution-assets .*?<!-- MERIDIAN:END -->",
            workflow_text,
            re.DOTALL,
        )
        block_zone = block_match.group(0) if block_match else ""
        match = re.search(
            r"<!-- MERIDIAN:BEGIN capability=execution-assets .*?<!-- MERIDIAN:END -->\s*(.*?)(?=^## |\Z)",
            workflow_text,
            re.MULTILINE | re.DOTALL,
        )
        zone = match.group(1) if match else ""
    queue_matches = re.findall(r"`([^`]*queue[^`]*\.md)`", zone, re.IGNORECASE)
    queues = [Path(path) for path in dict.fromkeys(path for path in queue_matches if "archive" not in path.lower())]
    if len(queues) != 1:
        block_matches = re.findall(r"`([^`]*queue[^`]*\.md)`", block_zone, re.IGNORECASE)
        queues = [Path(path) for path in dict.fromkeys(path for path in block_matches if "archive" not in path.lower())]
    queue = queues[0] if len(queues) == 1 else Path("tasks/QUEUE.md")
    roots = [Path("tasks")]
    for raw in re.findall(r"task files live (?:at|under)\s+`([^`]+)`", zone + "\n" + block_zone, re.IGNORECASE):
        prefix = raw.split("<", 1)[0].rstrip("/")
        candidate = Path(prefix)
        root = candidate.parent if candidate.suffix else candidate
        if root not in roots:
            roots.append(root)
    adr_matches = re.findall(r"ADR log(?:\s+is|\s+at)?\s+`([^`]+)`", zone, re.IGNORECASE)
    if len(set(adr_matches)) != 1:
        adr_matches = re.findall(r"ADR log(?:\s+is|\s+at)?\s+`([^`]+)`", block_zone, re.IGNORECASE)
    adr_log = Path(adr_matches[0]) if len(set(adr_matches)) == 1 else Path("docs/ARCHITECTURE_DECISIONS.md")
    handoff_matches = re.findall(r"[Cc]ompletion handoffs live at `([^`]+)/<TASK-ID>\.md`", zone)
    if len(set(handoff_matches)) != 1:
        handoff_matches = re.findall(r"[Cc]ompletion handoffs live at `([^`]+)/<TASK-ID>\.md`", block_zone)
    review_matches = re.findall(r"(?:durable )?review records (?:live )?at `([^`]+)/<TASK-ID>\.md`", zone, re.IGNORECASE)
    if len(set(review_matches)) != 1:
        review_matches = re.findall(r"(?:durable )?review records (?:live )?at `([^`]+)/<TASK-ID>\.md`", block_zone, re.IGNORECASE)
    handoff_root = Path(handoff_matches[0]) if len(set(handoff_matches)) == 1 else Path("tasks/handoffs")
    review_root = Path(review_matches[0]) if len(set(review_matches)) == 1 else Path("tasks/reviews")
    legacy_used = declaration is None and (queue != Path("tasks/QUEUE.md") or len(roots) != 1 or adr_log != Path("docs/ARCHITECTURE_DECISIONS.md") or handoff_root != Path("tasks/handoffs") or review_root != Path("tasks/reviews"))
    if declaration is not None:
        declared_locations = declaration.get("locations", {})
        assert isinstance(declared_locations, dict)
        if "queue" in declared_locations:
            queue = _safe_project_path(declared_locations["queue"], "locations.queue")
        if "taskRoots" in declared_locations:
            roots = [_safe_project_path(value, "locations.taskRoots") for value in declared_locations["taskRoots"]]
        if "adrLog" in declared_locations:
            adr_log = _safe_project_path(declared_locations["adrLog"], "locations.adrLog")
        if "handoffRoot" in declared_locations:
            handoff_root = _safe_project_path(declared_locations["handoffRoot"], "locations.handoffRoot")
        if "reviewRoot" in declared_locations:
            review_root = _safe_project_path(declared_locations["reviewRoot"], "locations.reviewRoot")
        plan = _safe_project_path(declared_locations["plan"], "locations.plan") if "plan" in declared_locations else Path("PROJECT_PLAN.md")
    else:
        plan = Path("PROJECT_PLAN.md")
    for label, path in (
        ("queue", queue),
        ("ADR log", adr_log),
        ("handoff root", handoff_root),
        ("review root", review_root),
        *(("task root", root) for root in roots),
    ):
        if path.is_absolute() or ".." in path.parts:
            raise MeridianError(f"canonical {label} must be a safe project-relative path: {path}")
    project_root = project_root.resolve()
    if legacy_used and project_root not in shared_project._LEGACY_LOCATION_WARNING_PROJECTS:
        print("DEPRECATED: resolve canonical locations with .meridian/project.json", file=sys.stderr)
        shared_project._LEGACY_LOCATION_WARNING_PROJECTS.add(project_root)
    return ProjectLocations(
        queue=queue,
        task_roots=tuple(roots),
        adr_log=adr_log,
        handoff_root=handoff_root,
        review_root=review_root,
        plan=plan,
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
        raise MeridianError("task identity declaration must be a JSON object")
    if set(declaration) != {"version", "mode"}:
        raise MeridianError("task identity declaration accepts only version and mode")
    if type(declaration["version"]) is not int or declaration["version"] != 1:
        raise MeridianError(f"unsupported task identity policy version: {declaration['version']!r}")
    if declaration["mode"] not in ("opaque", "milestone"):
        raise MeridianError(f"unsupported task identity mode: {declaration['mode']!r}")
    return TaskIdentityPolicy(version=1, mode=str(declaration["mode"]))


def read_task_identity_policy(project_root: Path) -> TaskIdentityPolicy:
    path = project_root / names().task_identity_path
    if not path.exists():
        return TaskIdentityPolicy(version=1, mode="opaque")
    if not path.is_file():
        raise MeridianError(f"invalid task identity declaration: {path}")
    try:
        declaration = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise MeridianError(f"invalid task identity declaration: {path}") from error
    return parse_task_identity_policy(declaration)


def _task_record_id(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    for pattern in (
        r"^>\s*\*\*ID\*\*:\s*`([^`]+)`\s*$",
        r"^ID:\s*`?([^`\s]+)`?\s*$",
    ):
        match = re.search(pattern, text, re.MULTILINE)
        if match and "[" not in match.group(1) and "<" not in match.group(1):
            return match.group(1)
    return None


def _clean_queue_id(cell: str) -> tuple[str, str | None]:
    cell = cell.strip().strip("`")
    link = re.fullmatch(r"\[([^]]+)\]\(([^)]+)\)", cell)
    if link:
        return link.group(1).strip().strip("`"), link.group(2).strip()
    return cell, None


def _task_authorities(project_root: Path, locations: ProjectLocations) -> dict[str, _TaskAuthority]:
    task_paths: dict[str, set[Path]] = {}
    queue_links: dict[str, set[Path]] = {}
    queue_counts: dict[str, int] = {}
    excluded_names = {"QUEUE.md", "QUEUE_ARCHIVE.md", "QUEUE_TEMPLATE.md", "TASK_BLUEPRINT.md"}
    for root in locations.task_roots:
        absolute = project_root / root
        if not absolute.is_dir():
            continue
        for path in absolute.rglob("*.md"):
            relative_parts = path.relative_to(absolute).parts
            if path.name in excluded_names or {"handoffs", "reviews"}.intersection(relative_parts):
                continue
            canonical = _task_record_id(path) or path.stem
            task_paths.setdefault(canonical, set()).add(path.resolve())

    queue_path = (project_root / locations.queue).resolve()
    if queue_path.is_file():
        lines = queue_path.read_text(encoding="utf-8").splitlines()
        headers: list[str] | None = None
        for line in lines:
            if not line.lstrip().startswith("|"):
                headers = None
                continue
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if "ID" in cells:
                headers = cells
                continue
            if headers is None or len(cells) != len(headers) or set("".join(cells)) <= {"-", ":"}:
                continue
            canonical, inline_link = _clean_queue_id(cells[headers.index("ID")])
            if not canonical or canonical in ("ID", "[ID]"):
                continue
            queue_counts[canonical] = queue_counts.get(canonical, 0) + 1
            link_value = inline_link
            for heading in ("Task file", "File"):
                if heading in headers:
                    _label, candidate = _clean_queue_id(cells[headers.index(heading)])
                    link_value = candidate or link_value
            if link_value and "://" not in link_value and not link_value.startswith("#"):
                resolved = (queue_path.parent / link_value.split("#", 1)[0]).resolve()
                if project_root.resolve() not in (resolved, *resolved.parents):
                    raise MeridianError(f"queue task link escapes the project: {link_value}")
                queue_links.setdefault(canonical, set()).add(resolved)

    identities = set(task_paths) | set(queue_counts)
    return {
        canonical: _TaskAuthority(
            canonical,
            tuple(sorted(task_paths.get(canonical, set()))),
            tuple(sorted(queue_links.get(canonical, set()))),
            queue_counts.get(canonical, 0),
        )
        for canonical in identities
    }


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
            raise MeridianError(f"invalid structured task ID: {canonical_id!r}")
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
        raise MeridianError(f"task ID is not a safe filesystem component: {canonical_id!r}")
    if artifact in (".", "..") or artifact.casefold() in {"con", "prn", "aux", "nul"} or artifact.endswith((".", ".lock")):
        raise MeridianError(f"task ID is a reserved filesystem or Git component: {canonical_id!r}")
    return branch, artifact, semantic


def _check_branch_name(canonical_id: str, branch: str) -> None:
    checked = subprocess.run(
        ["git", "check-ref-format", "--branch", branch],
        text=True,
        capture_output=True,
        check=False,
    )
    if checked.returncode != 0 or not SAFE_PATH_COMPONENT.fullmatch(branch):
        raise MeridianError(f"task ID does not derive a safe Git branch: {canonical_id!r}")


def _identity_derivations(canonical_id: str, kind: str) -> tuple[str, str, dict[str, object] | None]:
    branch, artifact, semantic = _identity_names(canonical_id, kind)
    _check_branch_name(canonical_id, branch)
    return branch, artifact, semantic


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
        raise MeridianError(f"unsupported task identity intent: {intent!r}")
    project_root = project_root.resolve()
    supplied = supplied_id.strip()
    if not supplied or supplied != supplied_id.strip() or any(separator in supplied for separator in ("/", "\\")):
        raise MeridianError(f"invalid task ID: {supplied_id!r}")
    context = context or task_identity_context(project_root)
    policy = context.policy
    locations = context.locations
    authorities = context.authorities
    matches = _authority_matches(authorities, supplied)
    if len(matches) > 1:
        raise MeridianError(f"ambiguous task identity {supplied_id!r}: {', '.join(sorted(matches))}")
    if intent == "existing" and not matches:
        raise MeridianError(f"unknown task identity: {supplied_id!r}")

    if matches:
        canonical = matches[0]
    elif policy.mode == "milestone":
        canonical = supplied.upper()
        if STRUCTURED_TASK_ID.fullmatch(canonical) is None:
            raise MeridianError("new milestone-mode tasks must use M<milestone>-<WORKSTREAM>-<ordinal>")
    else:
        canonical = supplied

    structured = STRUCTURED_TASK_ID.fullmatch(canonical)
    structured_casefold = STRUCTURED_TASK_ID.fullmatch(canonical.upper())
    if policy.mode == "milestone" and structured_casefold and structured is None:
        raise MeridianError(f"authoritative structured task ID is not canonical uppercase: {canonical!r}")
    if policy.mode == "milestone" and structured:
        kind = "structured"
    elif policy.mode == "milestone":
        if not matches:
            raise MeridianError(f"unknown legacy task identity: {supplied_id!r}")
        kind = "legacy-opaque"
    else:
        kind = "opaque"

    branch, artifact, semantic = _identity_derivations(canonical, kind)
    authority = authorities.get(canonical)
    if authority is not None:
        if len(authority.task_paths) > 1 or authority.queue_records > 1 or len(authority.queue_links) > 1:
            raise MeridianError(f"ambiguous authoritative artifacts for task {canonical}")
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
                raise MeridianError(f"queue link for task {canonical} does not resolve to an existing task file")
            if linked_existing and not authority.task_paths:
                raise MeridianError(f"queue and task authorities disagree for {canonical}")
            if authority.task_paths and linked_existing and authority.task_paths[0] != linked_existing[0]:
                raise MeridianError(f"task and queue authorities disagree for {canonical}")
        paths = authority.task_paths
        if not paths:
            raise MeridianError(f"task {canonical} has no authoritative task file")
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
        except MeridianError:
            continue
        raise MeridianError(f"task identity collision between {canonical!r} and {other_id!r}")

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


def task_identity_context(project_root: Path) -> TaskIdentityContext:
    """Build the authoritative identity inputs once for a command."""
    project_root = project_root.resolve()
    policy = read_task_identity_policy(project_root)
    locations = resolve_project_locations(project_root)
    return TaskIdentityContext(policy, locations, _task_authorities(project_root, locations))


def next_milestone_task_identity(
    project_root: Path, milestone: str, workstream: str
) -> ResolvedTaskIdentity:
    """Resolve the next unused structured identity from the task authorities."""
    context = task_identity_context(project_root)
    if context.policy.mode != "milestone":
        raise MeridianError("next task identity requires a milestone task-identity policy")
    if re.fullmatch(r"[1-9][0-9]*", milestone) is None:
        raise MeridianError("invalid milestone: expected a positive integer without a leading zero")
    if re.fullmatch(r"[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*", workstream) is None:
        raise MeridianError("invalid workstream: expected canonical uppercase task-ID grammar")

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
        raise MeridianError(f"next ordinal exceeds 999 for M{milestone}-{workstream}")
    return resolve_task_identity(
        project_root, f"M{milestone}-{workstream}-{highest + 1:03d}", "new", context=context
    )


def find_task_file(project_root: Path, task_id: str) -> Path:
    """Locate a task through the shared declaration-driven identity resolver."""
    return resolve_task_identity(project_root, task_id, "existing").task_path
