"""Self-update for pipx and uv installs, plus the post-update reports shared with clones."""

from __future__ import annotations

import re
import shlex
import subprocess
from pathlib import Path

from cardine.shared.errors import CardineError
from cardine.shared import terminal

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


class ReleaseUnresolved(CardineError):
    """The latest release could not be resolved; the explanation was already printed."""


def run_installer_update(kind: str, installed: str, *, apply: bool, target_tag: str | None = None,
                         urlopen_fn=None, runner=None, out=print, finish=None) -> str | None:
    """Plan or apply a pipx/uv reinstall; returns the target version after apply, else None.

    A preview resolves the target and prints the command without running anything. A failed
    resolution or reinstall raises before any plugin alignment, so a retry starts clean."""
    from cardine.release.update import explain_unknown_release, fetch_latest_release
    if target_tag is not None and not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", target_tag):
        raise CardineError("--to requires a release tag v<version>")
    try:
        with terminal.spinner("Resolving release"):
            version, templates = fetch_latest_release(installed, urlopen_fn=urlopen_fn, target_tag=target_tag)
    except (OSError, ValueError, CardineError) as error:
        tag_hint = target_tag or "v<version>"
        spec = f"{REPOSITORY_URL}@{tag_hint}"
        manual = shlex.join(["pipx", "install", "--force", spec] if kind == "pipx"
                            else ["uv", "tool", "install", "--force", spec])
        explain_unknown_release(error, manual, out=out)
        raise ReleaseUnresolved(f"cannot resolve the release: {error}") from error
    tag = f"v{version}"
    if target_tag is not None and tag != target_tag:
        raise CardineError("release response does not identify the requested release tag")
    command = reinstall_command(kind, tag)
    out(terminal.section("Plan"))
    out(f"Installer: {kind}")
    out(f"Current: {installed}")
    out(f"Target: {version}")
    out(f"Release kind: {templates}")
    out(f"Release notes: https://github.com/biagiolibe/cardine/releases/tag/{tag}")
    out(f"Reinstall: {shlex.join(command)}")
    if not apply:
        out(terminal.note("Run cardine self-update --apply to update"))
        return None
    out(terminal.section("Apply"))
    out(terminal.done(terminal.step(1, 4, "Resolve release")))
    with terminal.spinner("Reinstalling"):
        result = (runner or (lambda argv: subprocess.run(argv, check=False, capture_output=True, text=True)))(command)
    code = result if isinstance(result, int) else result.returncode
    if code:
        if not isinstance(result, int):
            for output in (result.stdout, result.stderr):
                if output:
                    out(output.rstrip())
        out(terminal.failed(terminal.step(2, 4, "Reinstall")))
        raise CardineError(f"{shlex.join(command)} failed with exit {code}; rerun cardine self-update --apply")
    out(terminal.done(terminal.step(2, 4, "Reinstall")))
    out(terminal.done(terminal.step(3, 4, "Verify installer result")))
    (finish or finish_update)(version, templates, out=out)
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


def finish_update(version, templates, *, project=None, align=None, out=print):
    """Align the plugin and present the project follow-up checklist."""
    if align is None:
        out(terminal.skipped(terminal.step(4, 4, "Align Claude Code plugin")))
    else:
        align(version, out=lambda line: out(terminal.note(line)))
        out(terminal.done(terminal.step(4, 4, "Align Claude Code plugin")))
    out(terminal.section("Next steps"))
    out("1. Restart running Claude Code and Codex sessions.")
    out("2. In each project that uses Cardine:")
    out(terminal.command("   cardine authorize --check --project <checkout>"))
    out(terminal.command("   cardine authorize --apply --project <checkout>"))
    if project is not None:
        stale = stale_runtime_report(project, out=lambda line: None)
        out(terminal.note(f"{Path(project).resolve()}: " + ("accepted runtime was replaced" if stale else "no accepted runtime found")))
    number = 3
    if templates == "template-changing":
        out("3. In each project, review and commit the managed files after:")
        out(terminal.command("   cardine upgrade --check --project <checkout>"))
        out(terminal.command("   cardine upgrade --apply --project <checkout>"))
        number = 4
    out(f"{number}. Confirm each project:")
    out(terminal.command("   cardine doctor --project <checkout>"))
