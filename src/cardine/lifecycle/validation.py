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
import shutil
from pathlib import Path
import subprocess
import uuid
from concurrent.futures import ThreadPoolExecutor

from cardine.lifecycle import receipts
from cardine.lifecycle.live import LiveLog
from cardine.lifecycle.delivery import verify_delivery
from cardine.lifecycle.execution import (_execution_location,
                                         _execution_state, execution_source_digest)
from cardine.lifecycle.source import commit_own_records, _execution_owned_paths
from cardine.tasks.validation import (inputs, _ledger, verified_validation,
                                      resolved_commands, environment_identity, host_observations_complete)
from cardine.shared.errors import CardineError
from cardine.shared.git import git_output
from cardine.shared.layout import names
from cardine.stops.render import stop_error

LOG_LIMIT = 64 * 1024
LOG_HEAD = 16 * 1024


def _read_log(stream, frame=None):
    """Retain the beginning and end while forwarding output as it arrives."""
    head, tail, length = bytearray(), bytearray(), 0
    with stream:
        while chunk := stream.read1(8192):
            if frame is not None:
                frame.output(chunk)
            length += len(chunk)
            room = LOG_HEAD - len(head)
            head += chunk[:room]
            tail += chunk[room:] if room > 0 else chunk
            del tail[:max(0, len(tail) - (LOG_LIMIT - LOG_HEAD))]
    omitted = length - len(head) - len(tail)
    if omitted <= 0:
        return bytes(head + tail).decode('utf-8', 'replace'), False
    marker = f'\n... {omitted} bytes omitted ...\n'.encode()
    return bytes(head + marker + tail).decode('utf-8', 'replace'), True


def execute_command(command, root, environment, descriptor, frame=None):
    """Drain both pipes without unbounded buffers or mixing logs into CLI JSON."""
    receipts.boundary('before_validation_process')
    from cardine.shared.git import invalidate_facts
    invalidate_facts()
    process = subprocess.Popen(command, shell=True, executable='/bin/bash', cwd=root,
                               env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               pass_fds=(descriptor,))
    receipts.boundary('after_validation_process')
    if frame is not None:
        frame.started(process.pid)
    with ThreadPoolExecutor(max_workers=2) as pool:
        stdout = pool.submit(_read_log, process.stdout, frame)
        stderr = pool.submit(_read_log, process.stderr, frame)
        process.wait()
        receipts.boundary('before_validation_exit')
        status = process.returncode
        if frame is not None:
            frame.finished(status)
        receipts.boundary('after_validation_exit')
        out, out_truncated = stdout.result()
        err, err_truncated = stderr.result()
    return status, out, err, out_truncated, err_truncated


def operation_path(root, task_id):
    common = Path(git_output(root, 'rev-parse', '--git-common-dir'))
    return receipts.safe_path((root / common).resolve(), f'cardine-operations/{task_id}.validation')


def byproducts_path(root, task_id):
    common = Path(git_output(root, 'rev-parse', '--git-common-dir'))
    return receipts.safe_path((root / common).resolve(), f'cardine-operations/{task_id}.byproducts')


def _untracked(root):
    return sorted(filter(None, git_output(root, 'ls-files', '--others', '--exclude-standard', '-z').split('\0')))


def _restore_worktree(root, task_id, intent, path, context):
    if 'untracked' not in intent:
        return
    owned = _execution_owned_paths(root, task_id, context=context)
    baseline = set(intent['untracked'])
    for relative in _untracked(root):
        if relative in baseline or relative in owned or relative.startswith('.cardine/'):
            continue
        source = root / relative
        # Validate parents without rejecting a symlink that is itself the byproduct.
        if source.parent != root:
            receipts.safe_path(root, source.parent.relative_to(root).as_posix())
        destination_root = byproducts_path(root, task_id)
        destination_relative = intent['attemptId'] + '/' + relative
        destination_parent = Path(destination_relative).parent.as_posix()
        receipts.safe_path(destination_root, destination_parent)
        destination = destination_root / destination_relative
        if destination.is_symlink():
            destination.unlink()
        destination = receipts.safe_path(destination_root, destination_relative)
        if relative not in intent.setdefault('byproducts', []):
            intent['byproducts'].append(relative)
            intent['byproducts'].sort()
            receipts._save_intent(path, intent)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))
        from cardine.shared.git import invalidate_facts
        invalidate_facts()
        parent = source.parent
        while parent != root:
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent
    receipts._save_intent(path, intent)


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


def _failed_quick(progress):
    """IDs that failed in the quick rounds of a recorded attempt."""
    runs = progress.get('runs', [])[:progress.get('quickRounds', 0)]
    return list(dict.fromkeys(item['id'] for run in runs for item in run if item['exitStatus'] != 0))


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
    if 'candidateValidation' in updated['run']:
        updated['run']['candidateValidation']['consecutiveFailures'] = progress['consecutiveFailures']
        updated['run']['candidateValidation']['quickFailures'] = progress['quickFailures']
    from cardine.tasks.identity import resolve_task_identity
    import re
    handoff = resolve_task_identity(root, task_id, 'existing').handoff_path.relative_to(root).as_posix()
    target = receipts.safe_path(root, handoff)
    text = target.read_text() if target.exists() else ''
    section = '\n'.join(['## Measured validation', '',
        f'- Attempt: `{progress["attemptId"]}`; result: {progress["phase"]}',
        f'- Evidence: `{path}`',
        f'- Quick rounds: {progress.get("quickRounds", 0)}; quick failures: {progress.get("quickFailures", 0)}',
        '- Intermittent commands: ' + (', '.join(item['id'] for item in progress['intermittent']) or 'none'),
        '- Scoped skips: ' + ('; '.join(item['id'] + ': ' + item['reason'] for item in progress['inputs']['skips']) or 'none'),
        *[f'- Round {index + 1}: ' + '; '.join(f'{item["id"]}: `{item["command"]}`, exit {item["exitStatus"]}, log `{item["log"]}`' for item in run)
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
    from cardine.lifecycle.context import resolve_run_locations
    inspection = _execution_location(root, task_id, context=context)
    context = context or resolve_run_locations(task_id, root)
    if set(inspection['errors']) - {'dirty-worktree'} or inspection['integration_active']:
        raise CardineError('validation requires the canonical task worktree')
    base = str(inspection['base_commit'])
    with runner_lock(root, task_id) as descriptor:
        path = operation_path(root, task_id)
        intent = receipts._load_intent(path) if path.exists() else None
        authority = receipts.require_authority(root)
        if intent and (intent['task_id'] != task_id or intent['root'] != str(root)
                       or not receipts.authority_covers(intent['authority'], authority, root)):
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
        if intent and intent['phase'] == 'process':
            _restore_worktree(root, task_id, intent, path, context)
        environment = dict(os.environ)
        current = inputs(root, task_id, state, base, environment)
        previous = state.get('run', {}).get('validation', {})
        from cardine.tasks.validation import (failure_count, quick_failure_count, quick_failure_limit,
                                              quick_failed, quick_limit_error, quick_plan)
        failures = failure_count(state)
        limit = state['contract']['options']['validationRetryLimit']
        quick_count, quick_limit = quick_failure_count(state), quick_failure_limit(state)
        if failures >= limit:
            raise stop_error('VALIDATION_RETRY_LIMIT', json.dumps(previous.get('runs', [])),
                             task_id=task_id, project=root)
        if quick_count >= quick_limit:
            raise quick_limit_error(task_id, root, quick_limit, _failed_quick(previous))
        if intent and intent['phase'] not in ('complete', 'invalidated') and intent['inputs'] != current:
            # An interrupted attempt for other inputs never published a result:
            # its runs say nothing about the current source, so it is replaced.
            receipts._save_intent(path, dict(intent, phase='invalidated'))
            intent = dict(intent, phase='invalidated')
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
            if intent['progress']['quickFailures'] >= quick_limit:
                raise quick_limit_error(task_id, root, quick_limit, _failed_quick(intent['progress']))
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
            commit_own_records(root, task_id, context=context)
            previous_byproducts = byproducts_path(root, task_id)
            if previous_byproducts.exists():
                shutil.rmtree(previous_byproducts)
            policy = state['contract']['validation']
            plan = quick_plan(policy.get('retry', {}), policy.get('preflight', []),
                              [key for key in current['commands'] if key in previous.get('lastFailed', [])],
                              policy['commands'])
            intent = dict(task_id=task_id, root=str(root), authority=authority, inputs=current,
                          attemptId=uuid.uuid4().hex, phase='process', runs=[], before=receipts.state_digest(state),
                          untracked=_untracked(root), byproducts=[],
                          quick=[dict(kind=kind, commands=[list(item) for item in commands]) for kind, commands in plan])
            receipts.boundary('before_validation_intent')
            receipts._save_intent(path, intent)
            receipts.boundary('after_validation_intent')
        if receipts.state_digest(state) != intent['before']:
            raise CardineError('validation input state changed')
        runs = intent['runs']
        live = LiveLog(path.parent.parent, task_id)
        retry = state['contract']['validation'].get('retry', {})
        quick = intent.get('quick', [])
        kinds, rounds = [item['kind'] for item in quick], len(quick)
        variants = {}
        if runs[rounds:]:
            failed = {item['id'] for item in runs[rounds] if item['exitStatus'] != 0}
            variants = {key: retry[key] for key in state['contract']['validation']['commands'] if key in failed and key in retry}
        while True:
            if quick_failed(kinds, runs):
                break  # A quick failure ends the attempt before the complete set.
            rest = runs[rounds:]
            if len(runs) < rounds:
                round_commands = dict(quick[len(runs)]['commands'])
            elif not rest:
                round_commands = current['commands']
            elif all(item['exitStatus'] == 0 for item in rest[0]):
                break
            else:
                failed = {item['id'] for item in rest[0] if item['exitStatus'] != 0}
                variants = {key: retry[key] for key in state['contract']['validation']['commands'] if key in failed and key in retry}
                if variants and len(rest) == 1:
                    round_commands = variants
                elif variants and len(rest) == 2 and any(item['exitStatus'] == 1 for item in rest[1]):
                    break
                elif len(rest) == (2 if variants else 1):
                    round_commands = current['commands']
                else:
                    break
            before_run = _execution_state(root, task_id, context=context)
            if (inputs(root, task_id, before_run, base, dict(os.environ)) != current
                    or receipts.state_digest(before_run) != intent['before']):
                receipts._save_intent(path, dict(intent, phase='invalidated'))
                raise stop_error('VALIDATION_FAILED', 'Validation inputs changed before the full rerun; start a fresh attempt',
                                 task_id=task_id, project=root)
            results = []
            for key, command in round_commands.items():
                with live.command(command, kind='validation', key=key, round_number=len(runs) + 1) as frame:
                    status, stdout, stderr, out_truncated, err_truncated = execute_command(
                        command, root, environment, descriptor, frame)
                results.append(dict(id=key, command=command, exitStatus=status,
                     commit=git_output(root, 'rev-parse', 'HEAD'), sourceDigest=current['sourceDigest'],
                     attemptId=intent['attemptId'], round=len(runs) + 1,
                     log=f'{names().execution_evidence_path(task_id)}#{intent["attemptId"]}/{len(runs)+1}/{key}',
                     stdout=stdout, stderr=stderr, stdoutTruncated=out_truncated, stderrTruncated=err_truncated))
            receipts.boundary('before_validation_restore')
            _restore_worktree(root, task_id, intent, path, context)
            receipts.boundary('after_validation_restore')
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
        rest = runs[rounds:]
        quick_hit = quick_failed(kinds, runs)
        if quick_hit:
            passed, intermittent, count = False, [], failures
            quick_new, last_failed = quick_count + 1, list(previous.get('lastFailed', []))
        else:
            complete_last = len(rest) == 1 or not variants or len(rest) == 3
            passed = complete_last and all(item['exitStatus'] == 0 for item in rest[-1])
            intermittent = [item for item in rest[0] if item['exitStatus'] != 0] if passed and len(rest) > 1 else []
            count = 0 if passed else failures + 1
            quick_new = 0 if passed else quick_count
            last_failed = [] if passed else [item['id'] for item in (rest[-1] if complete_last else rest[0])
                                             if item['exitStatus'] != 0]
        progress = dict(attemptId=intent['attemptId'], inputs=current, runs=runs,
                        phase='passed' if passed else 'failed', consecutiveFailures=count,
                        quickFailures=quick_new, quickRounds=min(rounds, len(runs)), lastFailed=last_failed,
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
        if quick_hit and quick_new >= quick_limit:
            raise quick_limit_error(task_id, root, quick_limit, _failed_quick(progress))
        return verified_validation(root, task_id, state)
