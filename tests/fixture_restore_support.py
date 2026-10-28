"""Build a run engine fixture once per process and restore it in place per case.

A prepared state cannot move: worktrees register absolute paths and receipts
bind the root's identity. The fixture therefore lives at one stable path owned
by this process, a copy is kept beside it, and every case removes the live
directory and copies the saved tree back into the same absolute path.
"""
import atexit
import hashlib
import os
from pathlib import Path
import shutil
import tempfile


class RestorableFixture:
    """One base fixture: built on first use, restored byte for byte after that."""

    def __init__(self, label, build):
        self.label = label
        self._build = build
        self.base = None
        self.record = None
        self.digest = None

    @property
    def live(self):
        return self.base / 'live'

    @property
    def copy(self):
        return self.base / 'copy'

    def restore(self):
        """Return the live directory and the build record of a pristine fixture."""
        if self.base is None:
            self._create()
        else:
            shutil.rmtree(self.live)
            self._copy(self.copy, self.live)
        return self.live, dict(self.record)

    def _create(self):
        self.base = Path(tempfile.mkdtemp(prefix=f'cardine-{self.label}-')).resolve()
        atexit.register(shutil.rmtree, self.base, ignore_errors=True)
        self.live.mkdir()
        self.record = self._build(self.live)
        self.digest = tree_digest(self.live)
        self._copy(self.live, self.copy)

    @staticmethod
    def _copy(source, target):
        shutil.copytree(source, target, symlinks=True)


def tree_digest(directory):
    """Digest of every path, mode, link target and file byte below a directory."""
    digest = hashlib.sha256()
    for current, directories, files in os.walk(directory):
        directories.sort()
        for name in sorted(directories + files):
            path = Path(current) / name
            relative = path.relative_to(directory).as_posix()
            mode = path.lstat().st_mode
            if path.is_symlink():
                content = os.readlink(path).encode()
            elif path.is_file():
                content = path.read_bytes()
            else:
                content = b''
            digest.update(f'{relative}\0{mode:o}\0{len(content)}\0'.encode() + content)
    return digest.hexdigest()
