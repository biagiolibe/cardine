"""Build and exercise Cardine in an isolated wheel installation."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parent.parent

RUNTIME_PROBE = """
from pathlib import Path
import sys

import cardine
from cardine.lifecycle import receipts

source = Path(sys.argv[1])
assert all(not Path(entry).resolve().is_relative_to(source) for entry in sys.path), sys.path
package = Path(cardine.__file__).resolve().parent
assert package.is_relative_to(Path(sys.prefix).resolve()), package
runtime, before = receipts._runtime_identity()
assert runtime == package, runtime
assert before != receipts.digest(receipts.encoded({})), before
with (package / '__main__.py').open('a', encoding='utf-8') as handle:
    handle.write('\\n# Installed runtime digest probe.\\n')
receipts._runtime_identity.cache_clear()
assert receipts.runtime_digest_once() != before
"""


def run(step, command, *, cwd, env):
    try:
        result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True)
    except OSError as error:
        raise RuntimeError(f"{step}: {error}") from error
    if result.returncode:
        raise RuntimeError(f"{step} (exit {result.returncode})\n{result.stdout}{result.stderr}")
    return result.stdout.strip()


def verify_wheel(wheel):
    prefix = "cardine/_framework/"
    with ZipFile(wheel) as archive:
        names = archive.namelist()
    if prefix + "VERSION" not in names:
        raise RuntimeError("wheel contents: missing VERSION")
    for asset in ("capabilities", "schemas", "migrations", "templates/single", "skills"):
        if not any(name.startswith(f"{prefix}{asset}/") and not name.endswith("/") for name in names):
            raise RuntimeError(f"wheel contents: missing {asset}/")


def check(scratch):
    home = scratch / "home"
    home.mkdir()
    env = dict(os.environ, HOME=str(home), XDG_CONFIG_HOME=str(home / ".config"),
               CARDINE_WORKTREE_ROOT=str(scratch / "worktrees"), PYTHONNOUSERSITE="1")
    for key in ("CARDINE_ROOT", "PYTHONPATH", "PYTHONHOME"):
        env.pop(key, None)

    run("build wheel", [sys.executable, "-m", "pip", "wheel", "--no-deps",
                        "--wheel-dir", str(scratch), str(ROOT)], cwd=scratch, env=env)
    wheels = list(scratch.glob("cardine-*.whl"))
    if len(wheels) != 1:
        raise RuntimeError(f"build wheel: expected one Cardine wheel, found {len(wheels)}")
    wheel, = wheels
    verify_wheel(wheel)
    virtualenv = scratch / "venv"
    run("create virtual environment", [sys.executable, "-m", "venv", str(virtualenv)],
        cwd=scratch, env=env)
    python = virtualenv / "bin/python"
    cardine = virtualenv / "bin/cardine"
    run("install wheel", [python, "-m", "pip", "install", "--no-index", "--no-deps", wheel],
        cwd=scratch, env=env)

    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    for command in ([cardine], [python, "-m", "cardine"]):
        step = "cardine --version" if command[0] == cardine else "python -m cardine --version"
        observed = run(step, [*command, "--version"], cwd=scratch, env=env)
        if observed != version:
            raise RuntimeError(f"{step}: expected {version!r}, got {observed!r}")

    project = scratch / "project"
    project.mkdir()
    run("initialize Git repository", ["git", "init", "-q", "-b", "main"], cwd=project, env=env)
    run("commit Git repository", ["git", "-c", "user.name=Cardine Test", "-c",
                                 "user.email=cardine@example.invalid", "commit",
                                 "--allow-empty", "-qm", "Initial commit"], cwd=project, env=env)

    validation = scratch / "validation.json"
    validation.write_text(json.dumps({"commands": {"tests": "true"}, "baseline": ["tests"],
                                      "candidate": {"BOUNDED": [], "FULL": [], "REUSE": []}}),
                          encoding="utf-8")
    options = ["--project", ".", "--name", "Installed Cardine Test", "--slug", "installed-cardine-test",
               "--preset", "lean", "--language", "English", "--task-identity", "opaque",
               "--validation", validation]
    run("cardine init --check", [cardine, "init", "--check", *options], cwd=project, env=env)
    copy = scratch / "project-copy"
    shutil.copytree(project, copy)
    run("cardine adopt --rehearse", [cardine, "adopt", "--rehearse", *options], cwd=copy, env=env)
    run("installed runtime digest", [python, "-c", RUNTIME_PROBE, ROOT], cwd=scratch, env=env)


def main():
    try:
        with tempfile.TemporaryDirectory(prefix="cardine-wheel-") as temporary:
            check(Path(temporary))
    except (OSError, RuntimeError) as error:
        print(f"Installed package check failed: {error}", file=sys.stderr)
        return 1
    print("Installed package check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
