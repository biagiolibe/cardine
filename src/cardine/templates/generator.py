"""Generate workflow shared bodies and consumer entry routers."""
from __future__ import annotations

from pathlib import Path
import re

from cardine.shared.constants import MARKED_BLOCK
from cardine.shared.errors import CardineError
from cardine.templates.markers import extract_marked_block
from cardine.templates.router import entry_router_outputs

# `CLAUDE.md` is Claude Code's own instructions file; it cannot be reduced to a
# bare pointer, since a Claude Code session never reads `AGENTS.md` itself. So
# each workflow's `CLAUDE.md` keeps a hand-authored preamble (title, pointer
# paragraph, any Claude-Code-specific sections) up to this anchor heading, and
# everything from the anchor onward — the actual shared rule content, capability
# markers included — is generated verbatim from `AGENTS.md`, which stays the
# single source of truth for that text. The anchor is matched by heading text,
# not position, per this repo's own role-scoped-agent-rules precedent: it must
# be a heading that both files currently carry.
CLAUDE_MD_SHARED_ANCHOR = {
    "governed-sdd": "## Command triggers",
    "lean-delivery": "## Command triggers",
}


def generate_claude_md(mode: str, agents_text: str, existing_claude_text: str) -> str:
    anchors = (CLAUDE_MD_SHARED_ANCHOR[mode], "## Code organization") if mode == "governed-sdd" else (CLAUDE_MD_SHARED_ANCHOR[mode],)
    for anchor in anchors:
        pattern = re.compile(rf"^{re.escape(anchor)}$", re.MULTILINE)
        agents_match = pattern.search(agents_text)
        claude_match = pattern.search(existing_claude_text)
        if agents_match is not None and claude_match is not None:
            break
    else:
        raise CardineError(f"AGENTS.md and CLAUDE.md ({mode}) do not share a supported anchor heading")
    preamble = existing_claude_text[: claude_match.start()]
    shared_body = agents_text[agents_match.start() :]

    # A capability marker's content is versioned; changing it without bumping
    # the version is exactly the defect this generator must never reproduce
    # (see tasks/014-generator-altered-protected-blocks.md). So the shared
    # body is copied from AGENTS.md everywhere *except* inside a marker: there,
    # CLAUDE.md's own existing block for that same capability+version wins
    # verbatim, byte for byte, if one is already present. A capability with no
    # prior block in CLAUDE.md (a brand-new marker) has nothing to preserve,
    # so it is copied from AGENTS.md like the rest of the shared body.
    def preserve_existing_marker(match: re.Match[str]) -> str:
        capability, version = match.group(1), int(match.group(2))
        existing_block = extract_marked_block(existing_claude_text, capability, version)
        return existing_block if existing_block is not None else match.group(0)

    shared_body = MARKED_BLOCK.sub(preserve_existing_marker, shared_body)
    return preamble + shared_body


def generated_outputs(framework_root: Path, project_root: Path, mode: str | None = None) -> dict[Path, str]:
    """Generate both entry files for a consumer, or a workflow's shared body."""
    if mode is None:
        return {project_root / path: text for path, text in entry_router_outputs(project_root).items()}
    workflow = framework_root / "templates" / "workflows" / mode
    claude = workflow / "CLAUDE.md"
    return {claude: generate_claude_md(mode, (workflow / "AGENTS.md").read_text(encoding="utf-8"), claude.read_text(encoding="utf-8"))}
