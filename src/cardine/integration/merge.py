from __future__ import annotations

from cardine.shared.layout import names

from cardine.integration.decision import IntegrationValidationOutcome
from cardine.shared.errors import CardineError
from pathlib import Path
from cardine.shared.models import ResolvedTaskIdentity
from cardine.worktree.storage import _branch_commit
from cardine.worktree.storage import _effective_worktree_root
from cardine.shared.git import _git_worktrees
from cardine.integration.evidence import _integration_evidence
from cardine.integration.evidence import _lifecycle_changes_after_validation
from cardine.worktree.storage import _lifecycle_paths
from cardine.worktree.storage import _merge_head_path
from cardine.shared.jsonio import _read_json_object
from cardine.integration.evidence import _remove_owned_file
from cardine.shared.git import _run_git
from cardine.integration.evidence import _string_tuple
from cardine.worktree.paths import _task_worktree_path_for_identity
from cardine.worktree.storage import _verified_lifecycle_project
from cardine.shared.jsonio import _write_json_atomic
from cardine.integration.evidence import candidate_validation_declaration
from cardine.integration.decision import decide_integration_validation
from cardine.templates.mode import detect_mode
from cardine.shared.authority import find_adr_log
from cardine.shared.git import git_output
from cardine.worktree.checkout import inspect_task_worktree
import os
import re
from cardine.shared.text import read_task_field
from cardine.tasks.state import read_task_state
from cardine.tasks.identity import resolve_project_locations
from cardine.tasks.identity import resolve_task_identity
import shlex
import shutil
from cardine.tasks.state import state_path
from cardine.stops.render import stop_error
from cardine.tasks import status_render
from cardine.integration.evidence import undeclared_validation_commands_error


def _spike_disallowed_paths(
    project_root: Path, identity: ResolvedTaskIdentity, validated_base: str, validated_task: str
) -> tuple[str, ...]:
    """Return changed paths a SPIKE task is not allowed to integrate."""
    record_path = identity.task_path
    shown = _run_git(project_root, "show", f"{validated_task}:{record_path.relative_to(project_root)}")
    task_record = shown.stdout if shown.returncode == 0 else ""
    if (read_task_field(task_record, "Class") or "").lower() != "spike":
        return ()
    allowed = {
        str(record_path.relative_to(project_root)),
        str(identity.handoff_path.relative_to(project_root)),
        str(identity.review_path.relative_to(project_root)),
        str(find_adr_log(project_root).relative_to(project_root)),
        names().execution_evidence_path.as_posix(),
        str(state_path(project_root, identity.canonical_id).relative_to(project_root)),
    }
    deliverable = read_task_field(task_record, "Deliverable") or ""
    allowed.update(
        match.split("#", 1)[0]
        for match in re.findall(r"`(docs/[^`]+)`", deliverable)
        if match.split("#", 1)[0]
    )
    changed = tuple(filter(None, git_output(
        project_root, "diff", "--name-only", validated_base, validated_task
    ).splitlines()))
    return tuple(path for path in changed if path not in allowed and not re.fullmatch(r"changelog\.d/[^/]+\.md", path))


def _integration_task_state(
    project_root: Path, identity: ResolvedTaskIdentity, task_commit: str, worktree: Path,
    *, require_tracked: bool = False,
) -> dict[str, object] | None:
    """Prove terminal state and commit-bound approval before any lease or merge."""
    relative = state_path(project_root, identity.canonical_id).relative_to(project_root)
    try:
        shown = _run_git(project_root, "show", f"{task_commit}:{relative.as_posix()}")
    except UnicodeError as error:
        raise stop_error(
            "TASK_STATE_INVALID", f"{relative}: expected readable UTF-8 JSON; found {error}",
            task_id=identity.canonical_id, project=project_root,
        ) from error
    if shown.returncode != 0:
        raise stop_error(
            "TASK_STATE_MISSING", f"{relative}: expected tracked state at {task_commit}; found missing",
            task_id=identity.canonical_id, project=project_root,
        )
    workflow = detect_mode(project_root)
    record = identity.task_path.relative_to(project_root)
    snapshot = _run_git(project_root, "show", f"{task_commit}:{record.as_posix()}")
    record_text = snapshot.stdout if snapshot.returncode == 0 else ""
    spike = (read_task_field(record_text, "Class") or "").lower() == "spike"
    state = read_task_state(
        project_root, identity.canonical_id, workflow, spike=spike, review_required=None,
        stop_factory=lambda code, detail, **context: stop_error(code, f"{relative}: {detail}", **context),
        text=shown.stdout,
    )
    spike = state.get("contract", {}).get("class", "spike" if spike else "standard") == "spike"
    review = state.get("review", {})
    from cardine.tasks.state import review_is_required
    required = review_is_required(state)
    terminal = ("in_progress",)
    if state["status"] not in terminal:
        raise stop_error(
            "TASK_STATE_INVALID", f"{relative}: status expected {terminal}; found {state['status']!r}",
            task_id=identity.canonical_id, project=project_root,
        )
    if spike and state.get("outcome") not in ("ANSWERED", "INCONCLUSIVE"):
        raise stop_error("TASK_STATE_INVALID", "spike landing requires an outcome", task_id=identity.canonical_id, project=project_root)
    if required:
        if review.get("verdict") != "APPROVE":
            raise stop_error(
                "REVIEW_NOT_APPROVED", f"{relative}: review.verdict expected APPROVE; found {review.get('verdict')!r}",
                task_id=identity.canonical_id, project=project_root,
            )
        reviewed = review.get("reviewed_commit")
        if not reviewed or _run_git(project_root, "merge-base", "--is-ancestor", str(reviewed), task_commit).returncode != 0:
            raise stop_error(
                "REVIEW_STALE", f"{relative}: review.reviewed_commit expected ancestor of {task_commit}; found {reviewed!r}",
                task_id=identity.canonical_id, project=project_root,
            )
        allowed = {
            record.as_posix(),
            identity.handoff_path.relative_to(project_root).as_posix(),
            identity.review_path.relative_to(project_root).as_posix(),
            relative.as_posix(), names().execution_evidence_path.as_posix(),
        }
        changed = git_output(project_root, "log", "--format=", "--name-only", f"{reviewed}..{task_commit}").splitlines()
        offending = sorted(set(filter(None, changed)) - allowed)
        if offending:
            raise stop_error(
                "REVIEW_STALE", f"{relative}: expected only task governance paths after {reviewed}; offending paths: {', '.join(offending)}",
                task_id=identity.canonical_id, project=project_root,
            )
    return state


def _regenerate_status_views(project_root: Path) -> dict[str, object]:
    """Regenerate the queue and plan views once on the candidate tree and stage what changed.

    A failed write leaves the already written landed state in place and reports
    the stale view with the command that regenerates it.
    """
    command = status_render.COMMAND
    try:
        changed = [path.relative_to(project_root).as_posix() for path in status_render.write_views(project_root)]
        if changed:
            staged = _run_git(project_root, "add", "--", *changed)
            if staged.returncode:
                raise CardineError(staged.stderr.strip() or "could not stage the regenerated views")
    except (OSError, CardineError) as error:
        return {"status": "STALE", "paths": [], "command": command,
                "warning": f"status views are stale: {error}; run `{command}` after integration"}
    return {"status": "REGENERATED", "paths": changed, "command": command, "warning": None}


def stage_task_integration(
    task_id: str,
    worktree_root: Path | None,
    evidence_path: Path,
    supplied_project: Path | None = None,
) -> dict[str, object]:
    project_root = _verified_lifecycle_project(supplied_project)
    if Path.cwd().resolve() != project_root:
        raise CardineError("integration stage must run from the canonical primary checkout")
    identity = resolve_task_identity(project_root, task_id, "existing")
    _state_path, lease_path, integration_path = _lifecycle_paths(project_root, identity)
    if integration_path.exists():
        prior = _read_json_object(integration_path, "staged integration state")
        lease_matches = lease_path.is_file() and _read_json_object(
            lease_path, "integration lease"
        ).get("task_id") == identity.canonical_id
        candidate_matches = prior.get("candidate_tree") == git_output(project_root, "write-tree")
        merge_matches = _merge_head_path(project_root).is_file() and git_output(
            project_root, "rev-parse", "HEAD"
        ) == prior.get("main_commit")
        if (
            prior.get("task_id") == identity.canonical_id
            and lease_matches
            and candidate_matches
            and merge_matches
        ):
            return prior
        raise CardineError(f"staged integration state is mismatched or stale at {integration_path}")
    if lease_path.exists():
        raise stop_error(
            "LEASE_HELD",
            f"an interrupted integration lease is retained at {lease_path}; use `cardine worktree integrate abort`",
            task_id=identity.canonical_id, project=project_root,
        )
    inspection, ready = inspect_task_worktree(
        identity.canonical_id,
        worktree_root,
        project_root,
        require_effective_worktree=False,
    )
    if not ready:
        raise CardineError(f"task worktree is not ready: {', '.join(inspection['errors'])}")
    if git_output(project_root, "branch", "--show-current") != "main":
        raise CardineError("primary checkout must be on main")
    if git_output(project_root, "status", "--porcelain"):
        raise stop_error("PRIMARY_DIRTY", "primary checkout must be clean")
    origin = _run_git(project_root, "remote", "get-url", "origin")
    remote_main = _run_git(project_root, "rev-parse", "--verify", "refs/remotes/origin/main")
    if (
        origin.returncode == 0
        and remote_main.returncode == 0
        and _run_git(
            project_root, "merge-base", "--is-ancestor", "main", "refs/remotes/origin/main"
        ).returncode == 0
        and git_output(project_root, "rev-parse", "main") != git_output(
            project_root, "rev-parse", "refs/remotes/origin/main"
        )
    ):
        raise stop_error(
            "MAIN_BEHIND_ORIGIN",
            "local main is behind the already fetched origin/main "
            f"(local main {git_output(project_root, 'rev-parse', '--short=12', 'main')}, "
            f"origin/main {git_output(project_root, 'rev-parse', '--short=12', 'refs/remotes/origin/main')})",
            task_id=identity.canonical_id, project=project_root, evidence=evidence_path,
        )
    evidence = _integration_evidence(evidence_path)
    declaration_state, _fragments = candidate_validation_declaration(
        project_root, identity.canonical_id, task_project=Path(str(inspection["worktree"])),
    )
    if declaration_state == "undeclared":
        # This is deliberately before inspection, lease creation, and merge so the
        # first-use decision cannot strand an integration transaction.
        raise undeclared_validation_commands_error(project_root, evidence)
    if not evidence["accepted"] or not evidence["validation_passed"]:
        raise CardineError("accepted, successful task validation evidence is required")
    task_commit = str(inspection["task_commit"])
    task_state = _integration_task_state(project_root, identity, task_commit, Path(str(inspection["worktree"])))
    validated_task = str(evidence["validated_task_commit"])
    validated_base = str(evidence["validated_base_commit"])
    if validated_base != inspection["base_commit"]:
        raise stop_error(
            "EVIDENCE_MISMATCH",
            f"validated base {validated_base} differs from recorded base {inspection['base_commit']}; renew validation evidence",
            task_id=identity.canonical_id, project=project_root,
        )
    base_is_ancestor = _run_git(
        project_root, "merge-base", "--is-ancestor", validated_base, validated_task
    ).returncode == 0
    validated_is_ancestor = _run_git(
        project_root, "merge-base", "--is-ancestor", validated_task, task_commit
    ).returncode == 0
    relevant_unchanged = validated_task == task_commit
    if validated_is_ancestor and not relevant_unchanged:
        relevant_unchanged, offending = _lifecycle_changes_after_validation(
            project_root, identity, validated_task, task_commit
        )
        if offending:
            raise CardineError(f"paths changed after validation: {', '.join(offending)}")
    current_main = git_output(project_root, "rev-parse", "main")
    task_paths = tuple(filter(None, git_output(
        project_root, "diff", "--name-only", validated_base, validated_task
    ).splitlines()))
    disallowed_spike_paths = _spike_disallowed_paths(
        project_root, identity, validated_base, validated_task
    )
    if disallowed_spike_paths:
        raise CardineError(
            "SPIKE task changes disallowed path(s): " + ", ".join(disallowed_spike_paths)
        )
    main_paths = tuple(
        filter(None, git_output(project_root, "diff", "--name-only", validated_base, current_main).splitlines())
    ) if current_main != validated_base else ()
    decision = decide_integration_validation(
        evidence_complete=True,
        validated_task_commit=validated_task,
        current_task_commit=task_commit,
        validated_base_commit=validated_base,
        current_main_commit=current_main,
        validated_base_is_task_ancestor=base_is_ancestor,
        full_validation_required=bool(evidence["full_validation_required"]),
        validated_task_is_current_ancestor=validated_is_ancestor,
        relevant_tree_unchanged_after_validation=relevant_unchanged,
        interaction_assessment_complete=bool(evidence["interaction_assessment_complete"]),
        task_paths=tuple(sorted(set(task_paths) | set(_string_tuple(evidence["task_paths"], "task_paths")))),
        main_advanced_paths=main_paths,
        task_dependencies=_string_tuple(evidence["task_dependencies"], "task_dependencies"),
        main_advanced_dependencies=_string_tuple(evidence["main_advanced_dependencies"], "main_advanced_dependencies"),
        task_behavioral_surfaces=_string_tuple(evidence["task_behavioral_surfaces"], "task_behavioral_surfaces"),
        main_advanced_behavioral_surfaces=_string_tuple(
            evidence["main_advanced_behavioral_surfaces"], "main_advanced_behavioral_surfaces"
        ),
    )
    if decision.outcome == IntegrationValidationOutcome.BLOCKED:
        raise stop_error("EVIDENCE_MISMATCH", decision.reason, task_id=identity.canonical_id, project=project_root)
    lease = {
        "version": 1,
        "task_id": identity.canonical_id,
        "branch": identity.branch_name,
        "project": str(project_root),
        "main_commit": current_main,
    }
    try:
        _write_json_atomic(lease_path, lease, exclusive=True)
    except FileExistsError as error:
        raise stop_error(
            "LEASE_HELD", f"integration lease already exists: {lease_path}",
            task_id=identity.canonical_id, project=project_root,
        ) from error
    merged = _run_git(project_root, "merge", "--no-ff", "--no-commit", identity.branch_name)
    if merged.returncode != 0:
        aborted = _run_git(project_root, "merge", "--abort")
        if aborted.returncode == 0:
            _remove_owned_file(lease_path)
        raise stop_error(
            "INTEGRATION_CONFLICT",
            "integration conflict was aborted; task branch and worktree were retained",
            task_id=identity.canonical_id, project=project_root, evidence=evidence_path,
        )
    try:
        from datetime import datetime, timezone
        import copy
        task_state = copy.deepcopy(task_state)
        task_state["transitions"].append({"from": "in_progress", "to": "done", "commit": task_commit,
                                          "at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")})
        task_state["status"] = "done"
        path = state_path(project_root, identity.canonical_id)
        _write_json_atomic(path, task_state)
        staged_state = _run_git(project_root, "add", "--", path.relative_to(project_root).as_posix())
        if staged_state.returncode:
            raise CardineError(staged_state.stderr.strip() or "could not stage landed task state")
    except (OSError, CardineError) as error:
        aborted = _run_git(project_root, "merge", "--abort")
        if aborted.returncode == 0:
            _remove_owned_file(lease_path)
        raise CardineError(str(error)) from error
    views = _regenerate_status_views(project_root)
    candidate_tree = git_output(project_root, "write-tree")
    staged = {
        **lease,
        "task_commit": task_commit,
        "validated_task_commit": validated_task,
        "validated_base_commit": validated_base,
        "task_paths": list(task_paths),
        "main_advanced_paths": list(main_paths),
        "decision": decision.outcome.value,
        "reason": decision.reason,
        "candidate_tree": candidate_tree,
        "next_action": "validate-candidate",
        "landed_status": "done",
        "views": views,
        "warnings": [views["warning"]] if views["status"] == "STALE" else [],
    }
    _write_json_atomic(integration_path, staged, exclusive=True)
    return staged


def finalize_task_integration(
    task_id: str,
    validation_path: Path,
    supplied_project: Path | None = None,
) -> dict[str, object]:
    project_root = _verified_lifecycle_project(supplied_project)
    if Path.cwd().resolve() != project_root:
        raise CardineError("integration finalize must run from the canonical primary checkout")
    identity = resolve_task_identity(project_root, task_id, "existing")
    _task_state, lease_path, integration_path = _lifecycle_paths(project_root, identity)
    lease = _read_json_object(lease_path, "integration lease")
    staged = _read_json_object(integration_path, "staged integration state")
    if lease.get("task_id") != identity.canonical_id or staged.get("task_id") != identity.canonical_id:
        raise CardineError("integration ownership does not match the requested task")
    if not _merge_head_path(project_root).is_file() or git_output(
        project_root, "rev-parse", "HEAD"
    ) != staged.get("main_commit"):
        raise CardineError("the owned staged merge state is missing or its main commit changed")
    if git_output(project_root, "write-tree") != staged.get("candidate_tree"):
        raise stop_error("EVIDENCE_MISMATCH", "staged candidate tree changed after integration stage", task_id=identity.canonical_id, project=project_root)
    validation = _read_json_object(validation_path.expanduser().resolve(), "candidate validation evidence")
    if validation.get("candidate_tree") != staged.get("candidate_tree") or validation.get("passed") is not True:
        raise stop_error(
            "EVIDENCE_MISMATCH", "candidate validation evidence is stale, mismatched, or failed", task_id=identity.canonical_id, project=project_root
        )
    required_scope = "full" if staged.get("decision") == "FULL" else "bounded"
    if validation.get("scope") != required_scope:
        raise stop_error(
            "EVIDENCE_MISMATCH", f"candidate validation scope must be {required_scope!r}", task_id=identity.canonical_id, project=project_root
        )
    commands = validation.get("commands")
    if not isinstance(commands, list) or not commands or not all(isinstance(item, str) and item for item in commands):
        raise stop_error(
            "EVIDENCE_MISMATCH", "candidate validation evidence must name successful commands", task_id=identity.canonical_id, project=project_root
        )
    declaration_state, declaration_fragments = candidate_validation_declaration(project_root, identity.canonical_id)
    if declaration_state == "undeclared":
        raise stop_error(
            "UNDECLARED_VALIDATION_COMMANDS", "declare candidate validation commands before finalize"
        )
    missing_commands = missing_candidate_validation_commands(
        staged["decision"], commands, declaration_fragments
    )
    if missing_commands:
        raise stop_error(
            "EVIDENCE_MISMATCH",
            "candidate validation evidence is missing mandatory command(s): " + ", ".join(missing_commands),
            task_id=identity.canonical_id, project=project_root,
        )
    committed = _run_git(project_root, "commit", "-m", f"Integrate {identity.canonical_id}")
    if committed.returncode != 0:
        raise CardineError(committed.stderr.strip() or "integration commit failed; staged state was retained")
    merge_commit = git_output(project_root, "rev-parse", "HEAD")
    _remove_owned_file(integration_path)
    _remove_owned_file(lease_path)
    return {
        "version": 1,
        "task_id": identity.canonical_id,
        "merge_commit": merge_commit,
        "candidate_tree": staged["candidate_tree"],
        "decision": staged["decision"],
        "next_action": "push-or-cleanup",
    }


def runnable_candidate_validation_command(command: str, project_root: Path) -> bool:
    """Check the first POSIX shell token locally, without running the command.

    A path token must name an executable file relative to the primary checkout
    (or an absolute file). Bare names resolve on PATH, with relative PATH
    entries anchored to that checkout. Invalid quoting and empty entries fail.
    This is executable discovery, not validation of arguments or shell syntax.
    """
    try:
        tokens = shlex.split(command)
    except ValueError:
        return False
    if not tokens:
        return False
    executable = tokens[0]
    if "/" in executable:
        path = project_root / executable
        return path.is_file() and os.access(path, os.X_OK)
    search_path = os.pathsep.join(str(project_root / entry) for entry in os.get_exec_path())
    return shutil.which(executable, path=search_path) is not None


def missing_candidate_validation_commands(
    decision: object, commands: list[str], fragments: dict[str, tuple[str, ...]] | None = None
) -> tuple[str, ...]:
    """Return mandatory command fragments absent from candidate evidence.

    This is intentionally a pure string check.  It accepts the profile's
    optional ``set -o pipefail;`` prefix and output-bounding pipelines because
    the required fragment remains in the command entry.
    """
    if fragments is None:
        _state, fragments = candidate_validation_declaration(Path.cwd())
    required = ("git diff --check", *fragments.get(str(decision), ()))
    return tuple(fragment for fragment in required if not any(fragment in command for command in commands))


def abort_task_integration(task_id: str, supplied_project: Path | None = None) -> dict[str, object]:
    project_root = _verified_lifecycle_project(supplied_project)
    if Path.cwd().resolve() != project_root:
        raise CardineError("integration abort must run from the canonical primary checkout")
    # Abort must stay possible when the queue link is stale, so it skips link checks.
    identity = resolve_task_identity(project_root, task_id, "existing", check_queue_links=False)
    _task_state, lease_path, integration_path = _lifecycle_paths(project_root, identity)
    lease = _read_json_object(lease_path, "integration lease")
    staged = _read_json_object(integration_path, "staged integration state") if integration_path.is_file() else None
    if lease.get("task_id") != identity.canonical_id or (
        staged is not None and staged.get("task_id") != identity.canonical_id
    ):
        raise CardineError("integration ownership does not match the requested task")
    merge_head = _merge_head_path(project_root)
    if merge_head.exists():
        aborted = _run_git(project_root, "merge", "--abort")
        if aborted.returncode != 0:
            raise CardineError(aborted.stderr.strip() or "cannot abort the owned staged integration")
    _remove_owned_file(integration_path)
    _remove_owned_file(lease_path)
    return {"version": 1, "task_id": identity.canonical_id, "status": "aborted", "next_action": "inspect"}


def cleanup_task_worktree(
    task_id: str,
    worktree_root: Path | None,
    supplied_project: Path | None = None,
) -> dict[str, object]:
    project_root = _verified_lifecycle_project(supplied_project)
    if Path.cwd().resolve() != project_root:
        raise CardineError("worktree cleanup must run from the canonical primary checkout")
    identity = resolve_task_identity(project_root, task_id, "existing")
    root = _effective_worktree_root(worktree_root)
    expected = _task_worktree_path_for_identity(project_root, root, identity)
    lifecycle_state_path, lease_path, integration_path = _lifecycle_paths(project_root, identity)
    registered = next((item for item in _git_worktrees(project_root)
                       if Path(item["worktree"]).resolve() == expected), None)
    branch_commit = _branch_commit(project_root, identity.branch_name)
    absent_or_empty = not expected.exists() or (expected.is_dir() and not any(expected.iterdir()))
    if lease_path.exists() or integration_path.exists() or _merge_head_path(project_root).exists():
        raise stop_error("CLEANUP_BLOCKED", "cleanup is blocked while an integration lease or staged merge is active", task_id=identity.canonical_id, project=project_root)
    if (
        registered is None
        and absent_or_empty
        and branch_commit is None
        and not lifecycle_state_path.exists()
    ):
        expected.mkdir(parents=True, exist_ok=True)
        return {"version": 1, "task_id": identity.canonical_id, "status": "cleaned", "already_cleaned": True}
    inspection, ready = inspect_task_worktree(
        identity.canonical_id,
        worktree_root,
        project_root,
        require_effective_worktree=False,
    )
    recovered_from = None
    allowed_errors: set[str] = set()
    if registered is not None and not expected.exists() and "prunable" in registered:
        recovered_from = "registered-directory-missing"
        allowed_errors = {"missing-worktree"}
    elif registered is None and absent_or_empty:
        recovered_from = "unregistered-worktree" if branch_commit else "branch-already-deleted"
        allowed_errors = {"unregistered-worktree"}
    if not ready and (not allowed_errors or set(inspection["errors"]) - allowed_errors):
        raise stop_error("CLEANUP_BLOCKED", f"cleanup preflight failed: {', '.join(inspection['errors'])}", task_id=identity.canonical_id, project=project_root)
    if git_output(project_root, "status", "--porcelain"):
        raise stop_error("CLEANUP_BLOCKED", "primary checkout must be clean", task_id=identity.canonical_id, project=project_root)
    task_commit = str(inspection["task_commit"]) if registered is not None else branch_commit
    if task_commit is None:
        # Preparation's lifecycle task_commit predates implementation. Only a
        # tracked terminal task state on main can prove closure without a ref.
        try:
            relative = state_path(project_root, identity.canonical_id).relative_to(project_root)
            shown = _run_git(project_root, "show", f"main:{relative.as_posix()}")
            if shown.returncode != 0:
                raise CardineError("missing tracked task state")
            workflow = detect_mode(project_root)
            spike = (read_task_field(identity.task_path.read_text(encoding="utf-8"), "Class") or "").lower() == "spike"
            state = read_task_state(
                project_root, identity.canonical_id, workflow, spike=spike, review_required=None,
                stop_factory=stop_error, text=shown.stdout,
            )
            terminal = ("done",)
            if state["status"] not in terminal:
                raise CardineError(f"nonterminal tracked task state: {state['status']}")
        except CardineError as error:
            raise stop_error("CLEANUP_BLOCKED", f"branch already deleted; tracked task state on main must be done: {error}", task_id=identity.canonical_id, project=project_root) from error
    elif _run_git(project_root, "merge-base", "--is-ancestor", task_commit, "main").returncode != 0:
        raise stop_error("CLEANUP_BLOCKED", "task commit is not integrated into main", task_id=identity.canonical_id, project=project_root)
    origin = _run_git(project_root, "remote", "get-url", "origin")
    if origin.returncode == 0:
        remote_main = _run_git(project_root, "rev-parse", "--verify", "refs/remotes/origin/main")
        if remote_main.returncode != 0 or _run_git(
            project_root, "merge-base", "--is-ancestor", "main", "refs/remotes/origin/main"
        ).returncode != 0:
            raise stop_error("CLEANUP_BLOCKED", "local main is not proven pushed to origin/main", task_id=identity.canonical_id, project=project_root)
    if registered is not None:
        removed = _run_git(project_root, "worktree", "remove", str(expected))
        if removed.returncode != 0:
            partial = "registered-directory-missing" if not expected.exists() else "registered-directory-present"
            raise stop_error(
                "CLEANUP_BLOCKED", f"{partial}: worktree removal failed; cleanup needs write access to the primary checkout's .git directory; {removed.stderr.strip()}", task_id=identity.canonical_id, project=project_root,
                resume=f"cardine worktree cleanup {shlex.quote(identity.canonical_id)} --project {shlex.quote(str(project_root))} --worktree-root {shlex.quote(str(root))} --format json"
            )
    # Codex launches Stop hooks with the session path as cwd, even after cleanup.
    # Keep an empty, unregistered directory so the host can start the hook.
    expected.mkdir(parents=True, exist_ok=True)
    if branch_commit is not None:
        deleted = _run_git(project_root, "branch", "-d", identity.branch_name)
        if deleted.returncode != 0:
            raise stop_error(
                "CLEANUP_BLOCKED", deleted.stderr.strip() or "non-force branch deletion failed", task_id=identity.canonical_id, project=project_root
            )
    _remove_owned_file(lifecycle_state_path)
    result = {"version": 1, "task_id": identity.canonical_id, "status": "cleaned"}
    if recovered_from:
        result["recovered_from"] = recovered_from
    return result
