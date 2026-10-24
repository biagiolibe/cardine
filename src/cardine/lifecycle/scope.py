"""Frozen implementation surfaces, independent of editable task prose."""
from pathlib import PurePosixPath
import fnmatch
import re

from cardine.shared.git import git_output
from cardine.stops.render import stop_error


def normalize_surface(paths):
    result = []
    for value in paths:
        path = PurePosixPath(value)
        if (not value or value == '.' or path.is_absolute() or '..' in path.parts
                or '\\' in value or path.as_posix() != value or '\0' in value
                or any(part == '.git' for part in path.parts)):
            raise ValueError(f'unsafe expected surface: {value!r}')
        if value not in result:
            result.append(value)
    return result


def parse_surface(text):
    """Creation/update adapter: accept path/glob bullets, never infer prose authority."""
    match = re.search(r'^## Expected code surface\s*\n(.*?)(?=^## |\Z)', text,
                      re.MULTILINE | re.DOTALL | re.IGNORECASE)
    if not match:
        return []
    paths = []
    for line in match.group(1).splitlines():
        value = line.strip().removeprefix('- ').strip()
        if value.startswith('`') and value.endswith('`'):
            value = value[1:-1]
        # Narrative declarations remain legacy inputs, not unattended authority.
        if value and not any(char.isspace() for char in value) and not value.startswith('['):
            paths.append(value)
    return normalize_surface(paths)


def _matches(path, pattern):
    """Segment-aware globbing: '*' cannot silently authorize a nested component."""
    parts, patterns = path.split('/'), pattern.split('/')
    def match(items, rules):
        if not rules:
            return not items
        if rules[0] == '**':
            return match(items, rules[1:]) or bool(items) and match(items[1:], rules)
        return bool(items) and fnmatch.fnmatchcase(items[0], rules[0]) and match(items[1:], rules[1:])
    return match(parts, patterns)


def changed_paths(root, base):
    # Disabling rename detection includes both ends, even for a move back to an
    # unchanged blob. NUL delimiters preserve spaces, newlines and quoted names.
    paths = set(git_output(root, 'diff', '--no-renames', '--name-only', '-z', base, '--').split('\0'))
    paths.update(git_output(root, 'ls-files', '--others', '--exclude-standard', '-z').split('\0'))
    return paths - {''}


def enforce_scope(root, state, base, *, owned=()):
    """Read-only check, reused before delivery, validation, review and staging."""
    def reject(detail):
        raise stop_error('SCOPE_CHANGE_REQUIRED', detail, task_id=state['task_id'], project=root)
    try:
        patterns = normalize_surface(state['contract'].get('expectedCodeSurface', []))
    except ValueError as error:
        reject(str(error))
    if not patterns:
        reject('unattended work requires a frozen Expected code surface')
    paths = changed_paths(root, base)
    for name in sorted(paths):
        try:
            normalize_surface([name])
        except ValueError as error:
            reject(str(error))
        path = root / name
        # Inspect every existing ancestor, including deleted targets below links.
        for parent in (path, *path.parents):
            if parent == root:
                break
            if parent.is_symlink() and not parent.resolve().is_relative_to(root.resolve()):
                reject(f'symlink escapes the project: {name}')
        if name not in owned and not any(_matches(name, pattern) for pattern in patterns):
            reject(f'path outside expected surface: {name}')
    return paths - set(owned)


def enforce_execution_scope(root, task_id, *, base=None, state=None):
    """Interactive legacy snapshots may omit the surface; frozen surfaces always bind."""
    from cardine.lifecycle.execution import _execution_owned_paths, _execution_state
    from cardine.worktree.checkout import inspect_task_worktree
    from cardine.shared.git import canonical_project_root
    state = state if state is not None else _execution_state(root, task_id)
    if not state['contract'].get('expectedCodeSurface'):
        return
    if base is None:
        inspection, _ = inspect_task_worktree(task_id, None, canonical_project_root(root),
                                              require_effective_worktree=False)
        base = str(inspection['base_commit'])
    return enforce_scope(root, state, base, owned=_execution_owned_paths(root, task_id))
