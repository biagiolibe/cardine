"""Helpers extracted from the legacy CLI; see the module split plan."""

from __future__ import annotations

from cardine.shared.errors import MeridianError
from cardine.shared.text import HEADING_LINE
from cardine.shared.text import extract_heading_block
from cardine.tasks.identity import find_task_file
from cardine.tasks.identity import resolve_project_locations
from pathlib import Path
import re


def find_adr_log(project_root: Path) -> Path:
    return project_root / resolve_project_locations(project_root).adr_log


def adr_title_matcher(adr_id: str):
    """The one title test that decides which heading is ADR `adr_id`, at any
    heading level; `adr show` and `adr list` both resolve entries through it."""
    return lambda title: re.match(rf"{re.escape(adr_id)}\b", title) is not None


def adr_show(project_root: Path, adr_id: str) -> str:
    """Print exactly one ADR section: the first heading whose title starts with
    the ID, up to the next heading at the same or a shallower level or EOF,
    without depending on contiguous numbering.
    """
    adr_log = find_adr_log(project_root)
    if not adr_log.is_file():
        raise MeridianError(f"ADR log not found for {adr_id}: {adr_log}")
    text = adr_log.read_text(encoding="utf-8")
    result = extract_heading_block(text, adr_title_matcher(adr_id))
    if result is None:
        raise MeridianError(f"unknown ADR {adr_id}: not found in {adr_log}")
    excerpt, _ = result
    return excerpt


ADR_HEADING_ID = re.compile(r"ADR-\d+\b")


ADR_LIKE_HEADING = re.compile(r"ADR\b", re.IGNORECASE)


ADR_STATUS_LINE = re.compile(r"^\s*(?:[-*]\s+)?\*{0,2}Status\*{0,2}\s*:\s*\*{0,2}\s*(.*?)\s*$", re.IGNORECASE)


def adr_entries(text: str) -> tuple[list[dict[str, str | None]], list[str]]:
    """Return `(entries, warnings)` for an ADR log. An entry exists exactly when
    `adr show` would resolve its ID: the first heading whose title starts with
    `ADR-<digits>`. A later heading that repeats an ID, or an ADR-like heading
    that carries no parsable ID, is reported as a warning, never dropped.
    """
    entries: list[dict[str, str | None]] = []
    warnings: list[str] = []
    seen: set[str] = set()
    for match in HEADING_LINE.finditer(text):
        title = match.group(2).strip()
        line = text.count("\n", 0, match.start()) + 1
        id_match = ADR_HEADING_ID.match(title)
        if id_match is None:
            if ADR_LIKE_HEADING.match(title):
                warnings.append(f"line {line}: heading is not an ADR-NNNN entry and cannot be listed or shown: {title}")
            continue
        adr_id = id_match.group(0)
        if adr_id in seen:
            warnings.append(f"line {line}: duplicate {adr_id}; `adr show` resolves only the first entry")
            continue
        seen.add(adr_id)
        result = extract_heading_block(text, adr_title_matcher(adr_id))
        block = result[0] if result is not None else ""
        status = None
        for block_line in block.splitlines()[1:]:
            status_match = ADR_STATUS_LINE.match(block_line)
            if status_match is not None:
                status = status_match.group(1) or None
                break
        entries.append({"id": adr_id, "title": title[len(adr_id):].lstrip(" \t:\u2014\u2013-").strip(), "status": status})
    return entries, warnings


def adr_list(
    project_root: Path, status_filter: str | None = None
) -> tuple[list[dict[str, str | None]], list[str]]:
    """List every ADR entry as `{id, title, status}` without printing a body."""
    adr_log = find_adr_log(project_root)
    if not adr_log.is_file():
        raise MeridianError(f"ADR log not found: {adr_log}")
    entries, warnings = adr_entries(adr_log.read_text(encoding="utf-8"))
    if status_filter is not None:
        wanted = status_filter.strip().casefold()
        entries = [entry for entry in entries if entry["status"] is not None and entry["status"].casefold() == wanted]
    return entries, warnings


def extract_spec_heading(project_root: Path, spec_path: str, heading: str) -> str:
    full = project_root / spec_path
    if not full.is_file():
        raise MeridianError(f"spec file not found: {spec_path}")
    text = full.read_text(encoding="utf-8")
    result = extract_heading_block(text, lambda title: title.strip() == heading.strip())
    if result is None:
        raise MeridianError(f"heading not found in {spec_path}: {heading}")
    excerpt, _ = result
    return excerpt


def authority_entries(text: str) -> list[str]:
    """Every `## Authority` bullet, with wrapped continuation lines merged
    into the bullet they belong to."""
    section = extract_heading_block(text, lambda title: title == "Authority")
    if section is None:
        return []
    body = section[0].split("\n", 1)[1] if "\n" in section[0] else ""
    entries: list[str] = []
    for line in body.splitlines():
        if line.startswith("- "):
            entries.append(line[2:].strip())
        elif line.strip() and entries:
            entries[-1] += " " + line.strip()
    return entries


SPEC_HEADING_CITATION = re.compile(r"^`([^`]+)`#(.+)$")


def resolve_authority_entry(
    project_root: Path, entry: str
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Resolve one Authority bullet to `(source, heading, excerpt)` triples,
    plus any part of the bullet that could not be resolved (named, not
    silently dropped): every `ADR-NNNN` token cited anywhere in the bullet
    resolves through `adr_show`; a `` `path`#Heading `` citation resolves
    through the same heading-range logic against that path; anything else is
    reported unresolved.
    """
    resolved: list[tuple[str, str, str]] = []
    unresolved: list[str] = []
    adr_ids = re.findall(r"\bADR-\d+\b", entry)
    if adr_ids:
        adr_log = find_adr_log(project_root)
        for adr_id in adr_ids:
            try:
                excerpt = adr_show(project_root, adr_id)
            except MeridianError:
                unresolved.append(f"{adr_id} (not found in {adr_log})")
                continue
            resolved.append((str(adr_log), adr_id, excerpt))
        return resolved, unresolved
    match = SPEC_HEADING_CITATION.match(entry.strip())
    if match:
        spec_path, heading = match.group(1), match.group(2).strip()
        try:
            excerpt = extract_spec_heading(project_root, spec_path, heading)
        except MeridianError as error:
            unresolved.append(f"{entry} ({error})")
            return resolved, unresolved
        resolved.append((spec_path, heading, excerpt))
        return resolved, unresolved
    unresolved.append(entry)
    return resolved, unresolved


def context_authority(project_root: Path, task_id: str, labels_only: bool = False) -> str:
    """Print the task's cited ADR sections and spec headings, labeled with
    source path and heading, in place of opening the ADR log or spec file
    directly. `labels_only` drops excerpt bodies, keeping only source and
    heading, for the queue-briefing hook.
    """
    task = find_task_file(project_root, task_id)
    text = task.read_text(encoding="utf-8")
    entries = authority_entries(text)
    if not entries:
        return f"{task_id}: no Authority entries."
    lines: list[str] = []
    unresolved_all: list[str] = []
    for entry in entries:
        resolved, unresolved = resolve_authority_entry(project_root, entry)
        for source, heading, excerpt in resolved:
            lines.append(f"### {source} — {heading}")
            if not labels_only:
                lines.append(excerpt)
        unresolved_all.extend(unresolved)
    if unresolved_all:
        lines.append("### Unresolved")
        lines.extend(f"- {item}" for item in unresolved_all)
    return "\n".join(lines).rstrip("\n")
