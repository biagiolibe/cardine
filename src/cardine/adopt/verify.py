"""Verify a converted project in its disposable rehearsal checkout."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess

from cardine.shared.errors import CardineError
from cardine.tasks.status import load_task_status


def _run(args, root, *, env=None):
    result = subprocess.run(args, cwd=root, env=env, text=True, capture_output=True)
    if result.returncode:
        raise CardineError(f"rehearsal command failed ({result.returncode}): {args!r}\n{result.stdout}{result.stderr}")
    return result.stdout


def verify_adoption(root: Path, framework: Path, expected_tasks: int, *, env=None):
    """Audit, inspect all converted tasks, start each, and run declared baseline."""
    root, framework = Path(root), Path(framework)
    command = [str(framework / 'bin/cardine')]
    output = _run(command + ['audit', '--project', str(root)], root, env=env)
    model = load_task_status(root, all_tasks=True)
    if model['diagnostics'] or len(model['tasks']) != expected_tasks:
        raise CardineError(f"rehearsal task count or status mismatch: {model['diagnostics']}")
    config = json.loads((root / '.cardine/project.json').read_text())
    validation = config['validation']
    for ident in validation['baseline']:
        _run(['sh', '-c', validation['commands'][ident]], root, env=env)
    # The actual start gate requires committed, clean task worktrees.
    _run(['git', 'add', '-A'], root, env=env)
    _run(['git', '-c', 'user.name=Cardine rehearsal', '-c',
          'user.email=rehearsal@example.invalid', 'commit', '--allow-empty', '-qm', 'Rehearse adoption'], root, env=env)
    for task in model['tasks']:
        task_id = task['id']
        prepared = _run(command + ['worktree', 'prepare', task_id, '--project', str(root), '--format', 'json'], root, env=env)
        worktree = Path(json.loads(prepared)['worktree'])
        _run(command + ['execution', 'start', task_id, '--project', str(worktree), '--format', 'json'], worktree, env=env)
    return {'audit': output, 'tasks': len(model['tasks']), 'baseline': list(validation['baseline'])}
