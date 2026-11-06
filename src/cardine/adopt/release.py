"""Pure helpers for releasing Meridian-owned marker blocks."""
from __future__ import annotations

import re
import json
import hashlib
import tempfile
from pathlib import Path

from cardine.shared.errors import CardineError
from cardine.legacy.conversion_reader import read_legacy_project
from cardine.templates.init import plan_init

_MARKER = re.compile(r"<!-- MERIDIAN:(BEGIN(?:\s+[^>]*?)?|END) -->")


def _checked(root: Path, name) -> Path:
    relative = Path(name)
    if relative.is_absolute() or not relative.parts or '..' in relative.parts:
        raise CardineError(f'unsafe adoption path: {name}')
    path = root
    for part in relative.parts:
        path = path / part
        if path.is_symlink():
            raise CardineError(f'refusing a symlink in adoption path: {path}')
    return path


def strip_managed_blocks(text: str) -> str:
    """Remove complete Meridian blocks, preserving every unmarked byte.

    Malformed or nested markers are refused rather than treating project-owned
    prose as managed content.
    """
    parts = []
    cursor = 0
    start = None
    for match in _MARKER.finditer(text):
        marker = match.group(1)
        if marker.startswith("BEGIN"):
            if start is not None:
                raise CardineError("nested Meridian markers")
            parts.append(text[cursor:match.start()])
            start = match.start()
        else:
            if start is None:
                raise CardineError("unmatched Meridian end marker")
            cursor = match.end()
            start = None
    if start is not None:
        raise CardineError("unmatched Meridian begin marker")
    parts.append(text[cursor:])
    return "".join(parts)


def _project_remainder(root: Path, name: str, old: str, manifest: dict) -> str:
    managed = manifest.get('managedFiles', {})
    commands = re.search(r'^## Commands\s*\n.*?(?=^## |\Z)', old, re.M | re.S)
    keep_commands = commands.group(0) if commands and '[' not in commands.group(0) else ''
    if hashlib.sha256(old.encode()).hexdigest() == managed.get(name):
        return keep_commands
    remainder = strip_managed_blocks(old)
    baseline = _checked(root, Path('.meridian/baselines') / str(manifest.get('workflowBaselineVersion', '')) / name)
    if baseline.is_file():
        blocks = re.split(r'\n\s*\n', strip_managed_blocks(baseline.read_text(encoding='utf-8')))
        patterns = [re.escape(' '.join(block.split())).replace(re.escape('[Project Name]'), '.*?') for block in blocks if block.strip()]
        remainder = '\n\n'.join(block for block in re.split(r'\n\s*\n', remainder)
                                if not any(re.fullmatch(pattern, ' '.join(block.split())) for pattern in patterns))
    return remainder


def conversion_outputs(root: Path, framework: Path, plan):
    """Pin the replacement files, task records and releases before any writes."""
    if (root / '.meridian').is_symlink():
        raise CardineError('refusing a symlinked Meridian installation')
    legacy = read_legacy_project(root)
    manifest = json.loads(_checked(root, '.meridian/manifest.json').read_text(encoding='utf-8'))
    config = json.loads(plan.outputs['.cardine/project.json'])
    policy = _checked(root, 'LANGUAGE_POLICY.md')
    text = policy.read_text(encoding='utf-8') if policy.exists() else ''
    match = re.search(r'\*\*Conversation language:\*\*\s*`([^`]+)`', text)
    if not match:
        raise CardineError('adoption requires a declared conversation language')
    with tempfile.TemporaryDirectory(prefix='cardine-adopt-plan-') as scratch:
        initial = plan_init(Path(scratch).resolve() / 'project', framework,
                            name=config['project']['name'], slug=config['project']['slug'],
                            preset=config['preset'], language=match.group(1),
                            task_identity=config['taskIdentity']['mode'], validation=config['validation'])
        outputs = dict(initial.outputs)
    # Existing project prose and the converted records are authoritative.
    for name in ('PROJECT_PLAN.md', 'tasks/QUEUE.md', 'docs/ARCHITECTURE_DECISIONS.md'):
        outputs.pop(name, None)
    for name, content in list(outputs.items()):
        path = _checked(root, name)
        if not path.is_file() or name.startswith('.cardine/'):
            continue
        old = path.read_text(encoding='utf-8')
        if name not in manifest.get('managedFiles', {}) and not _MARKER.search(old):
            outputs.pop(name)
            continue
        remainder = _project_remainder(root, name, old, manifest)
        if remainder.strip():
            outputs[name] = content.rstrip() + b'\n\n' + remainder.encode()
    outputs.update(plan.outputs)
    locations = legacy.locations
    config['locations'] = {'queue': locations.queue.as_posix(),
                           'taskRoots': [path.as_posix() for path in locations.task_roots],
                           'adrLog': locations.adr_log.as_posix(),
                           'handoffRoot': locations.handoff_root.as_posix(),
                           'reviewRoot': locations.review_root.as_posix(),
                           'plan': locations.plan.as_posix()}
    outputs['.cardine/project.json'] = (json.dumps(config, indent=2, sort_keys=True) + '\n').encode()
    queue = _checked(root, legacy.locations.queue)
    lines = queue.read_text(encoding='utf-8').splitlines(keepends=True)
    closed = [lines[row.line - 1] for row in legacy.rows if row.state != 'open']
    archive = _checked(root, 'tasks/QUEUE_ARCHIVE.md')
    if closed:
        existing = archive.read_bytes() if archive.exists() else b'# Queue Archive\n\n'
        outputs['tasks/QUEUE_ARCHIVE.md'] = existing + ''.join(closed).encode()
    budget = _checked(root, 'docs/CONTEXT_BUDGET_POLICY.md')
    if budget.is_file():
        name = 'docs/CONTEXT_READING_POLICY.md'
        remainder = _project_remainder(root, 'docs/CONTEXT_BUDGET_POLICY.md', budget.read_text(encoding='utf-8'), manifest)
        if remainder.strip():
            outputs[name] = outputs[name].rstrip() + b'\n\n' + remainder.encode()
    tasks = {}
    for row in legacy.open_rows:
        matches = [name for name in plan.outputs if Path(name).name == row.task_id + '.md'
                   or Path(name).name.startswith(row.task_id + '-')]
        if len(matches) != 1:
            raise CardineError(f'cannot identify converted task {row.task_id}')
        tasks[row.task_id] = matches[0]
    profile = outputs.get('docs/EXECUTION_EVIDENCE_PROFILE.md')
    if profile is not None:
        digest = hashlib.sha256(profile).hexdigest()
        for name in tasks.values():
            text = outputs[name].decode('utf-8')
            text = re.sub(r'(?m)^(- Profile revision: `sha256:)[0-9a-f]{64}(`)$',
                          lambda match: match.group(1) + digest + match.group(2), text)
            outputs[name] = text.encode('utf-8')
    cardine_manifest = json.loads(outputs['.cardine/manifest.json'])
    declared = {surface['path'] for profile in cardine_manifest.get('capabilityProfiles', {}).values()
                for declaration in profile.get('capabilities', {}).values()
                for surface in declaration.get('managedSurface', [])}
    missing = declared - outputs.keys()
    if missing:
        raise CardineError(f'declared surfaces not written by conversion: {sorted(missing)}')
    cardine_manifest['managedFiles'] = {name: digest for name, digest in cardine_manifest['managedFiles'].items()
                                        if name in outputs}
    outputs['.cardine/manifest.json'] = (json.dumps(cardine_manifest, indent=2, sort_keys=True) + '\n').encode()
    removals = []
    meridian = root / '.meridian'
    directories = ['.meridian']
    for path in sorted(meridian.rglob('*')):
        if path.is_symlink():
            raise CardineError(f'refusing a symlink in Meridian installation: {path}')
        if path.is_file():
            removals.append(path.relative_to(root).as_posix())
        elif path.is_dir():
            directories.append(path.relative_to(root).as_posix())
    if budget.is_file():
        removals.append('docs/CONTEXT_BUDGET_POLICY.md')
    return outputs, tasks, sorted(removals), sorted(directories, key=lambda name: (-len(Path(name).parts), name))
