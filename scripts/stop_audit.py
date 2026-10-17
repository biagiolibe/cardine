"""Stop-hook audit of `BLOCKED <CODE>` reports that no Meridian command emitted (task 173).

Advisory only: every failure is a silent no-op and the exit status is always 0.
The hook reads only the final assistant message and never stores its text; a
journal line carries the registered code and the host that ran the hook.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import meridian

BLOCKED_LINE = re.compile(r"^[\s>*_`-]*BLOCKED ([A-Z][A-Z0-9_]*)\b", re.MULTILINE)
FALLBACK_WINDOW = timedelta(hours=24)
HOSTS = ("claude", "codex")


def final_message(payload: dict) -> str:
    """The final assistant text: `last_assistant_message`, else the transcript's last assistant entry."""
    message = payload.get("last_assistant_message")
    if isinstance(message, str):
        return message
    path = payload.get("transcript_path")
    if not isinstance(path, str):
        return ""
    last = ""
    for raw in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict) or entry.get("type") not in {"assistant", "assistant_message"}:
            continue
        content = (entry.get("message") or {}).get("content")
        if isinstance(content, str):
            last = content
        elif isinstance(content, list):
            texts = [block.get("text", "") for block in content if isinstance(block, dict) and block.get("type") == "text"]
            if texts:
                last = "\n".join(texts)
    return last


def session_start(payload: dict, now: datetime) -> datetime:
    """The first transcript timestamp, else a bounded fallback window."""
    path = payload.get("transcript_path")
    if isinstance(path, str):
        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
                for raw in handle:
                    try:
                        when = datetime.fromisoformat(json.loads(raw).get("timestamp").replace("Z", "+00:00"))
                    except (json.JSONDecodeError, AttributeError, ValueError):
                        continue
                    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)
        except OSError:
            pass
    return now - FALLBACK_WINDOW


def active_task(cwd: Path) -> str | None:
    """The task of the registered task worktree the hook runs in; `None` from the primary checkout."""
    active = meridian.active_worktree_task(cwd)
    task = active.get("task_id") if isinstance(active, dict) else None
    return task if isinstance(task, str) else None


def audit(payload: dict, now: datetime | None = None, host: str = "claude") -> list[dict]:
    """Append one line per unbacked or declared code; return the appended lines."""
    now = now or datetime.now(timezone.utc)
    cwd = Path(payload["cwd"])
    if not (cwd / "PROJECT_WORKFLOW.md").is_file():
        return []
    codes = list(dict.fromkeys(BLOCKED_LINE.findall(final_message(payload))))
    registry = meridian.load_stop_registry()
    codes = [code for code in codes if code in registry]
    if not codes:
        return []
    project = meridian.canonical_project_root(cwd)
    directory = meridian.canonical_git_common_dir(project)
    if not any((directory / name).is_file() for name in (meridian.JOURNAL_NAME, meridian.JOURNAL_ROTATED_NAME)):
        return []
    records, _ = meridian._flow_read_journal(project)
    start = session_start(payload, now)
    task = active_task(cwd)
    written = []
    for code in codes:
        if registry[code].get("class") in {"command-exit", "judgment"}:
            result = "declared_block"
        else:
            backed = any(
                record["result"] == "blocked"
                and record.get("stop_code") == code
                and record["_when"] >= start
                and (task is None or record.get("task") in {None, task})
                for record in records
            )
            if backed:
                continue
            result = "unbacked_block"
        line = {
            "version": meridian.JOURNAL_VERSION,
            "ts": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "command": "stop-audit",
            "task": task,
            "result": result,
            "stop_code": code,
            "host": host,
            "exit": 0,
        }
        meridian.append_journal_line(project, line)
        written.append(line)
    return written


def main(host: str = "claude") -> int:
    try:
        payload = json.load(sys.stdin)
        if host in HOSTS and isinstance(payload, dict) and isinstance(payload.get("cwd"), str):
            audit(payload, host=host)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
