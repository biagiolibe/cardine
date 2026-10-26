"""Receipt-covered file effects for project upgrades and host setup.

Every file replace, backup, directory and link goes through the RE1b external
effect writer. A same-user receipt detects changed inputs and foreign owners
and lets an identical retry finish the exact recorded outputs. It does not
prove authorship, and nothing here installs or changes real host configuration.
"""
from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import uuid

from cardine.lifecycle import receipts
from cardine.shared import atomic
from cardine.shared.errors import CardineError


def pending(path, binding):
    """The unfinished operation recorded at `path`, or None; a foreign owner is refused."""
    if not path.exists():
        return None
    intent = receipts._load_intent(path)
    if intent.get('result') is not None:
        return None
    if intent.get('owner') != binding:
        raise CardineError(
            f"an unfinished {binding['kind']} operation has a different owner or inputs; "
            f"rerun its original command, or inspect and remove {path}")
    return intent


class Operation:
    def __init__(self, path, intent, root=None):
        self.path, self.intent, self.root = path, intent, root
        self.files = intent.setdefault('files', {})
        self.ran = set()
        self.resumed = False

    def _check(self):
        receipts.safe_path(self.path.parent, self.path.name)
        if self.path.exists() and receipts._load_intent(self.path).get('owner') != self.intent['owner']:
            raise CardineError('external operation owner or inputs changed')

    def guard(self, target):
        if self.root is not None:
            relative = Path(target).relative_to(self.root)
            walked = Path(self.root)
            for part in relative.parts:
                walked = walked / part
                if walked.is_symlink():
                    raise CardineError(f"refusing to write through a symlink: {walked}")
        atomic.file_digest(Path(target))

    def _save(self):
        receipts._save_intent(self.path, self.intent)

    def _ensure(self):
        if not self.path.exists():
            self._save()

    def state(self, name):
        """'before' or 'after' for a recorded file; anything else was changed by someone else."""
        record = self.files[name]
        self.guard(Path(record['target']))
        current = atomic.file_digest(Path(record['target']))
        if current == record['after']:
            return 'after'
        if current == record['before']:
            return 'before'
        raise CardineError(f"{record['target']} changed since it was planned; rerun --check")

    def declare(self, name, target, after, *, backup=None, mode=None):
        """Record a file's exact expected output before any effect touches it.

        `after` is bytes, None to remove the file, or a callable that returns
        either; a callable is evaluated only when the output is needed.
        """
        target = Path(target)
        self.guard(target)
        record = self.files.get(name)
        if record is None:
            output = after() if callable(after) else after
            record = dict(kind='file', target=str(target), before=atomic.file_digest(target),
                          after=None if output is None else receipts.digest(output),
                          backup=None if backup is None else str(backup), mode=mode)
            self.files[name] = record
            self._save()
            return
        if record['target'] != str(target):
            raise CardineError(f"recorded target of {name} changed")
        if self.state(name) == 'before':
            output = after() if callable(after) else after
            if (None if output is None else receipts.digest(output)) != record['after']:
                raise CardineError(f"planned output of {name} changed since it was recorded")

    def targets(self, state):
        return {name: record['target'] for name, record in self.files.items()
                if record['kind'] == 'file' and self.state(name) == state}

    def run(self, name, after=None):
        """Backup (when recorded) then replace; repeats only the unobserved part."""
        record = self.files[name]
        target = Path(record['target'])
        self.ran.add(name)

        def verify():
            self._check()
            self.state(name)

        def output():
            value = after() if callable(after) else after
            if (None if value is None else receipts.digest(value)) != record['after']:
                raise CardineError(f"planned output of {name} changed since it was recorded")
            return value

        if record['backup'] is not None and record['before'] not in (None, record['after']):
            backup = Path(record['backup'])

            def backed_up():
                return atomic.file_digest(backup) == record['before']

            def back_up():
                if self.state(name) != 'before':
                    return
                atomic.create_exclusive(backup, target.read_bytes())

            receipts.external_effect(self.path, self.intent, 'backup:' + name, verify, back_up, backed_up)

        def applied():
            return atomic.file_digest(target) == record['after']

        def apply():
            value = output()
            if value is None:
                target.unlink()
            else:
                atomic.replace_bytes(target, value, record['mode'])

        receipts.external_effect(self.path, self.intent, 'file:' + name, verify, apply, applied)

    def replace(self, name, target, after, *, backup=None, mode=None):
        self.declare(name, target, after, backup=backup, mode=mode)
        self.run(name, after)

    def directory(self, name, path, mode):
        path = Path(path)
        self.ran.add('directory:' + name)
        self.intent.setdefault('paths', {})
        if name not in self.intent['paths']:
            self.intent['paths'][name] = dict(kind='directory', target=str(path), mode=mode)
            self._save()
        elif self.intent['paths'][name] != dict(kind='directory', target=str(path), mode=mode):
            raise CardineError(f"recorded directory {name} changed")

        def verify():
            self._check()
            if path.is_symlink() or (path.exists() and not path.is_dir()):
                raise CardineError(f"expected a directory: {path}")

        def apply():
            if not path.exists():
                path.mkdir(parents=True, mode=mode)
            os.chmod(path, mode)

        def complete():
            return path.is_dir() and not path.is_symlink() and (path.stat().st_mode & 0o777) == mode

        receipts.external_effect(self.path, self.intent, 'directory:' + name, verify, apply, complete)

    def symlink(self, name, path, destination):
        path, destination = Path(path), Path(destination)
        self.ran.add('symlink:' + name)
        self.intent.setdefault('paths', {})
        record = dict(kind='symlink', target=str(path), destination=str(destination))
        if name not in self.intent['paths']:
            self.intent['paths'][name] = record
            self._save()
        elif self.intent['paths'][name] != record:
            raise CardineError(f"recorded link {name} changed")

        def complete():
            return path.is_symlink() and os.readlink(path) == str(destination)

        def verify():
            self._check()
            if (path.exists() or path.is_symlink()) and not complete():
                raise CardineError(f"{path} exists and is not the recorded link")

        receipts.external_effect(self.path, self.intent, 'symlink:' + name, verify,
                                 lambda: path.symlink_to(destination), complete)

    def effect(self, name, apply, complete):
        """A directory-level effect with no file record (for example pruning)."""
        self._ensure()
        receipts.external_effect(self.path, self.intent, name, self._check, apply, complete)

    def finish(self):
        """Observe recorded files that this invocation did not need to rewrite."""
        for name in self.files:
            if name not in self.ran:
                if self.state(name) != 'after':
                    raise CardineError(
                        f"recorded change to {self.files[name]['target']} was not replayed; "
                        "rerun the original command")
                self.run(name)
        for name, record in self.intent.get('paths', {}).items():
            if record['kind'] == 'directory':
                self.directory(name, record['target'], record['mode'])
            else:
                self.symlink(name, record['target'], record['destination'])
        self.intent['result'] = dict(done=True)
        self._save()


@contextmanager
def operation(path, binding, *, root=None):
    """Serialize writers, resume an unfinished operation for the same owner, or start one.

    Nothing is written until the first effect is declared, so an apply that
    changes nothing leaves no receipt.
    """
    with receipts.nonrun_lock(path):
        intent = pending(path, binding)
        resumed = intent is not None
        if intent is None:
            intent = dict(version=1, operation_id=uuid.uuid4().hex, owner=binding,
                          files={}, effects={}, result=None)
        op = Operation(path, intent, root)
        op.resumed = resumed
        yield op
        if op.files or op.intent.get('paths') or op.intent['effects']:
            op.finish()
