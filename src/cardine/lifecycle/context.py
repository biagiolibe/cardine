"""Immutable command location and policy resolution, below lifecycle effects."""
from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from cardine.lifecycle.model import RunLocations
from cardine.shared.errors import CardineError
from cardine.shared.git import canonical_git_common_dir, canonical_project_root, scoped_command
from cardine.tasks.identity import resolve_task_identity
from cardine.worktree.storage import resolve_worktree_root


@scoped_command
def resolve_run_locations(task_id: str, project: Path | None = None, *,
                          cwd: Path | None = None, registered_projects: Iterable[Path] = (),
                          worktree_root: Path | None = None) -> RunLocations:
    """Read locations from either checkout or unique supplied registry entries.

    Registry discovery is supplied by the machine registry reader; this function
    never scans arbitrary directories or creates a registration/configuration.
    """
    def identify(path):
        primary = canonical_project_root(path)
        common = canonical_git_common_dir(path)
        if common != canonical_git_common_dir(primary):
            raise CardineError("project/common-directory identity mismatch")
        identity = resolve_task_identity(primary, task_id, "existing", check_queue_links=False)
        return primary, common, identity

    if project is not None:
        primary, common, identity = identify(project.expanduser().resolve())
    else:
        enclosing = None
        try:
            enclosing = canonical_project_root(cwd or Path.cwd())
        except CardineError:
            pass
        if enclosing is not None:
            primary, common, identity = identify(enclosing)
        else:
            matches = {}
            for candidate in registered_projects:
                try:
                    item = identify(candidate)
                except CardineError:
                    continue
                matches[item[1]] = item
            if len(matches) != 1:
                raise CardineError("missing or ambiguous project/task identity; supply --project")
            primary, common, identity = next(iter(matches.values()))
    root = resolve_worktree_root(worktree_root).path
    from cardine.shared.project import read_project_declaration
    from cardine.lifecycle.receipts import runtime_digest_once
    from cardine.worktree.paths import _task_worktree_path_for_identity
    declaration = read_project_declaration(primary)
    return RunLocations(identity.canonical_id, primary, common, root,
                        _task_worktree_path_for_identity(primary, root, identity),
                        json.dumps(declaration, sort_keys=True) if declaration is not None else None,
                        runtime_digest_once(), identity.task_path.relative_to(primary),
                        identity.handoff_path.relative_to(primary))


