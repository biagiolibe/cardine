"""Helpers extracted from the legacy CLI; see the module split plan."""

from __future__ import annotations

from cardine.shared.constants import ENTRY_ROUTER_BUDGET_BYTES
from cardine.shared.constants import ENTRY_ROUTER_MAP_PATH
from cardine.shared.constants import ENTRY_ROUTER_OVERLAYS
from cardine.shared.constants import ENTRY_ROUTER_PATH
from cardine.shared.constants import ENTRY_ROUTER_ROUTES
from cardine.shared.constants import ENTRY_ROUTER_SAFEGUARDS
from cardine.shared.errors import CardineError
from cardine.shared.models import ManagedFile
from cardine.templates.markers import CLAUDE_AGENTS_POINTER_MARKER
from cardine.templates.markers import extract_marker_block
from cardine.templates.markers import is_agents_pointer
from cardine.templates.migrations import migration_capability_entries
from cardine.templates.migrations import migration_record_paths
from pathlib import Path
import json
import re


def entry_router_overlay(text: str, path: Path) -> str:
    """Validate the deliberately tiny, non-instructional host overlay."""
    if not text:
        return ""
    if len(text.encode("utf-8")) > 256 or not re.fullmatch(r"<!--[^\n]*-->\n?", text):
        raise CardineError(
            f"{path}: an entry-router host overlay must be one HTML comment of at most 256 UTF-8 bytes"
        )
    return text.rstrip() + "\n"


def render_entry_router(router_text: str, overlay_text: str = "") -> str:
    """Render one generated entry point from the consumer-owned router."""
    return router_text.rstrip() + "\n" + ("\n" + overlay_text if overlay_text else "")


def entry_router_outputs(project_root: Path) -> dict[Path, str]:
    """Return the expected generated entry points, or fail without writing."""
    router = project_root / ENTRY_ROUTER_PATH
    if not router.is_file():
        raise CardineError(f"entry-router source is missing: {router}")
    router_text = router.read_text(encoding="utf-8")
    if len(router_text.encode("utf-8")) > ENTRY_ROUTER_BUDGET_BYTES:
        raise CardineError(
            f"{router}: exceeds the {ENTRY_ROUTER_BUDGET_BYTES}-byte entry-router budget"
        )
    if CLAUDE_AGENTS_POINTER_MARKER in router_text or is_agents_pointer(router_text):
        raise CardineError(f"{router}: a generated entry router must not emit a Claude-to-AGENTS pointer")
    result = {}
    for target, relative_overlay in ENTRY_ROUTER_OVERLAYS.items():
        overlay = project_root / relative_overlay
        overlay_text = entry_router_overlay(overlay.read_text(encoding="utf-8"), overlay) if overlay.is_file() else ""
        output = render_entry_router(router_text, overlay_text)
        if len(output.encode("utf-8")) > ENTRY_ROUTER_BUDGET_BYTES:
            raise CardineError(f"{target}: exceeds the {ENTRY_ROUTER_BUDGET_BYTES}-byte entry-router budget")
        result[Path(target)] = output
    return result


def project_uses_entry_router(project_root: Path) -> bool:
    """Whether the project's top-level agent files are generated outputs."""
    return (project_root / ENTRY_ROUTER_PATH).is_file()


def entry_router_trigger_requirements(
    project_root: Path,
    framework_root: Path,
    pending_migrations: list[str],
    planned_files: list[ManagedFile],
) -> tuple[str, ...]:
    """Report command triggers a pending migration requires in the router.

    The framework template remains the authority for the exact command text
    and routed document, while ENTRY_ROUTER.md remains the only editable input
    in an opted-in consumer. Only literal command triggers are checked here;
    prose routes such as status and audit continue to be governed by the
    explicit entry-router route map.
    """
    if not project_uses_entry_router(project_root):
        return ()
    command_trigger_versions = []
    for path in migration_record_paths(framework_root, pending_migrations):
        data = json.loads(path.read_text(encoding="utf-8"))
        command_trigger_versions.extend(
            version
            for capability, version in migration_capability_entries(data)
            if capability == "command-triggers"
        )
    if not command_trigger_versions:
        return ()

    version = max(command_trigger_versions)
    templates = {
        item.target: item.source
        for item in planned_files
        if item.target in {Path("AGENTS.md"), Path("CLAUDE.md")}
    }
    source = templates.get(Path("AGENTS.md")) or templates.get(Path("CLAUDE.md"))
    if source is None:
        raise CardineError("upgrade plan has no managed entry-point template for command-triggers")
    block = extract_marker_block(source.read_text(encoding="utf-8"), "command-triggers", version)
    if block is None:
        raise CardineError(
            f"entry-point template lacks capability=command-triggers v{version} required by the migration ledger"
        )

    router_text = (project_root / ENTRY_ROUTER_PATH).read_text(encoding="utf-8")
    router_lines = router_text.splitlines()
    problems = []
    for line in block.splitlines():
        stripped = line.strip()
        if not stripped.startswith("- ") or "—" not in stripped:
            continue
        label, route = stripped[2:].split("—", 1)
        triggers = re.findall(r"`([^`]+)`", label)
        if not triggers:
            continue
        targets = [value for value in re.findall(r"`([^`]+)`", route) if value.endswith(".md")]
        if not targets:
            raise CardineError(f"command trigger has no routed Markdown target: {stripped}")
        target = targets[-1]
        for trigger in triggers:
            if any(trigger in router_line and target in router_line for router_line in router_lines):
                continue
            if router_text.count(target) == 1:
                guidance = (
                    f"add `{trigger}` to the existing route line for `{target}`; do not add another "
                    "line because the entry-router audit requires each route target exactly once"
                )
            else:
                guidance = f"add `{trigger}` and route it to `{target}`"
            problems.append(
                f"{ENTRY_ROUTER_PATH}: missing trigger `{trigger}` for `{target}`; {guidance}"
            )
    return tuple(problems)


def audit_entry_router(project_root: Path) -> list[tuple[str, str]]:
    """Audit an opting-in consumer's generated files and explicit route map."""
    if not (project_root / ENTRY_ROUTER_PATH).is_file():
        return []
    results = []
    try:
        outputs = entry_router_outputs(project_root)
    except CardineError as error:
        return [("FAIL", str(error))]
    for target, expected in outputs.items():
        actual = project_root / target
        if not actual.is_file() or actual.read_text(encoding="utf-8") != expected:
            results.append(("FAIL", f"generated entry router drift: {target}; rerun `python3 scripts/dev.py generate-entry-routers --write`"))
    mapping_path = project_root / ENTRY_ROUTER_MAP_PATH
    try:
        mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return results + [("FAIL", f"entry-router route map is missing or invalid: {mapping_path} ({error})")]
    if not isinstance(mapping, dict) or set(mapping) != set(ENTRY_ROUTER_ROUTES):
        results.append(("FAIL", f"entry-router route map must declare exactly: {', '.join(ENTRY_ROUTER_ROUTES)}"))
        return results
    router_text = (project_root / ENTRY_ROUTER_PATH).read_text(encoding="utf-8")
    for route, expected_path in ENTRY_ROUTER_ROUTES.items():
        actual_path = mapping.get(route)
        if actual_path != expected_path:
            results.append(("FAIL", f"entry-router route {route} must target {expected_path}"))
            continue
        if router_text.count(expected_path) != 1:
            results.append(("FAIL", f"entry-router must name {expected_path} exactly once for route {route}"))
        target = project_root / expected_path
        if not target.is_file():
            results.append(("FAIL", f"entry-router route {route} target is missing: {expected_path}"))
            continue
        target_text = target.read_text(encoding="utf-8").lower()
        missing = [token for token in ENTRY_ROUTER_SAFEGUARDS[route] if token not in target_text]
        if missing:
            results.append(
                ("FAIL", f"entry-router route {route} target lacks required safeguard token(s): {', '.join(missing)}")
            )
    return results
