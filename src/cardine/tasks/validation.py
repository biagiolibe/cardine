"""Read-only frozen validation identity and receipt-covered task results."""
import json
import os
from cardine.lifecycle import receipts
from cardine.lifecycle.source import _execution_owned_paths, execution_source_digest
from cardine.lifecycle.scope import enforce_scope, _matches
from cardine.shared.errors import CardineError
from cardine.shared.layout import names
from cardine.tasks.state import read_task_state
from cardine.stops.render import stop_error


def _validation_state(root, task_id):
    return read_task_state(root, task_id, 'single', stop_factory=stop_error, require_contract=True)


def environment_identity(environment):
    return receipts.digest(receipts.encoded({key: value for key, value in environment.items()
                           if key not in {'_', 'SHLVL', 'PWD', 'OLDPWD'}}))


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
    return dict(contractDigest=receipts.digest(receipts.encoded(state['contract'])),
                source=delivery.get('source', ''), sourceDigest=execution_source_digest(root, task_id, operation_paths=operation_paths),
                sourceTree=delivery.get('sourceTree', ''), cwd=str(root),
                commands=commands, skips=skips,
                commandDigest=receipts.digest(receipts.encoded(dict(commands=commands, skips=skips))),
                environmentDigest=environment_identity(environment))


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
