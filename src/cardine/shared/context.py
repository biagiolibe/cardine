"""Helpers extracted from the legacy CLI; see the module split plan."""

from __future__ import annotations

from cardine.shared.authority import SPEC_HEADING_CITATION
from cardine.shared.authority import authority_entries
from cardine.shared.authority import resolve_authority_entry
from cardine.shared.constants import CONTEXT_PHASE_READS_BLOCK
from cardine.shared.constants import CONTEXT_PHASE_READ_LINE
from cardine.shared.constants import CONTEXT_SIZE_CONFIG_PATH
from cardine.shared.constants import CONTEXT_SIZE_ROLES
from cardine.shared.errors import MeridianError
from cardine.tasks.identity import find_task_file
from cardine.tasks.identity import resolve_project_locations
from cardine.templates.mode import detect_mode
from pathlib import Path
import json
import re

def _context_path_references(text: str) -> list[Path]:
    """Return safe project-relative Markdown paths cited by a document.

    The workflow format uses both inline-code paths and Markdown links.  This
    intentionally recognizes only Markdown documents: command examples and
    arbitrary code literals are not startup reads.
    """
    raw = re.findall(r"`([^`]+\.md)`|\]\(([^)#]+\.md)(?:#[^)]+)?\)", text, re.IGNORECASE)
    paths: list[Path] = []
    for inline, link in raw:
        candidate = Path(inline or link)
        if candidate.is_absolute() or ".." in candidate.parts:
            continue
        if candidate not in paths:
            paths.append(candidate)
    return paths


def _context_relative_references(path: Path, text: str) -> list[Path]:
    """Resolve citations relative to the document that contains them."""
    references: list[Path] = []
    for candidate in _context_path_references(text):
        # Workflow prose conventionally names canonical project locations
        # (`docs/...`, `tasks/...`) from project root, while Markdown links
        # such as `README.md` remain document-relative.
        resolved = candidate if candidate.parts and candidate.parts[0] in {"docs", "tasks", ".meridian"} else path.parent / candidate
        if resolved not in references:
            references.append(resolved)
    return [item for item in references if item.parts[:2] != (".meridian", "tasks")]


def _context_phase_reads(path: Path, text: str) -> dict[Path, str]:
    """Map each document a routed workflow defers to the phase that first needs it.

    Only lines of the form `- At <phase>: <documents>` inside a
    `capability=phase-reads` managed block count; `At start` lines and every
    other citation stay startup reads.
    """
    deferred: dict[Path, str] = {}
    for block in CONTEXT_PHASE_READS_BLOCK.findall(text):
        for phase, documents in CONTEXT_PHASE_READ_LINE.findall(block):
            if phase.strip().lower() == "start":
                continue
            for cited in _context_relative_references(path, documents):
                deferred.setdefault(cited, phase.strip())
    return deferred


def _context_router(project_root: Path) -> Path:
    for name in ("AGENTS.md", "CLAUDE.md"):
        if (project_root / name).is_file():
            return Path(name)
    # Report the conventional router as missing instead of silently choosing a
    # template or an unrelated project file.
    return Path("AGENTS.md")


def _context_routed_workflow(project_root: Path, mode: str, role: str, router: Path) -> Path:
    if mode == "lean-delivery":
        return Path("PROJECT_WORKFLOW.md")
    text = (project_root / router).read_text(encoding="utf-8") if (project_root / router).is_file() else ""
    patterns = {
        "status": r"Status, project question, or tech-design alignment.*?`([^`]+\.md)`",
        "design": r"Status, project question, or tech-design alignment.*?`([^`]+\.md)`",
        "implementation": r"Proceed with <TASK-ID>.*?`([^`]+\.md)`",
        "review": r"Review <TASK-ID>.*?`([^`]+\.md)`",
        "remediation": r"Address review <TASK-ID>.*?`([^`]+\.md)`",
        "lifecycle": r"(?:Run lifecycle|Accept) <TASK-ID>.*?`([^`]+\.md)`",
    }
    match = re.search(patterns[role], text)
    if not match:
        raise MeridianError(f"cannot resolve the {role} route from {router}")
    path = Path(match.group(1))
    if path.is_absolute() or ".." in path.parts:
        raise MeridianError(f"unsafe {role} route in {router}: {path}")
    return path


def _context_file_record(project_root: Path, path: Path, category: str, label: str | None = None, text: str | None = None) -> dict[str, object]:
    target = project_root / path
    record: dict[str, object] = {"path": path.as_posix(), "label": label or path.as_posix(), "category": category}
    if text is None and not target.is_file():
        record.update({"status": "missing", "bytes": None, "lines": None, "estimated_tokens": None, "over_threshold": False})
        return record
    content = text if text is not None else target.read_text(encoding="utf-8")
    byte_count = len(content.encode("utf-8"))
    record.update({
        "status": "present", "bytes": byte_count, "lines": len(content.splitlines()),
        "estimated_tokens": {"low": round(byte_count / 4), "high": round(byte_count / 3.3)},
        "over_threshold": False,
    })
    return record


def _context_configuration(project_root: Path) -> tuple[int | None, int]:
    """Read the shared context-size limits (bytes and router-file lines)."""
    config = project_root / CONTEXT_SIZE_CONFIG_PATH
    if not config.is_file():
        return None, 1000
    try:
        value = json.loads(config.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise MeridianError(f"invalid context-size configuration {config}: {error}") from error
    if not isinstance(value, dict) or value.get("version") != 1 or set(value) - {"version", "fileBytesThreshold", "routerFileLinesCeiling"}:
        raise MeridianError("context-size configuration must contain version 1 and optional fileBytesThreshold and routerFileLinesCeiling")
    threshold = value.get("fileBytesThreshold")
    ceiling = value.get("routerFileLinesCeiling", 1000)
    if threshold is not None and (type(threshold) is not int or threshold < 0):
        raise MeridianError("context-size fileBytesThreshold must be a non-negative integer")
    if type(ceiling) is not int or ceiling < 0:
        raise MeridianError("context-size routerFileLinesCeiling must be a non-negative integer")
    return threshold, ceiling


def _context_threshold(project_root: Path, override: int | None) -> int | None:
    if override is not None:
        return override
    return _context_configuration(project_root)[0]


def context_router_files(project_root: Path, workflow_mode: str | None = None) -> list[Path]:
    """Return the shared startup-router file set used by read guards and size checks."""
    mode = workflow_mode or detect_mode(project_root)
    files = {Path("LANGUAGE_POLICY.md"), Path("PROJECT_WORKFLOW.md")}
    router = _context_router(project_root)
    if (project_root / router).is_file():
        files.add(router)
    legacy = Path("docs/workflows/ENTRY_ROUTER.md")
    legacy_path = project_root / legacy
    if legacy_path.is_file():
        files.add(legacy)
        for line in legacy_path.read_text(encoding="utf-8").splitlines():
            if "always" in line.lower():
                files.update(_context_relative_references(legacy, line))
    for role in CONTEXT_SIZE_ROLES[mode]:
        try:
            files.add(_context_routed_workflow(project_root, mode, role, router))
        except MeridianError:
            continue
    return sorted((item for item in files if item.parts[:2] != (".meridian", "tasks")), key=lambda item: item.as_posix())


def context_size_report(project_root: Path, role: str, task_id: str | None = None, threshold: int | None = None,
                        workflow_mode: str | None = None) -> dict[str, object]:
    """Measure the documents a role is instructed to read without writing or executing a project command."""
    mode = workflow_mode or detect_mode(project_root)
    if role not in CONTEXT_SIZE_ROLES[mode]:
        allowed = ", ".join(CONTEXT_SIZE_ROLES[mode])
        raise MeridianError(f"role {role!r} is not available for {mode}; choose: {allowed}")
    effective_threshold = _context_threshold(project_root, threshold)
    _configured_threshold, router_ceiling = _context_configuration(project_root)
    router = _context_router(project_root)
    routed = _context_routed_workflow(project_root, mode, role, router)
    roots: list[tuple[Path, str]] = [(router, "router"), (routed, "routed-workflow"), (Path("PROJECT_WORKFLOW.md"), "always-read"), (Path("LANGUAGE_POLICY.md"), "always-read")]
    router_text = (project_root / router).read_text(encoding="utf-8") if (project_root / router).is_file() else ""
    route_paths = {Path(value) for value in re.findall(r"(?:read|use) `([^`]+\.md)`", router_text)}
    routed_target = project_root / routed
    deferred_phases = _context_phase_reads(routed, routed_target.read_text(encoding="utf-8")) if routed_target.is_file() else {}
    for path, _ in roots:
        deferred_phases.pop(path, None)
    records: list[dict[str, object]] = []
    seen: set[Path] = set()
    pending = roots[:]
    while pending:
        path, category = pending.pop(0)
        if path in seen or path.parts[:2] == (".meridian", "tasks"):
            continue
        seen.add(path)
        record = _context_file_record(project_root, path, category)
        records.append(record)
        target = project_root / path
        # A startup document may name further material for later, conditional
        # work.  Count only citations from the router and its selected route;
        # recursively following every incidental documentation link would turn
        # a bounded role read set into a repository crawl.
        if category == "routed-workflow" and target.is_file():
            for cited in _context_relative_references(path, target.read_text(encoding="utf-8")):
                if cited not in seen and cited not in deferred_phases:
                    pending.append((cited, "cited"))
        elif category == "router" and target.is_file():
            for cited in _context_relative_references(path, router_text):
                conditional_source_rule = cited.name == "CODE_ORGANIZATION.md" and role in {"status", "design", "lifecycle"}
                if cited not in route_paths and cited not in seen and cited not in deferred_phases and not conditional_source_rule:
                    pending.append((cited, "cited"))
    if task_id is not None:
        task = find_task_file(project_root, task_id)
        records.append(_context_file_record(project_root, task.relative_to(project_root), "task-record"))
        for entry in authority_entries(task.read_text(encoding="utf-8")):
            citation = SPEC_HEADING_CITATION.match(entry.strip())
            if citation and Path(citation.group(1)).parts[:2] == (".meridian", "tasks"):
                continue
            resolved, unresolved = resolve_authority_entry(project_root, entry)
            for source, heading, excerpt in resolved:
                records.append(_context_file_record(project_root, Path(source).relative_to(project_root) if Path(source).is_absolute() else Path(source), "authority-excerpt", f"{source} — {heading}", excerpt))
            for item in unresolved:
                records.append({"path": item, "label": item, "category": "authority-excerpt", "status": "missing", "bytes": None, "lines": None, "estimated_tokens": None, "over_threshold": False})
    for record in records:
        record["over_threshold"] = bool(effective_threshold is not None and isinstance(record["bytes"], int) and record["bytes"] > effective_threshold)
    present = [record for record in records if isinstance(record["bytes"], int)]
    total_bytes = sum(int(record["bytes"]) for record in present)
    locations = resolve_project_locations(project_root)
    unbounded = []
    for path, note in ((locations.queue, "The routed workflow reads this only through the queue briefing."), (locations.adr_log, "The routed workflow reads this only through meridian context authority.")):
        record = _context_file_record(project_root, path, "unbounded-reference")
        record["note"] = note
        record["over_threshold"] = bool(effective_threshold is not None and isinstance(record["bytes"], int) and record["bytes"] > effective_threshold)
        unbounded.append(record)
    deferred_documents = []
    for path, phase in deferred_phases.items():
        record = _context_file_record(project_root, path, "deferred")
        record["phase"] = phase
        deferred_documents.append(record)
    router_records = [_context_file_record(project_root, path, "router-read") for path in context_router_files(project_root, mode)]
    for record in router_records:
        record["over_router_ceiling"] = bool(record["status"] == "present" and isinstance(record["lines"], int) and record["lines"] > router_ceiling)
    exceeded = [str(record["label"]) for record in records if record["over_threshold"]]
    exceeded.extend(str(record["path"]) for record in router_records if record["over_router_ceiling"])
    return {
        "mode": mode, "role": role, "task": task_id, "estimate": "Estimated token range: bytes / 4 to bytes / 3.3; this is not tokenizer-accurate.",
        "threshold_bytes": effective_threshold, "files": records,
        "total": {"bytes": total_bytes, "lines": sum(int(record["lines"]) for record in present), "estimated_tokens": {"low": round(total_bytes / 4), "high": round(total_bytes / 3.3)}},
        "unbounded_documents": unbounded, "deferred_documents": deferred_documents, "router_file_lines_ceiling": router_ceiling,
        "router_files": router_records, "exceeded": exceeded,
    }


def format_context_size_report(report: dict[str, object]) -> str:
    lines = [f"Context size — {report['mode']} / {report['role']}", str(report["estimate"])]
    for record in report["files"]:  # type: ignore[index]
        if record["status"] == "missing":
            lines.append(f"MISSING {record['category']}: {record['label']}")
        else:
            tokens = record["estimated_tokens"]
            flag = " OVER THRESHOLD" if record["over_threshold"] else ""
            lines.append(f"{record['category']}: {record['label']} — {record['bytes']} bytes, {record['lines']} lines, estimated {tokens['low']}-{tokens['high']} tokens{flag}")
    total = report["total"]  # type: ignore[assignment]
    lines.append(f"TOTAL: {total['bytes']} bytes, {total['lines']} lines, estimated {total['estimated_tokens']['low']}-{total['estimated_tokens']['high']} tokens")
    for record in report["deferred_documents"]:  # type: ignore[index]
        size = "missing" if record["status"] == "missing" else f"{record['bytes']} bytes"
        lines.append(f"DEFERRED {record['path']}: {size}. Read at: {record['phase']}.")
    for record in report["unbounded_documents"]:  # type: ignore[index]
        size = "missing" if record["status"] == "missing" else f"{record['bytes']} bytes"
        lines.append(f"UNBOUNDED {record['path']}: {size}. {record['note']}")
    for record in report["router_files"]:  # type: ignore[index]
        if record["over_router_ceiling"]:
            lines.append(f"ROUTER FILE OVER CEILING: {record['path']} — {record['lines']} lines (ceiling {report['router_file_lines_ceiling']}).")
    if report["threshold_bytes"] is None:
        lines.append("Threshold: advisory (no configured limit).")
    elif report["exceeded"]:
        lines.append("Threshold exceeded: " + ", ".join(report["exceeded"]))
    else:
        lines.append("Threshold: passed.")
    return "\n".join(lines)
