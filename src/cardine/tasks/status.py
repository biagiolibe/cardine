"""Read-only, state-first task status snapshots shared by product consumers."""
from __future__ import annotations

import json
import re
from pathlib import Path

from cardine.tasks.contract_fields import frozen_human_fields, snapshot_record_path
from cardine.shared.errors import CardineError
from cardine.shared.layout import names
from cardine.shared.project import parse_project_declaration
from cardine.tasks.state import STATUSES, TaskStateInvalid, dependency_satisfied, validate_task_state


def _inputs(root: Path, config: dict) -> dict[Path, bytes]:
    paths = {root / names().project_declaration_path}
    paths.update((root / names().tasks_path).glob('*.json'))
    # Record content is not an input: only snapshot paths and their existence matter.
    inputs = {path: path.read_bytes() for path in sorted(paths)}
    for path, content in list(inputs.items()):
        if path.parent != root / names().tasks_path:
            continue
        try:
            human = frozen_human_fields(json.loads(content))
            record = snapshot_record_path(root, human)
            if record.is_file():
                inputs[record] = b""
        except (ValueError, KeyError, TypeError, AttributeError, CardineError):
            pass
    return inputs


def load_task_status(project_root: Path, *, all_tasks: bool = False) -> dict:
    """Read a bounded consistent snapshot; never recover state from Markdown."""
    return load_task_snapshot(project_root, all_tasks=all_tasks)[0]


def load_task_snapshot(project_root: Path, *, all_tasks: bool = False) -> tuple[dict, dict[Path, bytes], dict]:
    """Return the status model, the snapshot bytes and record-presence markers, and the declaration."""
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
        return model, {}, {}
    model['preset'] = config['preset']

    def diagnose(path, error):
        diagnostics.append({'path': str(path.relative_to(root)), 'error': str(error)})

    records = {}
    invalid_records = set()
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
    rows = {}
    priorities = {}
    for task_id, state in sorted(states.items()):
        model['totals'][state['status']] += 1
        model['totals']['total'] += 1
        state_file = root / names().tasks_path / f'{task_id}.json'
        try:
            human = frozen_human_fields(state)
            path = snapshot_record_path(root, human)
        except CardineError as error:
            diagnose(state_file, error)
            invalid_records.add(task_id)
            human = dict(dependencies=[], title=task_id, phase='', priority='')
            path = None
        record = path if path in inputs else None
        if record:
            records[task_id] = record
        else:
            diagnose(state_file, f'missing record for {task_id}')
        priorities[task_id] = human['priority']
        rows[task_id] = {'id': task_id, 'title': human['title'],
                         'status': state['status'], 'record': str(record.relative_to(root)) if record else None,
                         'dependencies': human['dependencies'], 'blocked_by': [], 'startable': False,
                         'phase': human['phase'] or None, 'review': state.get('review', {})}
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
        priority = priorities[row['id']]
        match = re.search(r'P(\d+)', priority)
        return (int(match.group(1)) if match else 999, row['id'])
    model['tasks'] = sorted((row for row in rows.values() if all_tasks or row['status'] not in ('done', 'cancelled')), key=order)
    diagnostics.sort(key=lambda item: (item['path'], item['error']))
    return model, inputs, config


def render_task_status(model: dict) -> str:
    """Render the same filtered model exposed by JSON, including global totals."""
    lines = [f"Preset: {model['preset']}", 'Totals: ' + ', '.join(f"{key}={model['totals'][key]}" for key in (*STATUSES, 'total'))]
    for row in model['tasks']:
        lines.append(f"{row['id']} | {row['title']} | {row['status']} | dependencies: {', '.join(row['dependencies']) or '-'} | blocked_by: {', '.join(row['blocked_by']) or '-'} | startable: {str(row['startable']).lower()}")
    lines.extend(f"Diagnostic: {item['path']}: {item['error']}" for item in model['diagnostics'])
    return '\n'.join(lines)
