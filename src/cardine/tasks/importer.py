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
from cardine.tasks.identity import task_identity_context
from cardine.tasks.state import TaskStateInvalid
from cardine.tasks.state import machine
from cardine.tasks.state import state_path
from cardine.tasks.state import validate_task_state
from cardine.templates.mode import detect_mode
from cardine.tasks.contract import resolve_task_contract


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
    context = task_identity_context(project_root)
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
    terminal = {"DONE", "ACCEPTED", "ANSWERED", "INCONCLUSIVE"}

    def normalize(value):
        if workflow == "lean-delivery":
            return {"[ ]": "QUEUED", "TODO": "QUEUED", "[/]": "QUEUED", "IN_PROGRESS": "QUEUED",
                    "[x]": "DONE"}.get(value, value)
        return value

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
        if (record_status is None and workflow == "governed-sdd") or (record_status is not None and normalize(record_status) != status):
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
                latest[1] == "APPROVE" or status == "QUEUED"
                or (latest[1] == "BLOCKED" and status != "READY_FOR_REVIEW")):
            invalid(f"queue/record Status={status!r}; review verdict={latest[1]!r}")
        if status in terminal and workflow == "governed-sdd" and required and latest and latest[1] != "APPROVE":
            # A recorded verdict must agree with the terminal text; an absent
            # record stays absent (verdict null), so an import never invents an approval.
            invalid(f"queue/record Status={status!r}; review verdict: allowed 'APPROVE'; found {latest[1]!r}")
        if status == "CHANGES_REQUESTED" and (not latest or latest[1] != "CHANGES_REQUESTED"):
            invalid(f"queue/record Status={status!r}; review verdict={latest[1] if latest else None!r}")
        states = machine(workflow, spike, required)
        # A shortest legal path bootstraps current state without inventing old reviews.
        routes = [("QUEUED", [])]
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
        current = "QUEUED"
        for target in route:
            head = head or git_output(project_root, "rev-parse", "HEAD")
            state["transitions"].append({"from": current, "to": target, "commit": head, "at": at})
            current = target
        if workflow == "governed-sdd" and not required:
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
