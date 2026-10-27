"""Helpers extracted from the legacy CLI; see the module split plan."""

from __future__ import annotations

from cardine.shared.layout import names

from cardine.shared.constants import CAPABILITY_MARKER
from cardine.shared.errors import CardineError
from cardine.templates.files import managed_files
from cardine.templates.roots import single_template_root
from cardine.templates.manifest import load_manifest
from cardine.templates.marker_history import declared_capability_moves
from cardine.templates.marker_history import retired_capability_versions
from cardine.templates.markers import exact_marker_matches
from cardine.templates.markers import extract_marker_block
from cardine.templates.markers import is_agents_pointer
from cardine.templates.markers import marker_blocks
from cardine.templates.markers import marker_pairs
from pathlib import Path
import re


def audit_capability_markers(
    project_root: Path, framework_root: Path, mode: str
) -> list[tuple[str, str]]:
    """Protected-region integrity.

    For every capability marker found in a project's managed files, compare
    its exact bracketed content against the framework's own current template
    for that same file — not a project-wide search, since two files can
    carry different canonical text for the same capability (a workflow
    section in AGENTS.md is not the same text as a template file's body).
    `PASS` means unmodified; `FAIL` means the protected text was edited
    outside `cardine upgrade`; `SKIP` means the project's marker version
    predates what the current template carries, so there is nothing current
    to verify against yet (a staleness question for `upgrade`, not a drift
    question for this audit). Also reports `FAIL` when a single file carries
    more than one version of the same capability — the symptom left behind
    when a version bump was appended instead of replacing the version it
    superseded, so an already-damaged project is found instead of left to
    accumulate a growing set of contradictory pairs.
    """
    retired_versions = retired_capability_versions(framework_root)
    results: list[tuple[str, str]] = []
    for item in managed_files(framework_root, mode):
        local = project_root / item.target
        if not local.is_file():
            continue
        local_text = local.read_text(encoding="utf-8")
        local_pairs = marker_pairs(local_text)
        versions_by_name: dict[str, list[int]] = {}
        for capability, version in local_pairs:
            versions_by_name.setdefault(capability, []).append(version)
        for capability, versions in versions_by_name.items():
            if len(versions) > 1:
                results.append(
                    (
                        "FAIL",
                        f"{item.target}: capability={capability} carries {len(versions)} versions "
                        f"({', '.join(f'v{v}' for v in sorted(versions))}) in the same file — a "
                        "superseded marker was left in place instead of replaced; reconcile by hand",
                    )
                )
        for capability, version_text in CAPABILITY_MARKER.findall(local_text):
            version = int(version_text)
            local_block = extract_marker_block(local_text, capability, version)
            template_text = item.source.read_text(encoding="utf-8")
            template_block = extract_marker_block(template_text, capability, version)
            if template_block is None and (capability, version) in retired_versions:
                results.append(
                    (
                        "FAIL",
                        f"{item.target}: capability={capability} v{version} is retired but still "
                        "present here; run `cardine upgrade`, or reconcile by hand if this file was "
                        "outside the retiring migration's `managedPaths`",
                    )
                )
            elif template_block is None:
                results.append(
                    (
                        "SKIP",
                        f"{item.target}: capability={capability} v{version} — the current framework "
                        "template has no matching version to verify against here (likely stale; "
                        "run `cardine upgrade` first)",
                    )
                )
            elif local_block == template_block:
                results.append(
                    ("PASS", f"{item.target}: capability={capability} v{version} matches the released text")
                )
            else:
                results.append(
                    (
                        "FAIL",
                        f"{item.target}: capability={capability} v{version} — protected content does not "
                        "match the released text for this version; possible unauthorized edit",
                    )
                )
    return sorted(results, key=lambda pair: pair[1])


HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)


def marker_headings(text: str) -> list[tuple[str, int, str | None]]:
    """(capability, version, nearest preceding heading text) for every marker
    in `text`. `None` when a marker appears before any heading in the file.
    """
    headings = [(match.start(), match.group(2).strip()) for match in HEADING.finditer(text)]
    result: list[tuple[str, int, str | None]] = []
    for match in CAPABILITY_MARKER.finditer(text):
        capability, version = match.group(1), int(match.group(2))
        heading = None
        for offset, title in headings:
            if offset <= match.start():
                heading = title
            else:
                break
        result.append((capability, int(version), heading))
    return result


def audit_duplicate_headings(project_root: Path, framework_root: Path, mode: str) -> list[tuple[str, str]]:
    """Task 007's duplication-detection half: flag a capability whose marker
    sits under more than one distinct heading *within the same managed file*
    — the mechanical signature of an accidental duplicate paste, or a
    section split in two without updating the marker placement.

    Deliberately scoped to one file at a time, not across a project's whole
    managed-files set: the same capability legitimately appears under
    different heading names in different documents by design (for example
    `manual-verification-record` under the heading of
    `docs/REVIEW_RECORD_TEMPLATE.md` and under that of
    `docs/COMPLETION_REPORT_TEMPLATE.md` — one canonical rule, several
    consuming documents, not a drifted duplicate). A cross-file heuristic
    was tried against these templates and produced five false positives on
    exactly that intentional pattern before this scope was chosen. This does
    not (and cannot) catch a *paraphrased* duplicate with no shared marker at
    all, such as the reviewer-integrator-identity triplication that
    motivated this task — that is invisible to any mechanical check and
    remains a human review concern; this only catches the structural case a
    marker can see.
    """
    results: list[tuple[str, str]] = []
    for item in managed_files(framework_root, mode):
        local = project_root / item.target
        if not local.is_file():
            continue
        by_capability: dict[str, set[str]] = {}
        for capability, _version, heading in marker_headings(local.read_text(encoding="utf-8")):
            if heading is not None:
                by_capability.setdefault(capability, set()).add(heading)
        for capability, headings in sorted(by_capability.items()):
            if len(headings) > 1:
                results.append(
                    (
                        "FAIL",
                        f"{item.target}: capability={capability} appears under {len(headings)} "
                        f"distinct headings ({', '.join(sorted(headings))}) in this file — merge "
                        "into one canonical location, or retire the duplicate via a migration's "
                        "`removes`/`supersededBy`",
                    )
                )
    return results


def audit_capability_moves(project_root: Path, framework_root: Path, mode: str) -> list[tuple[str, str]]:
    """Verify that declared additive relocations retain both exact copies."""
    try:
        applied = {
            str(item)
            for item in load_manifest(
                project_root, framework_root, defer_surface_gaps=True
            ).get("appliedMigrations", [])
        }
    except CardineError:
        if (project_root / names().manifest_path).is_file():
            raise
        return []
    results = []
    moves = [move for move in declared_capability_moves(framework_root) if move.migration in applied]
    retired_sources = {
        (move.source_path, move.source_capability, move.source_version)
        for move in moves
        if move.stage == "retirement"
    }
    for move in moves:
        if move.stage == "additive" and (move.source_path, move.source_capability, move.source_version) in retired_sources:
            continue
        source = project_root / move.source_path
        target = project_root / move.target_path
        if move.stage == "additive":
            for path, capability, version, digest, side in (
                (source, move.source_capability, move.source_version, move.source_sha256, "source"),
                (target, move.target_capability, move.target_version, move.target_sha256, "target"),
            ):
                text = path.read_text(encoding="utf-8") if path.is_file() else ""
                if side == "source" and path == project_root / "CLAUDE.md" and is_agents_pointer(text):
                    continue
                if not exact_marker_matches(text, capability, version, digest):
                    results.append(
                        (
                            "FAIL",
                            f"capability move {move.migration}: {side} {path.relative_to(project_root)} "
                            f"for capability={capability} v{version} is missing, modified, or duplicated",
                        )
                    )
        else:
            source_text = source.read_text(encoding="utf-8") if source.is_file() else ""
            target_text = target.read_text(encoding="utf-8") if target.is_file() else ""
            if marker_blocks(source_text, move.source_capability, move.source_version):
                results.append(
                    (
                        "FAIL",
                        f"capability move {move.migration}: retired source {move.source_path} is still present",
                    )
                )
            target_matches = exact_marker_matches(
                target_text, move.target_capability, move.target_version, move.target_sha256
            )
            if not target_matches:
                template = single_template_root(framework_root) / move.target_path
                template_text = template.read_text(encoding="utf-8") if template.is_file() else ""
                superseding_versions = [
                    int(version)
                    for capability, version in CAPABILITY_MARKER.findall(template_text)
                    if capability == move.target_capability and int(version) > move.target_version
                ]
                if superseding_versions:
                    current_version = max(superseding_versions)
                    target_matches = (
                        extract_marker_block(target_text, move.target_capability, current_version)
                        == extract_marker_block(template_text, move.target_capability, current_version)
                        is not None
                    )
            if not target_matches:
                results.append(
                    (
                        "FAIL",
                        f"capability move {move.migration}: target {move.target_path} is missing, modified, or duplicated",
                    )
                )
    return results
