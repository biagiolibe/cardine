#!/usr/bin/env python3
"""Prepare one local Meridian release without contacting the network."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION = re.compile(r"\d+\.\d+\.\d+\Z")
CLI_ONLY = "CLI-only release"
TEMPLATE_CHANGING = "Template-changing release"
CHANGELOG_HEADINGS = (
    "Added", "Changed", "Deprecated", "Removed", "Fixed", "Security",
    "Documentation", "Upgrade notes",
)
WORKFLOW_POLL_INTERVAL_SECONDS = 5
WORKFLOW_LOOKUP_TIMEOUT_SECONDS = 120
WORKFLOW_RUN_LIST_LIMIT = 50
STABLE_BRANCH = "stable"


class ReleaseError(Exception):
    """A release precondition is not satisfied."""


class FragmentError(ReleaseError):
    """A changelog fragment does not follow the required format."""


class PostPushVerificationError(ReleaseError):
    """Git state is already published but GitHub verification was inconclusive."""


def version_key(value: str) -> tuple[int, int, int]:
    if not VERSION.fullmatch(value):
        raise ReleaseError(f"version must be plain X.Y.Z, got {value!r}")
    return tuple(int(part) for part in value.split("."))  # type: ignore[return-value]


def run_git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=root, text=True, capture_output=True, check=False)


def newest_record(root: Path) -> dict[str, object]:
    records = []
    for path in (root / "releases").glob("*.json"):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            version_key(str(record["version"]))
            records.append(record)
        except (json.JSONDecodeError, KeyError, ReleaseError) as error:
            raise ReleaseError(f"invalid release ledger record {path.relative_to(root)}: {error}") from error
    if not records:
        raise ReleaseError("release ledger has no records")
    return max(records, key=lambda record: version_key(str(record["version"])))


def read_migrations(root: Path) -> list[dict[str, object]]:
    result = []
    for path in (root / "migrations").glob("[0-9][0-9][0-9]-*.json"):
        try:
            result.append(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError as error:
            raise ReleaseError(f"invalid migration {path.relative_to(root)}: {error}") from error
    return result


def unreleased_body(changelog: str, *, required: bool = True) -> tuple[int, int, str]:
    match = re.search(r"^## \[Unreleased\]\s*$", changelog, re.MULTILINE)
    if not match:
        raise ReleaseError("CHANGELOG.md has no '## [Unreleased]' heading")
    body_start = match.end()
    following = re.search(r"^## \[", changelog[body_start:], re.MULTILINE)
    body_end = body_start + following.start() if following else len(changelog)
    body = changelog[body_start:body_end].strip()
    if required and not body:
        raise ReleaseError("CHANGELOG.md '## [Unreleased]' has an empty body")
    return body_start, body_end, body


def fragment_paths(root: Path) -> list[Path]:
    directory = root / "changelog.d"
    if not directory.exists():
        return []
    paths = []
    for path in directory.iterdir():
        if path.name == "README.md":
            continue
        if not path.is_file() or not re.fullmatch(r"[0-9]+\.md", path.name):
            raise FragmentError(f"{path.relative_to(root)}: filename must be <TASK-ID>.md")
        paths.append(path)
    return sorted(paths, key=lambda path: path.name)


def parse_fragment(path: Path) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    heading: str | None = None
    bullet: list[str] | None = None
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        match = re.fullmatch(r"### (.+)", line)
        if match:
            name = match.group(1)
            if name not in CHANGELOG_HEADINGS:
                raise FragmentError(f"{path}: line {number}: heading must be one of {', '.join(CHANGELOG_HEADINGS)}")
            if name in sections:
                raise FragmentError(f"{path}: line {number}: duplicate {name} heading")
            sections[name] = []
            heading, bullet = name, None
            continue
        if line.startswith("#"):
            raise FragmentError(f"{path}: line {number}: only ### subsection headings are allowed")
        if not line.strip():
            continue
        if line.startswith("- "):
            if heading is None:
                raise FragmentError(f"{path}: line {number}: text outside a subsection")
            bullet = [line]
            sections[heading].append("\n".join(bullet))
            continue
        if line[:1].isspace() and bullet is not None:
            bullet.append(line)
            sections[heading][-1] = "\n".join(bullet)
            continue
        if heading is None:
            raise FragmentError(f"{path}: line {number}: text outside a subsection")
        raise FragmentError(f"{path}: line {number}: subsection content must be a bullet or an indented bullet continuation")
    for name, bullets in sections.items():
        if not bullets:
            raise FragmentError(f"{path}: {name} subsection has no bullet")
    if not sections:
        raise FragmentError(f"{path}: fragment has no subsection")
    return sections


def render_fragments(root: Path) -> tuple[str, list[Path]]:
    parsed = [(path, parse_fragment(path)) for path in fragment_paths(root)]
    blocks = []
    for heading in CHANGELOG_HEADINGS:
        bullets = [bullet for _path, sections in parsed for bullet in sections.get(heading, [])]
        if bullets:
            blocks.append(f"### {heading}\n\n" + "\n".join(bullets))
    return "\n\n".join(blocks), [path for path, _sections in parsed]


def release_body(root: Path, changelog: str) -> tuple[str, list[Path], bool, bool]:
    _start, _end, legacy = unreleased_body(changelog, required=False)
    fragments, paths = render_fragments(root)
    if not legacy and not fragments:
        raise ReleaseError("CHANGELOG.md '[Unreleased]' has an empty body and changelog.d has no fragments")
    return "\n\n".join(part for part in (legacy, fragments) if part), paths, bool(legacy), bool(fragments)


def has_upgrade_notes(body: str) -> bool:
    match = re.search(r"^###\s+Upgrade notes\s*$", body, re.MULTILINE | re.IGNORECASE)
    if not match:
        return False
    following = re.search(r"^#{1,3}\s+", body[match.end():], re.MULTILINE)
    end = match.end() + following.start() if following else len(body)
    return bool(body[match.end():end].strip())


def require_migration_for_template_changes(root: Path, previous: dict[str, object]) -> None:
    """Fail closed when a CLI-only release would change managed templates."""
    tag = str(previous["gitTag"])
    result = run_git(root, "diff", "--name-only", "--no-renames", tag, "--", "templates/")
    if result.returncode:
        raise ReleaseError(
            f"preflight failed: cannot compare templates against previous release tag {tag}: "
            + result.stderr.strip()
        )
    changed = result.stdout.splitlines()
    if changed:
        raise ReleaseError(
            "preflight failed: cannot label release CLI-only; templates changed without a migration "
            f"since {tag}: " + ", ".join(changed)
        )


def derive_release(root: Path, new_version: str, previous: dict[str, object], body: str) -> tuple[str, list[str], str]:
    previous_baseline = str(previous["workflowBaselineVersion"])
    introduced = [
        migration for migration in read_migrations(root)
        if version_key(str(migration["to"])) > version_key(previous_baseline)
    ]
    if not introduced:
        require_migration_for_template_changes(root, previous)
        return CLI_ONLY, [], previous_baseline
    targets = {str(migration["to"]) for migration in introduced}
    if targets != {new_version}:
        raise ReleaseError(
            "BLOCKED: introduced migrations must all target the new version "
            f"{new_version}; found {', '.join(sorted(targets, key=version_key))}"
        )
    if not has_upgrade_notes(body):
        raise ReleaseError("BLOCKED: template-changing release needs a non-empty '### Upgrade notes' subsection")
    return TEMPLATE_CHANGING, [str(migration["id"]) for migration in introduced], new_version


def check_release_bump(root: Path, current: str, new_version: str, previous: dict[str, object]) -> None:
    """Enforce the minimum bump from fragment headings and new migrations."""
    old_major, old_minor, _ = version_key(current)
    new_major, new_minor, _ = version_key(new_version)
    bump = "major" if new_major > old_major else ("minor" if new_minor > old_minor else "patch")
    if bump == "major":
        return
    if bump == "patch":
        introduced = [
            migration for migration in read_migrations(root)
            if version_key(str(migration["to"])) > version_key(str(previous["workflowBaselineVersion"]))
        ]
        if introduced:
            raise ReleaseError(
                "BLOCKED: patch releases must not add migrations; requires at least minor: "
                + ", ".join(str(migration["id"]) for migration in introduced)
            )
    forbidden = ("Added", "Deprecated", "Removed") if bump == "patch" else ("Removed",)
    for path in fragment_paths(root):
        for heading in parse_fragment(path):
            if heading in forbidden:
                minimum = "major" if heading == "Removed" else "minor"
                raise ReleaseError(
                    f"BLOCKED: {bump} releases must not contain {heading}; requires at least "
                    f"{minimum}: {path.relative_to(root)}"
                )


def preflight(root: Path, new_version: str) -> tuple[dict[str, object], str, str, list[str], str, int]:
    branch = run_git(root, "branch", "--show-current")
    if branch.returncode or branch.stdout.strip() != "main":
        raise ReleaseError("preflight failed: current branch must be main")
    status = run_git(root, "status", "--porcelain")
    if status.returncode or status.stdout.strip():
        raise ReleaseError("preflight failed: working tree must be clean")
    current = (root / "VERSION").read_text(encoding="utf-8").strip()
    version_key(current)
    ensure_not_already_prepared(root, current)
    if version_key(new_version) <= version_key(current):
        raise ReleaseError(f"preflight failed: new version {new_version} must be greater than {current}")
    plugin = json.loads((root / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    previous = newest_record(root)
    if plugin.get("version") != current or str(previous.get("version")) != current:
        raise ReleaseError("preflight failed: VERSION, .claude-plugin/plugin.json, and newest release ledger record must agree")
    tag = run_git(root, "tag", "--list", f"v{new_version}")
    if tag.returncode or tag.stdout.strip():
        raise ReleaseError(f"preflight failed: local tag v{new_version} already exists")
    body, _paths, _legacy, _fragments = release_body(root, (root / "CHANGELOG.md").read_text(encoding="utf-8"))
    check_release_bump(root, current, new_version, previous)
    kind, migrations, baseline = derive_release(root, new_version, previous, body)
    protocol = protocol_version(root)
    old_protocol = previous.get("protocolVersion")
    return previous, body, kind, migrations, baseline, protocol if isinstance(protocol, int) else 0


def ensure_not_already_prepared(root: Path, current: str) -> None:
    """Tell a migration task's already-prepared release to publish instead."""
    tags = run_git(root, "tag", "--list", "v*")
    if tags.returncode:
        raise ReleaseError(f"could not list local tags: {tags.stderr.strip()}")
    published = []
    for tag in tags.stdout.splitlines():
        value = tag.removeprefix("v")
        if tag.startswith("v") and VERSION.fullmatch(value):
            published.append(value)
    current_is_published = current in published
    current_is_newer = bool(published) and version_key(current) > max(map(version_key, published))
    migration_targets_current = any(str(migration.get("to")) == current for migration in read_migrations(root))
    if current_is_newer or (migration_targets_current and not current_is_published):
        require_consumed_fragments(root, current)
        raise ReleaseError(
            f"preflight failed: release {current} is already prepared; "
            f"run python3 scripts/release.py publish --confirm v{current}"
        )


def protocol_version(root: Path) -> int:
    source = (root / "scripts" / "meridian.py").read_text(encoding="utf-8")
    match = re.search(r"^PROTOCOL_VERSION\s*=\s*(\d+)\s*$", source, re.MULTILINE)
    if not match:
        raise ReleaseError("could not read PROTOCOL_VERSION from scripts/meridian.py")
    return int(match.group(1))


def render_changelog(changelog: str, version: str, kind: str, body: str) -> str:
    start, end, _ = unreleased_body(changelog, required=False)
    section = render_release_section(version, kind, body)
    return changelog[:start] + "\n\n" + section + changelog[end:].lstrip("\n")


def render_release_section(version: str, kind: str, body: str) -> str:
    summary = "this release introduces no migration." if kind == CLI_ONLY else "this release advances the workflow baseline."
    return f"## [{version}]\n\n{kind}: {summary}\n\n{body}\n\n"


def write_release(root: Path, version: str, date: str, kind: str, migrations: list[str], baseline: str, protocol: int, body: str, fragments: list[Path]) -> list[Path]:
    version_path = root / "VERSION"
    plugin_path = root / ".claude-plugin" / "plugin.json"
    ledger_path = root / "releases" / f"{version}.json"
    changelog_path = root / "CHANGELOG.md"
    plugin = json.loads(plugin_path.read_text(encoding="utf-8"))
    plugin["version"] = version
    version_path.write_text(f"{version}\n", encoding="utf-8")
    plugin_path.write_text(json.dumps(plugin, indent=2) + "\n", encoding="utf-8")
    ledger_path.write_text(json.dumps({"version": version, "releaseDate": date, "gitTag": f"v{version}", "protocolVersion": protocol, "workflowBaselineVersion": baseline, "baselineChanged": bool(migrations), "migrations": migrations}, indent=2) + "\n", encoding="utf-8")
    changelog_path.write_text(render_changelog(changelog_path.read_text(encoding="utf-8"), version, kind, body), encoding="utf-8")
    for fragment in fragments:
        fragment.unlink()
    return [version_path, plugin_path, ledger_path, changelog_path, *fragments]


def restore(root: Path, paths: list[Path]) -> None:
    for path in paths:
        relative = path.relative_to(root)
        if run_git(root, "cat-file", "-e", f"HEAD:{relative}").returncode == 0:
            run_git(root, "checkout", "HEAD", "--", str(relative))
        elif path.exists():
            path.unlink()


def validate(root: Path, version: str) -> tuple[int, list[str]]:
    notes = tempfile.NamedTemporaryFile(prefix="meridian-release-", suffix=".md", delete=False)
    notes.close()
    commands = [
        [sys.executable, "scripts/check_repository.py"],
        [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
        [sys.executable, "scripts/prepare_release.py", "--tag", f"v{version}", "--notes-file", notes.name],
    ]
    try:
        for command in commands:
            result = subprocess.run(command, cwd=root, text=True, capture_output=True, check=False)
            if result.returncode:
                return result.returncode, command
    finally:
        Path(notes.name).unlink(missing_ok=True)
    return 0, []


def prepare_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--bump", choices=("patch", "minor", "major"))
    choice.add_argument("--version")
    parser.add_argument("--date")
    parser.add_argument("--protocol-reviewed", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        current = (root / "VERSION").read_text(encoding="utf-8").strip()
        current_key = version_key(current)
        if args.version:
            new_version = args.version
        else:
            major, minor, patch = current_key
            new_version = f"{major + 1}.0.0" if args.bump == "major" else (f"{major}.{minor + 1}.0" if args.bump == "minor" else f"{major}.{minor}.{patch + 1}")
        version_key(new_version)
        date = args.date or dt.date.today().isoformat()
        dt.date.fromisoformat(date)
        previous, body, kind, migrations, baseline, protocol = preflight(root, new_version)
        _combined, fragments, used_legacy, used_fragments = release_body(root, (root / "CHANGELOG.md").read_text(encoding="utf-8"))
        if protocol != previous.get("protocolVersion") and not args.protocol_reviewed:
            raise ReleaseError("BLOCKED: PROTOCOL_VERSION changed; use --protocol-reviewed only after CONTRIBUTING.md compatibility tests are added")
        if args.dry_run:
            print(f"Derived release kind: {kind}")
            print(f"Version: {new_version}")
            print("Would write: VERSION, .claude-plugin/plugin.json, " f"releases/{new_version}.json, CHANGELOG.md")
            print(render_release_section(new_version, kind, body), end="")
            if used_legacy and used_fragments:
                print("Release changelog uses both legacy [Unreleased] content and fragments.")
            return 0
        if protocol == previous.get("protocolVersion"):
            print("Manifest comparison remains a manual check; this command does not perform it.")
        paths = write_release(root, new_version, date, kind, migrations, baseline, protocol, body, fragments)
        status, command = validate(root, new_version)
        if status:
            restore(root, paths)
            print(f"validation failed: {' '.join(command)} exited {status}; release files restored", file=sys.stderr)
            return status
        commit = run_git(root, "add", "--", *(str(path.relative_to(root)) for path in paths))
        if commit.returncode:
            raise ReleaseError(f"could not stage release files: {commit.stderr.strip()}")
        commit = run_git(root, "commit", "-m", f"Release {new_version}")
        if commit.returncode:
            raise ReleaseError(f"could not create release commit: {commit.stderr.strip()}")
        print(
            f"Created {commit.stdout.strip()}\nDerived kind: {kind}\n"
            "Next: python3 scripts/release.py publish (Task 094)"
        )
        return 0
    except (ReleaseError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"release prepare failed: {error}", file=sys.stderr)
        return 1


def prepared_changelog_body(root: Path, changelog: str, version: str) -> tuple[int, int, str, list[Path]]:
    """Merge pending fragments into the current release, preserving its preamble."""
    if (root / "VERSION").read_text(encoding="utf-8").strip() != version:
        raise ReleaseError("--prepared requires the current VERSION")
    match = re.search(rf"^## \[{re.escape(version)}\][ \t]*$", changelog, re.MULTILINE)
    if not match:
        raise ReleaseError(f"CHANGELOG.md has no '## [{version}]' heading")
    start = match.end()
    following = re.search(r"^## \[", changelog[start:], re.MULTILINE)
    end = start + following.start() if following else len(changelog)
    old = changelog[start:end].strip()
    if not old.startswith((CLI_ONLY, TEMPLATE_CHANGING)):
        raise ReleaseError("prepared release must start with its release kind line")
    fragments = fragment_paths(root)
    parsed = [parse_fragment(path) for path in fragments]
    if not fragments:
        return start, end, old, fragments
    headings = list(re.finditer(r"^### (.+)$", old, re.MULTILINE))
    preamble = old[:headings[0].start()].strip() if headings else old
    sections: dict[str, list[str]] = {}
    for index, heading in enumerate(headings):
        name = heading.group(1)
        if name not in CHANGELOG_HEADINGS:
            raise ReleaseError(f"unsupported prepared release subsection: {name}")
        stop = headings[index + 1].start() if index + 1 < len(headings) else len(old)
        sections.setdefault(name, []).append(old[heading.end():stop].strip())
    for fragment in parsed:
        for name, bullets in fragment.items():
            sections.setdefault(name, []).extend(bullets)
    blocks = [preamble]
    for name in CHANGELOG_HEADINGS:
        if name in sections:
            blocks.append(f"### {name}\n\n" + "\n".join(sections[name]))
    return start, end, "\n\n".join(blocks), fragments


def require_consumed_fragments(root: Path, version: str) -> None:
    paths = fragment_paths(root)
    if paths:
        names = ", ".join(str(path.relative_to(root)) for path in paths)
        raise ReleaseError(
            f"preflight failed: pending changelog fragments: {names}; "
            f"run python3 scripts/release.py changelog render --version {version} --prepared --write "
            "and commit the updated CHANGELOG.md and fragment removals before publishing"
        )


def changelog_render_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Render changelog fragments without making a release commit.")
    parser.add_argument("--version", required=True)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--prepared", action="store_true", help="merge into the current prepared release section")
    parser.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        version_key(args.version)
        root = args.root.resolve()
        changelog_path = root / "CHANGELOG.md"
        changelog = changelog_path.read_text(encoding="utf-8")
        if args.prepared:
            start, end, body, fragments = prepared_changelog_body(root, changelog, args.version)
        else:
            body, fragments, _legacy, _fragment_source = release_body(root, changelog)
            start, end, _old = unreleased_body(changelog, required=False)
        print(body)
        if args.write and (not args.prepared or fragments):
            changelog_path.write_text(changelog[:start] + "\n\n" + body + "\n\n" + changelog[end:].lstrip("\n"), encoding="utf-8")
            for fragment in fragments:
                fragment.unlink()
        return 0
    except (ReleaseError, OSError, ValueError) as error:
        print(f"changelog render failed: {error}", file=sys.stderr)
        return 1


def command_text(command: list[str]) -> str:
    return " ".join(command)


def run_command(root: Path, command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=root, text=True, capture_output=True, check=False)


def git_output(root: Path, *args: str) -> str:
    result = run_git(root, *args)
    if result.returncode:
        raise ReleaseError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def remote_tag_exists(root: Path, tag: str) -> bool:
    result = run_git(root, "ls-remote", "--exit-code", "--tags", "origin", f"refs/tags/{tag}")
    if result.returncode == 0:
        return True
    if result.returncode == 2:
        return False
    raise ReleaseError(f"could not check origin for tag {tag}: {result.stderr.strip()}")


def remote_tag_head(root: Path, tag: str) -> str:
    result = run_git(root, "ls-remote", "--tags", "origin", f"refs/tags/{tag}", f"refs/tags/{tag}^{{}}")
    if result.returncode:
        raise ReleaseError(f"could not check origin for tag {tag}: {result.stderr.strip()}")
    entries = [line.split("\t", 1) for line in result.stdout.splitlines() if "\t" in line]
    if not entries:
        raise ReleaseError(f"verification failed: origin tag {tag} does not exist")
    peeled = next((sha for sha, ref in entries if ref == f"refs/tags/{tag}^{{}}"), None)
    return peeled or entries[0][0]


def remote_branch_head(root: Path, branch: str) -> str | None:
    result = run_git(root, "ls-remote", "--heads", "origin", f"refs/heads/{branch}")
    if result.returncode:
        raise ReleaseError(f"could not check origin for branch {branch}: {result.stderr.strip()}")
    for line in result.stdout.splitlines():
        sha, _, ref = line.partition("\t")
        if ref == f"refs/heads/{branch}":
            return sha
    return None


def ensure_plugin_version_matches(root: Path, revision: str, version: str) -> None:
    result = run_git(root, "show", f"{revision}:.claude-plugin/plugin.json")
    if result.returncode:
        raise ReleaseError(f"could not read .claude-plugin/plugin.json at {revision}: {result.stderr.strip()}")
    try:
        declared = json.loads(result.stdout).get("version")
    except (json.JSONDecodeError, AttributeError) as error:
        raise ReleaseError(f".claude-plugin/plugin.json at {revision} is not a JSON object") from error
    if declared != version:
        raise ReleaseError(f".claude-plugin/plugin.json at {revision} declares version {declared}, not {version}")


def advance_stable(root: Path, tag: str, version: str) -> str:
    """Fast-forward origin's `stable` branch to the commit carrying `tag`; never forces."""
    release_commit = git_output(root, "rev-parse", f"{tag}^{{commit}}")
    ensure_plugin_version_matches(root, release_commit, version)
    current = remote_branch_head(root, STABLE_BRANCH)
    if current is not None:
        if run_git(root, "cat-file", "-e", f"{current}^{{commit}}").returncode:
            run_git(root, "fetch", "origin", f"refs/heads/{STABLE_BRANCH}")
        ancestor = run_git(root, "merge-base", "--is-ancestor", current, release_commit)
        if ancestor.returncode:
            raise ReleaseError(
                f"origin {STABLE_BRANCH} ({current}) is not an ancestor of release commit {release_commit}; "
                f"{STABLE_BRANCH} was not moved. main and tag {tag} stay published as pushed"
            )
    result = run_command(root, ["git", "push", "origin", f"{release_commit}:refs/heads/{STABLE_BRANCH}"])
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        raise ReleaseError(f"{STABLE_BRANCH} push failed after main and tag {tag} were published: {detail}")
    return release_commit


def verify_stable(root: Path, tag: str, tag_head: str) -> None:
    current = remote_branch_head(root, STABLE_BRANCH)
    if current != tag_head:
        shown = current or "missing"
        raise ReleaseError(
            f"origin {STABLE_BRANCH} is {shown} but {tag} is {tag_head}; nothing was changed "
            f"(expected after a newer release moved {STABLE_BRANCH} past {tag})"
        )


def release_kind(root: Path, version: str) -> tuple[str, list[str]]:
    record_path = root / "releases" / f"{version}.json"
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ReleaseError(f"could not read release ledger {record_path.relative_to(root)}: {error}") from error
    if str(record.get("version")) != version:
        raise ReleaseError(f"release ledger {record_path.relative_to(root)} does not match VERSION")
    baseline_changed = record.get("baselineChanged")
    migrations = record.get("migrations")
    if not isinstance(baseline_changed, bool):
        raise ReleaseError(f"release ledger {record_path.relative_to(root)} baselineChanged must be true or false")
    if not isinstance(migrations, list) or not all(isinstance(migration, str) for migration in migrations):
        raise ReleaseError(f"release ledger {record_path.relative_to(root)} migrations must be a list of ids")
    if not baseline_changed:
        if migrations:
            raise ReleaseError("preflight failed: a CLI-only release ledger must list no migrations")
        older = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in (root / "releases").glob("*.json")
            if version_key(path.stem) < version_key(version)
        ]
        if not older:
            raise ReleaseError("preflight failed: no previous release ledger for template comparison")
        previous = max(older, key=lambda item: version_key(str(item["version"])))
        require_migration_for_template_changes(root, previous)
        return CLI_ONLY, []
    if not migrations:
        raise ReleaseError("preflight failed: a template-changing release ledger must list migrations")
    if len(set(migrations)) != len(migrations):
        raise ReleaseError("preflight failed: a template-changing release ledger must not repeat migration ids")
    available = {str(migration.get("id")): str(migration.get("to")) for migration in read_migrations(root)}
    invalid = [migration for migration in migrations if available.get(migration) != version]
    if invalid:
        raise ReleaseError(
            "preflight failed: template-changing release ledger migrations must exist "
            f"and target {version}: {', '.join(invalid)}"
        )
    return TEMPLATE_CHANGING, migrations


def release_state(root: Path, version: str) -> tuple[str, list[str]]:
    plugin = json.loads((root / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    newest = newest_record(root)
    if plugin.get("version") != version or str(newest.get("version")) != version:
        raise ReleaseError(
            "preflight failed: VERSION, .claude-plugin/plugin.json, and newest release ledger record must agree"
        )
    record_path = root / "releases" / f"{version}.json"
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ReleaseError(f"could not read release ledger {record_path.relative_to(root)}: {error}") from error
    if record.get("gitTag") != f"v{version}":
        raise ReleaseError(f"preflight failed: release ledger gitTag must equal v{version}")
    return release_kind(root, version)


def publish_preflight(root: Path, version: str) -> tuple[str, str, list[str], list[str]]:
    require_consumed_fragments(root, version)
    if git_output(root, "branch", "--show-current") != "main":
        raise ReleaseError("preflight failed: current branch must be main")
    if git_output(root, "status", "--porcelain"):
        raise ReleaseError("preflight failed: working tree must be clean")
    head = git_output(root, "rev-parse", "HEAD")
    ancestor = run_git(root, "merge-base", "--is-ancestor", "refs/remotes/origin/main", "HEAD")
    if ancestor.returncode:
        raise ReleaseError("preflight failed: origin/main must be an ancestor of HEAD")
    kind, migrations = release_state(root, version)
    tag = f"v{version}"
    if run_git(root, "show-ref", "--verify", "--quiet", f"refs/tags/{tag}").returncode == 0:
        raise ReleaseError(f"preflight failed: local tag {tag} already exists")
    if remote_tag_exists(root, tag):
        raise ReleaseError(f"preflight failed: origin tag {tag} already exists")
    commits = git_output(root, "log", "--format=%h %s", "refs/remotes/origin/main..HEAD").splitlines()
    return head, kind, migrations, commits


def github_repository(remote: str) -> str | None:
    match = re.search(r"github\.com[/:]([^/]+)/([^/]+?)(?:\.git)?$", remote)
    return f"{match.group(1)}/{match.group(2)}" if match else None


def print_publish_summary(version: str, kind: str, migrations: list[str], commits: list[str], remote: str) -> None:
    print(f"Release version: {version}")
    print(f"Release kind: {kind}")
    print("Migrations: " + (", ".join(migrations) if migrations else "none"))
    print("Commits to push:")
    for commit in commits:
        print(f"  {commit}")
    print(f"Destination: origin ({remote})")


def print_manual_urls(version: str, repository: str | None) -> None:
    if repository:
        base = f"https://github.com/{repository}"
        print(f"Workflow: {base}/actions/workflows/release.yml")
        print(f"Release: {base}/releases/tag/v{version}")
    print(f"Manual verification: gh release view v{version} --repo <owner/repository>")


def run_checked(root: Path, command: list[str], label: str) -> subprocess.CompletedProcess[str]:
    result = run_command(root, command)
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        raise ReleaseError(f"{label} failed ({result.returncode}): {detail}")
    return result


def manual_verification_commands(version: str, repository: str | None) -> tuple[str, str, str]:
    repository_args = ["--repo", repository] if repository else []
    run = command_text([
        "gh", "run", "list", "--workflow", "Publish release", "--branch", f"v{version}",
        "--limit", str(WORKFLOW_RUN_LIST_LIMIT), "--json", "databaseId,url,headSha,event", *repository_args,
    ])
    view = command_text(["gh", "release", "view", f"v{version}", *repository_args])
    verify = f"python3 scripts/release.py verify --version {version}"
    return run, view, verify


def post_push_verification_error(version: str, repository: str | None, detail: str) -> PostPushVerificationError:
    run, view, verify = manual_verification_commands(version, repository)
    return PostPushVerificationError(
        f"publication verification could not be completed after the push of main and tag v{version} completed; "
        "nothing was retried or moved, and publication was not confirmed by this command. "
        f"Details: {detail}\nContinue manually with:\n  {verify}\n  {run}\n  {view}"
    )


def workflow_run(root: Path, version: str, tag_head: str, repository: str | None) -> tuple[str, str]:
    deadline = time.monotonic() + WORKFLOW_LOOKUP_TIMEOUT_SECONDS
    last_error: str | None = None
    command = [
        "gh", "run", "list", "--workflow", "Publish release", "--branch", f"v{version}",
        "--limit", str(WORKFLOW_RUN_LIST_LIMIT), "--json", "databaseId,url,headSha,event",
    ]
    if repository:
        command.extend(("--repo", repository))
    while True:
        result = run_command(root, command)
        if result.returncode:
            last_error = f"gh run list exited {result.returncode}"
        else:
            try:
                entries = json.loads(result.stdout)
            except json.JSONDecodeError:
                last_error = "gh run list returned invalid JSON"
            else:
                if isinstance(entries, list):
                    for entry in entries:
                        if not isinstance(entry, dict):
                            continue
                        if entry.get("headSha") == tag_head and entry.get("event") == "push":
                            run_id = entry.get("databaseId")
                            if run_id is not None:
                                return str(run_id), str(entry.get("url", "(workflow URL unavailable)"))
                else:
                    last_error = "gh run list returned invalid JSON"
        if time.monotonic() >= deadline:
            detail = f" Last lookup error: {last_error}." if last_error else ""
            raise post_push_verification_error(
                version, repository,
                "the Publish release workflow run was not observed before the timeout." + detail,
            )
        time.sleep(WORKFLOW_POLL_INTERVAL_SECONDS)


def wait_for_publication(root: Path, version: str, repository: str | None, tag_head: str) -> None:
    if not shutil.which("gh"):
        print("gh is unavailable; skipping automated workflow and release verification.")
        print_manual_urls(version, repository)
        return
    run_id, run_url = workflow_run(root, version, tag_head, repository)
    watched = run_command(root, ["gh", "run", "watch", run_id, "--exit-status"])
    if watched.returncode:
        print(f"Publish release workflow failed: {run_url}. Nothing was published; the tag was left unchanged.", file=sys.stderr)
        raise ReleaseError("workflow failed; do not retry by moving the tag")
    release_command = ["gh", "release", "view", f"v{version}", "--json", "isDraft,isPrerelease,url"]
    if repository:
        release_command.extend(("--repo", repository))
    release = run_command(root, release_command)
    if release.returncode:
        detail = release.stderr.strip() or release.stdout.strip() or f"gh release view exited {release.returncode}"
        raise post_push_verification_error(version, repository, detail)
    try:
        details = json.loads(release.stdout)
    except json.JSONDecodeError as error:
        raise post_push_verification_error(version, repository, f"gh release view returned invalid JSON: {error}") from error
    if not isinstance(details, dict) or not all(
        isinstance(details.get(field), expected)
        for field, expected in (("isDraft", bool), ("isPrerelease", bool), ("url", str))
    ):
        raise post_push_verification_error(version, repository, "gh release view returned an unexpected JSON shape")
    if not repository:
        raise post_push_verification_error(version, repository, "GitHub repository could not be resolved for the latest-release check")
    latest_command = ["gh", "api", f"repos/{repository}/releases/latest"]
    latest = run_command(root, latest_command)
    if latest.returncode:
        detail = latest.stderr.strip() or latest.stdout.strip() or f"gh api exited {latest.returncode}"
        raise post_push_verification_error(version, repository, detail)
    try:
        latest_details = json.loads(latest.stdout)
    except json.JSONDecodeError as error:
        raise post_push_verification_error(version, repository, f"gh api returned invalid JSON: {error}") from error
    if not isinstance(latest_details, dict) or not isinstance(latest_details.get("tag_name"), str):
        raise post_push_verification_error(version, repository, "gh api returned an unexpected latest-release JSON shape")
    if details["isDraft"] or details["isPrerelease"] or latest_details["tag_name"] != f"v{version}":
        raise ReleaseError("release verification failed: release must be published, stable, and latest")
    print(f"Workflow succeeded: {run_url}")
    print(f"Release verified: {details['url']}")
    self_check = run_command(root, ["bin/meridian", "self-check", "--check-latest"])
    output = (self_check.stdout.strip() or self_check.stderr.strip() or f"exit {self_check.returncode}")
    print(f"Self-check: {output}")


def adopter_steps() -> str:
    return "\n".join((
        "Adopter update steps (not run):",
        "  Claude Code: /plugin marketplace add biagiolibe/meridian#v<version>",
        "  Claude Code, ref \"stable\": /plugin marketplace update meridian",
        "  Codex: git -C \"$MERIDIAN_ROOT\" fetch --tags && git -C \"$MERIDIAN_ROOT\" checkout v<version>",
    ))


def publish_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Publish the prepared Meridian release.")
    parser.add_argument("--confirm", metavar="vVERSION")
    parser.add_argument("--no-wait", action="store_true")
    parser.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        version = (root / "VERSION").read_text(encoding="utf-8").strip()
        version_key(version)
        head, kind, migrations, commits = publish_preflight(root, version)
        remote = git_output(root, "remote", "get-url", "origin")
        repository = github_repository(remote)
        print_publish_summary(version, kind, migrations, commits, remote)
        expected = f"v{version}"
        if args.confirm != expected:
            print(f"Refusing to publish: type --confirm {expected} to push main, tag, and stable.", file=sys.stderr)
            return 1
        status, command = validate(root, version)
        if status:
            raise ReleaseError(f"release validation failed: {command_text(command)} exited {status}")
        ensure_plugin_version_matches(root, "HEAD", version)
        completed: list[str] = []
        for command, step in ((["git", "push", "origin", "main"], "main push"), (["git", "tag", expected], "local tag"), (["git", "push", "origin", expected], "tag push")):
            result = run_command(root, command)
            if result.returncode:
                detail = result.stderr.strip() or result.stdout.strip()
                raise ReleaseError(f"{step} failed after completed steps: {', '.join(completed) or 'none'}: {detail}")
            completed.append(step)
        advance_stable(root, expected, version)
        completed.append(f"{STABLE_BRANCH} push")
        print("Completed: " + ", ".join(completed))
        if args.no_wait:
            print_manual_urls(version, repository)
        else:
            wait_for_publication(root, version, repository, head)
        print(adopter_steps())
        return 0
    except PostPushVerificationError as error:
        print(error, file=sys.stderr)
        return 1
    except (ReleaseError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"release publish failed: {error}", file=sys.stderr)
        return 1


def verify_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Verify a published Meridian release without changing Git state.")
    parser.add_argument("--version", required=True)
    parser.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        version_key(args.version)
        tag = f"v{args.version}"
        tag_head = remote_tag_head(root, tag)
        remote = git_output(root, "remote", "get-url", "origin")
        wait_for_publication(root, args.version, github_repository(remote), tag_head)
        verify_stable(root, tag, tag_head)
        return 0
    except (ReleaseError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"release verify failed: {error}", file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> int:
    values = list(sys.argv[1:] if argv is None else argv)
    if values == ["--help"]:
        parser = argparse.ArgumentParser(
            description="Prepare, publish, or verify a Meridian release.",
            epilog="prepare makes a local release commit; publish pushes main, the release tag, and stable; verify is read-only.",
        )
        subcommands = parser.add_subparsers(title="commands")
        subcommands.add_parser("prepare", help="prepare a local release without publishing")
        subcommands.add_parser("publish", help="publish a prepared release by pushing main, the tag, and stable")
        subcommands.add_parser("verify", help="read-only verification of an existing release tag")
        subcommands.add_parser("changelog", help="render changelog fragments")
        parser.print_help()
        return 0
    if values and values[0] == "prepare":
        return prepare_main(values[1:])
    if values and values[0] == "publish":
        return publish_main(values[1:])
    if values and values[0] == "verify":
        return verify_main(values[1:])
    if values and values[0] == "changelog":
        if len(values) < 2 or values[1] != "render":
            print("release changelog requires the 'render' command", file=sys.stderr)
            return 1
        return changelog_render_main(values[2:])
    return prepare_main(values)


if __name__ == "__main__":
    sys.exit(main())
