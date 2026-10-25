"""Injected role profiles and receipt-backed host sessions.

Adapters must provide effective host permissions and idempotent session creation
by request ID. No adapter is installed by default. Receipts detect changed data;
they do not authenticate an OS user or make an unenforced profile trustworthy.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from cardine.lifecycle import receipts
from cardine.lifecycle.source import execution_source_digest
from cardine.shared.errors import CardineError
from cardine.shared.git import git_output, invalidate_facts, scoped_command
from cardine.stops.render import stop_error
from cardine.tasks.state_core import state_path
import json


@dataclass(frozen=True)
class RoleProfile:
    identity: str
    role: str
    enforced: bool


class HostTransport(Protocol):
    """Trusted injected host channel; lookup/spawn use durable request identity.

    spawn must atomically create-or-return the same session for the request,
    even when its previous response was lost. poll must retain the terminal
    response and return it only after the worker has stopped.
    authorize must check the host-issued credential, never a caller role label.
    """
    def profile(self, role: str) -> RoleProfile | None: ...
    def authorize(self, credential: str, action: str) -> bool: ...
    def lookup(self, request: dict) -> dict | None: ...
    def spawn(self, request: dict) -> dict: ...
    def poll(self, session: dict) -> dict | None: ...


@dataclass(frozen=True)
class ProfileAdapter:
    host: str
    transport: HostTransport
    credential: str

    def require(self, action):
        if not self.transport.authorize(self.credential, action):
            raise CardineError('host denied ' + action)

    def profiles(self):
        self.require('launch')
        profiles = {role: self.transport.profile(role) for role in ('implementer', 'reviewer')}
        if (any(p is None or p.role != role or not p.identity or not p.enforced
                for role, p in profiles.items())
                or profiles['implementer'].identity == profiles['reviewer'].identity):
            raise stop_error('COMMAND_REFUSED',
                             'host role boundary unavailable: distinct enforced profiles required')
        return profiles


class CodexProfileAdapter(ProfileAdapter):
    def __init__(self, transport, credential):
        super().__init__('codex', transport, credential)


class ClaudeProfileAdapter(ProfileAdapter):
    def __init__(self, transport, credential):
        super().__init__('claude', transport, credential)


def _session(request, value):
    keys = ('request_id', 'role', 'profile', 'host')
    if (not isinstance(value, dict) or set(value) != {*keys, 'session_id'}
            or any(value.get(k) != request[k] for k in keys)
            or not isinstance(value['session_id'], str) or not value['session_id']):
        raise CardineError('host returned a foreign role/session identity')
    return deepcopy(value)


@scoped_command
def launch_work(root, task_id, work, *, attempt, adapter, context=None):
    """Persist request, reconcile one session, and receipt its retained response.

    Completion is a host response only; delivery, acceptance and verdict gates
    remain separate. A caller cannot use a response as an approval receipt.
    """
    root = Path(root).resolve()
    if (work.role not in ('implementer', 'reviewer') or work.worktree != root
            or not isinstance(attempt, str) or not attempt):
        raise CardineError('launch requires a role, canonical worktree and attempt identity')
    profiles = adapter.profiles()
    from cardine.lifecycle.execution import _execution_location, _execution_owned_paths
    from cardine.lifecycle.scope import enforce_scope
    inspection = _execution_location(root, task_id, context=context)
    if set(inspection['errors']) - {'dirty-worktree'} or inspection['integration_active']:
        raise CardineError('host launch requires the canonical task worktree')
    with receipts.task_lock(root, task_id):
        pending = None
        ignored = []
        if receipts.pending_operation(root, task_id):
            pending = receipts._load_intent(receipts._intent_path(root, task_id))
            ignored = [receipts._intent_path(root, task_id).relative_to(root).as_posix(),
                       *[item['staged'] for item in pending['files'].values()]]
            state = pending['state']
        else:
            state = json.loads(state_path(root, task_id).read_bytes())
            receipts.verify_receipts(root, state, context=context)
        contract = receipts.digest(receipts.encoded(state.get('contract')))
        if work.snapshot_digest != contract:
            raise CardineError('host request contract changed')
        enforce_scope(root, state, str(inspection['base_commit']),
                      owned=_execution_owned_paths(root, task_id, context=context) | set(ignored))
        request = dict(task_id=task_id, root=str(root), attempt=attempt,
                       contract=contract, source=git_output(root, 'rev-parse', 'HEAD'),
                       source_digest=execution_source_digest(root, task_id, context=context,
                                                            operation_paths=ignored),
                       role=work.role, host=adapter.host, profile=profiles[work.role].identity,
                       work=work.as_json(), authority=receipts.require_authority(root, context=context))
        # An attempt is immutable, including across process restarts. New source
        # or contract requires a new attempt; never silently spawn another worker.
        key = receipts.digest(receipts.encoded(dict(task=task_id, role=work.role, attempt=attempt)))
        request['request_id'] = key
        kind = 'host-launch:' + key
        if pending:
            record = state.get('run', {}).get('hostLaunches', {}).get(key)
            if (pending['task_id'] != task_id or not record or record['request'] != request
                    or state['run']['receipts'][-1]['kind'] != kind):
                raise CardineError('host launch pending operation has foreign owner or changed inputs')
            state = receipts.replay_operation(root, task_id, kind=kind)
        records = state.get('run', {}).get('hostLaunches', {})
        record = records.get(key)
        if record and record['request'] != request:
            raise CardineError('host launch has foreign owner or changed inputs')
        if any(other_key != key and other['response'] is None
               for other_key, other in records.items()):
            raise CardineError('another issued host session must stop before launching a new role or attempt')

        def publish(value, boundary):
            nonlocal state, record
            if (execution_source_digest(root, task_id, context=context) != request['source_digest']
                    or git_output(root, 'rev-parse', 'HEAD') != request['source']
                    or receipts.require_authority(root, context=context) != request['authority']):
                raise CardineError('host launch inputs changed during host operation')
            updated = deepcopy(state)
            updated.setdefault('run', {}).setdefault('hostLaunches', {})[key] = value
            receipts.boundary('before_host_' + boundary)
            state = receipts.write_operation(root, task_id, updated, previous=state, kind=kind)
            receipts.boundary('after_host_' + boundary)
            record = value

        if record is None:
            publish(dict(request=request, session=None, response=None), 'request')
        if record['session'] is None:
            session = adapter.transport.lookup(deepcopy(request))
            invalidate_facts()
            if session is None:
                receipts.boundary('before_host_spawn')
                session = adapter.transport.spawn(deepcopy(request))
                invalidate_facts()
                receipts.boundary('after_host_spawn')
            session = _session(request, session)
            if any(other['session'] and other['session']['session_id'] == session['session_id']
                   for other_key, other in records.items() if other_key != key):
                raise CardineError('host exchanged session identities between requests')
            publish(dict(record, session=session), 'session')
        session = _session(request, record['session'])
        if record['response'] is None:
            receipts.boundary('before_host_response')
            response = adapter.transport.poll(deepcopy(session))
            invalidate_facts()
            receipts.boundary('after_host_response')
            if response is not None:
                if (not isinstance(response, dict) or set(response) != {'session', 'result'}
                        or response['session'] != session or not isinstance(response['result'], str)):
                    raise CardineError('host returned a foreign session response')
                publish(dict(record, response=deepcopy(response)), 'response_receipt')
        return deepcopy(record)
