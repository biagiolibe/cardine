"""Measured task attempts with durable recovery, within the same-user boundary.

Receipts detect uncovered changes; they do not authenticate an author. Unknown
process outcomes rerun the entire set and never become invented exit statuses.
"""

from cardine.shared.git import scoped_command
from copy import deepcopy
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import subprocess
import uuid
from concurrent.futures import ThreadPoolExecutor

from cardine.lifecycle import receipts
from cardine.lifecycle.delivery import verify_delivery
from cardine.lifecycle.execution import (_execution_location, _execution_owned_paths,
                                         _execution_state, execution_source_digest)
from cardine.tasks.validation import (inputs, _ledger, verified_validation,
                                      resolved_commands, environment_identity, host_observations_complete)
from cardine.shared.errors import CardineError
from cardine.shared.git import git_output
from cardine.shared.layout import names
from cardine.stops.render import stop_error

LOG_LIMIT = 64 * 1024


def _read_log(stream):
    chunks, length, truncated = [], 0, False
    with stream:
        while chunk := stream.read(8192):
            remaining = max(0, LOG_LIMIT - length)
            if remaining:
                chunks.append(chunk[:remaining])
            length += min(len(chunk), remaining)
            truncated |= len(chunk) > remaining
    return b''.join(chunks).decode('utf-8', 'replace'), truncated


def execute_command(command, root, environment, descriptor):
    """Drain both pipes without unbounded buffers or mixing logs into CLI JSON."""
    receipts.boundary('before_validation_process')
    from cardine.shared.git import invalidate_facts
    invalidate_facts()
    process = subprocess.Popen(command, shell=True, executable='/bin/bash', cwd=root,
                               env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               pass_fds=(descriptor,))
    receipts.boundary('after_validation_process')
    with ThreadPoolExecutor(max_workers=2) as pool:
        stdout = pool.submit(_read_log, process.stdout)
        stderr = pool.submit(_read_log, process.stderr)
        process.wait()
        receipts.boundary('before_validation_exit')
        status = process.returncode
        receipts.boundary('after_validation_exit')
        out, out_truncated = stdout.result()
        err, err_truncated = stderr.result()
    return status, out, err, out_truncated, err_truncated


def operation_path(root, task_id):
    common = Path(git_output(root, 'rev-parse', '--git-common-dir'))
    return receipts.safe_path((root / common).resolve(), f'cardine-operations/{task_id}.validation')


@contextmanager
def runner_lock(root, task_id):
    # Separate from the short metadata lock: validation subprocesses never hold
    # task_lock. This guard prevents concurrent runners, including orphan work.
    path = operation_path(root, task_id).with_suffix('.validation.guard')
    path = receipts.safe_path(path.parent, path.name)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise CardineError('live foreign validation runner') from error
        try:
            yield handle.fileno()
        finally:
            # Closing our descriptor preserves an inherited orphan's guard.
            pass


def _host_observations(contract, runs):
    # Frozen profile names select declared commands, never install/configure a
    # host. Missing command mappings remain unverified and cannot claim success.
    latest = {item['id']: item for item in runs[-1]} if runs else {}
    return [dict(profile=profile, commandId=profile,
                 observed=profile in latest, exitStatus=latest.get(profile, {}).get('exitStatus'),
                 evidence=latest.get(profile, {}).get('log'))
            for profile, status in contract['hostImpact']['profiles'].items() if status == 'enforced']


def _publish(root, task_id, intent, state):
    if (inputs(root, task_id, state, state['run']['delivery']['base'], dict(os.environ)) != intent['inputs']
            or receipts.require_authority(root) != intent['authority']):
        raise CardineError('validation inputs changed before evidence publication')
    path, ledger = _ledger(root, task_id)
    progress = intent['progress']
    entries = [item for item in ledger.get(task_id, []) if item.get('attemptId') != progress['attemptId']]
    ledger[task_id] = entries + [item for run in progress['runs'] for item in run]
    updated = deepcopy(state)
    updated['run']['validation'] = progress
    from cardine.tasks.identity import resolve_task_identity
    import re
    handoff = resolve_task_identity(root, task_id, 'existing').handoff_path.relative_to(root).as_posix()
    target = receipts.safe_path(root, handoff)
    text = target.read_text() if target.exists() else ''
    section = '\n'.join(['## Measured validation', '',
        f'- Attempt: `{progress["attemptId"]}`; result: {progress["phase"]}',
        f'- Evidence: `{path}`',
        '- Intermittent commands: ' + (', '.join(item['id'] for item in progress['intermittent']) or 'none'),
        '- Scoped skips: ' + ('; '.join(item['id'] + ': ' + item['reason'] for item in progress['inputs']['skips']) or 'none'),
        *[f'- Round {index + 1}: ' + '; '.join(f'{item["id"]}: exit {item["exitStatus"]}' for item in run)
          for index, run in enumerate(progress['runs'])]]) + '\n'
    pattern = r'^## Measured validation\s*\n.*?(?=^## |\Z)'
    rendered = re.sub(pattern, lambda _: section + '\n', text, flags=re.MULTILINE | re.DOTALL) if re.search(
        pattern, text, flags=re.MULTILINE | re.DOTALL) else text.rstrip() + '\n\n' + section
    receipts.boundary('before_validation_evidence')
    result = receipts.write_operation(root, task_id, updated, previous=state,
                  kind='task-validation', files={path: receipts.encoded(ledger), handoff: rendered.encode()})
    receipts.boundary('after_validation_evidence')
    return result


@scoped_command
def run_task_validation(root, task_id, *, context=None):
    """Execute one complete attempt, including at most one unchanged full rerun."""
    root = Path(root).resolve()
    from cardine.lifecycle.engine import resolve_run_locations
    context = context or resolve_run_locations(task_id, root)
    inspection = _execution_location(root, task_id, context=context)
    if set(inspection['errors']) - {'dirty-worktree'} or inspection['integration_active']:
        raise CardineError('validation requires the canonical task worktree')
    base = str(inspection['base_commit'])
    with runner_lock(root, task_id) as descriptor:
        path = operation_path(root, task_id)
        intent = receipts._load_intent(path) if path.exists() else None
        authority = receipts.require_authority(root)
        if intent and (intent['task_id'] != task_id or intent['root'] != str(root)
                       or intent['authority'] != authority):
            raise CardineError('validation operation has foreign owner or changed authority')
        with receipts.task_lock(root, task_id):
            if receipts.pending_operation(root, task_id):
                if not intent or intent['phase'] != 'publish':
                    raise CardineError('validation cannot replay a foreign pending operation')
                pending = receipts._load_intent(receipts._intent_path(root, task_id))
                if pending['state']['run'].get('validation') != intent['progress']:
                    raise CardineError('validation pending result has foreign owner')
                ignored = [receipts._intent_path(root, task_id).relative_to(root).as_posix(),
                           *[item['staged'] for item in pending['files'].values()]]
                if inputs(root, task_id, pending['state'], base, dict(os.environ), operation_paths=ignored) != intent['inputs']:
                    raise CardineError('validation inputs changed before result replay')
                receipts.replay_operation(root, task_id, kind='task-validation')
            state = _execution_state(root, task_id, context=context)
            receipts.verify_receipts(root, state)
        if (intent and intent['phase'] == 'publish'
                and state.get('run', {}).get('validation') == intent['progress']):
            # The result receipt already proves publication. Finish that exact
            # historical effect before evaluating a later repair or revision.
            receipts.boundary('before_validation_result')
            intent = dict(intent, phase='complete')
            receipts._save_intent(path, intent)
            receipts.boundary('after_validation_result')
        environment = dict(os.environ)
        current = inputs(root, task_id, state, base, environment)
        previous = state.get('run', {}).get('validation', {})
        failures = previous.get('consecutiveFailures', 0)
        limit = state['contract']['options']['validationRetryLimit']
        if failures >= limit:
            raise stop_error('VALIDATION_RETRY_LIMIT', json.dumps(previous.get('runs', [])),
                             task_id=task_id, project=root)
        if intent and intent['phase'] not in ('complete', 'invalidated') and intent['inputs'] != current:
            raise CardineError('validation inputs changed during interrupted attempt')
        if intent and intent['phase'] == 'publish':
            with receipts.task_lock(root, task_id):
                if state.get('run', {}).get('validation') != intent['progress']:
                    state = _publish(root, task_id, intent, state)
            receipts.boundary('before_validation_result')
            receipts._save_intent(path, dict(intent, phase='complete'))
            receipts.boundary('after_validation_result')
            if intent['progress']['consecutiveFailures'] >= limit:
                raise stop_error('VALIDATION_RETRY_LIMIT', json.dumps(intent['progress']['runs']),
                                 task_id=task_id, project=root)
            return verified_validation(root, task_id, state)
        existing = verified_validation(root, task_id, state)
        if (existing is not None and (existing["phase"] != "passed"
                or host_observations_complete(state["contract"], existing))):
            return existing  # Failed unchanged work returns repair, never spends twice.
        if verify_delivery(root, state, base) is None:
            raise stop_error('ACCEPTANCE_UNMET', 'A complete committed implementation must be delivered first',
                             task_id=task_id, project=root)
        missing = [name for name in state['contract']['deliverables']
                   if not receipts.safe_path(root, name).is_file()]
        if missing:
            raise stop_error('ACCEPTANCE_UNMET', 'Missing acceptance deliverables: ' + ', '.join(missing),
                             task_id=task_id, project=root)
        if intent is None or intent['phase'] in ('complete', 'invalidated'):
            intent = dict(task_id=task_id, root=str(root), authority=authority, inputs=current,
                          attemptId=uuid.uuid4().hex, phase='process', runs=[], before=receipts.state_digest(state))
            receipts.boundary('before_validation_intent')
            receipts._save_intent(path, intent)
            receipts.boundary('after_validation_intent')
        if receipts.state_digest(state) != intent['before']:
            raise CardineError('validation input state changed')
        runs = intent['runs']
        while len(runs) < 2 and (not runs or any(item['exitStatus'] != 0 for item in runs[-1])):
            before_run = _execution_state(root, task_id, context=context)
            if (inputs(root, task_id, before_run, base, dict(os.environ)) != current
                    or receipts.state_digest(before_run) != intent['before']):
                receipts._save_intent(path, dict(intent, phase='invalidated'))
                raise stop_error('VALIDATION_FAILED', 'Validation inputs changed before the full rerun; start a fresh attempt',
                                 task_id=task_id, project=root)
            results = []
            for key, command in current['commands'].items():
                status, stdout, stderr, out_truncated, err_truncated = execute_command(command, root, environment, descriptor)
                results.append(dict(id=key, command=command, exitStatus=status,
                     commit=git_output(root, 'rev-parse', 'HEAD'), sourceDigest=current['sourceDigest'],
                     attemptId=intent['attemptId'], round=len(runs) + 1,
                     log=f'{names().execution_evidence_path(task_id)}#{intent["attemptId"]}/{len(runs)+1}/{key}',
                     stdout=stdout, stderr=stderr, stdoutTruncated=out_truncated, stderrTruncated=err_truncated))
            # A subprocess may change files, policy or environment; no result is
            # accepted until all inputs and receipt authority have been rechecked.
            state_after = _execution_state(root, task_id, context=context)
            if (inputs(root, task_id, state_after, base, dict(os.environ)) != current
                    or receipts.state_digest(state_after) != intent['before']
                    or receipts.require_authority(root) != authority):
                receipts._save_intent(path, dict(intent, phase='invalidated'))
                raise stop_error('VALIDATION_FAILED', 'Validation inputs changed while commands ran; run a fresh complete attempt',
                                 task_id=task_id, project=root)
            runs = [*runs, results]
            receipts.boundary('before_validation_logs')
            intent = dict(intent, runs=runs)
            receipts._save_intent(path, intent)
            receipts.boundary('after_validation_logs')
            if all(item['exitStatus'] == 0 for item in results):
                break
        passed = all(item['exitStatus'] == 0 for item in runs[-1])
        intermittent = [item for item in runs[0] if item['exitStatus'] != 0] if passed and len(runs) == 2 else []
        count = 0 if passed else failures + 1
        progress = dict(attemptId=intent['attemptId'], inputs=current, runs=runs,
                        phase='passed' if passed else 'failed', consecutiveFailures=count,
                        intermittent=intermittent, evidence=names().execution_evidence_path(task_id).as_posix(),
                        hostObservations=_host_observations(state['contract'], runs),
                        acceptanceReferences=[dict(path=name, digest=receipts.digest(receipts.safe_path(root, name).read_bytes()))
                           for name in state['contract']['deliverables'] if receipts.safe_path(root, name).is_file()])
        receipts.boundary('before_validation_counter')
        intent = dict(intent, progress=progress, phase='publish')
        receipts._save_intent(path, intent)
        receipts.boundary('after_validation_counter')
        with receipts.task_lock(root, task_id):
            state = _publish(root, task_id, intent, state)
        receipts.boundary('before_validation_result')
        receipts._save_intent(path, dict(intent, phase='complete'))
        receipts.boundary('after_validation_result')
        if count >= limit:
            raise stop_error('VALIDATION_RETRY_LIMIT', json.dumps(runs), task_id=task_id, project=root)
        return verified_validation(root, task_id, state)
