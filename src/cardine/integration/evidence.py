"""Task and candidate validation evidence: measured by the engine, never read from a caller-written record."""

from __future__ import annotations

from cardine.shared.layout import names

from cardine.shared.errors import CardineError
from cardine.shared.git import _run_git
from cardine.shared.git import git_output
from cardine.shared.jsonio import _read_json_object
from cardine.shared.models import CANDIDATE_VALIDATION_OUTCOMES
from cardine.shared.models import ResolvedTaskIdentity
from cardine.stops.render import stop_error
from cardine.tasks.identity import resolve_project_locations
from cardine.tasks.identity import resolve_task_identity
from cardine.tasks.state import state_path
from cardine.worktree.checkout import inspect_task_worktree
from cardine.worktree.storage import _verified_lifecycle_project
from pathlib import Path
import json


def candidate_validation_declaration(
    project_root: Path, task_id: str | None = None, *, task_project: Path | None = None,
) -> tuple[str, dict[str, tuple[str, ...]]]:
    """Use frozen task commands; retain declarations for pre-contract records."""
    if task_id is not None:
        source = task_project or project_root
        path = state_path(source, task_id)
        if path.is_file():
            try:
                snapshot = _read_json_object(path, "task state")
            except (CardineError, OSError, UnicodeError) as error:
                raise stop_error(
                    "TASK_STATE_INVALID", f"{path}: expected readable UTF-8 JSON; found {error}",
                    task_id=task_id, project=project_root,
                ) from error
            if "contract" in snapshot:
                from cardine.tasks.state import read_task_state
                from cardine.shared.project import project_validation_commands
                state = read_task_state(source, task_id, "single", stop_factory=stop_error)
                contract = state["contract"]
                return "declared", {
                    outcome: tuple(command for command in project_validation_commands(contract, outcome)
                                   if command != "git diff --check")
                    for outcome in CANDIDATE_VALIDATION_OUTCOMES
                }
    path = project_root / names().candidate_validation_path
    if not path.exists():
        return "undeclared", {}
    data = _read_json_object(path, "candidate-validation declaration")
    if data.get("version") != 1:
        raise CardineError(f"{path}: version must be 1")
    state = data.get("state")
    if state == "undeclared":
        if set(data) != {"version", "state"}:
            raise CardineError(f"{path}: undeclared state must contain only version and state")
        return state, {}
    if state == "none":
        if set(data) != {"version", "state"}:
            raise CardineError(f"{path}: none state must contain only version and state")
        return state, {}
    if state != "declared":
        raise CardineError(f"{path}: state must be declared, none, or undeclared")
    outcomes = data.get("outcomes")
    if set(data) != {"version", "state", "outcomes"} or not isinstance(outcomes, dict):
        raise CardineError(f"{path}: declared state requires only version, state, and outcomes")
    if set(outcomes) != set(CANDIDATE_VALIDATION_OUTCOMES):
        raise CardineError(f"{path}: outcomes must declare REUSE, BOUNDED, and FULL")
    parsed: dict[str, tuple[str, ...]] = {}
    for outcome in CANDIDATE_VALIDATION_OUTCOMES:
        fragments = outcomes[outcome]
        if not isinstance(fragments, list) or not fragments or not all(
            isinstance(fragment, str) and fragment.strip() for fragment in fragments
        ):
            raise CardineError(f"{path}: outcomes.{outcome} must be a non-empty array of non-empty strings")
        parsed[outcome] = tuple(fragments)
    return state, parsed


def proposed_candidate_validation_declaration(project_root: Path) -> dict[str, object]:
    """Offer conservative detected-stack defaults; setup applies them only on --apply."""
    repository_check = "python3 scripts/check_repository.py"
    has_repository_check = (project_root / "scripts/check_repository.py").is_file()
    has_python_tests = (project_root / "tests").is_dir()
    if not has_repository_check:
        return {"version": 1, "state": "undeclared"}
    outcomes: dict[str, list[str]] = {
        "REUSE": [repository_check],
        "BOUNDED": [repository_check],
        "FULL": [repository_check],
    }
    if has_python_tests:
        outcomes["FULL"].append("python3 -m unittest discover -s tests")
    return {"version": 1, "state": "declared", "outcomes": outcomes}


def undeclared_validation_commands_error(project_root: Path) -> CardineError:
    proposal = json.dumps(proposed_candidate_validation_declaration(project_root), sort_keys=True)
    return stop_error(
        "UNDECLARED_VALIDATION_COMMANDS",
        f"no project choice is recorded at {names().candidate_validation_path}. Proposed declaration: {proposal}",
    )


def measured_task_validation(worktree: Path, task_id: str) -> dict[str, object] | None:
    """Return the receipt-verified passing attempt that covers the delivered source.

    Nothing here is declared by a caller: the attempt, its commands, exits and
    source identity come from the measured state, and a stale or edited result
    is simply absent. ``worktree`` is the clean canonical task worktree.
    """
    from cardine.tasks.state import read_task_state
    from cardine.tasks.validation import host_observations_complete, verified_validation
    state = read_task_state(worktree, task_id, "single", stop_factory=stop_error, require_contract=True)
    progress = verified_validation(worktree, task_id, state)
    delivery = state.get("run", {}).get("delivery")
    if not progress or not delivery or progress["phase"] != "passed" or not progress["runs"]:
        return None
    last = progress["runs"][-1]
    if any(entry["exitStatus"] != 0 for entry in last) or not host_observations_complete(state["contract"], progress):
        return None
    return {"attempt": progress["attemptId"], "validated_task_commit": progress["inputs"]["source"],
            "validated_base_commit": delivery["base"]}


def measured_validation_report(
    task_id: str, worktree_root: Path | None, supplied_project: Path | None = None,
) -> dict[str, object]:
    """Report the measured validation of the delivered source; it records nothing."""
    project_root = _verified_lifecycle_project(supplied_project)
    identity = resolve_task_identity(project_root, task_id, "existing")
    inspection, ready = inspect_task_worktree(
        identity.canonical_id, worktree_root, project_root, require_effective_worktree=False,
    )
    if not ready:
        raise CardineError(f"task worktree is not ready: {', '.join(inspection['errors'])}")
    measured = measured_task_validation(Path(str(inspection["worktree"])), identity.canonical_id)
    if measured is None:
        raise stop_error(
            "EVIDENCE_INCOMPLETE", "no passing measured validation covers the delivered source",
            task_id=identity.canonical_id, project=project_root,
        )
    task_paths = tuple(filter(None, git_output(
        project_root, "diff", "--name-only", str(measured["validated_base_commit"]),
        str(measured["validated_task_commit"]),
    ).splitlines()))
    return {"version": 1, "task_id": identity.canonical_id, **measured, "task_paths": list(task_paths),
            "validation_passed": True}


def _remove_owned_file(path: Path) -> None:
    from cardine.shared.git import invalidate_facts
    invalidate_facts()
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _lifecycle_changes_after_validation(
    project_root: Path,
    identity: ResolvedTaskIdentity,
    validated_task: str,
    task_commit: str,
) -> tuple[bool, tuple[str, ...]]:
    """Accept only changes to the task's own stable record, handoff, review, state and evidence."""
    project_root = project_root.resolve()
    allowed = {
        str(identity.task_path.relative_to(project_root)),
        str(identity.handoff_path.relative_to(project_root)),
        str(identity.review_path.relative_to(project_root)),
        str(state_path(project_root, identity.canonical_id).relative_to(project_root)),
        names().execution_evidence_path(identity.canonical_id).as_posix(),
    }
    output = _run_git(
        project_root,
        "diff",
        "--name-status",
        "-z",
        "--no-renames",
        validated_task,
        task_commit,
    ).stdout
    fields = output.split("\0")
    if fields and fields[-1] == "":
        fields.pop()
    offending: set[str] = set()
    index = 0
    while index < len(fields):
        status = fields[index]
        if index + 1 >= len(fields):
            raise CardineError("invalid Git diff output")
        path = fields[index + 1]
        index += 2
        if path not in allowed or (path == str(identity.task_path.relative_to(project_root)) and status != "M"):
            offending.add(path)
    return not offending, tuple(sorted(offending))

