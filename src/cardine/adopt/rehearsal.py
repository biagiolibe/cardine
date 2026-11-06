"""Copy-first adoption and its source-bound rehearsal receipt."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
import tempfile

from cardine.adopt.apply import apply_adopt, decode_plan, encode_plan
from cardine.adopt.verify import verify_adoption
from cardine.legacy.conversion_reader import read_legacy_project
from cardine.lifecycle import receipts
from cardine.shared.errors import CardineError
from cardine.shared.git import _run_git
from cardine.worktree.storage import resolve_worktree_root


def _git(root, *args):
    result = _run_git(root, *args)
    if result.returncode:
        raise CardineError(f"rehearsal git failed: {result.stderr.strip()}")
    return result.stdout.strip()


def _binding(root, plan):
    if plan.missing or plan.refusals:
        raise CardineError('adoption plan has missing inputs or refusals')
    if _git(root, 'status', '--porcelain', '--untracked-files=all'):
        raise CardineError('adoption requires a clean project')
    return {'head': _git(root, 'rev-parse', 'HEAD'),
            'tree': _git(root, 'rev-parse', 'HEAD^{tree}'),
            'plan': hashlib.sha256(plan.bytes()).hexdigest(), 'source': str(root)}


def rehearse_adoption(project: Path, plan, framework: Path):
    root, framework = Path(project).resolve(), Path(framework).resolve()
    binding = _binding(root, plan)
    receipt = receipts.host_path('adopt-rehearsal', root)
    # A failed or interrupted new run must not leave an older success usable.
    receipt.unlink(missing_ok=True)
    scratch_root = resolve_worktree_root().path
    scratch_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='adopt-rehearsal-', dir=scratch_root) as temporary:
        scratch = Path(temporary)
        clone = scratch / 'project'
        env = os.environ.copy()
        env.update(HOME=str(scratch / 'home'), XDG_CONFIG_HOME=str(scratch / 'home/config'),
                   CARDINE_WORKTREE_ROOT=str(scratch / 'worktrees'),
                   TMPDIR=str(scratch / 'tmp'), PYTHONPATH=str(framework / 'src'))
        (scratch / 'home').mkdir()
        (scratch / 'tmp').mkdir()
        receipts.boundary('before_rehearsal_clone')
        result = _run_git(None, 'clone', '--no-hardlinks', '--no-local', str(root), str(clone), env=env)
        if result.returncode:
            raise CardineError(f"rehearsal clone failed: {result.stderr.strip()}")
        _git(clone, 'checkout', '--detach', binding['head'])
        receipts.boundary('after_rehearsal_clone')
        expected = len(read_legacy_project(root).open_rows) if plan.case == 'B' else 0
        plan_path = scratch / 'plan.json'
        plan_path.write_text(json.dumps(encode_plan(plan)), encoding='utf-8')
        result = subprocess.run([sys.executable, '-m', 'cardine.adopt.rehearsal',
                                 str(clone), str(plan_path), str(framework)],
                                cwd=clone, env=env, text=True, capture_output=True)
        if result.returncode:
            raise CardineError(f"rehearsal apply failed: {result.stderr.strip()}")
        receipts.boundary('before_rehearsal_verify')
        verified = verify_adoption(clone, framework, expected, env=env)
        if _binding(root, plan) != binding:
            raise CardineError('source changed during rehearsal')
        receipts.boundary('before_rehearsal_receipt')
        receipts._durable(receipt, (json.dumps({'version': 1, 'binding': binding, 'verification': verified}, sort_keys=True) + '\n').encode())
    return verified


def apply_rehearsed_adoption(project: Path, plan, framework: Path):
    root = Path(project).resolve()
    binding = _binding(root, plan)
    receipt = receipts.host_path('adopt-rehearsal', root)
    try:
        saved = json.loads(receipt.read_text())
    except (OSError, ValueError):
        saved = None
    if not isinstance(saved, dict) or saved.get('version') != 1 or saved.get('binding') != binding:
        rehearse_adoption(root, plan, framework)
    if _binding(root, plan) != binding:
        raise CardineError('source changed after rehearsal')
    return apply_adopt(root, plan, framework)


if __name__ == '__main__':
    apply_adopt(Path(sys.argv[1]), decode_plan(json.loads(Path(sys.argv[2]).read_text(encoding='utf-8'))),
                Path(sys.argv[3]))
