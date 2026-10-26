from __future__ import annotations

from cardine.tasks.state import require_contract_snapshot

from cardine.shared.layout import names

from cardine.integration.decision import IntegrationValidationOutcome
from cardine.shared.errors import CardineError
from pathlib import Path
from cardine.shared.models import ResolvedTaskIdentity
from cardine.worktree.storage import _branch_commit
from cardine.worktree.storage import _effective_worktree_root
from cardine.shared.git import _git_worktrees
from cardine.integration.evidence import measured_task_validation
from cardine.integration.evidence import _lifecycle_changes_after_validation
from cardine.worktree.storage import _lifecycle_paths
from cardine.worktree.storage import _merge_head_path
from cardine.shared.jsonio import _read_json_object
from cardine.integration.evidence import _remove_owned_file
from cardine.shared.git import _run_git
from cardine.worktree.paths import _task_worktree_path_for_identity
from cardine.worktree.storage import _verified_lifecycle_project
from cardine.shared.jsonio import _write_json_atomic
from cardine.integration.evidence import candidate_validation_declaration
from cardine.integration.decision import decide_integration_validation
from cardine.templates.mode import detect_mode
from cardine.shared.authority import find_adr_log
from cardine.shared.git import canonical_git_common_dir
from cardine.shared.git import git_output
from cardine.worktree.checkout import inspect_task_worktree
import os
import re
from cardine.tasks.state import read_task_state
from cardine.tasks.identity import resolve_project_locations
from cardine.tasks.identity import resolve_task_identity
import shlex
import shutil
from cardine.tasks.state import state_path
from cardine.stops.causes import cleanup_branch_stop_code
from cardine.stops.causes import lease_stop_code
from cardine.stops.causes import main_ahead_of_origin
from cardine.stops.render import stop_error
from cardine.tasks import status_render
from cardine.integration.evidence import undeclared_validation_commands_error


def _spike_disallowed_paths(
    project_root: Path, identity: ResolvedTaskIdentity, validated_base: str, validated_task: str, state: dict
) -> tuple[str, ...]:
    """Return changed paths a SPIKE task is not allowed to integrate."""
    record_path = identity.task_path
    contract = require_contract_snapshot(state, project_root)
    if contract["class"] != "spike":
        return ()
    allowed = {
        str(record_path.relative_to(project_root)),
        str(identity.handoff_path.relative_to(project_root)),
        str(identity.review_path.relative_to(project_root)),
        str(find_adr_log(project_root).relative_to(project_root)),
        names().execution_evidence_path(identity.canonical_id).as_posix(),
        str(state_path(project_root, identity.canonical_id).relative_to(project_root)),
    }
    from cardine.tasks.contract_fields import frozen_human_fields
    allowed.update(frozen_human_fields(state)["deliverables"])
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
    state = read_task_state(
        project_root, identity.canonical_id, workflow,
        stop_factory=lambda code, detail, **context: stop_error(code, f"{relative}: {detail}", **context),
        text=shown.stdout, require_contract=True,
    )
    spike = state["contract"]["class"] == "spike"
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
                "REVIEW_NOT_APPROVED", f"cause: missing; {relative}: review.verdict expected APPROVE; found {review.get('verdict')!r}",
                task_id=identity.canonical_id, project=project_root,
            )
        decision = state.get('run', {}).get('reviewDecision')
        from cardine.lifecycle import receipts
        if (not decision or decision['binding']['contract'] != receipts.digest(receipts.encoded(state['contract']))
                or decision['binding']['verdict'] != 'APPROVE'
                or decision['binding']['source'] != review.get('reviewed_commit')
                or not any(r['kind'] == 'review_verdict:' + receipts.digest(receipts.encoded(decision))
                           for r in state['run']['receipts'])):
            raise stop_error('REVIEW_NOT_APPROVED', 'cause: missing; no issued review decision receipt',
                             task_id=identity.canonical_id, project=project_root)
        reviewed = review.get("reviewed_commit")
        if not reviewed or _run_git(project_root, "merge-base", "--is-ancestor", str(reviewed), task_commit).returncode != 0:
            raise stop_error(
                "REVIEW_NOT_APPROVED", "cause: stale; " + f"{relative}: review.reviewed_commit expected ancestor of {task_commit}; found {reviewed!r}",
                task_id=identity.canonical_id, project=project_root,
            )
        allowed = {
            identity.task_path.relative_to(project_root).as_posix(),
            identity.handoff_path.relative_to(project_root).as_posix(),
            identity.review_path.relative_to(project_root).as_posix(),
            relative.as_posix(), names().execution_evidence_path(identity.canonical_id).as_posix(),
        }
        changed = git_output(project_root, "log", "--format=", "--name-only", f"{reviewed}..{task_commit}").splitlines()
        offending = sorted(set(filter(None, changed)) - allowed)
        if offending:
            raise stop_error(
                "REVIEW_NOT_APPROVED", "cause: stale; " + f"{relative}: expected only task governance paths after {reviewed}; offending paths: {', '.join(offending)}",
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
    evidence_path: Path | None = None,
    supplied_project: Path | None = None,
) -> dict[str, object]:
    """Stage the exact task candidate. ``evidence_path`` is only a diagnostic reference.

    The validation that gates staging is the receipt-verified attempt measured
    in the task worktree; no caller-supplied file or result is read.
    """
    from cardine.integration.residue import recover_landing_residue
    from cardine.lifecycle import receipts
    project_root = _verified_lifecycle_project(supplied_project)
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
            lease_stop_code(project_root, identity, lease_path),
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
    recover_landing_residue(project_root, identity.canonical_id)
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
    declaration_state, _fragments = candidate_validation_declaration(
        project_root, identity.canonical_id, task_project=Path(str(inspection["worktree"])),
    )
    if declaration_state == "undeclared":
        # This is deliberately before inspection, lease creation, and merge so the
        # first-use decision cannot strand an integration transaction.
        raise undeclared_validation_commands_error(project_root)
    task_commit = str(inspection["task_commit"])
    task_state = _integration_task_state(project_root, identity, task_commit, Path(str(inspection["worktree"])))
    from cardine.lifecycle.execution import enforce_execution_scope
    enforce_execution_scope(Path(str(inspection["worktree"])), identity.canonical_id,
                            state=task_state, base=str(inspection["base_commit"]))
    measured = measured_task_validation(Path(str(inspection["worktree"])), identity.canonical_id)
    if measured is None:
        raise stop_error(
            "EVIDENCE_INCOMPLETE", "no passing measured validation covers the delivered source",
            task_id=identity.canonical_id, project=project_root,
        )
    from cardine.integration.ci import require_ci_pass
    require_ci_pass(Path(str(inspection["worktree"])), project_root, identity.canonical_id, task_state)
    validated_task = str(measured["validated_task_commit"])
    validated_base = str(measured["validated_base_commit"])
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
        project_root, identity, validated_base, validated_task, task_state
    )
    if disallowed_spike_paths:
        raise CardineError(
            "SPIKE task changes disallowed path(s): " + ", ".join(disallowed_spike_paths)
        )
    main_paths = tuple(
        filter(None, git_output(project_root, "diff", "--name-only", validated_base, current_main).splitlines())
    ) if current_main != validated_base else ()
    decision = decide_integration_validation(
        validation_measured=True,
        validated_task_commit=validated_task,
        current_task_commit=task_commit,
        validated_base_commit=validated_base,
        current_main_commit=current_main,
        validated_base_is_task_ancestor=base_is_ancestor,
        validated_task_is_current_ancestor=validated_is_ancestor,
        relevant_tree_unchanged_after_validation=relevant_unchanged,
        task_paths=task_paths,
        main_advanced_paths=main_paths,
        pinned_paths=(names().project_declaration_path.as_posix(), names().candidate_validation_path.as_posix()),
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
    receipts.boundary("before_stage_lease")
    try:
        _write_json_atomic(lease_path, lease, exclusive=True)
    except FileExistsError as error:
        raise stop_error(
            "LEASE_HELD", f"integration lease already exists: {lease_path}",
            task_id=identity.canonical_id, project=project_root,
        ) from error
    receipts.boundary("after_stage_lease")
    merged = _run_git(project_root, "merge", "--no-ff", "--no-commit", identity.branch_name)
    if merged.returncode != 0:
        conflict = bool(git_output(project_root, "ls-files", "--unmerged"))
        aborted = _run_git(project_root, "merge", "--abort") if _merge_head_path(project_root).exists() else None
        if aborted is None or aborted.returncode == 0:
            _remove_owned_file(lease_path)
        raise stop_error(
            "INTEGRATION_CONFLICT" if conflict else "GIT_OPERATION_FAILED",
            "textual integration conflict" if conflict else "transient Git merge failure: " + merged.stderr.strip(),
            task_id=identity.canonical_id, project=project_root, evidence=evidence_path,
        )
    try:
        from datetime import datetime, timezone
        import copy
        previous_state = copy.deepcopy(task_state)
        task_state = copy.deepcopy(task_state)
        task_state["transitions"].append({"from": "in_progress", "to": "done", "commit": task_commit,
                                          "at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")})
        task_state["status"] = "done"
        path = state_path(project_root, identity.canonical_id)
        from cardine.lifecycle.receipts import task_lock, write_operation
        with task_lock(project_root, identity.canonical_id):
            write_operation(project_root, identity.canonical_id, task_state,
                            kind='landing_state', previous=previous_state)
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
    receipts.boundary("before_stage_json")
    _write_json_atomic(integration_path, staged, exclusive=True)
    receipts.boundary("after_stage_json")
    return staged


def finalize_task_integration(
    task_id: str,
    validation_path: Path | None = None,
    supplied_project: Path | None = None,
) -> dict[str, object]:
    from cardine.integration.finalize import finalize_candidate
    return finalize_candidate(task_id, supplied_project)


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


def abort_task_integration(task_id: str, supplied_project: Path | None = None, *, adapter=None) -> dict[str, object]:
    from cardine.lifecycle.control_abort import abort_owned
    return abort_owned(task_id, supplied_project, adapter=adapter)


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
        blocked = "CLEANUP_BLOCKED"
        if lease_path.exists() and not integration_path.exists() and (
            lease_stop_code(project_root, identity, lease_path) == "LEASE_INTERRUPTED"
        ):
            blocked = "LEASE_INTERRUPTED"
        raise stop_error(blocked, "cleanup is blocked while an integration lease or staged merge is active", task_id=identity.canonical_id, project=project_root)
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
            state = read_task_state(
                project_root, identity.canonical_id, workflow,
                stop_factory=stop_error, require_contract=True, text=shown.stdout,
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
            raise stop_error(
                "PUSH_PENDING" if main_ahead_of_origin(project_root) else "CLEANUP_BLOCKED",
                "local main is not proven pushed to origin/main", task_id=identity.canonical_id, project=project_root,
            )
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
                cleanup_branch_stop_code(project_root, identity.branch_name, task_commit, canonical_git_common_dir(project_root)),
                deleted.stderr.strip() or "non-force branch deletion failed", task_id=identity.canonical_id, project=project_root
            )
    _remove_owned_file(lifecycle_state_path)
    result = {"version": 1, "task_id": identity.canonical_id, "status": "cleaned"}
    if recovered_from:
        result["recovered_from"] = recovered_from
    return result
