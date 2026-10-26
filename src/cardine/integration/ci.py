"""Exact-repository CI before direct landing (``ciBeforeLanding``).

When the frozen contract enables it, the engine pushes the validated task head
once with a plain non-force push, then reads the check runs the provider
reports for that exact repository and SHA. Nothing a caller or an editable file
declares is evidence: the remote ref comes from ``ls-remote`` (never a local
tracking ref), and only a terminal pass is cached, as a receipt-covered ``run.ci``
result bound to repository, ref, head, review attempt, contract and checks.

Receipts detect uncovered edits within the same-user boundary; they are neither
signatures nor proof of authorship. When the contract does not enable CI, this
module runs no ``gh`` and no Git command.
"""
from __future__ import annotations

from copy import deepcopy
import json
import os
import re
import shutil
import subprocess

from cardine.integration.candidate import operation_path
from cardine.lifecycle import receipts
from cardine.lifecycle.control import operation_state
from cardine.shared.errors import CardineError
from cardine.shared.git import _run_git, scoped_command
from cardine.stops.render import stop_error
from cardine.tasks.identity import resolve_task_identity

QUERY_SECONDS = 30
PUSH_SECONDS = 120
PAGE_LIMIT = 10

_REMOTE = re.compile(
    r'^(?:(?:https?|ssh|git)://(?:[^@/]+@)?(?P<h1>[^/:@]+)(?::\d+)?/|(?:[^@/]+@)?(?P<h2>[^/:@]+):)'
    r'(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$')
_REFUSALS = re.compile(r'HTTP 40[134]|authentication|permission denied|could not read username|not found|'
                       r'protected branch|denied|auth login', re.IGNORECASE)


def ci_policy(contract):
    """The frozen CI requirement, or None when the contract does not enable it."""
    if not contract['options']['ciBeforeLanding']:
        return None
    ci = contract['ci']
    if ci == 'none' or ci['provider'] != 'github' or not ci['requiredChecks']:
        raise CardineError('ciBeforeLanding requires supported provider github and nonempty requiredChecks')
    return dict(provider=ci['provider'], checks=sorted(set(ci['requiredChecks'])))


def _git_environment():
    return {**os.environ, 'GIT_TERMINAL_PROMPT': '0'}


def _refused(text):
    return _REFUSALS.search(text) is not None


def remote_repository(worker):
    """Host, owner and name of the configured origin; gh never infers it from the cwd."""
    done = _run_git(worker, 'config', '--get', 'remote.origin.url')
    match = _REMOTE.match(done.stdout.strip()) if done.returncode == 0 else None
    if not match:
        raise CardineError('ciBeforeLanding requires a GitHub origin remote named origin')
    return match.group('h1') or match.group('h2'), match.group('owner'), match.group('repo')


def remote_tip(worker, ref, locations):
    """The tip the remote itself reports for ``ref``; a failed read is never an absent ref."""
    try:
        done = _run_git(worker, 'ls-remote', 'origin', ref, env=_git_environment(), timeout=PUSH_SECONDS)
    except subprocess.TimeoutExpired:
        done = None
    if done is None or done.returncode:
        detail = 'cannot read origin ' + ref + (': ' + done.stderr.strip() if done else ': timed out')
        raise stop_error('PUSH_REJECTED' if done and _refused(done.stderr) else 'GIT_OPERATION_FAILED',
                         detail, task_id=locations.task_id, project=locations.primary)
    for line in done.stdout.splitlines():
        sha, _, name = line.partition('\t')
        if name == ref:
            return sha
    return None


def _push(worker, locations, sha, ref):
    """Push the exact validated commit; a lost response is reconciled by reading the remote."""
    try:
        done = _run_git(worker, 'push', 'origin', f'{sha}:{ref}', env=_git_environment(), timeout=PUSH_SECONDS)
    except subprocess.TimeoutExpired:
        done = None
    tip = remote_tip(worker, ref, locations)
    if tip == sha:
        return
    advanced = tip is not None and _run_git(worker, 'merge-base', '--is-ancestor', tip, sha).returncode != 0
    if done is None:
        raise stop_error('GIT_OPERATION_FAILED', 'task push timed out and origin does not hold the head',
                         task_id=locations.task_id, project=locations.primary)
    raise stop_error('PUSH_REJECTED', ('origin advanced the task branch' if advanced else 'origin refused the task push')
                     + ': ' + done.stderr.strip(), task_id=locations.task_id, project=locations.primary)


def ci_binding(locations, state, policy):
    worker, task_id = locations.worktree, locations.task_id
    identity = resolve_task_identity(locations.primary, task_id, 'existing')
    delivery = state['run'].get('delivery')
    if not delivery:
        raise CardineError('CI requires a delivered head')
    if _run_git(worker, 'merge-base', '--is-ancestor', delivery['source'], 'HEAD').returncode:
        raise CardineError('delivered head is not part of the task branch')
    host, owner, name = remote_repository(worker)
    return dict(task_id=task_id, repository=f'{host}/{owner}/{name}', ref=f'refs/heads/{identity.branch_name}',
                head=delivery['source'], attempt=state.get('review', {}).get('attempt', 1),
                contract=receipts.digest(receipts.encoded(state['contract'])),
                provider=policy['provider'], checks=policy['checks'])


def _require_gh():
    gh = shutil.which('gh')
    if gh is None:
        raise CardineError('ciBeforeLanding requires the gh command; install and authenticate gh')
    return gh


def _provider(binding, endpoint):
    """One bounded read-only provider call; None means the provider did not answer."""
    gh = _require_gh()
    host = binding['repository'].split('/')[0]
    try:
        done = subprocess.run([gh, 'api', '--hostname', host, '-H', 'Accept: application/vnd.github+json', endpoint],
                              capture_output=True, text=True, timeout=QUERY_SECONDS, check=False,
                              env={**os.environ, 'GH_PROMPT_DISABLED': '1'})
    except subprocess.TimeoutExpired:
        return None
    if done.returncode:
        if _refused(done.stderr + done.stdout):
            raise CardineError('CI provider refused the query: ' + (done.stderr.strip() or done.stdout.strip()))
        return None
    try:
        value = json.loads(done.stdout)
    except ValueError as error:
        raise CardineError('CI provider returned invalid JSON') from error
    if not isinstance(value, dict):
        raise CardineError('CI provider returned an invalid response')
    return value


def query_checks(binding):
    """Required checks for the exact repository and SHA: passed, failed or waiting."""
    host, owner, name = binding['repository'].split('/', 2)
    runs, page = [], 1
    while True:
        data = _provider(binding, f'repos/{owner}/{name}/commits/{binding["head"]}/check-runs?per_page=100&page={page}')
        if data is None:
            return dict(phase='waiting', checks=[], detail='CI provider did not answer')
        listed, total = data.get('check_runs'), data.get('total_count')
        if not isinstance(listed, list) or not isinstance(total, int):
            raise CardineError('CI provider returned an invalid check-run list')
        runs += listed
        if len(runs) >= total or not listed or page >= PAGE_LIMIT:
            break
        page += 1
    latest = {}
    for run in runs:
        # A run on another SHA never counts, whatever the endpoint was asked for.
        if (isinstance(run, dict) and run.get('head_sha') == binding['head'] and run.get('name') in binding['checks']
                and isinstance(run.get('id'), int) and (run['name'] not in latest or run['id'] > latest[run['name']]['id'])):
            latest[run['name']] = run
    checks = [dict(name=name, id=latest[name]['id'], status=str(latest[name].get('status')),
                   conclusion=latest[name].get('conclusion') if isinstance(latest[name].get('conclusion'), str) else None,
                   head_sha=binding['head']) for name in binding['checks'] if name in latest]
    failed = [c for c in checks if c['status'] == 'completed' and c['conclusion'] != 'success']
    if failed:
        return dict(phase='failed', checks=checks, detail='; '.join(
            f'{c["name"]} concluded {c["conclusion"]} for {binding["head"]}' for c in failed))
    if len(checks) < len(binding['checks']) or any(c['status'] != 'completed' for c in checks):
        waiting = [n for n in binding['checks'] if n not in {c['name'] for c in checks if c['status'] == 'completed'}]
        return dict(phase='waiting', checks=checks, detail='waiting for ' + ', '.join(waiting))
    return dict(phase='passed', checks=checks, detail='')


def _identity(binding):
    return {key: binding[key] for key in ('task_id', 'repository', 'ref', 'contract')}


def _publish(locations, path, binding, current, run_ci, kind):
    """Write one receipt-covered ``run.ci`` value; the intent names it before the write."""
    worker, task_id = locations.worktree, locations.task_id
    receipts._save_intent(path, dict(binding=binding, expected=run_ci, done=False))
    with receipts.task_lock(worker, task_id):
        latest, pending = operation_state(worker, task_id)
        if pending or latest != current:
            raise CardineError('CI inputs changed before the result write')
        updated = deepcopy(current)
        updated['run']['ci'] = run_ci
        receipts.write_operation(worker, task_id, updated, previous=current, kind=kind)
    receipts._save_intent(path, dict(binding=binding, expected=run_ci, done=True))
    return operation_state(worker, task_id)[0]


def _result(binding, phase, changed, checks=(), detail=''):
    return dict(phase=phase, changed=changed, checks=list(checks), detail=detail,
                repository=binding['repository'], ref=binding['ref'], head=binding['head'])


@scoped_command
def ci_gate(locations):
    """One bounded CI step; None means no CI is required."""
    worker, task_id = locations.worktree, locations.task_id
    state, pending = operation_state(worker, task_id)
    policy = ci_policy(state['contract'])
    if policy is None:
        return None
    _require_gh()  # Before any push: a task head must not be published that cannot be checked.
    path = operation_path(locations, 'ci')
    intent = receipts._load_intent(path) if path.exists() else None
    replayed = False
    if pending:
        kind = pending['state']['run']['receipts'][-1]['kind']
        if (kind not in ('ci-push', 'ci-result') or intent is None or intent['done']
                or intent['expected'] != pending['state']['run'].get('ci')):
            raise CardineError('foreign pending operation before CI')
        with receipts.task_lock(worker, task_id):
            state = receipts.replay_operation(worker, task_id, kind=kind)
        replayed = True
        intent = dict(intent, done=True)
        receipts._save_intent(path, intent)
    binding = ci_binding(locations, state, policy)
    if intent is not None and not intent['done'] and _identity(intent['binding']) != _identity(binding):
        raise CardineError('foreign CI operation: repository, ref, task or contract changed')
    cached = state['run'].get('ci')
    if cached is not None:
        receipts.verify_receipts(worker, state)
    if cached is not None and cached['binding'] == binding:
        if cached['phase'] == 'passed':
            return _result(binding, 'passed', replayed, cached['checks'])
    else:
        cached = None
    if cached is None:
        push = dict(ref=binding['ref'], sha=binding['head'])
        if remote_tip(worker, binding['ref'], locations) != binding['head']:
            if intent is None or intent['done'] or intent['binding'] != binding:
                receipts._save_intent(path, dict(binding=binding, expected=None, done=False))
            receipts.boundary('before_ci_push')
            _push(worker, locations, binding['head'], binding['ref'])
            receipts.boundary('after_ci_push')
        state = _publish(locations, path, binding, state, dict(binding=binding, phase='pushed', push=push, checks=[]),
                         'ci-push')
        cached, replayed = state['run']['ci'], True
    receipts.boundary('before_ci_query')
    outcome = query_checks(binding)
    receipts.boundary('after_ci_query')
    if outcome['phase'] != 'passed':
        return _result(binding, outcome['phase'], replayed, outcome['checks'], outcome['detail'])
    _publish(locations, path, binding, state,
             dict(binding=binding, phase='passed', push=cached['push'], checks=outcome['checks']), 'ci-result')
    return _result(binding, 'passed', True, outcome['checks'])


def require_ci_pass(worker, project, task_id, task_state):
    """Read-only staging precondition: no gh call, no push, no write.

    Every route to a direct candidate, including the Internal ``worktree advance``
    and ``integrate stage`` adapters, passes here. The contract is the committed
    one; the result must be a receipt-covered pass bound to the current delivered
    head, repository, ref, review attempt, contract and required checks.
    """
    policy = ci_policy(task_state['contract'])
    if policy is None:
        return
    from cardine.lifecycle.context import resolve_run_locations
    locations = resolve_run_locations(task_id, project)
    state, pending = operation_state(worker, task_id)
    cached = state['run'].get('ci')
    if pending or cached is None:
        passed = False
    else:
        receipts.verify_receipts(worker, state)
        passed = cached['phase'] == 'passed' and cached['binding'] == ci_binding(locations, state, policy)
    if not passed:
        raise stop_error('EVIDENCE_INCOMPLETE', 'required CI has not passed for the delivered head; '
                         'run cardine run to push it and check the exact commit', task_id=task_id, project=project,
                         resume=f'cardine run {task_id} --project {project}')
