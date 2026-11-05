"""Measured candidate attempts, sharing task retry allowance and receipt writer.

The operation record detects uncovered edits within the same-user boundary; it
is neither a signature nor proof of authorship. Commands run outside task locks.
"""
from copy import deepcopy
import os
import time
import uuid
from pathlib import Path

from cardine.lifecycle import receipts
from cardine.lifecycle.control import operation_state, source_digest
from cardine.lifecycle.validation import execute_command, runner_lock
from cardine.shared.errors import CardineError
from cardine.shared.git import git_output, _run_git, scoped_command, invalidate_facts
from cardine.shared.jsonio import _read_json_object
from cardine.tasks.identity import resolve_task_identity
from cardine.tasks.validation import (environment_identity, failure_count, quick_failed, quick_failure_count,
                                      quick_failure_limit, quick_limit_error, quick_plan)
from cardine.stops.render import stop_error
from cardine.worktree.storage import _lifecycle_paths, _merge_head_path


def operation_path(locations, suffix='candidate'):
    return receipts.safe_path(locations.common_dir, f'cardine-operations/{locations.task_id}.{suffix}.json')


def locations_for(task_id, project):
    from cardine.lifecycle.context import resolve_run_locations
    return resolve_run_locations(task_id, project)


def staged_inputs(locations, state, pending=None, *, read_only=False):
    root, task_id = locations.primary, locations.task_id
    identity = resolve_task_identity(root, task_id, 'existing')
    _, lease_path, staged_path = _lifecycle_paths(root, identity)
    for path in (lease_path, staged_path):
        receipts.safe_path(path.parent, path.name)
    lease = _read_json_object(lease_path, 'integration lease')
    staged = _read_json_object(staged_path, 'staged integration')
    if (lease.get('task_id') != task_id or lease.get('project') != str(root)
            or lease.get('branch') != identity.branch_name
            or any(staged.get(k) != lease.get(k) for k in lease)
            or staged.get('task_commit') != git_output(locations.worktree, 'rev-parse', 'HEAD')):
        raise CardineError('foreign candidate ownership or changed task source')
    if (git_output(root, 'branch', '--show-current') != 'main'
            or git_output(root, 'rev-parse', 'HEAD') != staged['main_commit']
            or not _merge_head_path(root).is_file()
            or _merge_head_path(root).read_text().strip() != staged['task_commit']
            or (_run_git(root, 'diff', '--cached', '--quiet', staged['candidate_tree']).returncode
                if read_only else git_output(root, 'write-tree') != staged['candidate_tree'])
            or git_output(root, 'diff', '--binary')):
        raise stop_error('EVIDENCE_MISMATCH', 'candidate tree or main changed', task_id=task_id, project=root)
    # Candidate progress/counters may change, while lifecycle authority must
    # still match the committed task staged under this lease (including review
    # and cancellation). No later worker metadata can silently weaken it.
    import json
    from cardine.tasks.state import state_path
    name = state_path(locations.worktree, task_id).relative_to(locations.worktree).as_posix()
    committed = json.loads(git_output(locations.worktree, 'show', f'{staged["task_commit"]}:{name}'))
    if {k: v for k, v in state.items() if k != 'run'} != {k: v for k, v in committed.items() if k != 'run'}:
        raise stop_error('EVIDENCE_MISMATCH', 'task lifecycle authority changed after staging',
                         task_id=task_id, project=root)
    delivery = state.get('run', {}).get('delivery', {})
    validation = state.get('run', {}).get('validation', {})
    contract = receipts.digest(receipts.encoded(state['contract']))
    source = source_digest(locations.worktree, task_id, pending)
    if (source != delivery.get('sourceDigest') or delivery.get('contractDigest') != contract
            or validation.get('phase') != 'passed'
            or validation.get('inputs', {}).get('contractDigest') != contract):
        raise stop_error('EVIDENCE_MISMATCH', 'task source or contract changed after staging',
                         task_id=task_id, project=root)
    from cardine.shared.project import project_validation_commands
    commands = list(dict.fromkeys(['git diff --check', *project_validation_commands(state['contract'], staged['decision'])]))
    return dict(task_id=task_id, project=str(root), worker=str(locations.worktree),
        authority=receipts.require_authority(locations.worktree),
        primaryAuthority=receipts.require_authority(root),
        contract=contract,
        source=staged['task_commit'], sourceDigest=source,
        tree=staged['candidate_tree'], main=staged['main_commit'],
        lease=receipts.digest(lease_path.read_bytes()), staged=receipts.digest(staged_path.read_bytes()),
        commands=commands, environment=environment_identity(dict(os.environ)),
        worktreeStatus=git_output(root, 'status', '--porcelain', '--untracked-files=all'))


def require_budget(state, task_id, root):
    if failure_count(state) >= state['contract']['options']['validationRetryLimit']:
        raise stop_error('VALIDATION_RETRY_LIMIT', 'Task and candidate validation allowance exhausted',
                         task_id=task_id, project=root)
    if quick_failure_count(state) >= quick_failure_limit(state):
        progress = state['run'].get('candidateValidation') or {}
        runs = progress.get('runs', [])[:progress.get('quickRounds', 0)]
        raise quick_limit_error(task_id, root, quick_failure_limit(state),
                                list(dict.fromkeys(item['command'] for run in runs for item in run if item['exitStatus'] != 0)))


def verified_candidate(locations, *, read_only=False):
    state, pending = operation_state(locations.worktree, locations.task_id)
    if pending:
        return None
    progress = state.get('run', {}).get('candidateValidation')
    if not progress:
        return None
    return progress if progress['binding'] == staged_inputs(locations, state, read_only=read_only) else None


@scoped_command
def run_candidate_validation(task_id, project):
    locations = locations_for(task_id, project)
    root, worker, task_id = locations.primary, locations.worktree, locations.task_id
    with runner_lock(worker, task_id) as descriptor:
        path = operation_path(locations)
        intent = receipts._load_intent(path) if path.exists() else None
        state, pending = operation_state(worker, task_id)
        binding = staged_inputs(locations, state, pending)
        if intent and intent['binding'] != binding:
            if intent['phase'] != 'complete':
                raise CardineError('candidate inputs changed during interrupted operation')
            intent = None
        if pending:
            if (not intent or intent['phase'] != 'publish'
                    or pending['state']['run'].get('candidateValidation') != intent['progress']):
                raise CardineError('foreign pending candidate result')
            with receipts.task_lock(worker, task_id):
                state = receipts.replay_operation(worker, task_id, kind='candidate-validation')
        existing = state.get('run', {}).get('candidateValidation')
        if existing and existing['binding'] == binding:
            if intent and intent['phase'] == 'publish':
                receipts._save_intent(path, dict(intent, phase='complete'))
            require_budget(state, task_id, root)
            return existing
        require_budget(state, task_id, root)
        if intent is None:
            policy = state['contract']['validation']
            last = state['run'].get('candidateValidation', {}).get('lastFailed', [])
            plan = quick_plan(policy.get('retry', {}), policy.get('preflight', []),
                              [key for key, command in policy['commands'].items()
                               if command in last and command in binding['commands']],
                              policy['commands'])
            intent = dict(binding=binding, phase='process', attemptId=uuid.uuid4().hex,
                          before=receipts.state_digest(state), runs=[],
                          quick=[dict(kind=kind, commands=[list(item) for item in commands]) for kind, commands in plan])
            receipts.boundary('before_candidate_intent')
            receipts._save_intent(path, intent)
            receipts.boundary('after_candidate_intent')
        if receipts.state_digest(state) != intent['before']:
            raise CardineError('candidate state changed during validation')
        runs = intent['runs']
        policy = state['contract']['validation']
        retry = policy.get('retry', {})
        quick = intent.get('quick', [])
        kinds, rounds = [item['kind'] for item in quick], len(quick)
        variants = []
        while intent['phase'] == 'process':
            if quick_failed(kinds, runs):
                break  # A quick failure ends the attempt before the complete set.
            rest = runs[rounds:]
            if len(runs) < rounds:
                round_commands = [command for _, command in quick[len(runs)]['commands']]
            elif not rest:
                round_commands = binding['commands']
            elif all(item['exitStatus'] == 0 for item in rest[0]):
                break
            else:
                failed = {item['command'] for item in rest[0] if item['exitStatus'] != 0}
                variants = [retry[key] for key, command in policy['commands'].items()
                            if command in failed and key in retry]
                if variants and len(rest) == 1:
                    round_commands = variants
                elif variants and len(rest) == 2 and any(item['exitStatus'] == 1 for item in rest[1]):
                    break
                elif len(rest) == (2 if variants else 1):
                    round_commands = binding['commands']
                else:
                    break
            results = []
            for command in round_commands:
                status, out, err, out_cut, err_cut = execute_command(command, root, dict(os.environ), descriptor)
                results.append(dict(command=command, exitStatus=status, stdout=out, stderr=err,
                                    stdoutTruncated=out_cut, stderrTruncated=err_cut))
            current, current_pending = operation_state(worker, task_id)
            if (current_pending or staged_inputs(locations, current) != binding
                    or receipts.state_digest(current) != intent['before']):
                raise CardineError('candidate inputs changed while commands ran')
            runs = [*runs, results]
            receipts.boundary('before_candidate_logs')
            intent = dict(intent, runs=runs)
            receipts._save_intent(path, intent)
            receipts.boundary('after_candidate_logs')
        if intent['phase'] == 'process':
            rest = runs[rounds:]
            previous = state['run'].get('candidateValidation', {})
            if quick_failed(kinds, runs):
                passed, failures, quick_new = False, failure_count(state), quick_failure_count(state) + 1
                intermittent, last_failed = [], list(previous.get('lastFailed', []))
            else:
                complete_last = len(rest) == 1 or not variants or len(rest) == 3
                passed = complete_last and all(r['exitStatus'] == 0 for r in rest[-1])
                failures = 0 if passed else failure_count(state) + 1
                quick_new = 0 if passed else quick_failure_count(state)
                intermittent = [r for r in rest[0] if r['exitStatus'] != 0] if passed and len(rest) > 1 else []
                last_failed = [] if passed else [r['command'] for r in (rest[-1] if complete_last else rest[0])
                                                 if r['exitStatus'] != 0]
            progress = dict(attemptId=intent['attemptId'], binding=binding, runs=runs,
                phase='passed' if passed else 'failed', consecutiveFailures=failures,
                quickFailures=quick_new, quickRounds=min(rounds, len(runs)), lastFailed=last_failed,
                intermittent=intermittent)
            intent = dict(intent, phase='publish', progress=progress)
            receipts._save_intent(path, intent)
        progress = intent['progress']
        with receipts.task_lock(worker, task_id):
            current, pending = operation_state(worker, task_id)
            if (pending or staged_inputs(locations, current) != binding
                    or receipts.state_digest(current) != intent['before']):
                raise CardineError('candidate inputs changed before result write')
            updated = deepcopy(current)
            updated['run']['candidateValidation'] = progress
            # Both phases consume one allowance; a passing complete set resets it.
            if 'validation' in updated['run']:
                updated['run']['validation']['consecutiveFailures'] = progress['consecutiveFailures']
                updated['run']['validation']['quickFailures'] = progress['quickFailures']
            receipts.boundary('before_candidate_result')
            receipts.write_operation(worker, task_id, updated, previous=current, kind='candidate-validation')
            receipts.boundary('after_candidate_result')
        receipts._save_intent(path, dict(intent, phase='complete'))
        require_budget(updated, task_id, root)
        return progress


def wait_for_lease(locations, *, seconds=60, poll=5, sleep=time.sleep, clock=time.monotonic):
    """Wait only for a coherent competing task lease; never abort foreign work."""
    seconds, poll = min(60, max(0, seconds)), max(5, poll)
    identity = resolve_task_identity(locations.primary, locations.task_id, 'existing')
    _, lease_path, _ = _lifecycle_paths(locations.primary, identity)
    deadline = clock() + seconds
    while lease_path.exists():
        receipts.safe_path(lease_path.parent, lease_path.name)
        lease = _read_json_object(lease_path, 'integration lease')
        if lease.get('task_id') == locations.task_id:
            return True
        owner = lease.get('task_id')
        if (not isinstance(owner, str) or lease.get('project') != str(locations.primary)
                or lease.get('branch') != 'task-' + owner.lower()):
            raise stop_error('LEASE_HELD', 'unverified competing lease', task_id=locations.task_id, project=locations.primary)
        remaining = deadline - clock()
        if remaining < poll:
            return False
        sleep(poll)
        invalidate_facts()  # Release must recompute main, paths and the decision.
    return True
