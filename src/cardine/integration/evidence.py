"""Task and candidate validation evidence."""

from __future__ import annotations

from cardine.shared.layout import names

from cardine.shared.constants import VALIDATION_EVIDENCE_SCHEMA_PATH
from cardine.shared.constants import VALIDATION_EXIT_FAILED
from cardine.shared.constants import VALIDATION_EXIT_PASSED
from cardine.shared.constants import VALIDATION_EXIT_PENDING
from cardine.shared.errors import CardineError
from cardine.shared.git import _run_git
from cardine.shared.git import git_output
from cardine.shared.jsonio import _read_json_object
from cardine.shared.jsonio import _write_json_atomic
from cardine.shared.models import CANDIDATE_VALIDATION_OUTCOMES
from cardine.shared.models import ResolvedTaskIdentity
from cardine.stops.render import stop_error
from cardine.tasks.identity import resolve_project_locations
from cardine.tasks.identity import resolve_task_identity
from cardine.tasks.state import state_path
from cardine.worktree.checkout import inspect_task_worktree
from cardine.worktree.storage import _lifecycle_paths
from cardine.worktree.storage import _verified_lifecycle_project
from pathlib import Path
import json
import re
from cardine.shared.paths import SCRIPTS_ROOT


def _validation_reason(reasons: list[str], condition: bool, reason: str) -> None:
    if not condition:
        reasons.append(reason)


def validation_evidence_reasons(record: object) -> list[str]:
    """Return schema-shaped errors without running a project command."""
    if not isinstance(record, dict):
        return ["record: must be an object"]
    reasons: list[str] = []
    required = ("version", "task_id", "status", "level", "commit", "tree", "command", "tests_run", "produced_at")
    for field in required:
        _validation_reason(reasons, field in record, f"{field}: is required")
    _validation_reason(reasons, record.get("version") == 1, "version: must be 1")
    _validation_reason(reasons, isinstance(record.get("task_id"), str) and bool(record.get("task_id")), "task_id: must be a non-empty string")
    _validation_reason(reasons, record.get("status") in {"running", "unavailable", "failed", "passed"}, "status: unknown value")
    _validation_reason(reasons, record.get("level") in {"T1_CI", "T2_SHARDED", "T3_ATTESTED"}, "level: unknown value")
    for field in ("commit", "tree", "produced_at"):
        _validation_reason(reasons, isinstance(record.get(field), str) and bool(record.get(field)), f"{field}: must be a non-empty string")
    _validation_reason(reasons, isinstance(record.get("command"), list) and all(isinstance(item, str) and item for item in record.get("command", [])), "command: must be an array of non-empty strings")
    unknown_ci_count = record.get("level") == "T1_CI" and record.get("tests_run") is None
    _validation_reason(reasons, unknown_ci_count or (isinstance(record.get("tests_run"), int) and not isinstance(record.get("tests_run"), bool)), "tests_run: must be an integer or null for T1_CI")
    status = record.get("status")
    if status == "running":
        for field in ("started_at", "log"):
            _validation_reason(reasons, isinstance(record.get(field), str) and bool(record.get(field)), f"{field}: is required for running")
    elif status == "unavailable":
        _validation_reason(reasons, isinstance(record.get("reason"), str) and bool(record.get("reason")), "reason: is required for unavailable")
    elif status in {"failed", "passed"}:
        _validation_reason(reasons, isinstance(record.get("exit_code"), int) and not isinstance(record.get("exit_code"), bool), f"exit_code: is required for {status}")
    level = record.get("level")
    if level == "T1_CI":
        ci = record.get("ci")
        _validation_reason(reasons, isinstance(ci, dict), "ci: is required for T1_CI")
        if isinstance(ci, dict):
            for field in ("run_id", "run_url", "workflow", "conclusion", "head_sha"):
                _validation_reason(reasons, isinstance(ci.get(field), str) and bool(ci.get(field)), f"ci.{field}: is required for T1_CI")
    elif level == "T2_SHARDED":
        shards = record.get("shards")
        _validation_reason(reasons, isinstance(shards, list) and bool(shards), "shards: is required for T2_SHARDED")
        for field in ("total", "digest"):
            _validation_reason(reasons, field in record, f"{field}: is required for T2_SHARDED")
        if isinstance(shards, list):
            for number, shard in enumerate(shards, 1):
                _validation_reason(reasons, isinstance(shard, dict), f"shards[{number}]: must be an object")
                if isinstance(shard, dict):
                    for field in ("index", "count", "exit_code", "tests_run", "digest", "total"):
                        _validation_reason(reasons, field in shard, f"shards[{number}].{field}: is required")
    elif level == "T3_ATTESTED":
        _validation_reason(reasons, record.get("attested_by") == "developer", "attested_by: must be developer for T3_ATTESTED")
        _validation_reason(reasons, isinstance(record.get("attested_on"), str) and bool(record.get("attested_on")), "attested_on: is required for T3_ATTESTED")
        _validation_reason(reasons, isinstance(record.get("statement"), str) and bool(record.get("statement").strip()), "statement: is required for T3_ATTESTED")
    return reasons


def check_validation_evidence(record_path: Path, project_root: Path, expected_commit: str | None) -> tuple[dict[str, object], int]:
    """Read an external validation attestation using Git plumbing only."""
    reasons: list[str] = []
    try:
        schema = json.loads((SCRIPTS_ROOT.parent / VALIDATION_EVIDENCE_SCHEMA_PATH).read_text(encoding="utf-8"))
        if not isinstance(schema, dict) or schema.get("$id") != "https://cardine.local/schemas/validation-evidence-v1.schema.json":
            reasons.append("schema: validation-evidence-v1 is invalid")
    except (OSError, json.JSONDecodeError) as error:
        reasons.append(f"schema: {error}")
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        record = None
        reasons.append(f"record: {error}")
    reasons.extend(validation_evidence_reasons(record))
    if not isinstance(record, dict):
        return {"status": "VALIDATION_FAILED", "level": None, "reasons": reasons}, VALIDATION_EXIT_FAILED
    status, level = record.get("status"), record.get("level")
    if status == "running" and not reasons:
        return {"status": "VALIDATION_RUNNING", "level": level, "reasons": []}, VALIDATION_EXIT_PENDING
    if status == "unavailable" and not reasons:
        return {"status": "VALIDATION_UNAVAILABLE", "level": level, "reasons": []}, VALIDATION_EXIT_PENDING
    if status != "passed":
        reasons.append("status: is not passed")
    try:
        branch = resolve_task_identity(project_root, str(record.get("task_id", "")), "existing").branch_name
        target = expected_commit or git_output(project_root, "rev-parse", branch)
        resolved = git_output(project_root, "rev-parse", f"{record.get('commit', '')}^{{commit}}")
        _validation_reason(reasons, resolved == target, "commit: does not equal the expected commit")
        _validation_reason(reasons, git_output(project_root, "rev-parse", f"{resolved}^{{tree}}") == record.get("tree"), "tree: does not equal commit tree")
    except CardineError as error:
        reasons.append(f"commit: {error}")
    _validation_reason(reasons, record.get("exit_code") == 0, "exit_code: must be 0")
    unknown_ci_count = level == "T1_CI" and record.get("tests_run") is None
    _validation_reason(reasons, unknown_ci_count or (isinstance(record.get("tests_run"), int) and record.get("tests_run", 0) > 0), "tests_run: must be above 0 or null for T1_CI")
    if level == "T1_CI" and isinstance(record.get("ci"), dict):
        ci = record["ci"]
        _validation_reason(reasons, ci.get("conclusion") == "success", "ci.conclusion: must be success")
        _validation_reason(reasons, ci.get("head_sha") == record.get("commit"), "ci.head_sha: must equal commit")
    elif level == "T2_SHARDED" and isinstance(record.get("shards"), list):
        shards = record["shards"]
        counts = {shard.get("count") for shard in shards if isinstance(shard, dict)}
        count = next(iter(counts)) if len(counts) == 1 else None
        indexes = [shard.get("index") for shard in shards if isinstance(shard, dict)]
        _validation_reason(reasons, isinstance(count, int) and sorted(indexes) == list(range(1, count + 1)), "shards.index: must contain 1..count exactly once")
        _validation_reason(reasons, all(isinstance(shard, dict) and shard.get("exit_code") == 0 for shard in shards), "shards.exit_code: every shard must be 0")
        _validation_reason(reasons, sum(shard.get("tests_run", 0) for shard in shards if isinstance(shard, dict)) == record.get("total"), "total: must equal shard tests_run sum")
        _validation_reason(reasons, all(isinstance(shard, dict) and shard.get("digest") == record.get("digest") and shard.get("total") == record.get("total") for shard in shards), "shards.digest: every shard must carry the record digest and total")
    report_status = "VALIDATION_PASSED" if not reasons else "VALIDATION_FAILED"
    return {"status": report_status, "level": level, "reasons": reasons}, VALIDATION_EXIT_PASSED if not reasons else VALIDATION_EXIT_FAILED


def _string_tuple(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise CardineError(f"integration evidence field {label!r} must be an array of non-empty strings")
    return tuple(value)


def _bool_field(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise CardineError(f"integration evidence field {label!r} must be boolean")
    return value


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


def undeclared_validation_commands_error(project_root: Path, evidence: dict[str, object]) -> CardineError:
    commands = evidence.get("validation_commands")
    recorded = ", ".join(commands) if isinstance(commands, list) and commands else "none recorded"
    proposal = json.dumps(proposed_candidate_validation_declaration(project_root), sort_keys=True)
    return stop_error(
        "UNDECLARED_VALIDATION_COMMANDS",
        f"no project choice is recorded at {names().candidate_validation_path}. "
        f"Task validation commands: {recorded}. Proposed declaration: {proposal}",
    )


def _integration_evidence(path: Path) -> dict[str, object]:
    evidence = _read_json_object(path.expanduser().resolve(), "integration evidence")
    required = {
        "accepted",
        "validation_passed",
        "validated_task_commit",
        "validated_base_commit",
        "full_validation_required",
        "interaction_assessment_complete",
        "task_paths",
        "task_dependencies",
        "task_behavioral_surfaces",
        "main_advanced_dependencies",
        "main_advanced_behavioral_surfaces",
    }
    missing = sorted(required - evidence.keys())
    if missing:
        raise CardineError(f"integration evidence is incomplete; missing: {', '.join(missing)}")
    for field in ("accepted", "validation_passed", "full_validation_required", "interaction_assessment_complete"):
        _bool_field(evidence[field], field)
    for field in (
        "task_paths",
        "task_dependencies",
        "task_behavioral_surfaces",
        "main_advanced_dependencies",
        "main_advanced_behavioral_surfaces",
    ):
        _string_tuple(evidence[field], field)
    for field in ("validated_task_commit", "validated_base_commit"):
        if not isinstance(evidence[field], str) or not re.fullmatch(r"[0-9a-f]{40}", evidence[field]):
            raise CardineError(f"integration evidence field {field!r} must be a full Git object ID")
    return evidence


def record_task_evidence(
    task_id: str,
    worktree_root: Path | None,
    validation_commands: list[str],
    validation_exit_codes: list[int],
    *,
    accepted: bool,
    task_dependencies: list[str],
    task_behavioral_surfaces: list[str],
    main_advanced_dependencies: list[str],
    main_advanced_behavioral_surfaces: list[str],
    full_validation_required: bool,
    supplied_project: Path | None = None,
    require_effective_worktree: bool = True,
) -> dict[str, object]:
    """Record Git-derived task-validation facts without running validation."""
    if len(validation_commands) != len(validation_exit_codes):
        raise CardineError("each --validation-command requires one --validation-exit-code")
    if not validation_commands or any(not command.strip() for command in validation_commands):
        raise CardineError("at least one non-empty --validation-command is required")
    project_root = _verified_lifecycle_project(supplied_project)
    identity = resolve_task_identity(project_root, task_id, "existing")
    inspection, ready = inspect_task_worktree(
        identity.canonical_id,
        worktree_root,
        project_root,
        require_effective_worktree=require_effective_worktree,
    )
    if not ready:
        raise CardineError(f"task worktree is not ready: {', '.join(inspection['errors'])}")
    state_path, _lease, _integration = _lifecycle_paths(project_root, identity)
    state = _read_json_object(state_path, "worktree lifecycle state")
    task_commit = str(inspection["task_commit"])
    base_commit = str(state["base_commit"])
    task_paths = tuple(filter(None, git_output(
        project_root, "diff", "--name-only", base_commit, task_commit
    ).splitlines()))
    evidence_path = state_path.with_suffix(".evidence.json")
    evidence = {
        "accepted": accepted,
        "validation_passed": all(code == 0 for code in validation_exit_codes),
        "validated_task_commit": task_commit,
        "validated_base_commit": base_commit,
        "full_validation_required": full_validation_required,
        "interaction_assessment_complete": True,
        "task_paths": list(task_paths),
        "task_dependencies": task_dependencies,
        "task_behavioral_surfaces": task_behavioral_surfaces,
        "main_advanced_dependencies": main_advanced_dependencies,
        "main_advanced_behavioral_surfaces": main_advanced_behavioral_surfaces,
        "validation_commands": validation_commands,
        "validation_exit_codes": validation_exit_codes,
    }
    _write_json_atomic(evidence_path, evidence)
    return {
        "version": 1,
        "task_id": identity.canonical_id,
        "evidence": str(evidence_path),
        "validated_task_commit": task_commit,
        "validated_base_commit": base_commit,
        "task_paths": list(task_paths),
        "validation_passed": evidence["validation_passed"],
    }


def _remove_owned_file(path: Path) -> None:
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
        names().execution_evidence_path.as_posix(),
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

