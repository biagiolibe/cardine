"""Helpers extracted from the legacy CLI; see the module split plan."""

from __future__ import annotations

from cardine.shared.layout import PRODUCT_NAMES, names

from datetime import datetime, timezone
import json
from pathlib import Path
import re
import statistics

from cardine.shared.errors import CardineError
from cardine.shared.git import canonical_git_common_dir
from cardine.shared.journal import JOURNAL_VERSION
from cardine.stops.registry import load_stop_registry
from cardine.tasks.contract_snapshot import read_human_contract
from cardine.worktree.storage import lifecycle_started_at


FLOW_TARGETS_PATH = PRODUCT_NAMES.flow_targets_path


FLOW_TARGETS_VERSION = 1


FLOW_ORIGINS = ("capability", "friction", "maintenance", "release")


FLOW_ORIGIN_PATTERN = re.compile(r"^>\s*\*\*Origin\*\*:\s*(\S+)", re.MULTILINE)


FLOW_JOURNAL_TIME = "%Y-%m-%dT%H:%M:%SZ"


FLOW_UNCODED = "uncoded"


def _flow_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, FLOW_JOURNAL_TIME).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _flow_read_journal(project_root: Path) -> tuple[list[dict[str, object]], int]:
    """Read the rotated and current journal; return valid records in file order and the malformed-line count."""
    directory = canonical_git_common_dir(project_root)
    records: list[dict[str, object]] = []
    malformed = 0
    for name in (names().journal_rotated_name, names().journal_name):
        try:
            text = (directory / name).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for raw in text.splitlines():
            if not raw.strip():
                continue
            try:
                record = json.loads(raw)
            except json.JSONDecodeError:
                malformed += 1
                continue
            when = _flow_time(record.get("ts")) if isinstance(record, dict) else None
            if (
                when is None
                or record.get("version") != JOURNAL_VERSION
                or not isinstance(record.get("command"), str)
                or not isinstance(record.get("result"), str)
            ):
                malformed += 1
                continue
            record["_when"] = when
            records.append(record)
    return records, malformed


def _flow_origin(project_root: Path, task: str) -> str:
    """Read the frozen origin label, using unknown for unavailable snapshots."""
    try:
        origin = read_human_contract(project_root, task)["origin"].lower()
    except (CardineError, OSError, UnicodeDecodeError):
        return "unknown"
    return origin if origin in FLOW_ORIGINS else "unknown"


def _flow_median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def _flow_targets(project_root: Path, tasks: list[dict[str, object]], unbacked_times: list[datetime]) -> list[dict[str, object]]:
    """Evaluate the declared targets over count windows of integrated tasks; a missing file declares none."""
    path = project_root / names().flow_targets_path
    if not path.is_file():
        return []
    try:
        declared = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CardineError(f"{names().flow_targets_path} is unreadable: {error}") from error
    if not isinstance(declared, dict) or declared.get("version") != FLOW_TARGETS_VERSION:
        raise CardineError(f"{names().flow_targets_path} must be a version {FLOW_TARGETS_VERSION} object")
    integrated = sorted((task for task in tasks if task["_integrated"] is not None), key=lambda task: task["_integrated"])
    results: list[dict[str, object]] = []

    def window_of(entry: object, name: str) -> int:
        window = entry.get("window") if isinstance(entry, dict) else None
        if not isinstance(window, int) or isinstance(window, bool) or window < 1:
            raise CardineError(f"{names().flow_targets_path}: {name}.window must be a positive integer")
        return window

    def limit_of(entry: object, name: str, key: str) -> float:
        value = entry.get(key) if isinstance(entry, dict) else None
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
            raise CardineError(f"{names().flow_targets_path}: {name}.{key} must be a non-negative number")
        return value

    def state(measured: float | None, limit: float) -> str:
        return "insufficient data" if measured is None else ("met" if measured <= limit else "missed")

    if "unbacked_blocks" in declared:
        entry = declared["unbacked_blocks"]
        window, limit = window_of(entry, "unbacked_blocks"), limit_of(entry, "unbacked_blocks", "max")
        recent = integrated[-window:]
        measured = None
        if len(recent) >= window:
            start = min(task["_started"] or task["_integrated"] for task in recent)
            measured = sum(1 for when in unbacked_times if when >= start)
        results.append({"target": "unbacked_blocks", "window": window, "limit": limit, "measured": measured, "state": state(measured, limit)})
    if "lead_time_regression" in declared:
        entry = declared["lead_time_regression"]
        window, limit = window_of(entry, "lead_time_regression"), limit_of(entry, "lead_time_regression", "max_percent")
        timed = [task["lead_time_seconds"] for task in integrated if task["lead_time_seconds"] is not None]
        measured = None
        if len(timed) >= 2 * window:
            recent_median = statistics.median(timed[-window:])
            prior_median = statistics.median(timed[-2 * window:-window])
            measured = (recent_median - prior_median) / prior_median * 100 if prior_median else (0.0 if not recent_median else float("inf"))
        results.append({
            "target": "lead_time_regression", "window": window, "limit": limit,
            "measured": None if measured is None else (round(measured, 1) if measured != float("inf") else "unbounded"),
            "state": "insufficient data" if measured is None else ("met" if measured <= limit else "missed"),
        })
    if "friction_share" in declared:
        entry = declared["friction_share"]
        window, limit = window_of(entry, "friction_share"), limit_of(entry, "friction_share", "max_percent")
        declaring = [task for task in integrated if task["origin"] != "unknown"][-window:]
        measured = None
        if len(declaring) >= window:
            measured = round(100 * sum(1 for task in declaring if task["origin"] == "friction") / window, 1)
        results.append({"target": "friction_share", "window": window, "limit": limit, "measured": measured, "state": state(measured, limit)})
    return results


def _flow_resolution(record: dict[str, object]) -> str:
    """Preserve recorded classifications; infer them for journals written before task 030."""
    resolution = record.get("resolution")
    if resolution in ("guardrail", "recoverable", "failing-work"):
        return str(resolution)
    return str(load_stop_registry().get(str(record.get("stop_code")), {}).get("resolution", "unknown"))


def _flow_tasks(project_root: Path, records: list[dict[str, object]], cutoff: datetime | None) -> list[dict[str, object]]:
    """Build one entry per task that has a journal record in the period; lead time uses the task's whole history."""
    in_period = lambda record: cutoff is None or record["_when"] >= cutoff  # noqa: E731
    by_task: dict[str, list[dict[str, object]]] = {}
    for record in records:
        task = record.get("task")
        if isinstance(task, str) and record["command"] != "stop-audit":
            by_task.setdefault(task, []).append(record)
    tasks: list[dict[str, object]] = []
    for task, task_records in sorted(by_task.items(), key=lambda item: (len(item[0]), item[0])):
        if not any(in_period(record) for record in task_records):
            continue
        prepared = [r["_when"] for r in task_records if r["command"] == "prepare" and r["result"] == "ok" and not r.get("resume")]
        finalized = [r["_when"] for r in task_records if r["command"] == "integrate finalize" and r["result"] == "ok"]
        started = min(prepared) if prepared else None
        if started is None:
            try:
                recorded = lifecycle_started_at(task, project_root)
            except (CardineError, OSError):
                recorded = None
            started = datetime.fromisoformat(recorded.replace("Z", "+00:00")) if recorded else None
        integrated = min(finalized) if finalized else None
        counted = [r for r in task_records if in_period(r)]
        stops: dict[str, int] = {}
        resolutions: dict[str, int] = {}
        for record in counted:
            if record["result"] == "blocked":
                code = record.get("stop_code")
                key = code if isinstance(code, str) else FLOW_UNCODED
                stops[key] = stops.get(key, 0) + 1
                resolution = _flow_resolution(record)
                resolutions[resolution] = resolutions.get(resolution, 0) + 1
        tasks.append({
            "task": task,
            "lead_time_seconds": int((integrated - started).total_seconds()) if started and integrated else None,
            "stops": dict(sorted(stops.items())),
            "stops_by_resolution": dict(sorted(resolutions.items())),
            "aborts": sum(1 for r in counted if r["command"] == "integrate abort" and r["result"] == "ok"),
            "resumes": sum(1 for r in counted if r["command"] == "prepare" and r.get("resume") and r["result"] == "ok"),
            "origin": _flow_origin(project_root, task),
            "_started": started,
            "_integrated": integrated,
        })
    return tasks


def flow_report(project_root: Path, since: str | None, now: datetime | None = None) -> dict[str, object]:
    """Summarize the lifecycle journal into lead time, stops, and origin shares; read-only."""
    cutoff = None
    if since is not None:
        try:
            cutoff = datetime.strptime(since, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError as error:
            raise CardineError("--since must be an ISO date (YYYY-MM-DD)") from error
    records, malformed = _flow_read_journal(project_root)
    registry = load_stop_registry()
    in_period = lambda record: cutoff is None or record["_when"] >= cutoff  # noqa: E731
    tasks = _flow_tasks(project_root, records, cutoff)
    unbacked_times = [record["_when"] for record in records if record["result"] == "unbacked_block"]
    stops_by_code: dict[str, int] = {}
    stops_by_resolution: dict[str, int] = {}
    for record in records:
        if in_period(record) and record["result"] == "blocked":
            code = record.get("stop_code")
            key = code if isinstance(code, str) else FLOW_UNCODED
            stops_by_code[key] = stops_by_code.get(key, 0) + 1
            resolution = _flow_resolution(record)
            stops_by_resolution[resolution] = stops_by_resolution.get(resolution, 0) + 1
    stops_by_class: dict[str, int] = {}
    for code, count in stops_by_code.items():
        klass = FLOW_UNCODED if code == FLOW_UNCODED else str(registry.get(code, {}).get("class", "unknown"))
        stops_by_class[klass] = stops_by_class.get(klass, 0) + count
    origins = {name: 0 for name in (*FLOW_ORIGINS, "unknown")}
    for task in tasks:
        origins[str(task["origin"])] += 1
    total = len(tasks)
    origin_share = {name: (round(100 * count / total, 1) if total else 0.0) for name, count in origins.items()}
    lead_times = [task["lead_time_seconds"] for task in tasks if task["lead_time_seconds"] is not None]
    period_records = [record for record in records if in_period(record)]
    start = cutoff or (min(record["_when"] for record in period_records) if period_records else None)
    end = now or datetime.now(timezone.utc)
    period_days = max(0, (end - start).days) if start else 0
    emitted = {record.get("stop_code") for record in period_records if record["result"] == "blocked"}
    candidates = sorted(code for code, entry in registry.items() if entry.get("class") == "tool" and code not in emitted) if period_records else []
    # Targets use count windows over all integrated tasks, never the --since period.
    targets = _flow_targets(project_root, tasks if cutoff is None else _flow_tasks(project_root, records, None), unbacked_times)
    public_tasks = [{key: value for key, value in task.items() if not key.startswith("_")} for task in tasks]
    blocks_by_host = {host: {"unbacked": 0, "declared": 0} for host in ("claude", "codex")}
    for record in period_records:
        kind = {"unbacked_block": "unbacked", "declared_block": "declared"}.get(str(record["result"]))
        if kind is not None:
            host = record.get("host", "claude")
            blocks_by_host.setdefault(host if isinstance(host, str) else "unknown", {"unbacked": 0, "declared": 0})[kind] += 1
    report: dict[str, object] = {
        "since": since,
        "malformed_lines": malformed,
        "period_days": period_days,
        "tasks": public_tasks,
        "totals": {
            "tasks": total,
            "integrated": len(lead_times),
            "median_lead_time_seconds": _flow_median(lead_times),
            "aborts": sum(task["aborts"] for task in tasks),
            "resumes": sum(task["resumes"] for task in tasks),
            "stops": sum(stops_by_code.values()),
        },
        "stops_by_code": dict(sorted(stops_by_code.items())),
        "stops_by_class": dict(sorted(stops_by_class.items())),
        "stops_by_resolution": dict(sorted(stops_by_resolution.items())),
        "unbacked_blocks": sum(1 for record in period_records if record["result"] == "unbacked_block"),
        "blocks_by_host": blocks_by_host,
        "origin_counts": origins,
        "origin_share_percent": origin_share,
        "targets": targets,
        "removal_candidates": candidates,
    }
    return report


def format_flow_report(report: dict[str, object]) -> str:
    totals = report["totals"]  # type: ignore[assignment]
    median = totals["median_lead_time_seconds"]
    lines = [
        f"Flow report{' since ' + str(report['since']) if report['since'] else ''}: {totals['tasks']} tasks, "
        f"{totals['integrated']} integrated, median lead time {_flow_duration(median)}, "
        f"{totals['stops']} stops, {totals['aborts']} aborts, {totals['resumes']} resumes",
    ]
    if report["malformed_lines"]:
        lines.append(f"Malformed journal lines skipped: {report['malformed_lines']}")
    for task in report["tasks"]:  # type: ignore[index]
        stops = ", ".join(f"{code}={count}" for code, count in task["stops"].items()) or "none"
        resolutions = ", ".join(f"{key}={value}" for key, value in task["stops_by_resolution"].items()) or "none"
        lines.append(
            f"  task {task['task']}: lead time {_flow_duration(task['lead_time_seconds'])}, stops {stops}, "
            f"resolutions {resolutions}, aborts {task['aborts']}, resumes {task['resumes']}, origin {task['origin']}"
        )
    lines.append("Stops by code: " + (", ".join(f"{k}={v}" for k, v in report["stops_by_code"].items()) or "none"))  # type: ignore[attr-defined]
    lines.append("Stops by class: " + (", ".join(f"{k}={v}" for k, v in report["stops_by_class"].items()) or "none"))  # type: ignore[attr-defined]
    lines.append("Stops by resolution: " + (", ".join(f"{k}={v}" for k, v in report["stops_by_resolution"].items()) or "none"))
    by_host = report["blocks_by_host"]  # type: ignore[assignment]
    for kind, label in (("unbacked", "Unbacked stop reports"), ("declared", "Declared stop reports")):
        if any(counts[kind] for counts in by_host.values()):
            lines.append(f"{label}: " + ", ".join(f"{host}={counts[kind]}" for host, counts in by_host.items()))
    lines.append("Origin share: " + ", ".join(f"{k}={v}%" for k, v in report["origin_share_percent"].items()))  # type: ignore[attr-defined]
    for target in report["targets"]:  # type: ignore[index]
        lines.append(f"Target {target['target']}: {target['state']} (measured {target['measured']}, limit {target['limit']}, window {target['window']})")
    candidates = report["removal_candidates"]
    lines.append(
        f"Removal candidates (tool-class stops not emitted in {report['period_days']} days): "
        + (", ".join(candidates) or "none")  # type: ignore[arg-type]
    )
    return "\n".join(lines)


def _flow_duration(seconds: object) -> str:
    if not isinstance(seconds, (int, float)):
        return "n/a"
    return f"{seconds / 3600:.1f}h"
