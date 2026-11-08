"""Read-only frozen validation identity and receipt-covered task results."""
import json
import os
import shlex
import shutil
from cardine.lifecycle import receipts
from cardine.lifecycle.source import _execution_owned_paths, execution_source_digest
from cardine.lifecycle.scope import enforce_scope, _matches
from cardine.shared.errors import CardineError
from cardine.shared.layout import names
from cardine.tasks.state import read_task_state
from cardine.stops.render import stop_error


def _validation_state(root, task_id):
    return read_task_state(root, task_id, 'single', stop_factory=stop_error, require_contract=True)


def environment_identity(environment, commands=()):
    """The programs the validation commands would run in this environment.

    Each command's program is resolved on the environment's PATH. Session
    variables that hosts change on every call, such as tool-call IDs or terminal
    session keys, do not change which program runs, so they never make a
    measured result stale. A name with a path separator is a file of the
    checkout, which the source digest already covers.
    """
    resolved = {}
    for command in commands:
        try:
            words = shlex.split(command)
        except ValueError:
            continue
        words = [word for word in words if not ('=' in word and word.split('=', 1)[0].isidentifier())][:1]
        for name in words:
            if os.sep in name:
                continue
            found = shutil.which(name, path=environment.get('PATH', ''))
            resolved[name] = os.path.realpath(found) if found else None
    return receipts.digest(receipts.encoded(resolved))


def resolved_commands(contract, paths):
    """Frozen path rules restrict applicability; task checks are never inferred away.

    A command mentioned by several rules runs if any rule matches. Commands
    without a rule always run. An explicit empty baseline remains explicit.
    """
    policy = contract['validation']
    rules = contract['validationScoping']
    commands, skips = {}, []
    for key in policy['baseline']:
        applicable = [rule for rule in rules if key in rule['commands']]
        if contract['hostImpact']['profiles'].get(key) == 'enforced':
            applicable = []  # An enforced host observation cannot be scoped away.
        if applicable and not any(_matches(path, pattern) for rule in applicable
                                  for pattern in rule['paths'] for path in paths):
            skips.append(dict(id=key, command=policy['commands'][key],
                              reason='No changed path matches the frozen validationScoping rules'))
        else:
            commands[key] = policy['commands'][key]
    return commands, skips


def inputs(root, task_id, state, base, environment, *, operation_paths=()):
    paths = enforce_scope(root, state, base, owned=_execution_owned_paths(root, task_id) | set(operation_paths))
    commands, skips = resolved_commands(state['contract'], paths)
    delivery = state.get('run', {}).get('delivery', {})
    identity = dict(commands=commands, skips=skips)
    if 'retry' in state['contract']['validation']:
        identity['retry'] = state['contract']['validation']['retry']
    return dict(contractDigest=receipts.digest(receipts.encoded(state['contract'])),
                source=delivery.get('source', ''), sourceDigest=execution_source_digest(root, task_id, operation_paths=operation_paths),
                sourceTree=delivery.get('sourceTree', ''), cwd=str(root),
                commands=commands, skips=skips,
                commandDigest=receipts.digest(receipts.encoded(identity)),
                environmentDigest=environment_identity(environment, commands.values()))


def _ledger(root, task_id):
    from cardine.tasks.evidence import require_measured_ledger
    require_measured_ledger(root, task_id)
    path = names().execution_evidence_path(task_id).as_posix()
    target = receipts.safe_path(root, path)
    value = json.loads(target.read_bytes()) if target.exists() else {}
    if not isinstance(value, dict) or not isinstance(value.get(task_id, []), list):
        raise CardineError('invalid task validation ledger')
    return path, value


def verified_validation(root, task_id, state=None, *, environment=None):
    """Never promote an editable ledger or a stale successful attempt to progress."""
    state = state or _validation_state(root, task_id)
    receipts.verify_receipts(root, state)
    progress = state.get('run', {}).get('validation')
    if not progress:
        return None
    base = state['run']['delivery']['base']
    current = inputs(root, task_id, state, base, dict(os.environ) if environment is None else environment)
    if progress['inputs'] != current:
        return None
    path, ledger = _ledger(root, task_id)
    entries = [item for item in ledger.get(task_id, []) if item.get('attemptId') == progress['attemptId']]
    expected = [item for run in progress['runs'] for item in run]
    if entries != expected or progress['evidence'] != path:
        raise CardineError('validation ledger differs from measured attempt')
    return progress




def host_observations_complete(contract, progress):
    """Bind each enforced profile to its actual command result, not report prose."""
    latest = {entry['id']: entry for entry in progress['runs'][-1]} if progress['runs'] else {}
    observations = {entry['profile']: entry for entry in progress['hostObservations']}
    for profile, status in contract['hostImpact']['profiles'].items():
        if status != 'enforced':
            continue
        entry, observed = latest.get(profile, {}), observations.get(profile, {})
        if (not observed.get('observed') or observed.get('commandId') != profile
                or observed.get('exitStatus') != 0 or entry.get('exitStatus') != 0
                or entry.get('command') != progress['inputs']['commands'].get(profile)
                or not entry.get('log') or observed.get('evidence') != entry.get('log')):
            return False
    return True


def failure_count(state):
    """The one measured retry allowance shared by task and candidate attempts."""
    return max(state.get('run', {}).get(key, {}).get('consecutiveFailures', 0)
               for key in ('validation', 'candidateValidation'))


def quick_failure_count(state):
    """The separate allowance for quick-command failures, shared like failure_count."""
    return max(state.get('run', {}).get(key, {}).get('quickFailures', 0)
               for key in ('validation', 'candidateValidation'))


def quick_failure_limit(state):
    return state['contract']['options'].get('quickFailureLimit', 10)


def quick_plan(retry, preflight, failed, ordered):
    """Quick rounds an attempt runs before its complete set, in this order.

    `ordered` maps declared IDs to commands; `failed` holds the IDs whose last
    complete run failed. A variant round exists only when one has a variant.
    """
    variants = [(key, retry[key]) for key in ordered if key in failed and key in retry]
    rounds = [('variant', variants)] if variants else []
    if preflight:
        rounds.append(('preflight', [(key, ordered[key]) for key in preflight]))
    return rounds


def quick_failed(kinds, runs):
    """True once a recorded quick round failed: a variant only by exit 1, preflight by any non-zero."""
    for kind, run in zip(kinds, runs):
        statuses = [item['exitStatus'] for item in run]
        if (kind == 'variant' and 1 in statuses) or (kind == 'preflight' and any(statuses)):
            return True
    return False


def quick_limit_error(task_id, root, limit, failed):
    return stop_error('VALIDATION_RETRY_LIMIT',
                      f'Quick failure limit {limit} reached; failed quick commands: ' + (', '.join(failed) or 'none recorded'),
                      task_id=task_id, project=root)
