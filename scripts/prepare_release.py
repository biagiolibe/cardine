#!/usr/bin/env python3
"""Verify release consistency for a version tag and render its release notes."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ReleaseError(Exception):
    """A release precondition is not satisfied."""


def read_version(root: Path) -> str:
    return (root / "VERSION").read_text(encoding="utf-8").strip()


def extract_changelog_section(changelog: str, version: str) -> str:
    """Return the body of the `## [<version>]` section, without its heading."""
    heading = re.compile(rf"^## \[{re.escape(version)}\](\s.*)?$")
    lines = changelog.splitlines()
    for index, line in enumerate(lines):
        if heading.match(line):
            start = index + 1
            break
    else:
        raise ReleaseError(f"CHANGELOG.md has no '## [{version}]' section")
    end = len(lines)
    for index in range(start, len(lines)):
        if lines[index].startswith("## "):
            end = index
            break
    body = "\n".join(lines[start:end]).strip()
    if not body:
        raise ReleaseError(f"CHANGELOG.md section '## [{version}]' is empty")
    return body


CLI_ONLY_KIND = "CLI-only release"
TEMPLATE_CHANGING_KIND = "Template-changing release"
UPGRADE_NOTES_HEADING = re.compile(r"^(#{3,6})\s+Upgrade notes\s*$", re.IGNORECASE)


def check_release_notes_contract(section: str, version: str, baseline_changed: object) -> None:
    """Enforce that the section's kind line agrees with the ledger's `baselineChanged`.

    A template-changing section must also carry a non-empty Upgrade notes
    subsection (Decision 5 of docs/DISTRIBUTION_AND_UPDATE_DESIGN.md).
    """
    if not isinstance(baseline_changed, bool):
        raise ReleaseError(f"releases/{version}.json baselineChanged must be true or false")
    first_line = section.lstrip().splitlines()[0]
    if first_line.startswith(CLI_ONLY_KIND):
        declared = False
    elif first_line.startswith(TEMPLATE_CHANGING_KIND):
        declared = True
    else:
        raise ReleaseError(
            f"CHANGELOG.md section '## [{version}]' must start with "
            f"'{CLI_ONLY_KIND}' or '{TEMPLATE_CHANGING_KIND}'"
        )
    if declared != baseline_changed:
        kind = TEMPLATE_CHANGING_KIND if declared else CLI_ONLY_KIND
        raise ReleaseError(
            f"CHANGELOG.md section '## [{version}]' is a {kind.lower()} but "
            f"releases/{version}.json has baselineChanged {str(baseline_changed).lower()}"
        )
    if not declared:
        return
    lines = section.splitlines()
    for index, line in enumerate(lines):
        heading = UPGRADE_NOTES_HEADING.match(line)
        if heading:
            level = len(heading.group(1))
            body = []
            for following in lines[index + 1 :]:
                marks = re.match(r"^(#+)\s", following)
                if marks and len(marks.group(1)) <= level:
                    break
                body.append(following)
            if "\n".join(body).strip():
                return
            break
    raise ReleaseError(
        f"template-changing CHANGELOG.md section '## [{version}]' needs a non-empty "
        "'### Upgrade notes' subsection"
    )


def check_release_consistency(root: Path, tag: str) -> str:
    """Validate the tagged tree against the tag and return its version."""
    version = read_version(root)
    if tag != f"v{version}":
        raise ReleaseError(f"tag {tag!r} does not equal 'v' + VERSION ('v{version}')")
    record_path = root / "releases" / f"{version}.json"
    if not record_path.is_file():
        raise ReleaseError(f"releases/{version}.json is missing")
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ReleaseError(f"releases/{version}.json is invalid JSON: {error}") from error
    if record.get("gitTag") != tag:
        raise ReleaseError(
            f"releases/{version}.json gitTag {record.get('gitTag')!r} does not equal {tag!r}"
        )
    plugin = json.loads(
        (root / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    if plugin.get("version") != version:
        raise ReleaseError(
            f".claude-plugin/plugin.json version {plugin.get('version')!r} "
            f"does not match VERSION {version!r}"
        )
    section = extract_changelog_section(
        (root / "CHANGELOG.md").read_text(encoding="utf-8"), version
    )
    check_release_notes_contract(section, version, record.get("baselineChanged"))
    return version


def render_release_notes(root: Path, tag: str, repository: str | None = None) -> str:
    version = check_release_consistency(root, tag)
    section = extract_changelog_section(
        (root / "CHANGELOG.md").read_text(encoding="utf-8"), version
    )
    record = f"releases/{version}.json"
    target = f"https://github.com/{repository}/blob/{tag}/{record}" if repository else record
    return f"{section}\n\nRelease record: [{record}]({target})\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True, help="version tag, for example v1.2.3")
    parser.add_argument("--notes-file", type=Path, required=True, help="release body output")
    parser.add_argument("--repository", help="owner/name, used for the release record link")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    try:
        notes = render_release_notes(args.root, args.tag, args.repository)
    except ReleaseError as error:
        print(f"release check failed: {error}", file=sys.stderr)
        return 1
    args.notes_file.write_text(notes, encoding="utf-8")
    print(f"Release {args.tag} is consistent; notes written to {args.notes_file}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
