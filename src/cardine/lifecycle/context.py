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




def registration_recovery(locations):
    """Describe the explicit Git step needed before preparing from main."""
    import shlex
    from cardine.lifecycle.engine import command_reference, envelope
    from cardine.shared.git import _run_git
    from cardine.tasks.state import state_path
    from cardine.tasks.status import registration_missing_from_main
    root = locations.primary
    paths = (root / locations.record_path, state_path(root, locations.task_id))
    missing = registration_missing_from_main(root, paths)
    if not missing:
        return None
    all_paths = list(missing)
    branch = _run_git(root, 'branch', '--show-current').stdout.strip()
    staged = all(_run_git(root, 'cat-file', '-e', ':' + path).returncode == 0 for path in all_paths)
    if branch != 'main':
        # Preserve paths that exist only on this branch without overwriting
        # working files left by the switch. Each command remains visible.
        switch = shlex.join(['git', '-C', str(root), 'switch', 'main'])
        restores = []
        for path in missing:
            target = shlex.quote(str(root / path))
            restore = shlex.join(['git', '-C', str(root), 'restore', '--source', branch, '--worktree', '--', path])
            restores.append(f'(test -e {target} || {restore})')
        argv = ['sh', '-c', ' && '.join([switch, *restores])]

    elif not staged:
        argv = ['git', '-C', str(root), 'add', '--', *all_paths]
    else:
        argv = ['git', '-C', str(root), 'commit', '-m', f'Register task {locations.task_id}', '--', *all_paths]
    retry = shlex.join(['cardine', 'run', locations.task_id, '--project', str(root)])
    reason = ('Registration missing from main: ' + ', '.join(missing)
              + '. Stage and commit the missing registration files on main, push when required by the workflow, then retry: ' + retry)
    return envelope(locations.task_id, str(root), step='contract', outcome='next',
                    action='publish-registration', next_command=command_reference(argv, reason),
                    diagnostics=[{'code': 'REGISTRATION_UNCOMMITTED', 'message': reason}])
