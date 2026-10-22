"""Read-only queue row reader kept for the explicit state import.

Task status is never written to the queue or the plan here: the generated views
come from validated task state (see `cardine.tasks.status_render`).
"""

from __future__ import annotations

from cardine.tasks.identity import _clean_queue_id


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
