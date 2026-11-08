"""Live output of the commands `cardine run` executes, for the developer's console.

The engine appends what its commands print, as it arrives, to a log beside its
operation intents, and records the command it is running in a small status
file. Neither is evidence: the ledger, the intents and the receipts stay the
record, and an agent never reads either file. A failure to write them never
changes a run; the live view simply stops.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import threading
import time

from cardine.lifecycle import receipts

LIVE_LOG_LIMIT = 8 * 1024 * 1024


def live_paths(common_dir, task_id):
    """The log and the status file of one task, under the shared Git directory."""
    log = receipts.safe_path(Path(common_dir).resolve(), f'cardine-operations/{task_id}.live.log')
    return log, log.with_name(f'{task_id}.live.json')


def _stamp():
    return datetime.now(timezone.utc).astimezone().strftime('%H:%M:%S')


class LiveLog:
    """Append-only view of one task's runs; every write failure disables it."""

    def __init__(self, common_dir, task_id):
        self.task_id = task_id
        self._lock = threading.Lock()
        try:
            self.log, self.status = live_paths(common_dir, task_id)
            self._enabled = True
        except Exception:  # A path Cardine refuses only disables the view.
            self.log = self.status = None
            self._enabled = False

    def _append(self, data: bytes):
        if not self._enabled:
            return
        try:
            with self._lock:
                self.log.parent.mkdir(parents=True, exist_ok=True)
                if self.log.exists() and self.log.stat().st_size + len(data) > LIVE_LOG_LIMIT:
                    os.replace(self.log, self.log.with_name(self.log.name + '.1'))
                with self.log.open('ab') as handle:
                    handle.write(data)
        except OSError:
            self._enabled = False

    def note(self, text: str):
        """One line written by Cardine itself, as opposed to a command's output."""
        self._append(f'{_stamp()} cardine: {text}\n'.encode())

    def _write_status(self, value):
        if not self._enabled:
            return
        try:
            temporary = self.status.with_name(self.status.name + '.tmp')
            temporary.write_text(json.dumps(value, sort_keys=True) + '\n')
            os.replace(temporary, self.status)
        except OSError:
            self._enabled = False

    @contextmanager
    def command(self, command: str, *, kind: str, key: str | None = None, round_number: int | None = None):
        """Frame one command: a start line, its raw output, and an exit line."""
        label = ' · '.join(str(item) for item in (kind, f'round {round_number}' if round_number else None, key)
                           if item)
        started = time.monotonic()
        self.note(f'{label}: {command}')
        status = dict(task=self.task_id, kind=kind, id=key, round=round_number, command=command,
                      startedAt=datetime.now(timezone.utc).isoformat(timespec='seconds'), pid=None,
                      exitStatus=None, finishedAt=None)
        self._write_status(status)
        frame = _Frame(self, status)
        try:
            yield frame
        finally:
            elapsed = time.monotonic() - started
            exit_status = frame.exit_status
            self.note(f'{label}: ' + (f'exit {exit_status}' if exit_status is not None else 'interrupted')
                      + f' after {elapsed:.0f}s')
            self._write_status(dict(frame._status, exitStatus=exit_status,
                                    finishedAt=datetime.now(timezone.utc).isoformat(timespec='seconds')))


class _Frame:
    def __init__(self, live, status):
        self._live, self._status, self.exit_status = live, status, None

    def started(self, pid: int):
        self._status = dict(self._status, pid=pid)
        self._live._write_status(self._status)

    def output(self, chunk: bytes):
        self._live._append(chunk)

    def finished(self, exit_status: int):
        self.exit_status = exit_status

