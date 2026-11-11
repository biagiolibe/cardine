"""Self-update for pipx and uv installs, plus the post-update reports shared with clones."""

from __future__ import annotations

import re
import shlex
import subprocess
from pathlib import Path

from cardine.shared.errors import CardineError

REPOSITORY_URL = "git+https://github.com/biagiolibe/cardine"


def detect_installer(package_root: Path | None = None, checkout: Path | None = None) -> str:
    """`clone`, `pipx`, `uv` or `unknown`, judged from the executing installation only."""
    if package_root is None:
        from cardine.shared.paths import PACKAGE_ROOT, source_checkout
        package_root, checkout = PACKAGE_ROOT, source_checkout()
    if checkout is not None and (checkout / ".git").exists():
        return "clone"
    parts = Path(package_root).resolve().parts
    if any(parts[i:i + 2] == ("pipx", "venvs") for i in range(len(parts) - 1)):
        return "pipx"
    if any(parts[i:i + 2] == ("uv", "tools") for i in range(len(parts) - 1)):
        return "uv"
    return "unknown"


def reinstall_command(kind: str, tag: str) -> list[str]:
    if not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag):
        raise CardineError("--to requires a release tag v<version>")
    spec = f"{REPOSITORY_URL}@{tag}"
    if kind == "pipx":
        return ["pipx", "install", "--force", spec]
    if kind == "uv":
        return ["uv", "tool", "install", "--force", spec]
    raise CardineError(f"cannot reinstall an installation owned by {kind!r}")


def run_installer_update(kind: str, installed: str, *, apply: bool, target_tag: str | None = None,
                         urlopen_fn=None, runner=None, out=print) -> str | None:
    """Plan or apply a pipx/uv reinstall; returns the target version after apply, else None.

    A preview resolves the target and prints the command without running anything. A failed
    resolution or reinstall raises before any plugin alignment, so a retry starts clean."""
    from cardine.release.update import fetch_latest_release
    if target_tag is not None and not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", target_tag):
        raise CardineError("--to requires a release tag v<version>")
    try:
        version, _templates = fetch_latest_release(installed, urlopen_fn=urlopen_fn, target_tag=target_tag)
    except (OSError, ValueError, CardineError) as error:
        raise CardineError(f"cannot resolve the release: {error}") from error
    tag = f"v{version}"
    if target_tag is not None and tag != target_tag:
        raise CardineError("release response does not identify the requested release tag")
    command = reinstall_command(kind, tag)
    out(f"Installer: {kind}")
    out(f"Current: {installed}")
    out(f"Target: {version}")
    out(f"Reinstall: {shlex.join(command)}")
    if not apply:
        return None
    code = (runner or (lambda argv: subprocess.run(argv, check=False).returncode))(command)
    if code:
        raise CardineError(f"{shlex.join(command)} failed with exit {code}; rerun cardine self-update --apply")
    out(f"Updated to {tag}. Restart running Codex and Claude Code sessions.")
    return version


def stale_runtime_report(project: Path | None, *, out=print) -> bool:
    """Name the selected checkout when it holds an accepted runtime the update has replaced.

    Read only: the command is printed for the developer and never executed here."""
    if project is None:
        return False
    try:
        from cardine.lifecycle import receipts
        root = Path(project).resolve()
        accepted = receipts._local_authority_path(root).is_file()
    except (OSError, CardineError):
        return False
    if not accepted:
        return False
    out(f"Stale accepted runtime: {root}")
    out(f"Run: cardine authorize --apply --project {shlex.quote(str(root))}")
    return True
