"""Developer re-acceptance of this checkout's local receipt authority.

Tracked task state carries only portable authority (policy and accepted main).
The local, ignored `receipt-authority.json` binds this checkout, its Git common
directory, the worktree root, and the executing runtime. After a fresh clone or a
Cardine update, the developer re-accepts it here once; nothing in task JSON can
grant it (decision 14, amended on 2026-11-07).
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import sys

from cardine.lifecycle import receipts
from cardine.shared.errors import CardineError
from cardine.shared.layout import names


@dataclass(frozen=True)
class AuthorizationPlan:
    status: str  # ready, approval-required, or blocked
    path: Path
    accepted: dict | None
    changes: tuple[str, ...]
    detail: str


def _task_states(root: Path):
    directory = root / names().tasks_path
    # Intents and staged files start with a dot; only `<ID>.json` is task state.
    for path in sorted(directory.glob('*.json')) if directory.is_dir() else ():
        if not path.name.startswith('.'):
            yield path.stem, path


def plan_authorization(project: Path) -> AuthorizationPlan:
    """Read-only: what re-acceptance would write, after verifying every task state."""
    root = Path(project).resolve()
    from cardine.shared.git import primary_project_root
    if Path(primary_project_root(root)).resolve() != root:
        return AuthorizationPlan('blocked', root, None, (), 'run authorize from the primary checkout')
    path = receipts._local_authority_path(root)
    observed = receipts.observed_authority(root)
    try:
        current = json.loads(path.read_bytes()) if path.exists() else None
    except ValueError:
        current = None
    if isinstance(current, dict):
        try:
            receipts.require_authority(root)
            return AuthorizationPlan('ready', path, None, (), 'local receipt authority is accepted')
        except CardineError:
            pass
    changes = tuple(sorted(key for key in observed if not isinstance(current, dict)
                           or current.get(key) != observed[key]))
    main = observed['accepted_main']
    if main:
        policy = receipts._run_git(str(root), 'show', f"{main}:{names().project_declaration_path}", text=False)
        if policy.returncode == 0 and receipts.digest(policy.stdout) != observed['policy']:
            return AuthorizationPlan('blocked', path, None, changes,
                                     'project declaration differs from main; commit or restore it first')
    accepted = dict(observed)
    if isinstance(current, dict) and all(current.get(key) == observed[key]
                                         for key in ('project', 'common', 'root', 'worktree_root', 'policy')):
        # Same checkout and policy: keep the accepted base when it is still in main's history,
        # so bindings of operations already in progress keep matching.
        base = current.get('accepted_main')
        if base and observed['accepted_main'] and receipts._run_git(
                str(root), 'merge-base', '--is-ancestor', str(base), str(observed['accepted_main']),
                text=False).returncode == 0:
            accepted['accepted_main'] = base
            changes = tuple(key for key in changes if key != 'accepted_main')
    for task_id, state_file in _task_states(root):
        try:
            state = json.loads(state_file.read_bytes())
            pending = receipts.pending_operation(root, task_id) or state.get('run', {}).get('pending') is not None
            if not pending:
                receipts.verify_receipts(root, state, artifacts=False, accepted=accepted)
        except (CardineError, KeyError, TypeError, ValueError, AttributeError) as error:
            return AuthorizationPlan('blocked', path, None, changes, f'task {task_id}: {error}')
        if pending:
            return AuthorizationPlan('blocked', path, None, changes,
                                     f'task {task_id} has a pending operation; finish it with the runtime that started it')
    return AuthorizationPlan('approval-required', path, accepted, changes,
                             'accepts this checkout and runtime for the verified task states')


def _confirm(plan: AuthorizationPlan) -> str | None:
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return 'authorize --apply needs the developer terminal'
    expected = 'authorize ' + str(plan.accepted['accepted_main'])[:12]
    print(f"Type '{expected}' to accept; anything else refuses.", flush=True)
    try:
        typed = sys.stdin.readline()
    except (OSError, UnicodeDecodeError):
        typed = ''
    return None if typed.strip() == expected else 'confirmation did not match'


def apply_authorization(plan: AuthorizationPlan, *, confirm=_confirm) -> bool:
    if plan.status == 'ready':
        return False
    if plan.status != 'approval-required' or plan.accepted is None:
        raise CardineError(f'authorize is blocked: {plan.detail}')
    if plan_authorization(plan.path.parents[1]).accepted != plan.accepted:
        raise CardineError('authority changed since it was planned; rerun authorize --check')
    refusal = confirm(plan)
    if refusal:
        raise CardineError(refusal)
    receipts._durable(plan.path, receipts.encoded(plan.accepted))
    receipts.require_authority(plan.path.parents[1])
    return True


def print_authorization_plan(plan: AuthorizationPlan) -> None:
    print(f"receipt-authority: {plan.status} ({plan.path})")
    if plan.changes:
        print("changed: " + ", ".join(plan.changes))
    print(f"detail: {plan.detail}")
