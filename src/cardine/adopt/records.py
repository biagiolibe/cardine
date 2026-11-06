"""Pure translation of Meridian task records into Cardine creation input."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re

from cardine.lifecycle.scope import normalize_surface
from cardine.tasks.contract import _contract_field, _dependencies


@dataclass(frozen=True)
class RecordTranslation:
    text: str | None
    diagnostics: tuple[str, ...]
    dropped_dependencies: tuple[str, ...]
    dropped_validation: tuple[str, ...] = ()


def _section(text: str, name: str):
    return re.search(rf'^## {re.escape(name)}\s*\n(.*?)(?=^## |\Z)', text,
                     re.MULTILINE | re.DOTALL | re.IGNORECASE)


def _replace(text: str, match, name: str, body: str) -> str:
    return text[:match.start()] + f'## {name}\n\n{body}\n\n' + text[match.end():]


def _paths(body: str) -> list[str]:
    paths = []
    for line in body.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith('|'):
            cells = [cell.strip() for cell in line.strip('|').split('|')]
            if all(re.fullmatch(r':?-+:?', cell) for cell in cells):
                continue
            if cells[0].lower() in ('file', 'path', 'files'):
                continue
            line = cells[0]
        elif line.startswith('- '):
            line = line[2:].strip()
        # Each entry must consist solely of backtick paths or one bare path.
        tokens = re.findall(r'`([^`]+)`', line)
        if tokens:
            if re.sub(r'`[^`]+`|[,\s]', '', line):
                raise ValueError(f'not a path entry: {line}')
        else:
            tokens = [line]
        if any(any(c.isspace() for c in token) for token in tokens):
            raise ValueError(f'not a path entry: {line}')
        paths.extend(tokens)
    if not paths:
        raise ValueError('no paths declared')
    return normalize_surface(paths)


def translate_record(text: str, *, open_ids, closed_ids, profile: bytes | None = None) -> RecordTranslation:
    """Translate a record without I/O; unresolved input produces diagnostics.

    The caller supplies the complete sets of open and closed queue IDs. A result
    with diagnostics has no creation input, so incomplete records cannot be used
    accidentally. Dropped closed dependencies remain visible to the caller.
    """
    diagnostics = []
    dropped = []
    result = text
    dependencies = _section(result, 'Dependencies')
    if dependencies:
        try:
            values = _dependencies(result)
            unknown = [value for value in values if value not in open_ids and value not in closed_ids]
            if unknown:
                diagnostics.append('unknown dependencies: ' + ', '.join(unknown))
            dropped = [value for value in values if value in closed_ids]
            kept = [value for value in values if value not in closed_ids]
            result = _replace(result, dependencies, 'Dependencies',
                              '- Depends on: ' + (', '.join(f'`{x}`' for x in kept) or 'None'))
        except ValueError as error:
            diagnostics.append(str(error))
    relevant = _section(result, 'Relevant Files')
    if relevant:
        try:
            paths = _paths(relevant.group(1))
            existing = _section(result, 'Expected code surface')
            if existing:
                diagnostics.append('Expected code surface already exists; reconcile it with Relevant Files')
            else:
                result += '\n## Expected code surface\n\n' + ''.join(f'- `{p}`\n' for p in paths)
        except ValueError as error:
            diagnostics.append(f'Relevant Files: {error}')
    validation = _section(result, 'Validation')
    if validation:
        lines = []
        dropped_validation = []
        commands = 0
        for line in validation.group(1).splitlines(keepends=True):
            content = line.rstrip('\r\n')
            if not content.startswith('- '):
                lines.append(line)
                continue
            named = re.fullmatch(r'- `([^`]+)`: `([^`]+)`', content)
            plain = re.fullmatch(r'- `([^`]+)`', content)
            if named:
                ident, command = named.groups()
            elif plain:
                command = plain.group(1)
                ident = 'adopt-' + hashlib.sha256(command.encode()).hexdigest()[:16]
            else:
                diagnostics.append(f'Validation: cannot translate {content!r}')
                continue
            if re.match(r'^meridian(?:\s|$)', command):
                dropped_validation.append(command)
                continue
            commands += 1
            ending = line[len(content):]
            lines.append(f'- `{ident}`: `{command}`' + ending)
        if commands:
            result = result[:validation.start(1)] + ''.join(lines) + result[validation.end(1):]
        else:
            diagnostics.append('Validation: no translatable commands')
    else:
        dropped_validation = []
    if profile is not None:
        # The profile bytes are supplied by the caller; no reconcile mutation is
        # needed between task creation and the first start.
        old = _section(result, 'Execution contract — resolved')
        if old:
            result = result[:old.start()] + result[old.end():]
        digest = hashlib.sha256(profile).hexdigest()
        result += (f'\n## Execution contract — resolved\n\n'
                   f'- Profile source: `docs/EXECUTION_EVIDENCE_PROFILE.md`\n'
                   f'- Profile revision: `sha256:{digest}`\n'
                   '- Execution commands: `required via cardine execution`\n')
    for field in ('ID', 'Dependencies', 'Validation', 'Objective', 'Acceptance Criteria'):
        if not _contract_field(result, field):
            diagnostics.append(f'missing {field}')
    if (_contract_field(result, 'Category') or '').lower() != 'quick':
        for field in ('Priority', 'Estimate', 'Out of scope'):
            if not _contract_field(result, field):
                diagnostics.append(f'missing {field}')
        if not (_contract_field(result, 'Relevant Files') or _contract_field(result, 'Technical Context')):
            diagnostics.append('missing Relevant Files or Technical Context')
    return RecordTranslation(None if diagnostics else result, tuple(diagnostics), tuple(dropped), tuple(dropped_validation))
