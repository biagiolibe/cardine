"""Helpers extracted from the legacy CLI; see the module split plan."""

from __future__ import annotations

from pathlib import Path
import hashlib
import re

from cardine.shared.constants import CAPABILITY_MARKER


def marker_blocks(text: str, capability: str, version: int) -> list[str]:
    """Every complete exact marker block for one capability/version pair."""
    pattern = re.compile(
        rf"<!-- MERIDIAN:BEGIN capability={re.escape(capability)} v{version} -->\n?.*?"
        r"<!-- MERIDIAN:END -->",
        re.DOTALL,
    )
    return [match.group(0) for match in pattern.finditer(text)]

def marker_block_sha256(block: str) -> str:
    return hashlib.sha256(block.encode("utf-8")).hexdigest()

def exact_marker_matches(text: str, capability: str, version: int, expected_sha256: str) -> bool:
    blocks = marker_blocks(text, capability, version)
    return len(blocks) == 1 and marker_block_sha256(blocks[0]) == expected_sha256

def find_capability_marker_version(text: str, capability: str) -> int | None:
    for marker_capability, version in CAPABILITY_MARKER.findall(text):
        if marker_capability == capability:
            return int(version)
    return None

LEGACY_CAPABILITY_EVIDENCE = {
    "review-remediation-record": lambda project_root, text: (
        (project_root / "docs/REVIEW_RECORD_TEMPLATE.md").is_file() and "Address review" in text
    ),
    "lifecycle-orchestration": lambda project_root, text: (
        (project_root / "docs/LIFECYCLE_ORCHESTRATION.md").is_file() and "Run lifecycle" in text
    ),
}

def capability_ids_in_template(template: Path) -> list[str]:
    """Capability ids whose marker actually appears in this template file.

    `managedPaths` on a migration record lists every file that migration's
    diff touches, which is not the same as "every file that must carry that
    migration's capability marker" — a migration can mention or reference a
    capability in several files while only marking it in one (see
    `migrations/011-whole-file-baseline-capabilities.json`, where each of its
    four capabilities belongs to a different one of its four managed paths).
    The template's own marker set is the ground truth for what a project's
    copy of this file must contain to be verified, and it is the same source
    `audit_capability_markers` already checks against.
    """
    if not template.is_file():
        return []
    text = template.read_text(encoding="utf-8")
    return [capability for capability, _version in CAPABILITY_MARKER.findall(text)]

def extract_marker_block(text: str, capability: str, version: int) -> str | None:
    """The exact bracketed content of one capability+version marker occurrence.

    Returns None if that specific version's marker is not present in `text`
    (a different version, or no marker at all, are both "not present" here).
    The marker may sit on its own line (a whole-section wrap) or inline mid-
    sentence (a single clause inside a larger numbered step); both are legal.
    """
    pattern = re.compile(
        rf"<!-- MERIDIAN:BEGIN capability={re.escape(capability)} v{version} -->\n?(.*?)"
        r"<!-- MERIDIAN:END -->",
        re.DOTALL,
    )
    match = pattern.search(text)
    return match.group(1) if match else None

def extract_marked_block(text: str, capability: str, version: int) -> str | None:
    """Return one complete protected marker block, delimiters included."""
    pattern = re.compile(
        rf"<!-- MERIDIAN:BEGIN capability={re.escape(capability)} v{version} -->\n?(.*?)"
        r"<!-- MERIDIAN:END -->",
        re.DOTALL,
    )
    match = pattern.search(text)
    return match.group(0) if match else None

def marker_pairs(text: str) -> list[tuple[str, int]]:
    return [(capability, int(version)) for capability, version in CAPABILITY_MARKER.findall(text)]

def append_only_new_markers(local_text: str, base_text: str, template_text: str) -> str | None:
    """Reconcile newly introduced or superseded marker blocks into a customized
    local file, without touching any other project-owned text.

    A three-way line merge cannot recognize a protected block that a project has
    moved elsewhere in a file. This narrowly handles two safe cases, distinguished
    by capability *name* rather than by `(name, version)` pair — comparing pairs
    alone cannot tell a version bump from an unrelated new capability, since the
    bumped pair is absent from both the local and base pair sets exactly like a
    genuinely new one would be:

    - **Added**: the template introduces a capability the local file does not
      carry at all, and the base never carried it either. Its block is
      appended at the end, as before.
    - **Superseded**: the template raises a capability's version, and the
      local file's block for the *old* version still matches the base
      byte-for-byte (the project never edited it). The new version's block
      replaces the old one in place, preserving all surrounding text — never
      appended alongside it, where a stale rule would sit in the position an
      agent actually reads while the fix sits inert at the end of the file.

    Any other case returns None so the caller falls through to a manual
    conflict instead of guessing: a capability whose local block was edited
    from the base, a capability the base carried but the local file no longer
    does (a deliberate removal, not a merge target), or a local file that
    already carries more than one version of the same capability (itself the
    symptom of this defect; do not compound it, let `meridian audit` surface
    it for manual reconciliation instead).
    """
    base_pairs = set(marker_pairs(base_text))
    local_pairs = marker_pairs(local_text)
    template_pairs = marker_pairs(template_text)

    local_names = [capability for capability, _version in local_pairs]
    if len(local_names) != len(set(local_names)):
        return None

    local_by_name = dict(local_pairs)
    to_append: list[tuple[str, int]] = []
    to_supersede: list[tuple[str, int, int]] = []
    for capability, new_version in template_pairs:
        old_version = local_by_name.get(capability)
        if old_version is None:
            if (capability, new_version) in base_pairs:
                return None
            to_append.append((capability, new_version))
        elif old_version < new_version:
            to_supersede.append((capability, old_version, new_version))
        elif old_version == new_version:
            if extract_marker_block(local_text, capability, old_version) != extract_marker_block(
                template_text, capability, new_version
            ):
                return None
        # old_version > new_version: local is already ahead; leave it alone.

    if not to_append and not to_supersede:
        return None

    result = local_text
    for capability, old_version, new_version in to_supersede:
        base_block = extract_marker_block(base_text, capability, old_version)
        local_block = extract_marker_block(result, capability, old_version)
        if base_block is None or local_block != base_block:
            return None
        old_marked = extract_marked_block(result, capability, old_version)
        new_marked = extract_marked_block(template_text, capability, new_version)
        if old_marked is None or new_marked is None:
            return None
        result = result.replace(old_marked, new_marked, 1)

    if to_append:
        new_blocks = []
        for capability, version in to_append:
            block = extract_marked_block(template_text, capability, version)
            if block is None:
                return None
            content = extract_marker_block(template_text, capability, version)
            # A project can have manually adopted the exact new rule before a
            # later framework release wraps it in a marker. Promote that one
            # durable occurrence in place rather than appending a duplicate.
            if content and content not in base_text and result.count(content) == 1:
                result = result.replace(content, block, 1)
            else:
                new_blocks.append(block)
        if new_blocks:
            result = result.rstrip() + "\n\n" + "\n\n".join(new_blocks) + "\n"

    return result

CLAUDE_AGENTS_POINTER_MARKER = "<!-- MERIDIAN:CLAUDE-AGENTS-POINTER v1 -->"

def is_agents_pointer(text: str) -> bool:
    """Recognize a project-owned CLAUDE.md that deliberately delegates to AGENTS.

    New pointers declare a compact, versioned marker rather than depending on
    explanatory prose. The former prose signature remains a compatibility path
    for pointers created before the marker existed; neither form is safe when
    CLAUDE.md contains capability markers of its own.
    """
    legacy_pointer = (
        "`AGENTS.md`, which is authoritative" in text
        and "Every Meridian capability marker" in text
        and "lives in `AGENTS.md`, once" in text
        and "Keep this file a pointer" in text
    )
    explicit_pointer = text.count(CLAUDE_AGENTS_POINTER_MARKER) == 1
    return (explicit_pointer or legacy_pointer) and not marker_pairs(text)

def agents_pointer_satisfies_claude(
    project_root: Path, framework_root: Path, mode: str, claude_template_text: str, claude_local_text: str
) -> bool:
    """A pointer is safe only when AGENTS carries every shared Claude marker."""
    if not is_agents_pointer(claude_local_text):
        return False
    agent_local = project_root / "AGENTS.md"
    agent_template = framework_root / "templates" / "workflows" / mode / "AGENTS.md"
    if not agent_local.is_file() or not agent_template.is_file():
        return False
    local_text = agent_local.read_text(encoding="utf-8")
    template_text = agent_template.read_text(encoding="utf-8")
    pairs = marker_pairs(claude_template_text)
    return bool(pairs) and all(
        extract_marker_block(local_text, capability, version)
        == extract_marker_block(template_text, capability, version)
        for capability, version in pairs
    )

def agents_pointer_can_follow_upgrade(
    project_root: Path,
    framework_root: Path,
    mode: str,
    baseline_root: Path,
    claude_template_text: str,
    claude_local_text: str,
) -> bool:
    """Allow a valid pointer when this same upgrade makes AGENTS current.

    The check remains marker-exact: it predicts only the narrow marker-aware
    AGENTS update, never a broad merge or replacement of project-owned text.
    """
    if not is_agents_pointer(claude_local_text):
        return False
    if agents_pointer_satisfies_claude(
        project_root, framework_root, mode, claude_template_text, claude_local_text
    ):
        return True
    agent_local = project_root / "AGENTS.md"
    agent_base = baseline_root / "AGENTS.md"
    agent_template = framework_root / "templates" / "workflows" / mode / "AGENTS.md"
    if not agent_local.is_file() or not agent_base.is_file() or not agent_template.is_file():
        return False
    reconciled = append_only_new_markers(
        agent_local.read_text(encoding="utf-8"),
        agent_base.read_text(encoding="utf-8"),
        agent_template.read_text(encoding="utf-8"),
    )
    if reconciled is None:
        return False
    return all(
        extract_marker_block(reconciled, capability, version)
        == extract_marker_block(claude_template_text, capability, version)
        for capability, version in marker_pairs(claude_template_text)
    )

def reflowed_marker_normalization(local_text: str, template_text: str) -> str | None:
    """Canonicalize protected prose whose only drift is hard line wrapping.

    Fenced blocks must remain byte-identical. Outside fences, paragraph
    boundaries and non-whitespace characters must be identical; this permits a
    formatter's line wrap, not a content edit.
    """
    def paragraphs(value: str) -> list[str] | None:
        chunks = re.split(r"(```.*?```)", value, flags=re.DOTALL)
        result: list[str] = []
        for index, chunk in enumerate(chunks):
            if index % 2:
                result.append("FENCE:" + chunk)
                continue
            result.extend(
                " ".join(paragraph.split())
                for paragraph in re.split(r"\n\s*\n", chunk)
                if paragraph.strip()
            )
        return result

    local_pairs = dict(marker_pairs(local_text))
    template_pairs = dict(marker_pairs(template_text))
    if local_pairs != template_pairs:
        return None
    result = local_text
    changed = False
    for capability, version in marker_pairs(template_text):
        local_content = extract_marker_block(result, capability, version)
        template_content = extract_marker_block(template_text, capability, version)
        if local_content == template_content:
            continue
        if local_content is None or template_content is None or paragraphs(local_content) != paragraphs(template_content):
            return None
        local_marked = extract_marked_block(result, capability, version)
        template_marked = extract_marked_block(template_text, capability, version)
        if local_marked is None or template_marked is None or result.count(local_marked) != 1:
            return None
        result = result.replace(local_marked, template_marked, 1)
        changed = True
    return result if changed else None

def deduplicate_identical_template_markers(merged_text: str, template_text: str) -> str | None:
    """Remove only duplicate copies that are byte-identical to the template.

    A line merge can independently add the same newly introduced marker on both
    sides at different locations. That is structurally invalid even though the
    textual merge has no conflict. Never choose between divergent copies here:
    only an exact duplicate of the released block is safe to collapse.
    """
    result = merged_text
    changed = False
    for capability, version in marker_pairs(template_text):
        block = extract_marked_block(template_text, capability, version)
        if block is None:
            continue
        matches = list(re.finditer(re.escape(block), result))
        if len(matches) < 2:
            continue
        for match in reversed(matches[1:]):
            start, end = match.span()
            result = result[:start] + result[end:]
        changed = True
    if not changed:
        return None
    return re.sub(r"\n{3,}", "\n\n", result).rstrip() + "\n"

def remove_retired_markers(
    local_text: str, base_text: str, removals: list[tuple[str, int]]
) -> str | None:
    """Delete each retired capability's marker block from a customized local
    file — task 007's retirement path, the mirror of `append_only_new_markers`'s
    supersession case. Safe only when the local block still matches the
    project's own locked baseline for that capability+version byte-for-byte
    (unmodified since the project last upgraded): the same "replace in place
    only when it still matches the base" rule that case already applies,
    reused here for "remove" instead of "replace."

    Idempotent by design: a capability already absent locally (never present,
    or already removed by hand) is skipped, not an error, so retiring the
    same capability twice — or upgrading a project that already lacks it —
    never fails. Returns the input unchanged when no listed capability was
    found to remove, so a caller that only wants to know whether removal
    actually did anything can compare the result to `local_text`.

    Refuses (returns `None`) the moment a targeted block is present locally
    but no longer matches the base: a local edit under a marker this upgrade
    is about to delete, which must be reconciled by hand rather than
    silently discarded along with the block. Also refuses when the exact
    same block text occurs more than once in the file — `str.replace` is
    content-addressed, not position-addressed, and would otherwise delete
    only the first occurrence and silently leave the second (the duplicate-
    paste case `audit_duplicate_headings` exists to catch), a partial
    mutation this function's contract promises never to produce.
    """
    result = local_text
    changed = False
    for capability, version in removals:
        local_block = extract_marked_block(result, capability, version)
        if local_block is None:
            continue
        if result.count(local_block) > 1:
            return None
        base_block = extract_marked_block(base_text, capability, version)
        if base_block is None or local_block != base_block:
            return None
        start = result.index(local_block)
        end = start + len(local_block)
        before, after = result[:start], result[end:]
        # Collapse the blank-line run the deletion leaves behind, bounded to
        # a small window right at the splice point so a run of blank lines
        # anywhere else in the file — this project's own, unrelated to this
        # removal — is never touched.
        boundary = re.sub(r"\n{3,}", "\n\n", before[-4:] + after[:4])
        result = before[:-4] + boundary + after[4:]
        changed = True
    return result if changed else local_text
