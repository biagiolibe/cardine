"""Concrete Claude and Codex host transports for issued role sessions.

A transport implements `launch.HostTransport` over a durable directory that the
host owner controls. It never decides that a profile is enforced: `enforced`
comes only from a complete host-evaluated proof injected by the caller (D3);
without one the launch adapter refuses the role. Credentials are opaque tokens
that the transport issues and stores only as digests, bound to a request.
Receipts detect changed data; they do not authenticate an OS user.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys

from cardine.hosts.claude import claude_role_profile
from cardine.hosts.codex import codex_role_profiles
from cardine.shared.errors import CardineError

# Runs once per request inside its own process: the exclusive `started` marker
# guarantees that a replayed spawn never runs the host twice, and `result.json`
# appears only after the host process has stopped.
_WRAPPER = '''
import json, os, subprocess, sys
directory = sys.argv[1]
try:
    marker = os.open(os.path.join(directory, "started"), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
except FileExistsError:
    sys.exit(0)
os.close(marker)
with open(os.path.join(directory, "launch.json"), "rb") as stream:
    launch = json.load(stream)
with open(os.path.join(directory, "session.json"), "rb") as stream:
    session = json.load(stream)
environment = dict(launch["env"], CARDINE_HOST_CREDENTIAL=launch["credential"])
try:
    with open(os.path.join(directory, "host.log"), "wb") as log:
        code = subprocess.run(launch["argv"], cwd=launch["cwd"], env=environment,
                              stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT).returncode
except OSError:
    code = 127
result = os.path.join(directory, "result.json")
with open(result + ".tmp", "w") as stream:
    json.dump({"session": session, "result": "completed" if code == 0 else "failed"}, stream)
    stream.flush()
    os.fsync(stream.fileno())
os.replace(result + ".tmp", result)
'''

_SESSION_KEYS = ('request_id', 'role', 'profile', 'host')
_ROLE_ACTIONS = {'implementer': ('implementation',), 'reviewer': ('verdict',)}


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _write_atomic(path: Path, value, *, exclusive: bool = False) -> None:
    """Durable JSON write; an exclusive write fails if another writer got there first."""
    data = json.dumps(value, sort_keys=True).encode()
    if exclusive:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        return
    temporary = path.with_name(path.name + '.tmp')
    with open(temporary, 'wb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _read(path: Path):
    try:
        return json.loads(path.read_bytes())
    except FileNotFoundError:
        return None


class HostSessionTransport:
    """Shared durable session, credential and process protocol; hosts supply argv."""
    host = ''

    def __init__(self, directory, executable, *, policies, proofs=None, environment=None):
        self.directory = Path(directory)
        self.executable = str(executable)
        self.policies = dict(policies)
        self.proofs = dict(proofs or {})
        self.environment = dict(environment or {})
        self.directory.mkdir(parents=True, exist_ok=True)
        self.credentials = self.directory / 'credentials.json'

    # -- profiles ----------------------------------------------------------
    def profile(self, role):
        raise NotImplementedError

    # -- credentials -------------------------------------------------------
    def _entries(self) -> dict:
        return _read(self.credentials) or {}

    def issue(self, actions, binding=None) -> str:
        """Issue an opaque credential for exactly these actions, optionally bound to one session."""
        token = secrets.token_hex(24)
        entries = self._entries()
        entries[_digest(token)] = dict(actions=sorted(actions), binding=binding)
        _write_atomic(self.credentials, entries)
        return token

    def _entry(self, credential):
        if not isinstance(credential, str) or not credential:
            return None
        return self._entries().get(_digest(credential))

    def authorize(self, credential, action):
        entry = self._entry(credential)
        return bool(entry) and action in entry['actions']

    def authorize_operation(self, credential, action, binding, session):
        """Allow `action` only for the exact session the credential was issued to."""
        entry = self._entry(credential)
        if not entry or action not in entry['actions']:
            return None
        bound = entry['binding']
        if bound is None:
            return None if session else dict(host=self.host, profile='coordinator',
                                             session_id=None, role='coordinator')
        if (not session or any(session.get(key) != bound.get(key) for key in (*_SESSION_KEYS, 'session_id'))
                or (binding or {}).get('request_id', bound['request_id']) != bound['request_id']):
            return None
        return {key: session[key] for key in ('host', 'profile', 'session_id', 'role')}

    # -- sessions ----------------------------------------------------------
    def _path(self, request) -> Path:
        name = request['request_id']
        if not isinstance(name, str) or not name or name != Path(name).name:
            raise CardineError('host request identity is not a plain name')
        return self.directory / name

    def lookup(self, request):
        path = self._path(request)
        saved = _read(path / 'request.json')
        if saved is None:
            return None
        if saved != request:
            raise CardineError('foreign host request')
        # A killed spawn may have recorded the request without its session:
        # report none and let spawn complete the same directory.
        return _read(path / 'session.json')

    def argv(self, request, path: Path) -> list[str]:
        raise NotImplementedError

    def prompt(self, request) -> str:
        work = request['work']
        return (f"Cardine {request['role']} session for task {request['task_id']}. "
                f"Contract digest {request['contract']}. Work only within {work['worktree']}.")

    def spawn(self, request):
        """Create or return the single session of this request, then start its process at most once."""
        path = self._path(request)
        try:
            path.mkdir(mode=0o700)
        except FileExistsError:
            pass
        try:
            _write_atomic(path / 'request.json', request, exclusive=True)
        except FileExistsError:
            if _read(path / 'request.json') != request:
                raise CardineError('foreign host request')
        session = {key: request[key] for key in _SESSION_KEYS}
        session['session_id'] = self.host + ':' + request['request_id']
        if _read(path / 'session.json') is None:
            _write_atomic(path / 'session.json', session)
        session = _read(path / 'session.json')
        if not (path / 'started').exists() and not (path / 'launch.json').exists():
            credential = self.issue(_ROLE_ACTIONS[request['role']], binding=session)
            _write_atomic(path / 'launch.json', dict(argv=self.argv(request, path), cwd=request['root'],
                          env={**os.environ, **self.environment}, credential=credential), exclusive=True)
        if not (path / 'started').exists():
            subprocess.Popen([sys.executable, '-c', _WRAPPER, str(path)], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        return session

    def poll(self, session):
        """The retained terminal response, only after the host process stopped; reading writes nothing."""
        path = self.directory / session['request_id']
        result = _read(path / 'result.json')
        return result if result and result['session'] == session else None


class ClaudeTransport(HostSessionTransport):
    host = 'claude'

    def profile(self, role):
        policy = self.policies.get(role)
        return claude_role_profile(policy, self.proofs.get(role)) if policy else None

    def argv(self, request, path):
        settings = path / 'settings.json'
        _write_atomic(settings, self.policies[request['role']].settings)
        return [self.executable, '-p', self.prompt(request), '--settings', str(settings)]


class CodexTransport(HostSessionTransport):
    host = 'codex'

    def __init__(self, directory, executable, *, policies, proofs=None, plan, environment=None):
        super().__init__(directory, executable, policies=policies, proofs=proofs, environment=environment)
        self.plan = plan

    def profile(self, role):
        if role not in self.policies:
            return None
        return codex_role_profiles(self.plan, self.policies, self.proofs).get(role)

    def argv(self, request, path):
        return [self.executable, 'exec', '--profile', self.policies[request['role']].identity,
                self.prompt(request)]
