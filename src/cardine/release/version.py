"""Release version bindings extracted from the legacy CLI."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from cardine.shared.errors import MeridianError


@dataclass(frozen=True)
class SemVer:
    major: int
    minor: int
    patch: int
    prerelease: str = ""
    build: str = ""

    def __str__(self) -> str:
        text = f"{self.major}.{self.minor}.{self.patch}"
        if self.prerelease:
            text += f"-{self.prerelease}"
        if self.build:
            text += f"+{self.build}"
        return text


_SEMVER_IDENTIFIER = r"[0-9A-Za-z-]+"


_SEMVER_PATTERN = re.compile(
    r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    rf"(?:-({_SEMVER_IDENTIFIER}(?:\.{_SEMVER_IDENTIFIER})*))?"
    rf"(?:\+({_SEMVER_IDENTIFIER}(?:\.{_SEMVER_IDENTIFIER})*))?"
)


def parse_semver(value: str) -> SemVer:
    """Parse `MAJOR.MINOR.PATCH[-PRERELEASE][+BUILD]`.

    Used only for display and the persist-time guard; `version_key()` remains the
    comparator for upgrade planning.
    """
    match = _SEMVER_PATTERN.fullmatch(value)
    if match is None:
        raise MeridianError(f"invalid framework version: {value}")
    major, minor, patch, prerelease, build = match.groups()
    return SemVer(int(major), int(minor), int(patch), prerelease or "", build or "")


def read_raw_version(framework_root: Path) -> str:
    version_file = framework_root / "VERSION"
    if not version_file.is_file():
        raise MeridianError(f"framework VERSION file is missing: {version_file}")
    return version_file.read_text(encoding="utf-8").strip()


def require_release_version(framework_root: Path) -> None:
    """Reject a prerelease framework VERSION before it can become durable."""
    version = parse_semver(read_raw_version(framework_root))
    if version.prerelease:
        raise MeridianError(
            f"framework VERSION {version} is a prerelease; a prerelease version cannot be "
            "persisted into a manifest, migration, or release record"
        )


def read_version(framework_root: Path) -> str:
    """Return the framework version without build metadata, which never becomes durable."""
    raw = read_raw_version(framework_root)
    match = _SEMVER_PATTERN.fullmatch(raw)
    if match is not None and match.group(5):
        return raw.split("+", 1)[0]
    return raw


def version_key(value: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in value.split("."))
    except ValueError as error:
        raise MeridianError(f"invalid framework version: {value}") from error


def semver_precedence_key(version: SemVer) -> tuple[object, ...]:
    """Return a SemVer precedence key; build metadata is intentionally ignored."""
    prerelease: tuple[tuple[int, object], ...]
    if version.prerelease:
        prerelease = tuple(
            (0, int(identifier)) if identifier.isdigit() else (1, identifier)
            for identifier in version.prerelease.split(".")
        )
        release_rank = 0
    else:
        prerelease = ()
        release_rank = 1
    return (version.major, version.minor, version.patch, release_rank, prerelease)


def release_kind_from_body(body: str) -> str:
    first_line = next((line.strip() for line in body.splitlines() if line.strip()), "")
    if first_line.startswith("CLI-only release:"):
        return "CLI-only"
    if first_line.startswith("Template-changing release:"):
        return "template-changing"
    raise ValueError("release body has no recognized kind line")
