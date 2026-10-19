"""Helpers extracted from the legacy CLI; see the module split plan."""

from __future__ import annotations

from datetime import datetime
from datetime import timezone
from pathlib import Path
import json

from cardine.shared.constants import USAGE_ADAPTER_NOTES
from cardine.shared.constants import USAGE_HOSTS
from cardine.shared.constants import USAGE_PRIVACY_BOUNDARY
from cardine.shared.errors import CardineError


def _usage_counter(value: object) -> int:
    """Return a non-negative private-format counter, rejecting malformed values."""
    return value if type(value) is int and value >= 0 else 0

def _claude_usage_call(usage: dict[str, object]) -> dict[str, object] | None:
    """Return total input (fresh + cache read + cache creation) or None when no field is present."""
    fields = [usage.get(name) for name in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")]
    if not any(type(value) is int and value >= 0 for value in fields):
        return None
    return {"input": sum(_usage_counter(value) for value in fields), "cached": usage.get("cache_read_input_tokens"), "output": usage.get("output_tokens")}

def _usage_start(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None

def _usage_session(host: str, start: datetime, project_name: str, model: object, calls: list[dict[str, object]], breakdown: bool) -> dict[str, object] | None:
    if not calls:
        return None
    inputs = [_usage_counter(call.get("input")) for call in calls]
    cached = [_usage_counter(call.get("cached")) for call in calls]
    outputs = [_usage_counter(call.get("output")) for call in calls]
    total_input = sum(inputs)
    result: dict[str, object] = {
        "host": host,
        "start": start.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "project": project_name,
        "model": model if isinstance(model, str) else None,
        "calls": len(calls),
        "first_call_input": inputs[0],
        "mean_call_input": round(total_input / len(inputs), 2),
        "peak_call_input": max(inputs),
        "cumulative_input": total_input,
        "cached_input": sum(cached),
        "output": sum(outputs),
        "cache_ratio": round(sum(cached) / total_input, 4) if total_input else 0.0,
    }
    if breakdown:
        growth = [inputs[index] - inputs[index - 1] for index in range(1, len(inputs))]
        result["breakdown"] = {
            "calls": len(calls),
            "largest_input_growth": {
                "call": growth.index(max(growth)) + 2 if growth else 1,
                "tokens": max(growth) if growth else 0,
            },
        }
    return result

def _codex_usage_session(path: Path, breakdown: bool) -> dict[str, object] | None:
    """Parse only Codex metadata and token_count counters from one rollout JSONL."""
    start: datetime | None = None
    project_name = "unknown"
    model: object = None
    calls: list[dict[str, object]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            payload = event.get("payload")
            if event.get("type") == "session_meta" and isinstance(payload, dict):
                start = _usage_start(payload.get("timestamp")) or _usage_start(event.get("timestamp"))
                cwd = payload.get("cwd")
                project_name = Path(cwd).name if isinstance(cwd, str) else project_name
                model = payload.get("model") or payload.get("model_name")
            if event.get("type") != "event_msg" or not isinstance(payload, dict) or payload.get("type") != "token_count":
                continue
            info = payload.get("info")
            usage = info.get("last_token_usage") if isinstance(info, dict) else None
            if isinstance(usage, dict):
                calls.append({"input": usage.get("input_tokens"), "cached": usage.get("cached_input_tokens"), "output": usage.get("output_tokens")})
    return _usage_session("codex", start, project_name, model, calls, breakdown) if start else None

def _claude_usage_session(path: Path, breakdown: bool) -> dict[str, object] | None:
    """Parse only Claude Code metadata and assistant usage counters from one JSONL."""
    start: datetime | None = None
    project_name = path.parent.name.removeprefix("-Users-").replace("-", "/").split("/")[-1]
    model: object = None
    calls: list[dict[str, object]] = []
    unavailable = 0
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            timestamp = _usage_start(event.get("timestamp"))
            start = min(start, timestamp) if start and timestamp else start or timestamp
            cwd = event.get("cwd")
            if isinstance(cwd, str):
                project_name = Path(cwd).name
            message = event.get("message")
            usage = message.get("usage") if event.get("type") == "assistant" and isinstance(message, dict) else None
            if isinstance(message, dict) and model is None:
                model = message.get("model")
            if isinstance(usage, dict):
                call = _claude_usage_call(usage)
                if call is None:
                    unavailable += 1
                else:
                    calls.append(call)
    session = _usage_session("claude", start, project_name, model, calls, breakdown) if start else None
    if session is not None and unavailable:
        session["unavailable_calls"] = unavailable
    return session

def usage_report(host: str | None, project_root: Path | None, since: str | None, breakdown: bool, home: Path | None = None) -> dict[str, object]:
    """Produce a deterministic, local-only session-counter report from private host logs."""
    selected = (host,) if host else USAGE_HOSTS
    cutoff = _usage_start(f"{since}T00:00:00+00:00") if since else None
    if since and cutoff is None:
        raise CardineError("--since must be an ISO date (YYYY-MM-DD)")
    root = home or Path.home()
    parsers = {
        "codex": (root / ".codex" / "sessions", "rollout-*.jsonl", _codex_usage_session),
        "claude": (root / ".claude" / "projects", "*.jsonl", _claude_usage_session),
    }
    sessions: list[dict[str, object]] = []
    adapter_status: list[dict[str, str]] = []
    wanted_project = project_root.name if project_root else None
    for current_host in selected:
        location, pattern, parser = parsers[current_host]
        recognized = 0
        if location.is_dir():
            for path in sorted(location.rglob(pattern)):
                try:
                    session = parser(path, breakdown)
                except (OSError, UnicodeDecodeError):
                    continue
                if session is None:
                    continue
                recognized += 1
                start = _usage_start(session["start"])
                if (cutoff and start and start < cutoff) or (wanted_project and session["project"] != wanted_project):
                    continue
                sessions.append(session)
        adapter_status.append({"host": current_host, "status": "ok" if recognized else "unsupported", "note": USAGE_ADAPTER_NOTES[current_host]})
    sessions.sort(key=lambda session: (str(session["start"]), str(session["host"]), str(session["project"])))
    return {
        "status": "ok" if sessions else "unsupported",
        "privacy": USAGE_PRIVACY_BOUNDARY,
        "adapters": adapter_status,
        "sessions": sessions,
        "summary": (
            "Startup cost is first_call_input; later growth is measured separately in per-call input and --breakdown. "
            "Input includes cached input for both hosts; cached is the cache-read part and cache_ratio = cached / input."
        ),
    }

def format_usage_report(report: dict[str, object]) -> str:
    lines = [str(report["privacy"]), str(report["summary"])]
    for adapter in report["adapters"]:  # type: ignore[index]
        lines.append(f"Adapter {adapter['host']}: {adapter['status']} — {adapter['note']}")
    for session in report["sessions"]:  # type: ignore[index]
        lines.append(
            f"{session['start']} {session['host']} {session['project']} model={session['model'] or 'unknown'} "
            f"calls={session['calls']} startup={session['first_call_input']} mean={session['mean_call_input']} "
            f"peak={session['peak_call_input']} input={session['cumulative_input']} cached={session['cached_input']} "
            f"output={session['output']} cache_ratio={session['cache_ratio']}"
            + (f" unavailable_calls={session['unavailable_calls']}" if "unavailable_calls" in session else "")
        )
        if "breakdown" in session:
            growth = session["breakdown"]["largest_input_growth"]
            lines.append(f"  breakdown: calls={session['breakdown']['calls']} largest_input_growth=call {growth['call']} (+{growth['tokens']})")
    return "\n".join(lines)
