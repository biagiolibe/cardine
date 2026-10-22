"""Helpers extracted from the legacy CLI; see the module split plan."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re

from cardine.integration.projections import _queue_task_rows
from cardine.shared.errors import CardineError
from cardine.shared.git import git_output
from cardine.shared.text import read_task_field
from cardine.stops.render import stop_error
from cardine.tasks.identity import _authority_matches
from cardine.tasks.identity import resolve_task_identity
from cardine.tasks.state import TaskStateInvalid
from cardine.tasks.state import machine
from cardine.tasks.state import state_path
from cardine.tasks.state import validate_task_state
from cardine.templates.mode import detect_mode
from cardine.tasks.contract import resolve_task_contract

from cardine.shared.models import TaskIdentityContext
from cardine.tasks.identity import (_TaskAuthority, _clean_queue_id,
    read_task_identity_policy, resolve_project_locations)


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


def _legacy_task_authorities(project_root, locations):
    task_paths: dict[str, set[Path]] = {}
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

    return {canonical: _TaskAuthority(canonical, tuple(sorted(paths)), (), 0)
            for canonical, paths in task_paths.items()}


def legacy_identity_context(project_root: Path) -> TaskIdentityContext:
    """Read queue identity evidence only for explicit import and installation snapshots."""
    project_root = project_root.resolve()
    locations = resolve_project_locations(project_root)
    task_paths = {key: set(value.task_paths) for key, value in _legacy_task_authorities(project_root, locations).items()}
    queue_links = {}
    queue_counts = {}
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
                    raise CardineError(f"queue task link escapes the project: {link_value}")
                queue_links.setdefault(canonical, set()).add(resolved)

    identities = set(task_paths) | set(queue_counts)
    authorities = {
        canonical: _TaskAuthority(
            canonical,
            tuple(sorted(task_paths.get(canonical, set()))),
            tuple(sorted(queue_links.get(canonical, set()))),
            queue_counts.get(canonical, 0),
        )
        for canonical in identities
    }

    return TaskIdentityContext(read_task_identity_policy(project_root), locations, authorities)


def import_task_states(
    project_root: Path, task_ids: list[str], *, apply: bool = False, include_terminal: bool = False
) -> dict[str, object]:
    """Explicitly bootstrap tasks; validate the entire proposal before writing.

    Terminal legacy tasks are skipped unless `include_terminal` asks for their
    state, which needs consistent texts and, for a reviewed Governed task, a
    recorded APPROVE verdict.

    Imported transitions describe the bootstrap at HEAD, not historical events.
    Existing machine files are never rewritten.
    """
    project_root = project_root.resolve()
    workflow = detect_mode(project_root)
    context = legacy_identity_context(project_root)
    queue_path = project_root / context.locations.queue
    rows: dict[str, list[dict[str, object]]] = {}
    for found in _queue_task_rows(queue_path.read_text(encoding="utf-8")):
        rows.setdefault(str(found["id"]), []).append({
            "path": context.locations.queue.as_posix(), "line": found["line"],
            "status": found["status"], "review": found["review"]})
    selected = task_ids or list(rows)
    proposals = []
    seen = set()
    head = None
    at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    terminal = {"done", "cancelled"}

    def normalize(value):
        return {"[ ]": "queued", "[/]": "in_progress",
                "[x]": "done"}.get(value, value)

    for supplied in selected:
        matches = _authority_matches(context.authorities, supplied)
        task_id = matches[0] if len(matches) == 1 else supplied

        def invalid(message):
            raise stop_error("TASK_STATE_INVALID", message, task_id=task_id, project=project_root)

        if task_id in seen:
            continue
        seen.add(task_id)
        entries = rows.get(task_id, [])
        if len(entries) != 1:
            invalid(f"queue evidence: allowed one row for {task_id}; found {len(entries)}")
        queue = entries[0]
        status = normalize(queue["status"])
        path = state_path(project_root, task_id)
        proposal = {"task_id": task_id, "path": path.relative_to(project_root).as_posix(),
                    "evidence": {"queue": queue}}
        proposals.append(proposal)
        if path.exists():
            proposal["action"] = "skip-existing"
            continue
        if status in terminal and not include_terminal:
            proposal["action"] = "skip-terminal"
            continue
        try:
            identity = resolve_task_identity(project_root, task_id, "existing", context=context,
                                             allow_archived_queue_links=True)
        except CardineError as error:
            invalid(str(error))
        record = identity.task_path.read_text(encoding="utf-8")
        record_status = read_task_field(record, "Status")
        record_status = record_status.strip("`") if record_status else None
        proposal["evidence"]["record"] = {"path": identity.task_path.relative_to(project_root).as_posix(),
                                             "status": record_status}
        # Lean records may have no Status field; progress is derived from worktrees.
        if (record_status is not None and normalize(record_status) != status):
            invalid(f"queue Status={queue['status']!r}; record Status={record_status!r}")
        try:
            contract = resolve_task_contract(project_root, task_id, text=record)
        except CardineError as error:
            invalid(str(error))
        spike = contract["class"] == "spike"
        review_policy = read_task_field(record, "Review")
        review_policy = review_policy.strip("`") if review_policy else None
        required = contract["options"]["review"] == "required"
        spike_column = spike and queue["review"] == "SPIKE"  # the queue's own spelling of Class: SPIKE
        if (queue["review"] and not spike_column
                and queue["review"].lower() != contract["options"]["review"]):
            invalid(f"queue Review={queue['review']!r}; record Review={review_policy!r}")
        review_path = identity.review_path
        review_text = review_path.read_text(encoding="utf-8") if review_path.is_file() else ""
        attempts = []
        for heading in re.finditer(r"^## Attempt (\d+)[^\n]*", review_text, re.MULTILINE):
            verdicts = re.findall(r"\b(APPROVE|CHANGES_REQUESTED|BLOCKED)\b", heading.group())
            if not verdicts and status in terminal:
                continue  # a remediation heading of a closed task carries no verdict
            if len(verdicts) != 1:
                invalid(f"review heading: allowed one verdict; found {heading.group()!r}")
            attempts.append((int(heading.group(1)), verdicts[0], heading.start(), heading.group()))
        if len({item[0] for item in attempts}) != len(attempts):
            invalid("review evidence: allowed unique attempt numbers; found duplicate attempts")
        latest = max(attempts, default=None, key=lambda item: item[0])
        proposal["evidence"]["review"] = {"path": review_path.relative_to(project_root).as_posix(),
                                             "exists": review_path.is_file(),
                                             "heading": latest[3] if latest else None,
                                             "verdict": latest[1] if latest else None}
        if latest and status not in terminal and (
                (latest[1] == "APPROVE" and status != "in_progress") or status == "queued"
                or (latest[1] == "BLOCKED" and status != "in_review")):
            invalid(f"queue/record Status={status!r}; review verdict={latest[1]!r}")
        if status in terminal and required and latest and latest[1] != "APPROVE":
            # A recorded verdict must agree with the terminal text; an absent
            # record stays absent (verdict null), so an import never invents an approval.
            invalid(f"queue/record Status={status!r}; review verdict: allowed 'APPROVE'; found {latest[1]!r}")
        states = machine(workflow, spike, required)
        # A shortest legal path bootstraps current state without inventing old reviews.
        routes = [("queued", [])]
        visited = set()
        route = None
        while routes:
            current, steps = routes.pop(0)
            if current == status:
                route = steps
                break
            if current in visited:
                continue
            visited.add(current)
            routes.extend((target, steps + [target]) for target in states[current])
        if route is None:
            invalid(f"queue Status: allowed {list(states)}; found {status!r}")
        state = {"version": 1, "task_id": task_id, "workflow": workflow, "status": status,
                 "transitions": [], "contract": contract}
        current = "queued"
        for target in route:
            head = head or git_output(project_root, "rev-parse", "HEAD")
            state["transitions"].append({"from": current, "to": target, "commit": head, "at": at})
            current = target
        if not required:
            state["review"] = {"required": False, "verdict": None, "attempt": 1,
                               "reviewed_commit": None, "approved_by": None}
        if latest:
            if not required:
                invalid(f"record Review={review_policy!r}, Class={read_task_field(record, 'Class')!r}; review verdict={latest[1]!r}")
            state["review"] = {"required": True, "verdict": latest[1], "attempt": latest[0],
                               "reviewed_commit": None, "approved_by": None}
        try:
            validate_task_state(state, task_id, workflow, spike=spike, review_required=required)
        except TaskStateInvalid as error:
            invalid(str(error))
        proposal.update(action="write", state=state)
    if apply:
        for proposal in proposals:
            if proposal["action"] != "write":
                continue
            path = project_root / proposal["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            # Exclusive creation also refuses a file created since the preview.
            with path.open("x", encoding="utf-8") as stream:
                stream.write(json.dumps(proposal["state"], indent=2, sort_keys=True) + "\n")
    return {"version": 1, "workflow": workflow, "applied": apply, "tasks": proposals}
