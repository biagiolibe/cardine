"""Receipt-covered application of a pinned adoption plan."""
from __future__ import annotations

import base64
import json
from pathlib import Path

from cardine.lifecycle import receipts
from cardine.lifecycle.file_operation import operation
from cardine.shared.atomic import file_digest
from cardine.shared.errors import CardineError
from cardine.adopt.release import conversion_outputs


def _target(root: Path, relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or not path.parts or any(part in ('.', '..') for part in path.parts):
        raise CardineError(f"unsafe adoption path: {relative}")
    target = root / path
    current = root
    for part in path.parts:
        current = current / part
        if current.is_symlink():
            raise CardineError(f"refusing a symlink in adoption path: {current}")
    return target


def _binding(root: Path, plan) -> dict:
    return {'kind': 'adopt', 'anchor': str(root), 'digest': receipts.digest(plan.bytes())}


def _completed(receipt: Path, binding: dict, root: Path, outputs: dict[str, bytes]) -> bool:
    if not receipt.exists():
        return False
    intent = receipts._load_intent(receipt)
    if intent.get('owner') != binding or not intent.get('result'):
        return False
    for name, content in outputs.items():
        record = intent.get('files', {}).get(name)
        if (record is None or record.get('target') != str(_target(root, name))
                or record.get('after') != receipts.digest(content)
                or file_digest(_target(root, name)) != record['after']):
            raise CardineError(f"completed adoption output changed: {name}")
    return True


def _encode_outputs(outputs):
    return {name: base64.b64encode(value).decode('ascii') for name, value in outputs.items()}


def encode_plan(plan) -> dict:
    return {'case': plan.case, 'outputs': _encode_outputs(plan.outputs),
            'diagnostics': list(plan.diagnostics), 'missing': list(plan.missing),
            'refusals': list(plan.refusals),
            'dropped_dependencies': {k: list(v) for k, v in plan.dropped_dependencies.items()}}


def decode_plan(data):
    from cardine.adopt.plan import AdoptPlan
    return AdoptPlan(data['case'], {k: base64.b64decode(v) for k, v in data['outputs'].items()},
                     tuple(data['diagnostics']), tuple(data['missing']), tuple(data['refusals']),
                     {k: tuple(v) for k, v in data['dropped_dependencies'].items()})


def _saved_plan(receipt):
    if not receipt.exists():
        raise CardineError('no interrupted adoption plan; plan adoption first')
    saved = receipts._load_intent(receipt).get('adoption', {}).get('plan')
    if not saved:
        raise CardineError('interrupted adoption receipt lacks its original plan')
    return decode_plan(saved)


def _task_state(root, task_id, record):
    from cardine.tasks.contract import resolve_task_contract
    from cardine.tasks.identity import resolve_task_identity
    from cardine.tasks.state import state_path, validate_task_state
    path = state_path(root, task_id)
    with receipts.task_lock(root, task_id):
        if receipts.pending_operation(root, task_id):
            receipts.replay_operation(root, task_id, kind='creation')
        if path.exists():
            state = json.loads(path.read_bytes())
            receipts.verify_receipts(root, state)
            if state['contract']['recordPath'] != record:
                raise CardineError(f'converted task differs from recorded state: {task_id}')
            return
        identity = resolve_task_identity(root, task_id, 'existing', check_queue_links=False)
        if identity.task_path != root / record:
            raise CardineError(f'converted task path changed: {task_id}')
        content = (root / record).read_bytes()
        contract = resolve_task_contract(root, task_id, text=content.decode(), identity=identity)
        state = {'version': 1, 'task_id': task_id, 'workflow': 'single',
                 'status': 'queued', 'transitions': [], 'contract': contract}
        validate_task_state(state, task_id, 'single')
        receipts.write_operation(root, task_id, state, kind='creation', files={record: content})


def _declare(active, root, name, content, before):
    target = _target(root, name)
    record = active.files.get(name)
    if record is None and file_digest(target) != before:
        raise CardineError(f'adoption input changed: {name}')
    active.declare(name, target, content)
    if active.files[name]['before'] != before:
        raise CardineError(f'adoption input ownership changed: {name}')


def _verify_task(root, task_id, record):
    from cardine.tasks.state import state_path
    path = state_path(root, task_id)
    if not path.is_file():
        raise CardineError(f'completed adoption state is missing: {task_id}')
    state = json.loads(path.read_bytes())
    receipts.verify_receipts(root, state)
    if state['contract']['recordPath'] != record:
        raise CardineError(f'completed adoption state changed: {task_id}')


def _views(root, original_plan):
    from cardine.tasks.status import load_task_snapshot
    from cardine.tasks.status_render import input_digest, render_queue, render_plan_region, splice_region
    model, inputs, config = load_task_snapshot(root, all_tasks=True)
    if model['diagnostics'] or model['preset'] is None:
        raise CardineError(f"cannot render converted tasks: {model['diagnostics']}")
    locations = config.get('locations', {})
    queue = locations.get('queue', 'tasks/QUEUE.md')
    plan = locations.get('plan', 'PROJECT_PLAN.md')
    digest = input_digest(root, inputs, {_target(root, queue), _target(root, plan)})
    region = render_plan_region(model, digest)
    if original_plan and b'<!-- cardine-status:begin -->' not in original_plan:
        original_plan = original_plan.rstrip() + b'\n\n<!-- cardine-status:begin -->\n<!-- cardine-status:end -->\n'
    return {queue: render_queue(model, digest).encode(), plan: splice_region(original_plan, region)}


def apply_adopt(project: Path, plan, framework: Path | None = None) -> bool:
    """Apply the exact plan supplied by the caller, or resume its interruption.

    An interrupted operation can be resumed with ``plan=None``; its recorded
    original plan remains bound to the operation owner.
    """
    root = Path(project).resolve()
    receipt = receipts.host_path('adopt', root)
    if plan is None:
        plan = _saved_plan(receipt)
    if plan.missing or plan.refusals:
        raise CardineError('adoption plan has missing inputs or refusals')
    binding = _binding(root, plan)
    with operation(receipt, binding, root=root) as active:
        old = receipts._load_intent(receipt) if receipt.exists() else None
        if old and old.get('result') and old.get('owner') == binding:
            payload = old.get('adoption')
            outputs = {name: base64.b64decode(value) for name, value in payload['outputs'].items()}
            if _completed(receipt, binding, root, outputs):
                if plan.case == 'B' and (root / '.meridian').exists():
                    raise CardineError('completed adoption directory reappeared: .meridian')
                for name in payload['removals']:
                    if _target(root, name).exists():
                        raise CardineError(f'completed adoption removal reappeared: {name}')
                for name in ('.cardine/tasks', 'tasks/done'):
                    if not _target(root, name).is_dir():
                        raise CardineError(f'completed adoption directory is missing: {name}')
                for task_id, record in sorted(payload['tasks'].items()):
                    _verify_task(root, task_id, record)
                return False
        receipts.boundary('before_adopt_declare')
        payload = active.intent.get('adoption')
        if payload is None:
            from cardine.shared.git import _run_git, git_output
            probe = _run_git(root, 'rev-parse', '--show-toplevel')
            if probe.returncode == 0 and git_output(root, 'status', '--porcelain', '--untracked-files=all'):
                raise CardineError('adoption requires a clean project')
            if plan.case == 'A':
                outputs, tasks, removals, directories = dict(plan.outputs), {}, [], []
            elif plan.case == 'B' and framework is not None:
                outputs, tasks, removals, directories = conversion_outputs(root, Path(framework), plan)
            else:
                raise CardineError('adoption needs a recognized case and framework path')
            paths = set(outputs) | set(removals)
            if plan.case == 'B':
                locations = json.loads(outputs['.cardine/project.json']).get('locations', {})
                paths.update((locations.get('plan', 'PROJECT_PLAN.md'), locations.get('queue', 'tasks/QUEUE.md')))
            before = {name: file_digest(_target(root, name)) for name in paths}
            store = _target(root, '.cardine/tasks')
            if store.exists() and (not store.is_dir() or any(store.iterdir())):
                raise CardineError('adoption requires an empty task state store')
            if tasks and _target(root, '.cardine/receipt-authority.json').exists():
                raise CardineError('adoption conflicts with existing receipt authority')
            for name in outputs:
                if before[name] is not None and (plan.case == 'A' or name.startswith('.cardine/')):
                    raise CardineError(f'adoption conflicts with existing path: {name}')
            payload = {'outputs': _encode_outputs(outputs), 'tasks': tasks, 'removals': removals,
                       'directories': directories, 'before': before,
                       'plan': encode_plan(plan)}
            if plan.case == 'B':
                old_plan = _target(root, locations.get('plan', 'PROJECT_PLAN.md'))
                payload['original_plan'] = base64.b64encode(old_plan.read_bytes() if old_plan.exists() else b'').decode('ascii')
            active.intent['adoption'] = payload
            active._save()
        outputs = {name: base64.b64decode(value) for name, value in payload['outputs'].items()}
        for name, content in sorted(outputs.items()):
            _declare(active, root, name, content, payload['before'][name])
        for name in payload['removals']:
            _declare(active, root, name, None, payload['before'][name])
        for name in ('.cardine/tasks', 'tasks/done'):
            directory = _target(root, name)
            if not directory.exists() or str(directory) in active.intent.get('paths', {}):
                active.directory(str(directory), directory, 0o755)
        for name, content in sorted(outputs.items()):
            receipts.boundary(f'before_adopt_write:{name}')
            active.run(name, content)
        if payload['tasks']:
            authority = root / '.cardine/receipt-authority.json'
            if not authority.exists():
                receipts.boundary('before_adopt_write:.cardine/receipt-authority.json')
                receipts.authorize_project(root, accepted=receipts.observed_authority(root), new=True)
            for task_id, record in sorted(payload['tasks'].items()):
                receipts.boundary(f'before_adopt_state:{task_id}')
                _task_state(root, task_id, record)
        if plan.case == 'B':
            if 'views' not in payload:
                original = base64.b64decode(payload['original_plan'])
                payload['views'] = _encode_outputs(_views(root, original or None))
                payload['outputs'].update(payload['views'])
                active._save()
            for name, value in sorted(payload['views'].items()):
                content = base64.b64decode(value)
                _declare(active, root, name, content, payload['before'][name])
                receipts.boundary(f'before_adopt_write:{name}')
                active.run(name, content)
        for name in payload['removals']:
            receipts.boundary(f'before_adopt_release:{name}')
            active.run(name, None)
        for name in payload['directories']:
            directory = _target(root, name)
            receipts.boundary(f'before_adopt_release:{name}')
            active.effect('release-directory:' + name,
                          lambda path=directory: path.rmdir() if path.exists() else None,
                          lambda path=directory: not path.exists())
        receipts.boundary('before_adopt_result')
    receipts.boundary('after_adopt_result')
    return True
