"""Helpers extracted from the legacy CLI; see the module split plan."""

from __future__ import annotations

from cardine.shared.console_workflow import latest_review_verdict
from cardine.shared.console_workflow import record_review
from cardine.shared.errors import CardineError
from cardine.shared.errors import CardineStop
from cardine.shared.models import ResolvedTaskIdentity
from cardine.shared.text import read_task_field
from cardine.stops.render import stop_error
from cardine.tasks.identity import _authority_matches
from cardine.tasks.identity import _clean_queue_id
from cardine.tasks.identity import resolve_project_locations
from cardine.tasks.identity import task_identity_context
from cardine.tasks.state import TaskStateInvalid
from cardine.tasks.state import read_task_state
from cardine.tasks.state import state_path
from cardine.templates.mode import detect_mode
from collections.abc import Callable
from pathlib import Path
import os
import re

def _completed_task_row(contents: str, task_id: str, path: Path, pattern: str) -> str:
    """Return one known task row with its status set to complete."""
    matches = list(re.finditer(pattern, contents, flags=re.MULTILINE))
    if len(matches) != 1:
        raise CardineError(
            f"unrecognized completion row for task {task_id} in {path}"
        )
    match = matches[0]
    return f"{contents[:match.start(1)]}[x]{contents[match.end(1):]}"


def _queue_task_rows(contents: str) -> list[dict[str, object]]:
    """Read task rows by the named ID and Status columns of each pipe table.

    Archival and state import share this reader so both find the same rows and
    IDs. Column order, heading level, and status wording are not interpreted.
    """
    rows: list[dict[str, object]] = []
    headers: list[str] = []
    offset = 0
    for number, line in enumerate(contents.splitlines(keepends=True), 1):
        start, offset = offset, offset + len(line)
        if not line.lstrip().startswith("|"):
            headers = []
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        folded = [cell.strip("`").casefold() for cell in cells]
        if "id" in folded and "status" in folded:
            headers = folded
            continue
        if not headers or len(cells) != len(headers) or set("".join(cells)) <= {"-", ":"}:
            continue
        row = dict(zip(headers, cells))
        task_id, _link = _clean_queue_id(row["id"])
        rows.append({"line": number, "start": start, "id": task_id,
                     "status": row["status"].strip("`"), "review": row.get("review", "").strip("`")})
    return rows


_QUEUE_TABLE_DIVIDER = re.compile(r"^\|(?:\s*:?-{3,}:?\s*\|)+\s*$")


_QUEUE_TASK_ROW = re.compile(r"^\| `(?P<status>\[[ /x]\])` \| [^|]+ \|.*$")


_QUEUE_ARCHIVE_HEADER = (
    "# Task Execution Queue — Archive\n\n"
    "Closed phases and sections moved out of the operational queue once every row in them is\n"
    "`[x]`, to keep that file's reading cost low. Mirrors the queue's own table\n"
    "structure.\n"
)


_GOVERNED_QUEUE_ARCHIVE_HEADER = (
    "# Task Execution Queue — Archive\n\n"
    "Accepted tasks moved out of the operational queue. Mirrors the queue's own table\n"
    "structure.\n"
)


_GOVERNED_QUEUE_TASK_ROW = re.compile(
    r"^\| (?P<order>[^|]+) \| (?P<id>[^|]+) \| (?P<priority>[^|]+) \| "
    r"(?P<status>queued|in_progress|in_review|done|cancelled) \| "
    r"(?P<review>REQUIRED|NOT_REQUIRED|SPIKE) \| (?P<dependencies>[^|]*) \| (?P<task_file>[^|]*) \|$",
    re.MULTILINE,
)


_GOVERNED_QUEUE_STATUSES = frozenset(
    {"queued", "in_progress", "in_review", "done", "cancelled"}
)


_MARKDOWN_HEADING = re.compile(r"^(?P<marks>#{1,6})\s+(?P<title>.+?)\s*$")


def _governed_completion_error(path: Path, section: str, reason: str) -> CardineError:
    """Build an actionable error for an unrecognized Governed queue table."""
    return CardineError(f"unrecognized completion row in {path}, section {section}: {reason}")


def _governed_completion_row(
    contents: str, identity: ResolvedTaskIdentity, path: Path,
    task_state: dict[str, object] | None = None,
) -> tuple[str, bool, str]:
    """Accept one Governed row found by its section table's named columns."""
    lines = contents.splitlines(keepends=True)
    starts: list[int] = []
    offset = 0
    for line in lines:
        starts.append(offset)
        offset += len(line)

    section = "<preamble>"
    recognized_headers = 0
    incomplete_header_sections: list[str] = []
    candidates: list[tuple[int, int, int, int, str, list[str]]] = []
    for index, line in enumerate(lines):
        heading = _MARKDOWN_HEADING.match(line.rstrip("\n"))
        if heading:
            section = heading.group("title")
        if not line.startswith("|"):
            continue
        header = [cell.strip() for cell in line.strip().strip("|").split("|")]
        folded = [cell.casefold() for cell in header]
        if "id" not in folded or "status" not in folded:
            if "id" in folded:
                incomplete_header_sections.append(section)
            continue
        recognized_headers += 1
        id_index, status_index = folded.index("id"), folded.index("status")
        if index + 1 >= len(lines) or not _QUEUE_TABLE_DIVIDER.fullmatch(lines[index + 1].rstrip("\n")):
            raise _governed_completion_error(path, section, "table header has no valid divider")
        row_index = index + 2
        while row_index < len(lines) and lines[row_index].startswith("|"):
            cells = [cell.strip() for cell in lines[row_index].strip().strip("|").split("|")]
            if len(cells) != len(header):
                if id_index < len(cells) and cells[id_index].strip("`") == identity.canonical_id:
                    raise _governed_completion_error(path, section, "task row cell count differs from its header")
                row_index += 1
                continue
            if cells[id_index].strip("`") == identity.canonical_id:
                candidates.append((row_index, status_index, starts[row_index], len(lines[row_index]), section, header))
            row_index += 1

    if not candidates:
        if not recognized_headers:
            section = ", ".join(sorted(set(incomplete_header_sections))) or section
            raise _governed_completion_error(path, section, "no table header has both ID and Status columns")
        raise _governed_completion_error(path, section, f"task {identity.canonical_id} appears zero times")
    if len(candidates) != 1:
        sections = ", ".join(sorted({candidate[4] for candidate in candidates}))
        raise _governed_completion_error(path, sections, f"task {identity.canonical_id} appears {len(candidates)} times")

    row_index, status_index, start, _, section, header = candidates[0]
    cells = [cell.strip() for cell in lines[row_index].strip().strip("|").split("|")]
    status = cells[status_index].strip("`")
    if status not in _GOVERNED_QUEUE_STATUSES:
        raise _governed_completion_error(path, section, f"unknown Governed status {cells[status_index]!r}")

    if task_state is not None:
        terminal = str(task_state["status"])
        parts = lines[row_index].split("|")
        parts[status_index + 1] = re.sub(
            r"(?<!\S)(?:`)?[^`\s|]+(?:`)?(?!\S)", terminal,
            parts[status_index + 1], count=1,
        )
        return (
            f"{contents[:start]}{'|'.join(parts)}{contents[start + len(lines[row_index]):]}",
            True, f"task state is {terminal}",
        )

    review_index = next((i for i, cell in enumerate(header) if cell.casefold() == "review"), None)
    record_path = identity.task_path
    archived_path = record_path.parent / "done" / record_path.name
    if not record_path.is_file() and archived_path.is_file():
        record_path = archived_path
    record_text = record_path.read_text(encoding="utf-8") if record_path.is_file() else ""
    if review_index is None:
        review = record_review(record_text)
        review = "REQUIRED" if review == "REQUIRED" else "NOT_REQUIRED" if review == "NOT REQUIRED" else None
        if review is None:
            raise _governed_completion_error(path, section, "no Review column and task record has no recognized review policy")
    else:
        review = cells[review_index].strip("`")
        if review == "SPIKE":
            # Class never waives review; old table layouts obtain policy from
            # the task declaration, or inherit the configured project default.
            declared = record_review(record_text)
            if declared is not None:
                review = declared.replace(" ", "_")
            else:
                from cardine.shared.project import resolve_project_configuration
                from cardine.shared.git import canonical_project_root
                policy = resolve_project_configuration(canonical_project_root(path.parent))["taskDefaults"]["review"]
                review = "REQUIRED" if policy == "required" else "NOT_REQUIRED"
        if review not in ("REQUIRED", "NOT_REQUIRED"):
            raise _governed_completion_error(path, section, f"unknown Review value {cells[review_index]!r}")

    if review == "REQUIRED":
        review_path = identity.review_path
        verdict = latest_review_verdict(
            review_path.read_text(encoding="utf-8") if review_path.is_file() else None
        )
        if verdict != "APPROVE":
            reason = "review record is missing or malformed" if verdict is None else f"latest review verdict is {verdict}"
            return contents, False, reason

    if status == "done":
        return (
            contents,
            True,
            "review not required" if review == "NOT_REQUIRED" else "latest review verdict is APPROVE",
        )

    line = lines[row_index]
    parts = line.split("|")
    # A leading pipe makes markdown cell N live at split index N + 1. Replace
    # only the cell payload so all formatting around it remains unchanged.
    cell_index = status_index + 1
    payload = parts[cell_index]
    replacement = re.sub(r"(?<!\S)(?:`)?[^`\s|]+(?:`)?(?!\S)", "done", payload, count=1)
    if replacement == payload:
        raise _governed_completion_error(path, section, "Status cell has no replaceable token")
    parts[cell_index] = replacement
    return (
        f"{contents[:start]}{'|'.join(parts)}{contents[start + len(line):]}",
        True,
        "review not required" if review == "NOT_REQUIRED" else "latest review verdict is APPROVE",
    )


def _queue_section_ranges(contents: str) -> list[tuple[int, int, int, str]]:
    """Bound each heading by the next heading of the same or higher level."""
    marks = list(re.finditer(r"^(?P<marks>#{1,6})[ \t]+.+$", contents, re.MULTILINE))
    ranges = []
    for index, mark in enumerate(marks):
        level = len(mark.group("marks"))
        end = next((other.start() for other in marks[index + 1:]
                    if len(other.group("marks")) <= level), len(contents))
        ranges.append((mark.start(), end, level, mark.group(0).strip()))
    return ranges


def _queue_section_completion(section: str, mode: str) -> tuple[list[re.Match[str]], str | None]:
    """Check every pipe table, retaining ambiguous task input with a reason."""
    expected = "| Order | ID | Priority | Status | Review |" if mode == "governed-sdd" else "| Status |"
    pattern = _GOVERNED_QUEUE_TASK_ROW if mode == "governed-sdd" else _QUEUE_TASK_ROW
    lines = section.splitlines()
    rows: list[re.Match[str]] = []
    index = 0
    while index < len(lines):
        if not lines[index].lstrip().startswith("|"):
            index += 1
            continue
        end = index + 1
        while end < len(lines) and lines[end].lstrip().startswith("|"):
            end += 1
        table = lines[index:end]
        index = end
        cells = [cell.strip().strip("`").casefold() for cell in table[0].strip().strip("|").split("|")]
        task_like = "status" in cells or any(pattern.fullmatch(line) for line in table)
        if not task_like:
            continue
        if not (table[0].startswith(expected + " ") or table[0].rstrip() == expected):
            return rows, f"table header {table[0].strip()!r} does not start with the expected columns {expected!r}"
        if len(table) < 3 or not _QUEUE_TABLE_DIVIDER.fullmatch(table[1]):
            return rows, "task table has a missing or malformed divider or no task rows"
        column_count = len(table[0].split("|"))
        if len(table[1].split("|")) != column_count:
            return rows, "task table divider does not match its header columns"
        for line in table[2:]:
            row = pattern.fullmatch(line)
            if row is None or len(line.split("|")) != column_count:
                return rows, f"unrecognized task row or mismatched cells: {line.strip()!r}"
            rows.append(row)
    return rows, None


_STATE_TERMINAL_STATUSES = {
    "governed-sdd": frozenset({"done", "cancelled"}),
    "lean-delivery": frozenset({"done", "cancelled"}),
}


# (kind, detail): kind is terminal, open, legacy (no state file), or invalid.
QueueStateResolver = Callable[[str], tuple[str, str]]


def _queue_state_resolver(
    project_root: Path, mode: str, overrides: dict[str, dict[str, object]] | None = None
) -> QueueStateResolver:
    """Resolve each queue row's status from its state file, read by task ID."""
    context = task_identity_context(project_root)
    terminal = _STATE_TERMINAL_STATUSES[mode]
    cache: dict[str, tuple[str, str]] = {}

    def resolve(supplied: str) -> tuple[str, str]:
        if supplied in cache:
            return cache[supplied]
        matches = _authority_matches(context.authorities, supplied)
        task_id = matches[0] if len(matches) == 1 else supplied
        override = (overrides or {}).get(task_id)
        try:
            path = state_path(project_root, task_id)
            if override is None and not path.exists():
                result = ("legacy", "no state file")
            else:
                record = ""
                authority = context.authorities.get(task_id)
                if mode == "governed-sdd" and authority is not None and len(authority.task_paths) == 1:
                    record = authority.task_paths[0].read_text(encoding="utf-8")
                state = override or read_task_state(
                    project_root, task_id, mode, review_required=None, stop_factory=stop_error,
                    spike=(read_task_field(record, "Class") or "").lower() == "spike",
                )
                status = str(state["status"])
                result = ("terminal" if status in terminal else "open", status)
        except (CardineStop, TaskStateInvalid, OSError, UnicodeError) as error:
            result = ("invalid", str(error))
        cache[supplied] = result
        return result

    return resolve


def _queue_unidentified_tables(section: str, mode: str) -> bool:
    """Whether a task-like table lacks the named ID column the state rule reads."""
    pattern = _GOVERNED_QUEUE_TASK_ROW if mode == "governed-sdd" else _QUEUE_TASK_ROW
    lines = section.splitlines()
    index = 0
    while index < len(lines):
        if not lines[index].lstrip().startswith("|"):
            index += 1
            continue
        end = index + 1
        while end < len(lines) and lines[end].lstrip().startswith("|"):
            end += 1
        table = lines[index:end]
        index = end
        cells = [cell.strip().strip("`").casefold() for cell in table[0].strip().strip("|").split("|")]
        if "id" in cells and "status" in cells:
            continue
        if "status" in cells or any(pattern.fullmatch(line) for line in table):
            return True
    return False


def _queue_section_decisions(
    queue_contents: str, mode: str, resolve_state: QueueStateResolver | None
) -> list[dict[str, object]]:
    """Decide every section; nested sections of an archived section are covered by it."""
    completed_statuses = {"done", "cancelled"} if mode == "governed-sdd" else {"[x]"}
    ranges = _queue_section_ranges(queue_contents)
    decisions: list[dict[str, object]] = []
    covered_until = -1
    for index, (start, end, level, heading) in enumerate(ranges):
        if start < covered_until:
            continue
        section = queue_contents[start:end]
        next_heading = ranges[index + 1][0] if index + 1 < len(ranges) else len(queue_contents)
        direct = queue_contents[start:min(end, next_heading)]
        rows = _queue_task_rows(section)
        legacy_rows, legacy_reason = _queue_section_completion(section, mode)
        legacy_ok = (level == 3 and bool(legacy_rows) and legacy_reason is None
                     and all(row.group("status") in completed_statuses for row in legacy_rows))
        kinds = {str(row["id"]): resolve_state(str(row["id"])) for row in rows} if resolve_state else {}
        decision: dict[str, object] = {"section": heading, "level": level, "archive": False,
                                       "rule": "legacy", "reason": "", "open": [], "legacy": []}
        if not any(kind != "legacy" for kind, _ in kinds.values()):
            # No state file anywhere in the section: the conservative table rule decides.
            if legacy_ok:
                decision.update(archive=True, reason="every row is terminal in the table")
            elif legacy_reason is not None:
                decision["reason"] = legacy_reason
            elif legacy_rows and level != 3:
                decision["reason"] = f"heading level {level} is not `###` and no row has a task state file"
            elif legacy_rows:
                decision["reason"] = "a row is not terminal in the table"
            else:
                decision["reason"] = "no task rows"
            decision["legacy"] = sorted(kinds)
        else:
            decision["rule"] = "state"
            open_ids = sorted(i for i, (kind, _) in kinds.items() if kind == "open")
            invalid = sorted(i for i, (kind, _) in kinds.items() if kind == "invalid")
            legacy_ids = sorted(i for i, (kind, _) in kinds.items() if kind == "legacy")
            unidentified = _queue_unidentified_tables(section, mode)
            decision.update({"open": open_ids + invalid, "legacy": legacy_ids})
            if not any(_queue_task_rows(direct)):
                decision["reason"] = "container: its task rows belong to nested sections"
            elif open_ids or invalid:
                parts = []
                if open_ids:
                    parts.append("open by task state: " + ", ".join(open_ids))
                if invalid:
                    parts.append("invalid task state: " + ", ".join(
                        f"{i} ({kinds[i][1]})" for i in invalid))
                decision["reason"] = "; ".join(parts)
            elif (legacy_ids or unidentified) and not legacy_ok:
                decision["reason"] = (
                    "rows without a state file are retained by the table rule: "
                    + (", ".join(legacy_ids) or "table without an ID column")
                    + (f" ({legacy_reason})" if legacy_reason else "")
                )
            else:
                decision.update(archive=True, reason=(
                    "every row is terminal by task state"
                    if not (legacy_ids or unidentified) else "terminal by task state and by the table rule"))
        decisions.append(decision)
        if decision["archive"]:
            decision["range"] = (start, end)
            covered_until = end
    return decisions


def _archive_completed_queue_sections(
    queue_contents: str, queue_path: Path, archive_path: Path, mode: str = "lean-delivery",
    *, resolve_state: QueueStateResolver | None = None, report: list[dict[str, object]] | None = None,
) -> tuple[str, str | None]:
    """Move disjoint, fully complete sections to the archive in memory.

    A row with a state file is read from it; a row without one keeps the
    conservative table rule, and a mixed section needs both to agree. `report`
    receives one entry per section, archived or retained, with its reason.
    """
    decisions = _queue_section_decisions(queue_contents, mode, resolve_state)
    if report is not None:
        report.extend({key: value for key, value in decision.items() if key != "range"}
                      for decision in decisions)
    completed_sections = [
        (decision["range"][0], decision["range"][1], queue_contents[decision["range"][0]:decision["range"][1]])
        for decision in decisions if decision["archive"]
    ]
    if not completed_sections:
        return queue_contents, None
    archived = "".join(section.rstrip("\n") + "\n" for _, _, section in completed_sections)
    retained: list[str] = []
    cursor = 0
    for start, end, _section in completed_sections:
        retained.append(queue_contents[cursor:start])
        cursor = end
    retained.append(queue_contents[cursor:])
    updated_queue = "".join(retained).rstrip("\n") + "\n"
    default_header = _GOVERNED_QUEUE_ARCHIVE_HEADER if mode == "governed-sdd" else _QUEUE_ARCHIVE_HEADER
    archive_contents = archive_path.read_text(encoding="utf-8") if archive_path.exists() else default_header
    return updated_queue, archive_contents.rstrip("\n") + "\n\n" + archived


def _queue_archival_warnings(
    queue_contents: str, mode: str = "lean-delivery", resolve_state: QueueStateResolver | None = None
) -> list[str]:
    """Use the archival boundaries and completion checks to explain retained input."""
    warnings: list[str] = []
    ranges = _queue_section_ranges(queue_contents)
    for index, (start, end, level, heading) in enumerate(ranges):
        if level > 3 and any(parent_start < start < parent_end and parent_level == 3
                             for parent_start, parent_end, parent_level, _ in ranges):
            continue
        # Non-archival headings own only their direct content, not child tables.
        if level != 3 and index + 1 < len(ranges):
            end = min(end, ranges[index + 1][0])
        if resolve_state is not None:
            ids = [str(row["id"]) for row in _queue_task_rows(queue_contents[start:end])]
            if ids and all(resolve_state(task_id)[0] != "legacy" for task_id in ids):
                continue  # the archival report names this section and reason
        rows, reason = _queue_section_completion(queue_contents[start:end], mode)
        if reason is not None:
            warnings.append(f"queue section {heading!r} is not archived: {reason}")
        elif rows and level != 3:
            warnings.append(
                f"queue section {heading!r} is not archived: heading level {level} is not `###`, "
                "the only level archival reads"
            )
    return warnings


def _relink_archived_task_row(contents: str, queue_path: Path, identity: ResolvedTaskIdentity) -> str:
    """Point the task's queue row at its record when the merge archived it under done/."""
    active_record = identity.task_path
    archive_record = active_record.parent / "done" / active_record.name
    if not active_record.exists() and not archive_record.is_file():
        return contents
    row = re.search(
        rf"^\| (?:`\[[ /x]\]`|[^|]+) \| \[?{re.escape(identity.canonical_id)}\b.*$",
        contents,
        flags=re.MULTILINE,
    )
    if row is None:
        return contents
    target_record = archive_record if archive_record.is_file() else active_record
    new_target = Path(os.path.relpath(target_record, queue_path.parent)).as_posix()

    def retarget(link: re.Match[str]) -> str:
        target = link.group(1)
        if "://" in target or target.startswith("#"):
            return link.group(0)
        linked_record = (queue_path.parent / target.split("#", 1)[0]).resolve()
        if linked_record not in (active_record, archive_record):
            return link.group(0)
        return f"]({new_target})"

    relinked = re.sub(r"\]\(([^)]*)\)", retarget, row.group(0))
    return f"{contents[:row.start()]}{relinked}{contents[row.end():]}"


def _apply_task_completion_rows(
    project_root: Path, identity: ResolvedTaskIdentity,
    task_state: dict[str, object] | None = None,
    report: list[dict[str, object]] | None = None,
) -> dict[str, str]:
    """Set known completion rows and archive fully complete queue sections.

    `report` receives one decision per queue section, archived or retained.
    """
    queue_path = identity.queue_path
    archive_path = queue_path.with_name("QUEUE_ARCHIVE.md")
    task_id = identity.canonical_id
    queue_contents = queue_path.read_text(encoding="utf-8")
    mode = detect_mode(project_root)
    # The integrating task's proven state stands in for its file on the candidate tree.
    overrides = {task_id: task_state} if task_state else None
    if mode == "governed-sdd":
        queue_completed, accepted, reason = _governed_completion_row(queue_contents, identity, queue_path, task_state)
        queue_completed = _relink_archived_task_row(queue_completed, queue_path, identity)
        if not accepted:
            raise stop_error("REVIEW_NOT_APPROVED", f"{identity.review_path}: expected APPROVE; found {reason}",
                             task_id=task_id, project=project_root)
        archived_queue, archive_contents = _archive_completed_queue_sections(
            queue_completed, queue_path, archive_path, mode, report=report,
            resolve_state=_queue_state_resolver(project_root, mode, overrides),
        )
        if archived_queue != queue_contents:
            queue_path.write_text(archived_queue, encoding="utf-8")
        if archive_contents is not None:
            archive_path.write_text(archive_contents, encoding="utf-8")
        return {"status": "COMPLETED", "reason": reason, "source": "machine" if task_state else "legacy"}
    plan_path = project_root / resolve_project_locations(project_root).plan
    plan_contents = plan_path.read_text(encoding="utf-8") if plan_path.is_file() else ""
    queue_completed = _completed_task_row(
        queue_contents,
        task_id,
        queue_path,
        rf"^\| `(?P<status>\[[ /x]\])` \| {re.escape(task_id)} \|.*$",
    )
    plan_completed = _completed_task_row(
        plan_contents,
        task_id,
        plan_path,
        rf"^- `(?P<status>\[[ /x]\])` {re.escape(task_id)} — .*$",
    )
    queue_completed = _relink_archived_task_row(queue_completed, queue_path, identity)
    archived_queue, archive_contents = _archive_completed_queue_sections(
        queue_completed, queue_path, archive_path, mode, report=report,
        resolve_state=_queue_state_resolver(project_root, mode, overrides),
    )
    if archived_queue != queue_contents:
        queue_path.write_text(archived_queue, encoding="utf-8")
    if plan_completed != plan_contents:
        plan_path.write_text(plan_completed, encoding="utf-8")
    if archive_contents is not None:
        archive_path.write_text(archive_contents, encoding="utf-8")
    return {"status": "COMPLETED", "reason": "lean completion rows updated",
            "source": "machine" if task_state else "legacy"}
