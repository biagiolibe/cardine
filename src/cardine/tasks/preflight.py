"""Execution contract preflight and readiness checks."""

from __future__ import annotations

from cardine.shared.git import TASK_BRANCH_OPEN_STATUSES
from cardine.shared.git import current_branch
from cardine.shared.text import read_task_field
from cardine.stops.render import stop_error
from cardine.tasks.contract import NORMAL_PREFLIGHT_HEADINGS
from cardine.tasks.contract import PREFLIGHT_HEADINGS
from cardine.tasks.contract import SPIKE_PREFLIGHT_FIELDS
from cardine.tasks.contract import check_handoff
from cardine.tasks.contract import contract_digest
from cardine.tasks.contract import contract_requires_execution_commands
from cardine.tasks.contract import profile_digest
from cardine.tasks.contract import validate_host_impact_declaration
from cardine.tasks.contract import verify_host_impact_completion_evidence
from cardine.tasks.evidence import require_named_validation_commands
from cardine.tasks.evidence import validation_commands
from cardine.tasks.identity import find_task_file
from cardine.tasks.identity import resolve_task_identity
from pathlib import Path
import re


def execution_contract(project_root: Path, task_id: str) -> str:
    """Render the profile-derived execution block placed in a task at design time."""
    task = find_task_file(project_root, task_id)
    text = task.read_text(encoding="utf-8")
    require_named_validation_commands(text)
    commands = ", ".join(validation_commands(text)) or "none"
    return "\n".join((
        "## Execution contract — resolved",
        "",
        "- Profile source: `docs/EXECUTION_EVIDENCE_PROFILE.md`",
        f"- Profile revision: `sha256:{profile_digest(project_root)}`",
        f"- Validation IDs: {commands}",
        "- Execution commands: `required via meridian execution`",
    ))


def execution_preflight(project_root: Path, task_id: str, *, options: dict | None = None) -> str:
    """Validate the minimum durable execution contract before implementation.

    This intentionally does not inspect a chat's reasoning setting: that is a
    host concern and is outside this command's authority.
    """
    identity = resolve_task_identity(project_root, task_id, "existing")
    task_file = identity.task_path
    text = task_file.read_text(encoding="utf-8")
    require_named_validation_commands(text)
    validate_host_impact_declaration(text)
    expected_digest = profile_digest(project_root)
    recorded_digest = contract_digest(text)
    task_name = task_file.relative_to(project_root).as_posix()
    if recorded_digest is None:
        raise stop_error(
            "EXECUTION_CONTRACT_UNRESOLVED",
            f"rule: a task needs a resolved execution contract; field checked: `- Profile revision` in {task_name}; "
            f"expected: sha256:{expected_digest}; found: no such line",
            task_id=task_id,
        )
    if recorded_digest != expected_digest:
        raise stop_error(
            "EXECUTION_CONTRACT_UNRESOLVED",
            f"rule: the resolved contract must match the current profile; field checked: `- Profile revision` in "
            f"{task_name} against docs/EXECUTION_EVIDENCE_PROFILE.md; expected: sha256:{expected_digest}; "
            f"found: sha256:{recorded_digest}",
            task_id=task_id,
        )
    if not contract_requires_execution_commands(text):
        raise stop_error(
            "EXECUTION_CONTRACT_UNRESOLVED",
            f"rule: the contract must require execution commands; field checked: `- Execution commands` in "
            f"{task_name}; expected: `required via meridian execution`; found: no such line",
            task_id=task_id,
        )
    if options is None:
        from cardine.tasks.state import read_task_state, state_path
        from cardine.templates.mode import detect_mode
        if state_path(project_root, task_id).exists():
            snapshot = read_task_state(project_root, task_id, detect_mode(project_root), stop_factory=stop_error)
            options = snapshot.get("contract", {}).get("options")
    required_headings = tuple(heading for heading in PREFLIGHT_HEADINGS
                              if heading != "Authority" or options is None or options["authorityRequired"])
    missing = [
        f"## {heading}"
        for heading in required_headings
        if not re.search(rf"^## {re.escape(heading)}\s*$", text, re.MULTILINE)
    ]
    if (read_task_field(text, "Class") or "").lower() == "spike":
        missing.extend(field for field in SPIKE_PREFLIGHT_FIELDS if not read_task_field(text, field))
    elif options is None or options["expectedCodeSurfaceRequired"]:
        missing.extend(
            f"## {heading}"
            for heading in NORMAL_PREFLIGHT_HEADINGS
            if not re.search(rf"^## {re.escape(heading)}\s*$", text, re.MULTILINE)
        )
    if missing:
        is_spike = (read_task_field(text, "Class") or "").lower() == "spike"
        required = [f"## {heading}" for heading in PREFLIGHT_HEADINGS] + (
            list(SPIKE_PREFLIGHT_FIELDS) if is_spike else [f"## {heading}" for heading in NORMAL_PREFLIGHT_HEADINGS]
        )
        raise stop_error(
            "TASK_RECORD_INCOMPLETE",
            f"rule: a {'SPIKE' if is_spike else 'normal'} task record must contain its required headings"
            f"{' and fields' if is_spike else ''}; source checked: {task_name}; accepted: "
            + ", ".join(required) + "; missing: " + ", ".join(missing),
            task_id=task_id,
        )
    from cardine.tasks.state import read_task_state
    from cardine.templates.mode import detect_mode
    status = read_task_state(project_root, task_id, detect_mode(project_root), stop_factory=stop_error)["status"]
    on_task_branch = current_branch(project_root) == identity.branch_name
    open_statuses = TASK_BRANCH_OPEN_STATUSES if on_task_branch else ("queued", "in_progress")
    if status not in open_statuses:
        raise stop_error(
            "TASK_STATUS_REJECTED",
            f"rule: preflight runs only on an open task; field checked: validated task state for {task_name}; "
            f"accepted: {', '.join(open_statuses)}; found: {status or 'missing'}",
        )
    return f"Execution contract: {task_file.relative_to(project_root)}"


def reconcile_execution_contract(project_root: Path, task_id: str, apply: bool) -> str:
    """Refresh only a nonterminal task's generated execution-contract block."""
    task_file = find_task_file(project_root, task_id)
    text = task_file.read_text(encoding="utf-8")
    from cardine.tasks.state import read_task_state
    from cardine.templates.mode import detect_mode
    status = read_task_state(project_root, task_id, detect_mode(project_root), stop_factory=stop_error)["status"]
    if status in ("done", "cancelled"):
        return f"Execution reconciliation skipped for terminal task {task_id} ({status})"
    if status not in ("queued", "in_progress"):
        raise stop_error(
            "TASK_STATUS_REJECTED",
            f"rule: reconcile refreshes only an open task; field checked: validated task state for "
            f"{task_file.relative_to(project_root).as_posix()}; accepted: queued, in_progress "
            f"(terminal tasks are skipped); found: {status}",
        )
    generated = execution_contract(project_root, task_id)
    section = re.compile(
        r"^## Execution contract — resolved\s*$\n.*?(?=^## |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    replacement = generated + "\n\n"
    match = section.search(text)
    if match:
        separator = "\n\n" if match.end() < len(text) else "\n"
        reconciled = text[:match.start()] + generated + separator + text[match.end():]
    elif re.search(r"^## Completion\s*$", text, re.MULTILINE):
        reconciled = re.sub(r"^## Completion\s*$", replacement + "## Completion", text, count=1, flags=re.MULTILINE)
    else:
        reconciled = text.rstrip() + "\n\n" + generated + "\n"
    if reconciled == text:
        return f"Execution reconciliation already current for {task_id}: {task_file.relative_to(project_root)}"
    if not apply:
        return f"Execution reconciliation required for {task_id}: {task_file.relative_to(project_root)} (rerun with --apply)"
    task_file.write_text(reconciled, encoding="utf-8")
    return f"Execution reconciliation applied for {task_id}: {task_file.relative_to(project_root)}"


def readiness_check(project_root: Path, task_id: str, report: Path) -> str:
    """Combine execution and handoff gates before a task enters review."""
    execution_preflight(project_root, task_id)
    verify_host_impact_completion_evidence(find_task_file(project_root, task_id).read_text(encoding="utf-8"))
    check_handoff(project_root, task_id, report)
    return f"in_review gate passed for {task_id}"



def check_dependencies(project_root: Path, task_id: str, record: str) -> None:
    """Check canonical state on primary main, never an unlanded task branch."""
    from cardine.templates.mode import detect_mode
    from cardine.shared.git import canonical_project_root, _run_git
    from cardine.tasks.state import read_task_state, state_path, dependency_satisfied
    match = re.search(r"^## Dependencies\s*$\n(.*?)(?=^## |\Z)", record, re.MULTILINE | re.DOTALL)
    body = match.group(1) if match else ""
    field = re.search(r"(?:Depends on|Dependencies)\*{0,2}\s*:\s*(.+)", body, re.IGNORECASE)
    raw = field.group(1) if field else body.strip()
    raw = re.sub(r"\[([^]]+)\]\([^)]+\)", r"\1", raw)
    dependencies = []
    for item in re.split(r"[,\n]", raw):
        item = item.strip().removeprefix("- ").strip().strip("`").strip()
        if item.lower().strip(" .") in ("", "none", "—", "-"):
            continue
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", item) is None:
            raise stop_error("TASK_STATUS_REJECTED", f"invalid dependency declaration {item!r}", task_id=task_id, project=project_root)
        dependencies.append(item)
    primary = canonical_project_root(project_root)
    for dependency in dependencies:
        path = state_path(project_root, dependency).relative_to(project_root)
        shown = _run_git(primary, "show", f"main:{path.as_posix()}")
        if shown.returncode:
            raise stop_error("TASK_STATUS_REJECTED", f"dependency {dependency} has no landed state", task_id=task_id, project=project_root)
        state = read_task_state(project_root, dependency, detect_mode(project_root), text=shown.stdout, stop_factory=stop_error)
        if not dependency_satisfied(state):
            raise stop_error("TASK_STATUS_REJECTED", f"dependency {dependency} is not a landed successful result", task_id=task_id, project=project_root)
