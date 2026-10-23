"""Read-only location compatibility for installed Meridian snapshots."""
from pathlib import Path
import re
from cardine.shared.constants import MARKER_BEGIN, MARKER_END
from cardine.shared.snapshot_adapters import execution_assets_adapter
from cardine.shared.models import ProjectLocations
from cardine.shared.project import read_project_declaration, _safe_project_path
from cardine.shared.git import primary_project_root
from cardine.shared.errors import CardineError

def read_execution_assets(workflow_text: str) -> tuple[str, str]:
    """Return the execution-assets block and the zone that follows it, or empty strings."""
    reader = execution_assets_adapter.get()
    if reader is not None:
        return reader(workflow_text)
    block = rf"<!-- {MARKER_BEGIN} capability=execution-assets .*?{re.escape(MARKER_END)}"
    block_match = re.search(block, workflow_text, re.DOTALL)
    match = re.search(block + r"\s*(.*?)(?=^## |\Z)", workflow_text, re.MULTILINE | re.DOTALL)
    return (block_match.group(0) if block_match else ""), (match.group(1) if match else "")


def resolve_meridian_locations(project_root: Path) -> ProjectLocations:
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
        block_zone, zone = read_execution_assets(workflow.read_text(encoding="utf-8"))
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
            raise CardineError(f"canonical {label} must be a safe project-relative path: {path}")
    project_root = project_root.resolve()
    return ProjectLocations(
        queue=queue,
        task_roots=tuple(roots),
        adr_log=adr_log,
        handoff_root=handoff_root,
        review_root=review_root,
        plan=plan,
    )
