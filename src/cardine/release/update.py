"""Helpers extracted from the legacy CLI; see the module split plan."""

from __future__ import annotations

from cardine.shared.git import _run_git, scoped_command, invalidate_facts
from cardine.lifecycle import receipts
from cardine.release import update_operation
from cardine.hosts.claude import plugin_alignment_commands
from contextlib import nullcontext

from cardine.release.version import parse_semver
from cardine.release.version import read_raw_version
from cardine.release.version import release_kind_from_body
from cardine.release.version import semver_precedence_key
from cardine.shared.constants import LATEST_RELEASE_RESPONSE_LIMIT
from cardine.shared.constants import LATEST_RELEASE_TIMEOUT_SECONDS
from cardine.shared.constants import LATEST_RELEASE_URL
from cardine.shared.constants import SELF_CHECK_UNKNOWN
from cardine.shared.constants import SELF_CHECK_UPDATE_AVAILABLE
from cardine.shared import terminal
from cardine.shared.errors import CardineError
from cardine.shared.errors import CardineStop
from cardine.shared.git import git_output
from cardine.stops.render import stop_error
from cardine.stops.nonrun import os_stop_code
from pathlib import Path
import json
import os
import re
import shlex
import tempfile


def urlopen(*args, **kwargs):
    """Load the network stack only when a release request is made."""
    from urllib.request import urlopen as open_url

    return open_url(*args, **kwargs)


PLUGIN_UPDATE_COMMAND = " && ".join(
    " ".join(command) for command in plugin_alignment_commands("mismatch", "<version>")
)

def fetch_latest_release(
    installed_version: str,
    *,
    urlopen_fn=None,
    target_tag: str | None = None,
) -> tuple[str, str]:
    """Return a release version and template kind from GitHub's public API."""
    from urllib.request import Request

    request = Request(
        LATEST_RELEASE_URL if target_tag is None else
        LATEST_RELEASE_URL.rsplit("/", 1)[0] + "/tags/" + target_tag,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"cardine/{installed_version}",
        },
    )
    opener = urlopen if urlopen_fn is None else urlopen_fn
    with opener(request, timeout=LATEST_RELEASE_TIMEOUT_SECONDS) as response:
        payload = response.read(LATEST_RELEASE_RESPONSE_LIMIT + 1)
    if len(payload) > LATEST_RELEASE_RESPONSE_LIMIT:
        raise ValueError("response exceeds 1 MiB")
    try:
        document = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("response is not valid UTF-8 JSON") from error
    if not isinstance(document, dict):
        raise ValueError("response root is not an object")
    tag_name = document.get("tag_name")
    body = document.get("body")
    if not isinstance(tag_name, str) or not tag_name.startswith("v"):
        raise ValueError("response has no valid v-prefixed tag_name")
    if not isinstance(body, str):
        raise ValueError("response has no release body")
    latest_version = tag_name[1:]
    parse_semver(latest_version)
    return latest_version, release_kind_from_body(body)


@scoped_command
def run_self_update(framework_root: Path, *, apply: bool = False,
                    target_tag: str | None = None, urlopen_fn=None, finish=None) -> int:
    """Serialize apply and keep recovery metadata outside the tracked checkout."""
    root = framework_root.resolve()
    try:
        # Refusal gates precede even the writer guard creation.
        if any(root.parts[i:i + 2] == ("plugins", "cache") for i in range(len(root.parts) - 1)):
            raise stop_error("SELF_UPDATE_PLUGIN_CACHE", f"plugin manager owns this checkout; use {PLUGIN_UPDATE_COMMAND}",
                             resume=PLUGIN_UPDATE_COMMAND)
        if target_tag is not None and not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", target_tag):
            raise stop_error("SELF_UPDATE_INPUT_INVALID", "--to requires a release tag v<version>")
        if Path(git_output(root, "rev-parse", "--show-toplevel")).resolve() != root:
            raise CardineError("not the framework Git root")
        if git_output(root, "status", "--porcelain", "--untracked-files=all"):
            raise stop_error("SELF_UPDATE_DIRTY", "commit or remove checkout changes before updating")
        path = receipts.nonrun_path(root, 'self-update')
        with receipts.nonrun_lock(path) if apply else nullcontext():
            if apply:
                invalidate_facts()
            return _run_self_update(root, apply=apply, target_tag=target_tag,
                                    urlopen_fn=urlopen_fn, receipt_path=path, finish=finish)
    except CardineStop:
        raise
    except OSError as error:
        raise stop_error(os_stop_code(error, diagnostic=not apply), str(error),
                         resume="cardine self-update --check") from error
    except CardineError as error:
        raise stop_error("SELF_UPDATE_VERIFY", str(error)) from error


def explain_unknown_release(reason: object, manual: str, *, out=print) -> None:
    out(terminal.error(f"Latest: unknown ({reason})"))
    out("Exit 11 means the latest release could not be determined; nothing was changed.")
    out("Manual update: see https://github.com/biagiolibe/cardine/releases, then run:")
    out(terminal.command(manual))


def _explain_unknown(root: Path, error: object, target_tag: str | None) -> None:
    tag = target_tag or "v<version>"
    remote = git_output(root, "remote", "get-url", "origin")
    fetch = shlex.join(["git", "fetch", "--no-tags", "--", remote, f"refs/tags/{tag}:refs/tags/{tag}"])
    explain_unknown_release(error, f"{fetch}; git switch --detach {tag}")


def _run_self_update(framework_root: Path, *, apply: bool = False,
                    target_tag: str | None = None, urlopen_fn=None, receipt_path=None, finish=None) -> int:
    """Plan in an isolated object store; mutate only the CLI checkout on apply."""
    from http.client import HTTPException
    from urllib.error import HTTPError, URLError

    root = framework_root.resolve()

    def refuse(code: str, detail: str, **fields: object) -> None:
        raise stop_error(code, detail, **fields)

    try:
        # Recheck after taking the guard; another writer may have just stopped.
        if git_output(root, "status", "--porcelain", "--untracked-files=all"):
            refuse("SELF_UPDATE_DIRTY", "commit or remove checkout changes before updating")
        branch = git_output(root, "branch", "--show-current")
        if branch not in ("", "stable"):
            refuse("SELF_UPDATE_BRANCH", f"development branch {branch!r}; only stable or a detached release tag is supported")
        if branch == "stable" and target_tag is not None:
            refuse("SELF_UPDATE_BRANCH", "--to does not reset stable; use git switch --detach v<version>, then rerun --to")
        current = read_raw_version(root)
        if not branch and git_output(root, "rev-parse", "HEAD") != git_output(root, "rev-parse", f"refs/tags/v{current}^{{commit}}"):
            refuse("SELF_UPDATE_TARGET", "detached HEAD is not its VERSION release tag")
        print(terminal.section("Plan"))
        print(f"Checkout: {root}")
        print(f"Current: {current}")
        binding = update_operation.owner(root, target_tag)
        intent = update_operation.pending(receipt_path, binding)
        if intent is not None:
            update_operation.verify(root, intent)
            version, templates = intent['version'], intent['templates']
        else:
            try:
                with terminal.spinner("Resolving release"):
                    version, templates = fetch_latest_release(current, urlopen_fn=urlopen_fn, target_tag=target_tag)
            except HTTPError as error:
                if target_tag is not None and error.code == 404:
                    refuse("SELF_UPDATE_TARGET", f"{target_tag} is not a published release")
                _explain_unknown(root, error, target_tag)
                return SELF_CHECK_UNKNOWN
            except (HTTPException, URLError, TimeoutError, OSError, ValueError, CardineError) as error:
                _explain_unknown(root, error, target_tag)
                return SELF_CHECK_UNKNOWN
        tag = f"v{version}"
        if not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag) or (target_tag and tag != target_tag):
            refuse("SELF_UPDATE_TARGET", "release response does not identify the requested release tag")
        release = parse_semver(version)
        kind = "patch" if release.patch else ("minor" if release.minor else "major")
        print(f"Target: {version}")
        print(f"Release kind: {kind}; templates: {templates} (release notes)")
        print(f"Release notes: https://github.com/biagiolibe/cardine/releases/tag/{tag}")
        remote = git_output(root, "remote", "get-url", "origin")
        head = git_output(root, "rev-parse", "HEAD")
        source = dict(head=head, branch=branch, version=current, remote=remote)
        if intent is not None:
            target, source = intent['target'], intent['source']
        else:
            with tempfile.TemporaryDirectory(prefix="cardine-self-update-") as directory:
                probe = Path(directory)
                git_output(probe, "init", "--bare", "--quiet")
                git_output(probe, "fetch", "--quiet", "--no-tags", str(root), head)
                try:
                    git_output(probe, "fetch", "--quiet", "--no-tags", "--", remote,
                               f"refs/tags/{tag}:refs/tags/{tag}",
                               *(["refs/heads/stable:refs/heads/stable"] if branch else []))
                except CardineError as error:
                    refuse("SELF_UPDATE_TARGET", f"cannot resolve release refs: {error}")
                target = git_output(probe, "rev-parse", f"refs/tags/{tag}^{{commit}}")
                if branch:
                    if git_output(probe, "rev-parse", "stable") != target:
                        refuse("SELF_UPDATE_TARGET", "origin/stable is not the target release tag")
                    ancestry = _run_git(str(probe), 'merge-base', '--is-ancestor', head, target, text=False)
                    if ancestry.returncode:
                        refuse("SELF_UPDATE_TARGET", "cause non-fast-forward: stable cannot fast-forward to origin/stable")
                if git_output(probe, "show", f"{target}:VERSION") != version:
                    refuse("SELF_UPDATE_TARGET", "release tag VERSION does not match the release")
        fetch = shlex.join(['git', 'fetch', '--no-tags', '--', remote,
                            f'refs/tags/{tag}:refs/tags/{tag}'])
        operation = (f"{fetch}; git merge --ff-only {target}"
                     if branch else f"{fetch}; git switch --detach {target}")
        print(f"Git operation (in checkout): {operation}")
        if not apply:
            print(terminal.note("Run cardine self-update --apply to update"))
            return 0
        print(terminal.section("Apply"))
        print(terminal.done(terminal.step(1, 4, "Resolve release")))
        with terminal.spinner("Fetching release"):
            intent = update_operation.apply_update(root, receipt_path, binding, source, version,
                                                   templates, target, tag, intent)
        print(terminal.done(terminal.step(2, 4, "Fetch and update checkout")))
        if git_output(root, "rev-parse", "HEAD") != target or read_raw_version(root) != version:
            refuse("SELF_UPDATE_VERIFY", f"post-apply HEAD/VERSION verification failed; recovery: git -C {shlex.quote(str(root))} switch --detach {tag}")
        intent['result'] = dict(head=target, version=version, verified=True)
        receipts._save_intent(receipt_path, intent)
        print(terminal.done(terminal.step(3, 4, "Verify checkout")))
        from cardine.release.installer import finish_update
        (finish or finish_update)(version, templates)
        return 0
    except CardineStop:
        raise
    except OSError as error:
        code = os_stop_code(error, diagnostic=not apply)
        if code == "OS_ACCESS_FAILED":
            refuse(code, f"self-update access failed: {error}; inspect checkout before retrying")
        argv = ["cardine", "self-update", "--check"]
        if target_tag is not None:
            argv.extend(("--to", target_tag))
        raise stop_error(code, str(error), resume=shlex.join(argv)) from error
    except CardineError as error:
        refuse("SELF_UPDATE_VERIFY", f"Git operation failed: {error}; inspect checkout and retry cardine self-update --check")


def claude_plugin_registry_path() -> Path:
    configured = os.environ.get("CLAUDE_CONFIG_DIR")
    return (Path(configured) if configured else Path.home() / ".claude") / "plugins/installed_plugins.json"


def installed_plugin_versions(registry_path: Path) -> tuple[list[str] | None, str]:
    """Read installed Cardine versions without changing the Claude registry."""
    try:
        document = json.loads(registry_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return [], ""
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None, f"plugin registry at {registry_path} is unreadable"
    try:
        entries = document.get("plugins", {}).get("cardine@cardine", [])
        if not isinstance(entries, list):
            raise ValueError("plugin entries must be a list")
        versions = sorted({entry["version"] for entry in entries})
        for version in versions:
            parse_semver(version)
    except (AttributeError, KeyError, TypeError, ValueError, CardineError):
        return None, f"plugin registry at {registry_path} has invalid Cardine entries"
    return versions, ""


def installed_plugin_report(registry_path: Path, latest_version: str | None) -> str:
    """Describe the installed Claude Code plugin without writing files."""
    versions, reason = installed_plugin_versions(registry_path)
    if versions is None:
        return f"Plugin: unknown ({reason})"
    if not versions:
        return "Plugin: not installed"
    label = ", ".join(versions)
    if latest_version is None:
        return f"Plugin: {label} (latest release unknown)"
    latest = semver_precedence_key(parse_semver(latest_version))
    if all(semver_precedence_key(parse_semver(version)) >= latest for version in versions):
        return f"Plugin: {label} (latest release)"
    return (
        f"Plugin: {label} (older than latest release {latest_version}; "
        "run cardine self-update --apply)"
    )


def run_self_check(framework_root: Path, *, urlopen_fn=None, registry_path: Path | None = None) -> int:
    """Print the installed/latest comparison without mutating local state."""
    from http.client import HTTPException
    from urllib.error import HTTPError, URLError

    installed_version = read_raw_version(framework_root)
    installed = parse_semver(installed_version)
    registry = claude_plugin_registry_path() if registry_path is None else registry_path
    print(f"Installed: {installed_version}")
    try:
        latest_version, release_kind = fetch_latest_release(
            installed_version,
            urlopen_fn=urlopen_fn,
        )
        latest = parse_semver(latest_version)
    except HTTPError as error:
        print("Status: UNKNOWN")
        print(f"Reason: GitHub returned HTTP {error.code}")
        print(installed_plugin_report(registry, None))
        return SELF_CHECK_UNKNOWN
    except (HTTPException, URLError, TimeoutError, OSError) as error:
        reason = getattr(error, "reason", error)
        print("Status: UNKNOWN")
        print(f"Reason: network error: {reason}")
        print(installed_plugin_report(registry, None))
        return SELF_CHECK_UNKNOWN
    except (CardineError, ValueError) as error:
        print("Status: UNKNOWN")
        print(f"Reason: malformed response: {error}")
        print(installed_plugin_report(registry, None))
        return SELF_CHECK_UNKNOWN

    print(f"Latest: {latest_version}")
    print(f"Kind: {release_kind}")
    print(installed_plugin_report(registry, latest_version))
    if semver_precedence_key(latest) > semver_precedence_key(installed):
        print("Status: UPDATE_AVAILABLE")
        return SELF_CHECK_UPDATE_AVAILABLE
    print("Status: UP_TO_DATE")
    return 0
