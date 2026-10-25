"""Execute emitted recovery commands against this checkout's CLI without rewriting them."""

from pathlib import Path
import os
import shlex
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def run_recovery(command: str, cwd: Path, worktree_root: Path | None = None, *, control_host: bool = False) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory() as directory:
        launcher = Path(directory) / "cardine"
        if control_host:
            # An explicit disposable host channel, never an environment role flag.
            source = (f"#!{sys.executable}\nimport sys\n"
                f"sys.path[:0] = {[str(ROOT/'src'), str(ROOT/'tests')]!r}\n"
                "from unittest.mock import patch\nfrom control_support import adapter\n"
                "from cardine.cli import main\n"
                "with patch('cardine.lifecycle.control.host_adapter', return_value=adapter('coordinator')):\n"
                "    raise SystemExit(main())\n")
        else:
            source = (f"#!{sys.executable}\nimport os, sys\n"
                f"os.execv({sys.executable!r}, [{sys.executable!r}, {str(ROOT / 'scripts/cardine_cli.py')!r}, *sys.argv[1:]])\n")
        launcher.write_text(source, encoding='utf-8')
        launcher.chmod(0o755)
        environment = {**os.environ, "PATH": directory + os.pathsep + os.environ["PATH"]}
        if worktree_root is not None:
            environment["CARDINE_WORKTREE_ROOT"] = str(worktree_root)
        return subprocess.run(shlex.split(command), cwd=cwd, env=environment, text=True, capture_output=True)


def resume_from(stderr: str) -> str:
    return next(line.split("; resume: ", 1)[1] for line in stderr.splitlines() if line.startswith(("BLOCKED ", "NEXT ", "ITERATE ")))
