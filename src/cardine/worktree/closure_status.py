from __future__ import annotations

from cardine.shared.errors import CardineError
from pathlib import Path
from cardine.shared.models import ResolvedTaskIdentity
from cardine.worktree.storage import _branch_commit
from cardine.worktree.storage import _effective_worktree_root
from cardine.shared.git import _git_worktrees
from cardine.integration.evidence import _integration_evidence
from cardine.worktree.storage import _lifecycle_paths
from cardine.shared.jsonio import _read_json_object
from cardine.shared.git import _run_git
from cardine.worktree.paths import _task_worktree_path_for_identity
from cardine.worktree.storage import _verified_lifecycle_project
from cardine.shared.git import git_output
from cardine.worktree.checkout import inspect_task_worktree
from cardine.tasks.identity import resolve_task_identity
from cardine.stops.causes import lease_stop_code
from cardine.stops.render import stop_resume


def closure_status(
    task_id: str,
    worktree_root: Path | None,
    supplied_project: Path | None = None,
    identity: ResolvedTaskIdentity | None = None,
) -> tuple[dict[str, object], bool]:
    """Report the next closure step without changing Git or lifecycle state.

    `identity` is the caller's already resolved identity of `task_id` under the
    primary checkout; it only saves the resolution.
    """
    project_root = _verified_lifecycle_project(supplied_project)
    root = _effective_worktree_root(worktree_root)
    identity = identity or resolve_task_identity(project_root, task_id, "existing")
    expected = _task_worktree_path_for_identity(project_root, root, identity)
    state_path, lease_path, integration_path = _lifecycle_paths(project_root, identity)
    records = _git_worktrees(project_root)
    registered = next((item for item in records if Path(item["worktree"]).resolve() == expected), None)
    branch_commit = _branch_commit(project_root, identity.branch_name)
    project = str(project_root)

    def report(step: str, stop_reason: str | None, resume: str | None) -> tuple[dict[str, object], bool]:
        if stop_reason is not None:
            stop_resume(stop_reason, task_id=identity.canonical_id, project=project, evidence="")
        return ({
            "version": 1,
            "task_id": identity.canonical_id,
            "step": step,
            "stop_reason": stop_reason,
            "resume": resume,
        }, stop_reason is None)

    if not state_path.is_file() or registered is None or branch_commit is None:
        if identity.handoff_path.is_file() and registered is None and branch_commit is None:
            return report("C10", None, None)
        return report(
            "C4",
            "WRONG_WORKTREE",
            stop_resume("WRONG_WORKTREE", task_id=identity.canonical_id, project=project),
        )

    if lease_path.exists() and not integration_path.exists():
        lease_code = lease_stop_code(project_root, identity, lease_path)
        return report(
            "C6",
            lease_code,
            stop_resume(lease_code, task_id=identity.canonical_id, project=project),
        )
    if integration_path.exists():
        return report("C7", None, "run the selected candidate validation")

    state = _read_json_object(state_path, "worktree lifecycle state")
    inspection, _ready = inspect_task_worktree(task_id, root, project_root, require_effective_worktree=False,
                                               identity=identity)
    if inspection.get("stop_reason") == "STALE_WORKTREE_BASE":
        return report("C4", "STALE_WORKTREE_BASE", str(inspection["resume"]))
    if state.get("base_commit") == branch_commit:
        return report("C1", "ACCEPTANCE_UNMET", stop_resume("ACCEPTANCE_UNMET"))

    if _run_git(project_root, "merge-base", "--is-ancestor", branch_commit, "main").returncode == 0:
        origin = _run_git(project_root, "remote", "get-url", "origin")
        remote_main = _run_git(project_root, "rev-parse", "--verify", "refs/remotes/origin/main")
        if origin.returncode != 0 or (
            remote_main.returncode == 0
            and _run_git(project_root, "merge-base", "--is-ancestor", "main", "refs/remotes/origin/main").returncode == 0
        ):
            return report(
                "C10",
                None,
                f"cardine worktree cleanup {identity.canonical_id} --project {project} --format json",
            )
        return report(
            "C9",
            "PUSH_PENDING" if remote_main.returncode == 0 and _run_git(
                project_root, "merge-base", "--is-ancestor", "refs/remotes/origin/main", "main"
            ).returncode == 0 else None,
            stop_resume("PUSH_PENDING"),
        )

    dirty_primary = git_output(project_root, "status", "--porcelain").splitlines()
    if dirty_primary:
        paths = [line[3:] for line in dirty_primary]
        listed = ", ".join(paths[:10])
        if len(paths) > 10:
            listed += f", … (+{len(paths) - 10} more)"
        detail = f"primary checkout is dirty ({len(paths)} path(s): {listed})"
        return report(
            "C6",
            "PRIMARY_DIRTY",
            f"{detail}; {stop_resume('PRIMARY_DIRTY')}",
        )
    evidence_path = state_path.with_suffix(".evidence.json")
    if evidence_path.is_file():
        try:
            evidence = _integration_evidence(evidence_path)
        except CardineError:
            evidence = None
        if (
            evidence is not None
            and evidence["accepted"] is True
            and evidence["validation_passed"] is True
            and evidence["validated_task_commit"] == branch_commit
            and evidence["validated_base_commit"] == state["base_commit"]
        ):
            return report(
                "C6",
                None,
                f"cardine worktree integrate stage {identity.canonical_id} --project {project} "
                f"--evidence {evidence_path} --format json",
            )
    return report("C5", "EVIDENCE_INCOMPLETE", stop_resume(
        "EVIDENCE_INCOMPLETE", task_id=identity.canonical_id, project=project))
