"""Helpers extracted from the legacy CLI; see the module split plan."""

from __future__ import annotations

from cardine.release.version import parse_semver
from cardine.release.version import read_raw_version
from cardine.release.version import release_kind_from_body
from cardine.release.version import semver_precedence_key
from cardine.shared.constants import LATEST_RELEASE_RESPONSE_LIMIT
from cardine.shared.constants import LATEST_RELEASE_TIMEOUT_SECONDS
from cardine.shared.constants import LATEST_RELEASE_URL
from cardine.shared.constants import SELF_CHECK_UNKNOWN
from cardine.shared.constants import SELF_CHECK_UPDATE_AVAILABLE
from cardine.shared.errors import CardineError
from cardine.shared.errors import CardineStop
from cardine.shared.git import git_output
from cardine.stops.render import stop_error
from cardine.stops.nonrun import os_stop_code
from http.client import HTTPException
from pathlib import Path
from urllib.error import HTTPError
from urllib.error import URLError
from urllib.request import Request
from urllib.request import urlopen
import json
import os
import re
import shlex
import subprocess
import tempfile

def fetch_latest_release(
    installed_version: str,
    *,
    urlopen_fn=None,
    target_tag: str | None = None,
) -> tuple[str, str]:
    """Return a release version and template kind from GitHub's public API."""
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


def run_self_update(framework_root: Path, *, apply: bool = False,
                    target_tag: str | None = None, urlopen_fn=None) -> int:
    """Plan in an isolated object store; mutate only the CLI checkout on apply."""
    root = framework_root.resolve()

    def refuse(code: str, detail: str) -> None:
        raise stop_error(code, detail)

    if any(root.parts[index:index + 2] == ("plugins", "cache")
           for index in range(len(root.parts) - 1)):
        refuse("SELF_UPDATE_PLUGIN_CACHE", "plugin manager owns this checkout; use /plugin marketplace update meridian")
    if target_tag is not None and not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", target_tag):
        refuse("SELF_UPDATE_INPUT_INVALID", "--to requires a release tag v<version>")
    try:
        if Path(git_output(root, "rev-parse", "--show-toplevel")).resolve() != root:
            raise CardineError("not the framework Git root")
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
        print(f"Checkout: {root}")
        print(f"Current: {current}")
        try:
            version, templates = fetch_latest_release(current, urlopen_fn=urlopen_fn, target_tag=target_tag)
        except HTTPError as error:
            if target_tag is not None and error.code == 404:
                refuse("SELF_UPDATE_TARGET", f"{target_tag} is not a published release")
            print(f"Latest: unknown ({error})")
            return SELF_CHECK_UNKNOWN
        except (HTTPException, URLError, TimeoutError, OSError, ValueError, CardineError) as error:
            print(f"Latest: unknown ({error})")
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
                ancestry = subprocess.run(["git", "-C", str(probe), "merge-base", "--is-ancestor", head, target], capture_output=True)
                if ancestry.returncode:
                    refuse("SELF_UPDATE_TARGET", "cause non-fast-forward: stable cannot fast-forward to origin/stable")
            if git_output(probe, "show", f"{target}:VERSION") != version:
                refuse("SELF_UPDATE_TARGET", "release tag VERSION does not match the release")
            operation = (f"git fetch --tags origin; git merge --ff-only {target}"
                         if branch else f"git fetch --tags origin; git switch --detach {tag}")
            print(f"Git operation (in checkout): {operation}")
            if not apply:
                return 0
            # Fetch only after all refusal gates passed. Pin the operation to the
            # inspected commit so a concurrent remote update cannot widen it.
            git_output(root, "fetch", "--tags", "origin")
            if git_output(root, "rev-parse", f"refs/tags/{tag}^{{commit}}") != target or (branch and git_output(root, "rev-parse", "origin/stable") != target):
                refuse("SELF_UPDATE_VERIFY", "remote changed during apply; inspect checkout before retrying")
            if branch:
                git_output(root, "merge", "--ff-only", target)
            else:
                git_output(root, "switch", "--detach", tag)
        if git_output(root, "rev-parse", "HEAD") != target or read_raw_version(root) != version:
            refuse("SELF_UPDATE_VERIFY", f"post-apply HEAD/VERSION verification failed; recovery: git -C {shlex.quote(str(root))} switch --detach {tag}")
        print(f"Updated to {tag}. Restart running Codex and Claude Code sessions.")
        if templates == "template-changing":
            print("Run cardine upgrade --check in each project.")
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


def claude_user_settings_path() -> Path:
    configured = os.environ.get("CLAUDE_CONFIG_DIR")
    return (Path(configured) if configured else Path.home() / ".claude") / "settings.json"


def plugin_marketplace_ref(settings_path: Path) -> tuple[str | None, str]:
    """Read extraKnownMarketplaces.meridian.source.ref; return (ref, reason when unknown)."""
    try:
        document = json.loads(settings_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, f"no user settings at {settings_path}"
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None, f"user settings at {settings_path} are unreadable"
    marketplaces = document.get("extraKnownMarketplaces") if isinstance(document, dict) else None
    entry = marketplaces.get("meridian") if isinstance(marketplaces, dict) else None
    source = entry.get("source") if isinstance(entry, dict) else None
    ref = source.get("ref") if isinstance(source, dict) else None
    if not isinstance(ref, str) or not ref:
        return None, "no extraKnownMarketplaces.meridian.source.ref declared"
    return ref, ""


def plugin_ref_report(settings_path: Path, latest_version: str | None) -> str:
    """Describe the Claude Code marketplace ref without writing settings."""
    ref, reason = plugin_marketplace_ref(settings_path)
    if ref is None:
        return f"Plugin ref: unknown ({reason})"
    if ref == "stable":
        return "Plugin ref: stable"
    try:
        pinned = parse_semver(ref[1:]) if ref.startswith("v") else None
    except CardineError:
        pinned = None
    if pinned is None:
        return f"Plugin ref: {ref} (neither stable nor a release tag)"
    if latest_version is None:
        return f"Plugin ref: {ref} (latest release unknown)"
    if semver_precedence_key(pinned) >= semver_precedence_key(parse_semver(latest_version)):
        return f"Plugin ref: {ref} (latest release)"
    return (
        f"Plugin ref: {ref} (older than latest release {latest_version}; "
        f'set "ref" to "stable" or "v{latest_version}" in extraKnownMarketplaces.meridian.source)'
    )


def run_self_check(framework_root: Path, *, urlopen_fn=None, settings_path: Path | None = None) -> int:
    """Print the installed/latest comparison without mutating local state."""
    installed_version = read_raw_version(framework_root)
    installed = parse_semver(installed_version)
    settings = claude_user_settings_path() if settings_path is None else settings_path
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
        print(plugin_ref_report(settings, None))
        return SELF_CHECK_UNKNOWN
    except (HTTPException, URLError, TimeoutError, OSError) as error:
        reason = getattr(error, "reason", error)
        print("Status: UNKNOWN")
        print(f"Reason: network error: {reason}")
        print(plugin_ref_report(settings, None))
        return SELF_CHECK_UNKNOWN
    except (CardineError, ValueError) as error:
        print("Status: UNKNOWN")
        print(f"Reason: malformed response: {error}")
        print(plugin_ref_report(settings, None))
        return SELF_CHECK_UNKNOWN

    print(f"Latest: {latest_version}")
    print(f"Kind: {release_kind}")
    print(plugin_ref_report(settings, latest_version))
    if semver_precedence_key(latest) > semver_precedence_key(installed):
        print("Status: UPDATE_AVAILABLE")
        return SELF_CHECK_UPDATE_AVAILABLE
    print("Status: UP_TO_DATE")
    return 0
