"""Read-only, state-first task status snapshots shared by product consumers."""
from __future__ import annotations

import json
import re
from pathlib import Path

from cardine.shared.errors import CardineError
from cardine.shared.layout import names
from cardine.shared.project import parse_project_declaration
from cardine.tasks.state import STATUSES, TaskStateInvalid, dependency_satisfied, validate_task_state


def _field(text: str, name: str) -> str:
    match = re.search(rf"^(?:>\s*)?(?:-\s*)?(?:\*\*)?{name}(?:\*\*)?:\s*(.*)$", text, re.M | re.I)
    return match.group(1).strip().strip('`') if match else ""


def _inputs(root: Path, config: dict) -> dict[Path, bytes]:
    paths = {root / names().project_declaration_path}
    paths.update((root / names().tasks_path).glob('*.json'))
    locations = config.get('locations', {})
    excluded = {'QUEUE.md', 'QUEUE_ARCHIVE.md', 'QUEUE_TEMPLATE.md', 'TASK_BLUEPRINT.md'}
    for directory in locations.get('taskRoots', ['tasks']):
        for path in (root / directory).rglob('*.md'):
            if path.name not in excluded and not {'handoffs', 'reviews'}.intersection(path.relative_to(root / directory).parts):
                paths.add(path)
    return {path: path.read_bytes() for path in sorted(paths)}


def _dependencies(text: str) -> list[str]:
    section = re.search(r'^## Dependencies\s*\n(.*?)(?=^## |\Z)', text, re.M | re.S)
    if not section:
        return []
    body = section.group(1)
    raw = _field(body, 'Depends on') or body.strip()
    raw = re.sub(r'\[([^]]+)\]\([^)]+\)', r'\1', raw)
    result = []
    for item in re.split(r'[,\n]', raw):
        item = item.strip().removeprefix('- ').strip().strip('`').strip()
        if item.lower().strip(' .') in ('', 'none', '—', '-'):
            continue
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', item):
            raise ValueError(f'invalid dependency declaration: {item!r}')
        if item not in result:
            result.append(item)
    return result


def load_task_status(project_root: Path, *, all_tasks: bool = False) -> dict:
    """Read a bounded consistent snapshot; never recover state from Markdown."""
    root = Path(project_root).resolve()
    diagnostics = []
    model = {'version': 1, 'preset': None, 'totals': {**dict.fromkeys(STATUSES, 0), 'total': 0},
             'tasks': [], 'diagnostics': diagnostics}
    config_path = root / names().project_declaration_path
    try:
        for attempt in range(2):
            config_bytes = config_path.read_bytes()
            config = parse_project_declaration(json.loads(config_bytes.decode('utf-8')))
            inputs = _inputs(root, config)
            if inputs.get(config_path) == config_bytes and inputs == _inputs(root, config):
                break
        else:
            raise ValueError('inputs changed during snapshot; retry status')
        # Creation publishes a pair under a lock; readers must not accept a partial pair.
        if (root / names().project_directory / 'task-creation.lock').exists():
            raise ValueError('task creation is in progress; retry status')
    except (OSError, UnicodeError, ValueError, CardineError) as error:
        diagnostics.append({'path': str(config_path.relative_to(root)), 'error': str(error)})
        return model
    model['preset'] = config['preset']

    def diagnose(path, error):
        diagnostics.append({'path': str(path.relative_to(root)), 'error': str(error)})

    records = {}
    invalid_records = set()
    for path, content in inputs.items():
        if path.suffix != '.md':
            continue
        try:
            text = content.decode('utf-8')
            task_id = _field(text, 'ID')
            if not task_id:
                continue
            if task_id in records:
                invalid_records.add(task_id)
                diagnose(path, f'duplicate task ID {task_id}')
                continue
            records[task_id] = (path, text)
        except UnicodeError as error:
            diagnose(path, error)
    states = {}
    for path, content in inputs.items():
        if path.parent != root / names().tasks_path:
            continue
        try:
            state = json.loads(content.decode('utf-8'))
            validate_task_state(state, path.stem, 'single', spike='outcome' in state)
            states[path.stem] = state
        except (ValueError, UnicodeError, TaskStateInvalid) as error:
            diagnose(path, error)
    for task_id, (path, _) in records.items():
        if task_id not in states:
            diagnose(path, f'missing or invalid state for {task_id}')
    rows = {}
    for task_id, state in sorted(states.items()):
        model['totals'][state['status']] += 1
        model['totals']['total'] += 1
        record = records.get(task_id)
        if record is None:
            diagnose(root / names().tasks_path / f'{task_id}.json', f'missing record for {task_id}')
        path, text = record or (root / names().tasks_path / f'{task_id}.json', '')
        try:
            dependencies = _dependencies(text)
        except ValueError as error:
            diagnose(path, error)
            invalid_records.add(task_id)
            dependencies = []
        title = re.search(r'^#\s+(.+)$', text, re.M)
        rows[task_id] = {'id': task_id, 'title': title.group(1) if title else task_id,
                         'status': state['status'], 'record': str(path.relative_to(root)) if record else None,
                         'dependencies': dependencies, 'blocked_by': [], 'startable': False,
                         'phase': _field(text, 'Phase') or None, 'review': state.get('review', {})}
    # Reachability detects every member of a cycle without recursion depth limits.
    cyclic = set()
    for task_id in rows:
        pending = list(rows[task_id]['dependencies'])
        seen = set()
        while pending:
            dependency = pending.pop()
            if dependency == task_id:
                cyclic.add(task_id)
                break
            if dependency not in seen and dependency in rows:
                seen.add(dependency)
                pending.extend(rows[dependency]['dependencies'])
    for task_id, row in rows.items():
        path = root / row['record'] if row['record'] else root / names().tasks_path / f'{task_id}.json'
        for dependency in row['dependencies']:
            if dependency not in states:
                diagnose(path, f'missing or invalid dependency {dependency}')
            if dependency not in states or not dependency_satisfied(states[dependency]) or dependency in invalid_records or dependency in cyclic:
                row['blocked_by'].append(dependency)
        if task_id in cyclic:
            diagnose(path, f'dependency cycle involving {task_id}')
        row['startable'] = (row['status'] == 'queued' and not row['blocked_by']
                            and task_id not in cyclic | invalid_records and task_id in records)
    def order(row):
        priority = _field(records.get(row['id'], (None, ''))[1], 'Priority')
        match = re.search(r'P(\d+)', priority)
        return (int(match.group(1)) if match else 999, row['id'])
    model['tasks'] = sorted((row for row in rows.values() if all_tasks or row['status'] not in ('done', 'cancelled')), key=order)
    diagnostics.sort(key=lambda item: (item['path'], item['error']))
    return model


def render_task_status(model: dict) -> str:
    """Render the same filtered model exposed by JSON, including global totals."""
    lines = [f"Preset: {model['preset']}", 'Totals: ' + ', '.join(f"{key}={model['totals'][key]}" for key in (*STATUSES, 'total'))]
    for row in model['tasks']:
        lines.append(f"{row['id']} | {row['title']} | {row['status']} | dependencies: {', '.join(row['dependencies']) or '-'} | blocked_by: {', '.join(row['blocked_by']) or '-'} | startable: {str(row['startable']).lower()}")
    lines.extend(f"Diagnostic: {item['path']}: {item['error']}" for item in model['diagnostics'])
    return '\n'.join(lines)
