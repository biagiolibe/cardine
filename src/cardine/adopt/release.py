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


def conversion_outputs(root: Path, framework: Path, plan):
    """Pin the replacement files, task records and releases before any writes."""
    legacy = read_legacy_project(root)
    manifest = json.loads((root / '.meridian/manifest.json').read_text(encoding='utf-8'))
    config = json.loads(plan.outputs['.cardine/project.json'])
    policy = root / 'LANGUAGE_POLICY.md'
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
        path = root / name
        if not path.is_file() or name.startswith('.cardine/'):
            continue
        old = path.read_text(encoding='utf-8')
        if name in ('AGENTS.md', 'CLAUDE.md'):
            baseline = root / '.meridian/baselines' / str(manifest.get('workflowBaselineVersion', '')) / name
            if baseline.is_file():
                base = baseline.read_text(encoding='utf-8')
                first = _MARKER.search(base)
                if first and old.startswith(base[:first.start()]):
                    preamble = old[:first.start()]
                    commands = re.search(r'^## Commands\s*\n.*?(?=^## |\Z)', preamble, re.M | re.S)
                    old = old[first.start():]
                    if commands:
                        old = commands.group(0) + old
        remainder = strip_managed_blocks(old)
        if remainder.strip():
            outputs[name] = content.rstrip() + b'\n\n' + remainder.encode()
    outputs.update(plan.outputs)
    queue = root / legacy.locations.queue
    lines = queue.read_text(encoding='utf-8').splitlines(keepends=True)
    closed = [lines[row.line - 1] for row in legacy.rows if row.state != 'open']
    archive = root / 'tasks/QUEUE_ARCHIVE.md'
    if closed:
        existing = archive.read_bytes() if archive.exists() else b'# Queue Archive\n\n'
        outputs['tasks/QUEUE_ARCHIVE.md'] = existing + ''.join(closed).encode()
    budget = root / 'docs/CONTEXT_BUDGET_POLICY.md'
    if budget.is_file():
        name = 'docs/CONTEXT_READING_POLICY.md'
        remainder = strip_managed_blocks(budget.read_text(encoding='utf-8'))
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
    removals = []
    meridian = root / '.meridian'
    for path in sorted(meridian.rglob('*')):
        if path.is_symlink():
            raise CardineError(f'refusing a symlink in Meridian installation: {path}')
        if path.is_file():
            removals.append(path.relative_to(root).as_posix())
    if budget.is_file():
        removals.append('docs/CONTEXT_BUDGET_POLICY.md')
    return outputs, tasks, sorted(removals)
