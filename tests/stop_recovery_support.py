"""Execute emitted recovery commands against this checkout's CLI without rewriting them."""

from pathlib import Path
import os
import shlex
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def run_recovery(command: str, cwd: Path, worktree_root: Path | None = None) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory() as directory:
        launcher = Path(directory) / "meridian"
        launcher.write_text(
            f"#!{sys.executable}\nimport os, sys\n"
            f"os.execv({sys.executable!r}, [{sys.executable!r}, {str(ROOT / 'scripts/cardine_cli.py')!r}, *sys.argv[1:]])\n",
            encoding="utf-8",
        )
        launcher.chmod(0o755)
        environment = {**os.environ, "PATH": directory + os.pathsep + os.environ["PATH"]}
        if worktree_root is not None:
            environment["MERIDIAN_WORKTREE_ROOT"] = str(worktree_root)
        return subprocess.run(shlex.split(command), cwd=cwd, env=environment, text=True, capture_output=True)


def resume_from(stderr: str) -> str:
    return next(line.split("; resume: ", 1)[1] for line in stderr.splitlines() if line.startswith("BLOCKED "))
