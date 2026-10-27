"""Pure cause classification for worktree, state, lease and cleanup stops.

Each classifier only reads. It returns the registered code of the cause it can
prove, and the caller's original guardrail code for anything ambiguous, corrupt,
foreign or denied. A proof here is a fact measured on this checkout (an intact
lease naming this task and project, an idle writer guard, a writable Git
directory); it is not authorship proof and never grants authority.
"""

from __future__ import annotations

import os
from pathlib import Path

from cardine.shared.errors import CardineError
from cardine.shared.git import _run_git
from cardine.shared.git import git_output
from cardine.shared.jsonio import _read_json_object
from cardine.shared.models import ResolvedTaskIdentity
from cardine.worktree.storage import _merge_head_path


def lease_stop_code(project_root: Path, identity: ResolvedTaskIdentity, lease_path: Path) -> str:
    """`LEASE_INTERRUPTED` for this task's own idle lease, else `LEASE_HELD`.

    A lease held by another task, an unreadable or mismatched lease, a live
    writer, or a staged merge that no longer matches the lease stays a
    guardrail: existence alone proves neither liveness nor permission to abort.
    """
    from cardine.lifecycle.receipts import operation_live
    try:
        lease = _read_json_object(lease_path, "integration lease")
    except CardineError:
        return "LEASE_HELD"
    if (
        lease.get("task_id") != identity.canonical_id
        or lease.get("branch") != identity.branch_name
        or lease.get("project") != str(project_root)
        or operation_live(project_root, identity.canonical_id)
    ):
        return "LEASE_HELD"
    if _merge_head_path(project_root).exists() and (
        git_output(project_root, "rev-parse", "HEAD") != lease.get("main_commit")
        or git_output(project_root, "rev-parse", "MERGE_HEAD") != git_output(
            project_root, "rev-parse", f"refs/heads/{identity.branch_name}")
    ):
        return "LEASE_HELD"
    return "LEASE_INTERRUPTED"


def cleanup_branch_stop_code(
    project_root: Path, branch: str, task_commit: str | None, common_dir: Path,
) -> str:
    """`CLEANUP_PARTIAL` when the worktree is gone and only a merged branch remains.

    The worktree removal already happened, so rerunning the identical cleanup is
    the next effect, not a repeat. An unmerged or reused branch, a primary
    checkout off main, or an unwritable Git directory stays `CLEANUP_BLOCKED`.
    """
    if task_commit is None or not os.access(common_dir, os.W_OK | os.X_OK):
        return "CLEANUP_BLOCKED"
    if git_output(project_root, "branch", "--show-current") != "main":
        return "CLEANUP_BLOCKED"
    if _run_git(project_root, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}").stdout.strip() != task_commit:
        return "CLEANUP_BLOCKED"
    if _run_git(project_root, "merge-base", "--is-ancestor", task_commit, "main").returncode != 0:
        return "CLEANUP_BLOCKED"
    return "CLEANUP_PARTIAL"


def main_ahead_of_origin(project_root: Path) -> bool:
    """True only when origin/main is a proper ancestor of local main (a push is pending)."""
    remote = _run_git(project_root, "rev-parse", "--verify", "--quiet", "refs/remotes/origin/main")
    if remote.returncode != 0:
        return False
    main = git_output(project_root, "rev-parse", "main")
    return remote.stdout.strip() != main and _run_git(
        project_root, "merge-base", "--is-ancestor", "refs/remotes/origin/main", "main",
    ).returncode == 0


# Executable inventory of every emitter of the worktree, state, lease, order and
# cleanup stop families: (file, function, code) -> (disposition, reason). A test
# scans the source with the same rules and fails on any emitter missing here.
# `split` means the emitter classifies a recoverable cause, `guardrail` keeps the
# real authority negative, `passthrough` forwards a code chosen elsewhere, and
# `deferred` names the later row that owns the audit.
EMITTER_CAUSES: dict[tuple[str, str, str], tuple[str, str]] = {
    ("src/cardine/integration/cleanup.py", "_inactive", "<dynamic>"): ("passthrough", "idle owned lease is recoverable before acquiring the writer guard; foreign or active integration is retained"),
    ("src/cardine/integration/cleanup.py", "_inactive", "CLEANUP_BLOCKED"): ("guardrail", "idle owned lease is recoverable before acquiring the writer guard; foreign or active integration is retained"),
    ("src/cardine/integration/cleanup.py", "_inactive", "LEASE_INTERRUPTED"): ("split", "idle owned lease is recoverable before acquiring the writer guard; foreign or active integration is retained"),
    ("src/cardine/integration/cleanup.py", "_fail", "<dynamic>"): ("passthrough", "receipt-bound cleanup classifier; exact remote ancestry and owned partial effects retain foreign work"),
    ("src/cardine/integration/cleanup.py", "_fail", "CLEANUP_BLOCKED"): ("guardrail", "receipt-bound cleanup classifier; exact remote ancestry and owned partial effects retain foreign work"),
    ("src/cardine/integration/cleanup.py", "_fail", "PUSH_PENDING"): ("split", "receipt-bound cleanup classifier; exact remote ancestry and owned partial effects retain foreign work"),
    ("src/cardine/integration/cleanup.py", "_remote", "CLEANUP_BLOCKED"): ("guardrail", "receipt-bound cleanup classifier; exact remote ancestry and owned partial effects retain foreign work"),
    ("src/cardine/integration/cleanup.py", "_remote", "PUSH_PENDING"): ("split", "receipt-bound cleanup classifier; exact remote ancestry and owned partial effects retain foreign work"),
    ("src/cardine/integration/ci.py", "remote_tip", "<dynamic>"): ("passthrough", "an unreadable origin is recoverable unless the remote refused authentication or access"),
    ("src/cardine/integration/candidate.py", "wait_for_lease", "LEASE_HELD"): ("guardrail", "malformed or unverified competing lease is preserved"),
    ("src/cardine/lifecycle/control.py", "authorize", "COMMAND_REFUSED"): ("guardrail", "missing enforced host channel cannot authorize a review, cancellation or owned abort"),
    ("src/cardine/review/verdict.py", "_clean_review_outputs", "TASK_STATE_INVALID"): ("guardrail", "unreceipted or foreign work is preserved before recording or replaying a verdict"),
    ("src/cardine/hosts/launch.py", "ProfileAdapter.profiles", "COMMAND_REFUSED"): ("guardrail", "missing, shared or unenforced host role profiles require separately authorized host configuration; never fall back"),
    ("src/cardine/tasks/recording.py", "record_validation", "WRONG_WORKTREE"): ("guardrail", "a task branch cannot record another task's evidence"),
    ("src/cardine/lifecycle/engine.py", "diagnostic_result", "COMMAND_REFUSED"): ("guardrail", "unregistered or untyped diagnostic cannot authorize repair"),
    ("src/cardine/lifecycle/engine.py", "dispatch_run", "COMMAND_REFUSED"): ("guardrail", "unknown resolved-task failure has no safe ownership or recovery proof"),
    ("src/cardine/lifecycle/preview.py", "preview_run", "COMMAND_REFUSED"): ("guardrail", "read-only preview refuses uncovered state or foreign operation inputs without executing recovery"),
    ("src/cardine/tasks/preflight.py", "check_dependencies", "DEPENDENCY_PENDING"): ("split", "read-only resolution of valid task order or pending landed dependency"),
    ("src/cardine/tasks/preflight.py", "execution_preflight", "TASK_STEP_PENDING"): ("split", "read-only resolution of valid task order or pending landed dependency"),
    ("src/cardine/tasks/preflight.py", "reconcile_execution_contract", "TASK_STEP_PENDING"): ("split", "read-only resolution of valid task order or pending landed dependency"),
    ("src/cardine/tasks/preflight.py", "check_dependencies", "<dynamic>"): ("passthrough", "valid task order and pending dependencies are nonhuman; cancelled or failed results retain guardrails"),
    ("src/cardine/tasks/preflight.py", "execution_preflight", "<dynamic>"): ("passthrough", "valid task order and pending dependencies are nonhuman; cancelled or failed results retain guardrails"),
    ("src/cardine/cli.py", "_run_cli", "<dynamic>"): ("passthrough", "the code is chosen by an upstream classifier or a registered error carried through"),
    ("src/cardine/cli.py", "_run_cli", "COMMAND_REFUSED"): ("guardrail", "unknown input/state or damaged host markers; non-run OS classification is audited in stops/nonrun.py"),
    ("src/cardine/cli.py", "_run_cli", "OS_ACCESS_FAILED"): ("split", "explicit read-only missing/busy errno; denied or uncertain effect residue remains a guardrail"),
    ("src/cardine/cli.py", "_run_cli", "WRONG_WORKTREE"): ("guardrail", "missing, mismatched, dirty-foreign or unproven task location"),
    ("src/cardine/console/snapshot.py", "_read_console_state", "TASK_STATE_INVALID"): ("guardrail", "corrupt, foreign or forbidden state is never rewritten from prose"),
    ("src/cardine/hosts/codex.py", "plan_codex_user_rules", "COMMAND_REFUSED"): ("guardrail", "unknown input/state or damaged host markers; non-run OS classification is audited in stops/nonrun.py"),
    ("src/cardine/integration/evidence.py", "candidate_validation_declaration", "TASK_STATE_INVALID"): ("guardrail", "corrupt, foreign or forbidden state is never rewritten from prose"),
    ("src/cardine/integration/merge.py", "_integration_task_state", "<dynamic>"): ("passthrough", "the code is chosen by an upstream classifier or a registered error carried through"),
    ("src/cardine/integration/merge.py", "_integration_task_state", "TASK_STATE_INVALID"): ("guardrail", "corrupt, foreign or forbidden state is never rewritten from prose"),
    ("src/cardine/integration/merge.py", "stage_task_integration", "<dynamic>"): ("passthrough", "the code is chosen by an upstream classifier or a registered error carried through"),
    ("src/cardine/integration/merge.py", "stage_task_integration", "LEASE_HELD"): ("guardrail", "exclusive-create race or foreign or live lease"),
    ("src/cardine/integration/merge.py", "stage_task_integration", "PRIMARY_DIRTY"): ("guardrail", "foreign dirt only; the exact owned landing residue (intent and stage files) is cleared under an operation record before this check"),
    ("src/cardine/legacy/snapshot.py", "_read_console_state", "TASK_STATE_INVALID"): ("guardrail", "corrupt, foreign or forbidden state is never rewritten from prose"),
    ("src/cardine/lifecycle/closure.py", "advance_task_closure", "<dynamic>"): ("passthrough", "the code is chosen by an upstream classifier or a registered error carried through"),
    ("src/cardine/lifecycle/closure.py", "advance_task_closure", "PUSH_PENDING"): ("split", "origin/main is a proper ancestor of local main"),
    ("src/cardine/lifecycle/closure.py", "advance_task_closure.result", "<dynamic>"): ("passthrough", "the code is chosen by an upstream classifier or a registered error carried through"),
    ("src/cardine/lifecycle/commands.py", "execution_start", "TASK_STATUS_REJECTED"): ("guardrail", "wrong order or forbidden transition needs a developer decision"),
    ("src/cardine/lifecycle/commands.py", "execution_start", "WRONG_WORKTREE"): ("guardrail", "missing, mismatched, dirty-foreign or unproven task location"),
    ("src/cardine/lifecycle/execution.py", "_execution_location", "<dynamic>"): ("passthrough", "the code is chosen by an upstream classifier or a registered error carried through"),
    ("src/cardine/lifecycle/execution.py", "_execution_location", "WORKTREE_RELOCATE"): ("split", "project names another checkout than the registered task worktree"),
    ("src/cardine/lifecycle/execution.py", "_execution_location", "WRONG_WORKTREE"): ("guardrail", "missing, mismatched, dirty-foreign or unproven task location"),
    ("src/cardine/lifecycle/execution.py", "_execution_worktree", "WRONG_WORKTREE"): ("guardrail", "missing, mismatched, dirty-foreign or unproven task location"),
    ("src/cardine/lifecycle/execution.py", "delivery_readiness", "TASK_STATUS_REJECTED"): ("guardrail", "wrong order or forbidden transition needs a developer decision"),
    ("src/cardine/lifecycle/execution.py", "delivery_readiness", "WRONG_WORKTREE"): ("guardrail", "missing, mismatched, dirty-foreign or unproven task location"),
    ("src/cardine/release/update.py", "run_self_update", "<dynamic>"): ("passthrough", "non-run errno classifier before the receipt writer; no plugin bypass or host setup"),
    ("src/cardine/release/update.py", "_run_self_update", "OS_ACCESS_FAILED"): ("split", "missing/busy errno is nonhuman only for --check; denied or apply residue stays guarded"),
    ("src/cardine/release/update.py", "_run_self_update", "<dynamic>"): ("passthrough", "non-run errno classifier; pending apply retries retain the receipt-pinned target"),
    ("src/cardine/release/update.py", "_run_self_update.refuse", "<dynamic>"): ("passthrough", "the code is chosen by an upstream classifier or a registered error carried through"),
    ("src/cardine/review/verdict.py", "record_review_verdict", "TASK_STATE_INVALID"): ("guardrail", "corrupt, foreign or forbidden state is never rewritten from prose"),
    ("src/cardine/tasks/importer.py", "import_task_states.invalid", "TASK_STATE_INVALID"): ("guardrail", "corrupt, foreign or forbidden state is never rewritten from prose"),
    ("src/cardine/tasks/preflight.py", "check_dependencies", "TASK_STATUS_REJECTED"): ("guardrail", "cancelled task or failed/cancelled landed dependency retains authority"),
    ("src/cardine/tasks/preflight.py", "execution_preflight", "TASK_STATUS_REJECTED"): ("guardrail", "cancelled task or failed/cancelled landed dependency retains authority"),
    ("src/cardine/tasks/state.py", "read_task_state", "TASK_STATE_INTERRUPTED"): ("split", "intact plain transition intent and no live writer"),
    ("src/cardine/tasks/state.py", "read_task_state", "TASK_STATE_INVALID"): ("guardrail", "corrupt, foreign or forbidden state is never rewritten from prose"),
    ("src/cardine/tasks/transitions.py", "close_task", "TASK_STATUS_REJECTED"): ("guardrail", "wrong order or forbidden transition needs a developer decision"),
    ("src/cardine/tasks/transitions.py", "record_spike_outcome", "TASK_STATUS_REJECTED"): ("guardrail", "wrong order or forbidden transition needs a developer decision"),
    ("src/cardine/tasks/transitions.py", "transition_task_state", "TASK_STATE_INVALID"): ("guardrail", "corrupt, foreign or forbidden state is never rewritten from prose"),
    ("src/cardine/worktree/checkout.py", "_prepare_task_worktree", "WRONG_WORKTREE"): ("guardrail", "missing, mismatched, dirty-foreign or unproven task location"),
    ("src/cardine/worktree/checkout.py", "prepare_task_worktree", "WRONG_WORKTREE"): ("guardrail", "missing, mismatched, dirty-foreign or unproven task location"),
    ("src/cardine/worktree/checkout.py", "repair_task_worktree_base", "WRONG_WORKTREE"): ("guardrail", "missing, mismatched, dirty-foreign or unproven task location"),
    ("src/cardine/worktree/closure_status.py", "closure_status", "<dynamic>"): ("passthrough", "the code is chosen by an upstream classifier or a registered error carried through"),
    ("src/cardine/worktree/closure_status.py", "closure_status", "PRIMARY_DIRTY"): ("guardrail", "foreign dirt only; the exact owned landing residue (intent and stage files) is cleared under an operation record before this check"),
    ("src/cardine/worktree/closure_status.py", "closure_status", "PUSH_PENDING"): ("split", "origin/main is a proper ancestor of local main"),
    ("src/cardine/worktree/closure_status.py", "closure_status", "WRONG_WORKTREE"): ("guardrail", "missing, mismatched, dirty-foreign or unproven task location"),
    ("src/cardine/worktree/closure_status.py", "closure_status.report", "<dynamic>"): ("passthrough", "the code is chosen by an upstream classifier or a registered error carried through"),
}
