"""Terminal onboarding and explicit publication of its planned paths."""
from __future__ import annotations

import json
import shlex
import sys
from pathlib import Path

from cardine.adopt.plan import plan_adopt
from cardine.adopt.release import conversion_outputs
from cardine.adopt.rehearsal import apply_rehearsed_adoption
from cardine.lifecycle.control import _interactive
from cardine.shared import terminal
from cardine.shared.errors import CardineError
from cardine.shared.git import _run_git
from cardine.shared.project_guide import _project_option
from cardine.shared.project_defaults import test_validation
from cardine.templates.init import apply_init, plan_init


def _git(root, *args):
    result = _run_git(root, *args)
    if result.returncode:
        raise CardineError(result.stderr.strip() or result.stdout.strip() or 'git failed')
    return result.stdout


def _confirm(question):
    return input(f'{question} [y/N] ').strip().lower() in ('y', 'yes')


def interactive_init(arguments, framework: Path) -> int:
    if not _interactive():
        print('error: interactive init requires a TTY on stdin and stdout; use --check or --apply', file=sys.stderr)
        return 2
    try:
        root = arguments.project.resolve()
        validation = json.loads(arguments.validation.read_text(encoding='utf-8')) if arguments.validation else None
        flags = dict(name=arguments.name, slug=arguments.slug, preset=arguments.preset,
                     language=arguments.language, task_identity=arguments.task_identity,
                     validation=validation, test=arguments.test)
        initial = plan_adopt(root, framework, **flags)
        values = {}
        for key, choice in initial.choices.items():
            value = choice['value']
            display = json.dumps(value, sort_keys=True) if isinstance(value, dict) else (value or '')
            label = "validation (test command to change)" if key == "validation" else key
            answer = input(f'{label} [{display}] ({choice["source"]}): ').strip()
            if key == 'validation':
                values[key] = test_validation(answer) if answer else value
                if values[key] is None:
                    raise CardineError('a test command is required')
            else:
                values[key] = answer or value
        adopt = plan_adopt(root, framework, **values)
        candidate = plan_init(root, framework, **values, refuse_existing=False)
        use_adopt = adopt.case != 'A' or any((root / name).exists() or (root / name).is_symlink()
                                             for name in candidate.outputs)
        if use_adopt:
            if adopt.missing or adopt.refusals:
                raise CardineError(f'adoption blocked: {", ".join((*adopt.missing, *adopt.refusals, *adopt.diagnostics))}')
            if adopt.case == 'B':
                outputs, _, removals, _ = conversion_outputs(root, framework, adopt)
            else:
                outputs, removals = adopt.outputs, []
            paths = sorted(set(outputs) | set(removals))
        else:
            candidate = plan_init(root, framework, **values)
            paths = sorted(candidate.outputs)
        print(terminal.section('Plan'))
        print(f'plan: {"adoption" if use_adopt else "init"} in {root}')
        for path in paths:
            print(f'project output: {path}')
        # Only planned paths must be clean; publication must not absorb prior edits.
        if paths and _git(root, 'status', '--porcelain', '--untracked-files=all', '--', *paths).strip():
            raise CardineError('planned paths contain pre-existing edits')
        if not _confirm('Apply this plan?'):
            print('result: cancelled')
            return 0
        print(terminal.section('Apply'))
        print(terminal.step(1, 2, 'Writing project files'))
        if use_adopt:
            apply_rehearsed_adoption(root, adopt, framework)
        else:
            apply_init(candidate)
        message = 'Initialize Cardine project'
        print(f'proposed commit: {message}')
        for path in paths:
            print(f'written: {path}')
        if not _confirm('Commit these paths and push main?'):
            print('result: applied; publication declined')
            print(terminal.section('Next steps'))
            print(f'Next: cardine guide{_project_option(root)}')
            return 0
        if _git(root, 'branch', '--show-current').strip() != 'main':
            raise CardineError('publication requires the main branch')
        print(terminal.step(2, 2, 'Committing project files'))
        _git(root, 'add', '--', *paths)
        _git(root, 'commit', '--only', '-m', message, '--', *paths)
        retry = 'git push origin main'
        try:
            with terminal.spinner('Pushing main'):
                _git(root, 'push', 'origin', 'main')
        except CardineError as error:
            raise CardineError(f'push failed: {error}\nRetry: {retry}') from error
        print('result: committed and pushed main')
        print(terminal.section('Next steps'))
        print(f'Next: cardine guide{_project_option(root)}')
        return 0
    except (CardineError, OSError, ValueError, UnicodeError, EOFError) as error:
        message = str(error).split('\n')
        print(terminal._style(f'error: {message[0]}', '31'), file=sys.stderr)
        for line in message[1:]:
            print(line, file=sys.stderr)
        return 2
