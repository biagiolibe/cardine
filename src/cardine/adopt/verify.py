"""Verify a converted project in its disposable rehearsal checkout."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess

from cardine.shared.errors import CardineError
from cardine.shared.git import _run_git
from cardine.templates.init import apply_init, plan_init


def _run(args, root, *, env=None):
    result = (_run_git(root, *args[1:], env=env) if args[0] == 'git' else
              subprocess.run(args, cwd=root, env=env, text=True, capture_output=True))
    if result.returncode:
        raise CardineError(f"rehearsal command failed ({result.returncode}): {args!r}\n{result.stdout}{result.stderr}")
    return result.stdout


def _audit(root, command, env):
    result = subprocess.run(command + ['audit', '--project', str(root)], cwd=root,
                            env=env, text=True, capture_output=True)
    pairs, summaries = [], []
    for line in result.stdout.splitlines():
        fields = line.split()
        if fields and fields[0] == 'SUMMARY':
            summaries.append(line)
        elif len(fields) >= 2 and fields[0] in {'PASS', 'FAIL', 'ADVISORY', 'UNVERIFIED', 'NOT_APPLICABLE'}:
            pairs.append((fields[0], fields[1]))
    if result.returncode not in (0, 1) or len(summaries) != 1 or not pairs:
        raise CardineError(f'audit failed or could not be evaluated ({result.returncode}): {result.stdout}{result.stderr}')
    return {'exit': result.returncode, 'summary': summaries[0], 'pairs': sorted(set(pairs))}


def _compare_audits(copy, reference):
    extra = set(copy['pairs']) - set(reference['pairs'])
    bad = sorted(pair for pair in copy['pairs'] if pair[0] == 'FAIL' or
                 (pair[0] != 'PASS' and pair in extra))
    if bad:
        raise CardineError(f'rehearsal audit failed: {bad}')


def verify_adoption(root: Path, framework: Path, expected_tasks: int, *, env=None):
    """Audit, inspect all converted tasks, start each, and run declared baseline."""
    root, framework = Path(root), Path(framework)
    command = [str(framework / 'bin/cardine')]
    config = json.loads((root / '.cardine/project.json').read_text())
    validation = config['validation']
    reference = root.parent / 'reference'
    initial = plan_init(reference, framework, name=config['project']['name'],
                        slug=config['project']['slug'], preset=config['preset'], language='English',
                        task_identity=config['taskIdentity']['mode'], validation=validation)
    apply_init(initial)
    reference_audit = _audit(reference, command, env)
    copy_audit = _audit(root, command, env)
    _compare_audits(copy_audit, reference_audit)
    status = json.loads(_run(command + ['status', '--all', '--project', str(root), '--format', 'json'], root, env=env))
    tasks = status['tasks']
    if status['diagnostics'] or len(tasks) != expected_tasks:
        raise CardineError(f"rehearsal task count or status mismatch: {status['diagnostics']}")
    for ident in validation['baseline']:
        _run(['sh', '-c', validation['commands'][ident]], root, env=env)
    _run(['git', 'switch', '-C', 'main'], root, env=env)
    _run(['git', 'add', '-A'], root, env=env)
    _run(['git', 'add', '-f', '.cardine'], root, env=env)
    _run(['git', '-c', 'user.name=Cardine rehearsal', '-c',
          'user.email=rehearsal@example.invalid', 'commit', '--allow-empty', '-qm', 'Rehearse adoption'], root, env=env)
    for task in tasks:
        task_id = task['id']
        prepared = _run(command + ['worktree', 'prepare', task_id, '--project', str(root), '--format', 'json'], root, env=env)
        worktree = Path(json.loads(prepared)['worktree'])
        _run(command + ['execution', 'start', task_id, '--project', str(worktree), '--format', 'json'], worktree, env=env)
    # Use a distinct structured identity in both supported identity modes.
    existing = {task['id'].upper() for task in tasks}
    ordinal = 1
    while f'M999999-REHEARSAL-{ordinal:03d}' in existing and ordinal < 999:
        ordinal += 1
    task_id = f'M999999-REHEARSAL-{ordinal:03d}'
    proposal = root.parent / 'rehearsal-task.md'
    proposal.write_text(f'ID: {task_id}\n## Objective\nVerify task creation.\n'
                        '## Acceptance Criteria\nVerified.\n## Validation\nnone\n## Dependencies\nnone\n')
    _run(command + ['task', 'new', task_id, '--record', str(proposal), '--quick', '--project', str(root)], root, env=env)
    return {'audit': {'copy': copy_audit, 'reference': reference_audit},
            'tasks': len(tasks), 'baseline': list(validation['baseline']), 'task_new': task_id}
