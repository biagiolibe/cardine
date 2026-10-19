"""Helpers extracted from the legacy CLI; see the module split plan."""

from __future__ import annotations

from cardine.release.version import read_version
from cardine.release.version import version_key
from cardine.shared.errors import CardineError
from cardine.shared.models import ManagedFile
from cardine.templates.markers import append_only_new_markers
from cardine.templates.markers import marker_pairs
from cardine.templates.migrations import migration_capability_entries
from cardine.templates.migrations import migration_capability_moves
from cardine.templates.roots import LEGACY_WORKFLOW_ROOT
from cardine.templates.roots import single_template_root
from pathlib import Path
import json
import re


def latest_migration_to(framework_root: Path, upto: str | None = None) -> str:
    """Return the newest migration baseline, or the release itself for an empty ledger."""
    limit = upto or read_version(framework_root)
    versions = [
        str(json.loads(path.read_text(encoding="utf-8"))["to"])
        for path in (framework_root / "migrations").glob("*.json")
    ]
    if not versions:
        return limit
    eligible = [version for version in versions if version_key(version) <= version_key(limit)]
    if not eligible:
        raise CardineError(f"no migration baseline exists at or below framework version {limit}")
    return max(eligible, key=version_key)


def manifest_baseline_version(manifest: dict[str, object]) -> str:
    """Read the explicit baseline version, with compatibility for legacy manifests."""
    return str(manifest.get("workflowBaselineVersion", manifest.get("frameworkVersion", "")))


def managed_files_for_workflow(workflow: Path, mode: str) -> list[ManagedFile]:
    if not workflow.is_dir():
        raise CardineError(f"workflow template is missing: {workflow}")

    paths = [
        Path("PROJECT_WORKFLOW.md"),
        Path("AGENTS.md"),
        Path("CLAUDE.md"),
        Path("LANGUAGE_POLICY.md"),
    ]
    if mode == "lean-delivery":
        paths.extend(
            [
                Path("docs/CONTEXT_BUDGET_POLICY.md"),
                Path("docs/EXECUTION_EVIDENCE_PROFILE.md"),
            ]
        )
    if mode == "governed-sdd":
        paths.extend(
            [
                Path("tasks/TASK_BLUEPRINT.md"),
                *[
                    item.relative_to(workflow)
                    for item in sorted((workflow / "docs").rglob("*.md"))
                ],
            ]
        )
    # Include optional managed files only when the workflow supplies them.
    optional_paths = [Path(".codex/rules/meridian.rules"), Path(".codex/hooks.json")]
    if mode == "lean-delivery":
        optional_paths.append(Path("docs/WORKTREE_LIFECYCLE.md"))
    for optional_path in optional_paths:
        if (workflow / optional_path).is_file():
            paths.append(optional_path)

    result = []
    for target in paths:
        source = workflow / target
        if not source.is_file():
            raise CardineError(f"managed template is missing: {source}")
        result.append(ManagedFile(source=source, target=target))
    return result


def single_managed_files(root: Path) -> list[ManagedFile]:
    """The managed files of a single template set; the same for every preset."""
    if not root.is_dir():
        raise CardineError(f"single template set is missing: {root}")
    paths = [
        Path("PROJECT_WORKFLOW.md"),
        Path("AGENTS.md"),
        Path("CLAUDE.md"),
        Path("LANGUAGE_POLICY.md"),
        Path("tasks/TASK_BLUEPRINT.md"),
        *[item.relative_to(root) for item in sorted((root / "docs").rglob("*.md"))],
    ]
    # Include optional managed files only when the template set supplies them.
    for optional_path in (Path(".codex/rules/meridian.rules"), Path(".codex/hooks.json")):
        if (root / optional_path).is_file():
            paths.append(optional_path)
    result = []
    for target in paths:
        source = root / target
        if not source.is_file():
            raise CardineError(f"managed template is missing: {source}")
        result.append(ManagedFile(source=source, target=target))
    return result


def managed_files(framework_root: Path, mode: str | None = None) -> list[ManagedFile]:
    """The managed files every installation receives. `mode` is a legacy
    compatibility key; the single template set is the only source."""
    return single_managed_files(single_template_root(framework_root))


def legacy_managed_files(framework_root: Path, mode: str) -> list[ManagedFile]:
    """The managed files of an old per-workflow root.

    Only the catalog and marker-baseline checks that still key on those paths
    call this; row SW5 moves them to the single set and deletes the accessor.
    """
    return managed_files_for_workflow(framework_root / LEGACY_WORKFLOW_ROOT / mode, mode)


def marker_declaring_migrations(framework_root: Path) -> dict[tuple[str, int], str]:
    """Map every declared (capability, version) pair to the migration id that
    introduces it — via `capability`/`capabilityVersion`, a `capabilities`
    list entry, or a `capabilityMoves` source/target — so a capped upgrade can
    tell whether a marker version present in the live template belongs to an
    excluded migration. A pair declared more than once keeps its first
    (earliest) declaring migration, in file order."""
    result: dict[tuple[str, int], str] = {}

    def record(pair: tuple[str, int], migration_id: str) -> None:
        result.setdefault(pair, migration_id)

    for path in sorted((framework_root / "migrations").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        migration_id = str(data["id"])
        for capability, version in migration_capability_entries(data):
            record((capability, version), migration_id)
        for move in migration_capability_moves(data):
            record((move.source_capability, move.source_version), migration_id)
            record((move.target_capability, move.target_version), migration_id)
    return result


def strip_marker_block(text: str, capability: str, version: int) -> str:
    """Remove one complete exact marker block, leaving surrounding text
    untouched. Mirrors `marker_blocks()`'s pattern; used to synthesize a
    template as it existed before an excluded migration introduced or bumped
    one of its markers."""
    pattern = re.compile(
        rf"<!-- MERIDIAN:BEGIN capability={re.escape(capability)} v{version} -->\n?.*?"
        r"<!-- MERIDIAN:END -->\n?",
        re.DOTALL,
    )
    return pattern.sub("", text, count=1)


def capped_managed_files(
    framework_root: Path,
    mode: str,
    baseline_root: Path,
    excluded_migration_ids: set[str],
    scratch_dir: Path,
) -> list[ManagedFile]:
    """`managed_files()`, substituting a synthesized capped template for any
    file that carries a marker block declared by an excluded migration, so
    the live (always-latest) template cannot leak a change gated to a
    migration a capped upgrade must stop before.

    Stripping the excluded marker straight out of the live template would
    leave a fragment missing whatever unrelated content the file already had
    at the installed baseline (the `--replace` fast path would then apply
    that fragment wholesale). Instead, build the capped content up from the
    installed baseline, splicing in only the marker adds/supersessions the
    live template declares via a *non*-excluded migration, reusing
    `append_only_new_markers`'s own add/supersede rules by treating the
    baseline as if it were both the local file and the base of a normal
    upgrade. A file with no baseline snapshot yet (a new managed file, e.g.
    one migration 037 alone introduces) is returned unchanged — its content
    already reflects only the migrations that created it."""
    declaring = marker_declaring_migrations(framework_root)
    result = []
    for item in managed_files(framework_root, mode):
        base_path = baseline_root / item.target
        if not base_path.is_file():
            result.append(item)
            continue
        target_text = item.source.read_text(encoding="utf-8")
        base_text = base_path.read_text(encoding="utf-8")
        filtered_target = target_text
        for capability, version in marker_pairs(target_text):
            if declaring.get((capability, version)) in excluded_migration_ids:
                filtered_target = strip_marker_block(filtered_target, capability, version)
        spliced = append_only_new_markers(base_text, base_text, filtered_target)
        capped_text = base_text if spliced is None else spliced
        if capped_text == target_text:
            result.append(item)
            continue
        scratch_dir.mkdir(parents=True, exist_ok=True)
        capped_path = scratch_dir / item.target
        capped_path.parent.mkdir(parents=True, exist_ok=True)
        capped_path.write_text(capped_text, encoding="utf-8")
        result.append(ManagedFile(source=capped_path, target=item.target))
    return result
