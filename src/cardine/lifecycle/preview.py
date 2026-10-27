"""Read-only composition of the engine's receipt-verifying observations.

No recovery, lock creation, host polling or lifecycle effect belongs here.
Receipt integrity is relative to accepted policy, never proof of authorship.
"""
from dataclasses import replace

from cardine.lifecycle import receipts
from cardine.lifecycle.engine import resolve_run, diagnostic_result
from cardine.lifecycle.model import RunFacts, WorkRequest
from cardine.shared.errors import CardineError, CardineStop
from cardine.shared.git import scoped_command
from cardine.stops.render import stop_error
from cardine.tasks.state import read_task_state, state_path


@scoped_command
def preview_run(locations):
    """Return the same closed next-step envelope without executing that step."""
    try:
        return resolve_run(observe_run(locations))
    except CardineStop as error:
        return diagnostic_result(locations, error)
    except (CardineError, OSError, ValueError, KeyError) as error:
        return diagnostic_result(locations, stop_error('COMMAND_REFUSED', str(error)))


def observe_run(locations):
    root, task = locations.worktree, locations.task_id
    from cardine.integration.candidate import operation_path
    cleanup = operation_path(locations, 'cleanup')
    if cleanup.exists():
        intent = receipts._load_intent(cleanup)
        from cardine.integration.cleanup import _landed
        _landed(locations, intent)
        complete = intent.get('effects', {}).get('cleanup_lifecycle') == 'done'
        if complete:
            from cardine.shared.git import _git_worktrees, _run_git
            complete = (not any(item.get('worktree') == str(root) for item in _git_worktrees(locations.primary))
                and _run_git(locations.primary, 'rev-parse', '--verify', '--quiet',
                             'refs/heads/' + intent['binding']['branch']).returncode == 1)
        return RunFacts(task, locations.primary, 'done', cleanup_pending=not complete,
                        landing_complete=complete)
    final = operation_path(locations, 'finalize')
    if final.exists():
        from cardine.integration.finalize import finalization_aborted
        intent = receipts._load_intent(final)
        if not finalization_aborted(locations, intent):
            from cardine.shared.git import git_output, _run_git
            from cardine.lifecycle.control import source_digest
            binding = intent['binding']
            if (intent['task_id'] != task or binding['project'] != str(locations.primary)
                    or binding['worker'] != str(root)
                    or binding['authority'] != receipts.require_authority(root, context=locations)
                    or binding['primaryAuthority'] != receipts.require_authority(locations.primary)
                    or binding['source'] != git_output(root, 'rev-parse', 'HEAD')
                    or binding['sourceDigest'] != source_digest(root, task)):
                raise CardineError('foreign finalize operation or changed source')
            head = git_output(locations.primary, 'rev-parse', 'HEAD')
            landed = intent['result']['merge_commit'] if intent['result'] else head
            if head != binding['main']:
                if (git_output(locations.primary, 'show', '-s', '--format=%T', landed) != binding['tree']
                        or git_output(locations.primary, 'show', '-s', '--format=%P', landed).split()
                        != [binding['main'], binding['source']]
                        or _run_git(locations.primary, 'merge-base', '--is-ancestor', landed, head).returncode):
                    raise CardineError('main does not prove the intended landing')
            else:
                from cardine.integration.candidate import verified_candidate
                if intent['result'] or not verified_candidate(locations, read_only=True):
                    raise CardineError('finalize has no matching candidate')
            return RunFacts(task, locations.primary, 'in_progress', pending_step='landing')
    if not state_path(root, task).is_file():
        root = locations.primary
    if receipts.pending_operation(root, task):
        if receipts.operation_live(root, task):
            raise CardineError('live foreign operation; wait for the current writer')
        intent = receipts._load_intent(receipts._intent_path(root, task))
        if intent['task_id'] != task or intent['authority'] != receipts.require_authority(root, context=locations):
            raise CardineError('foreign pending preview operation')
        state = intent['state']
        receipts.verify_receipts(root, state, artifacts=False, context=locations)
        kind = state['run']['receipts'][-1]['kind']
        if kind.startswith('host-launch:'):
            record = state['run']['hostLaunches'][kind.removeprefix('host-launch:')]
            request = record['request']
            from cardine.lifecycle.control import source_digest
            from cardine.shared.git import git_output
            if (request['root'] != str(root) or request['task_id'] != task
                    or request['source'] != git_output(root, 'rev-parse', 'HEAD')
                    or request['source_digest'] != source_digest(root, task, intent)):
                raise CardineError('host preview has foreign owner or changed inputs')
            work = request['work']
            request = WorkRequest(work['role'], root, work['contract_digest'],
                tuple(work['expected_surface']), tuple(work['acceptance_references']),
                tuple(work['validation_references']), tuple(work['delivery_receipt_requirements']))
            return RunFacts(task, locations.primary, state['status'],
                pending_step='implementation' if request.role == 'implementer' else 'review',
                implementation_work=request if request.role == 'implementer' else None,
                review_work=request if request.role == 'reviewer' else None)
        step = {'implementation-delivery': 'implementation', 'task-validation': 'validation',
                'candidate-validation': 'candidate', 'ci-push': 'candidate', 'ci-result': 'candidate'}.get(kind)
        if kind.startswith('review-submit:'):
            step = 'review'
        if step:
            from cardine.shared.git import git_output
            if state['run']['receipts'][-1]['source'] != git_output(root, 'rev-parse', 'HEAD'):
                raise CardineError('pending preview source changed')
            for relative, item in intent['files'].items():
                path = receipts.safe_path(root, relative)
                current = receipts.digest(path.read_bytes()) if path.exists() else None
                allowed = {item['before'], item['digest']}
                if path == state_path(root, task):
                    allowed.add(receipts.digest(receipts.encoded(intent['pending_state'])))
                if current not in allowed:
                    raise CardineError('foreign pending preview output: ' + relative)
            return RunFacts(task, locations.primary, state['status'], pending_step=step)
        # Unknown effects are never replayed or promoted by a read-only preview.
        raise CardineError('pending operation requires its Stable recovery command: ' + kind)
    state = read_task_state(root, task, 'single', stop_factory=stop_error,
                            require_contract=True, context=locations)
    contract = state['contract']
    facts = RunFacts(task, locations.primary, state['status'])
    if facts.status == 'cancelled':
        return facts
    if facts.status == 'done':
        return replace(facts, cleanup_pending=True)
    from cardine.tasks.preflight import check_dependencies
    check_dependencies(root, task, '')
    from cardine.lifecycle.control import require_review_budget
    require_review_budget(root, task, state)
    if root == locations.primary:
        return facts
    from cardine.lifecycle.execution import _execution_location
    inspection = _execution_location(root, task, context=locations)
    if set(inspection['errors']) - {'dirty-worktree'}:
        raise CardineError('preview requires the verified canonical worktree: '
                           + ', '.join(inspection['errors']))
    request = WorkRequest('implementer', root, receipts.digest(receipts.encoded(contract)),
        tuple(contract['expectedCodeSurface']), tuple(contract['deliverables']),
        tuple(contract['validation']['baseline']), ('committed implementation delivery',))
    facts = replace(facts, contract_ready=True, worktree_ready=True,
                    review_required=contract['options']['review'] == 'required',
                    implementation_work=request,
                    review_work=replace(request, role='reviewer',
                        delivery_receipt_requirements=('independent source-bound review',)))
    failed = state.get('run', {}).get('candidateValidation')
    if failed and failed['phase'] == 'failed':
        from cardine.integration.candidate import require_budget
        from cardine.lifecycle.control import source_digest
        require_budget(state, task, locations.primary)
        if source_digest(root, task) == failed['binding']['sourceDigest']:
            return replace(facts, validation_failed=True)
    from cardine.lifecycle.delivery import verify_delivery
    delivered = verify_delivery(root, state, str(inspection['base_commit']), context=locations)
    if delivered is None:
        return facts
    from cardine.tasks.validation import verified_validation, host_observations_complete
    progress = verified_validation(root, task, state)
    passed = bool(progress and progress['phase'] == 'passed'
                  and host_observations_complete(contract, progress))
    facts = replace(facts, implementation_delivered=True, validation_passed=passed,
                    validation_failed=bool(progress and not passed))
    if not passed:
        return facts
    from cardine.review.progress import review_progress
    approved, pending = review_progress(root, task, state)
    facts = replace(facts, review_approved=approved, review_pending=pending,
        review_changes_requested=state.get('review', {}).get('verdict') == 'CHANGES_REQUESTED')
    if facts.review_required and not approved:
        return facts
    from cardine.integration.ci import ci_policy, ci_binding
    policy = ci_policy(contract)
    if policy:
        cached = state['run'].get('ci')
        if not cached or cached['phase'] != 'passed' or cached['binding'] != ci_binding(locations, state, policy):
            return replace(facts, ci_pending=True)
    from cardine.integration.candidate import verified_candidate
    candidate = verified_candidate(locations, read_only=True)
    return replace(facts, candidate_validated=bool(candidate and candidate['phase'] == 'passed'))
