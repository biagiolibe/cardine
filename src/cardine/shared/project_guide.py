"""Read-only onboarding guidance from the resolved project declaration."""

from pathlib import Path
import shlex

from cardine.shared.errors import CardineError
from cardine.shared.git import _run_git
from cardine.shared.project import read_project_declaration

from cardine.shared.project import resolve_project_configuration
from cardine.shared.paths import framework_root as resolve_framework_root
from cardine.release.version import read_version


def _project_option(root: Path) -> str:
    try:
        here = Path.cwd().resolve()
    except OSError:
        here = None
    return '' if here == root else f' --project {shlex.quote(str(root))}'


def _quick_start(framework_root: Path | None) -> str:
    version = read_version(framework_root or resolve_framework_root())
    return f'https://github.com/biagiolibe/cardine/blob/v{version}/docs/QUICKSTART.md'


def _choice_lines(config: dict, project: str) -> list[str]:
    defaults = config['taskDefaults']
    commands = (config.get('validation') or {}).get('commands') or {}
    if commands:
        validation = 'Validation: ' + '; '.join(f'{key} runs {value}' for key, value in commands.items())
    else:
        validation = 'Validation: not declared; run cardine init'
    ci = config.get('ci', 'none')
    if isinstance(ci, dict):
        ci_line = f"CI before landing: yes ({ci['provider']}, checks: {', '.join(ci['requiredChecks'])})"
    else:
        ci_line = 'CI before landing: no'
    return [
        f"Preset: {config['preset']}. Review: {'required' if defaults['review'] == 'required' else 'not required'}. "
        f"Authority: {'required' if defaults['authorityRequired'] else 'optional'}.",
        validation,
        ci_line,
        f'Console: cardine console{project}.',
    ]


def project_guide(project: Path, framework_root: Path | None = None) -> dict:
    root = project.resolve()
    declaration = read_project_declaration(root)
    target = _project_option(root)
    if declaration is None:
        result = _run_git(root, 'rev-parse', '--show-toplevel') if root.is_dir() else None
        if not result or result.returncode or Path(result.stdout.strip()).resolve() != root:
            raise CardineError('unsupported checkout: --project must name the root of a non-bare Git checkout')
        return {
            'version': 1, 'project': str(root),
            'facts': {'configuration': 'missing'},
            'sections': {
                'bootstrap': [
                    'This checkout is not configured for Cardine yet.',
                    f'Run cardine init{target}. It chooses between initialization and adoption, proposes every choice with a default, and asks before writing or publishing anything.',
                    'If no test command is detected, add --test "<command>".',
                    f'Then run cardine guide{target} again.',
                ],
                'references': [_quick_start(framework_root)],
            },
        }
    config = resolve_project_configuration(root)
    defaults = config['taskDefaults']
    ci = config.get('ci', 'none')
    validation = config.get('validation')
    facts = {
        'preset': config['preset'], 'task_defaults': defaults,
        'task_identity': config['taskIdentity'], 'validation': validation,
        'ci': ci, 'host_policy': 'unverified', 'remote_ci': 'unverified',
    }
    sections = {
        'first_task': [
            f'Connect your agent: preview with cardine setup --check{target}, then run cardine setup --apply{target} from your terminal.',
            f'Check the host with cardine doctor --host claude{target} or cardine doctor --host codex{target}.',
            f'Ask your agent for a task, or write one from tasks/TASK_BLUEPRINT.md and register it with cardine task new <ID> --record <file>{target}. Commit and push the record on main.',
            f'Deliver it with cardine run <ID>{target}, following each next command until done.',
        ],
        'choices': _choice_lines(config, target),
        'references': [_quick_start(framework_root), 'tasks/TASK_BLUEPRINT.md', 'docs/RUN_COMMANDS.md'],
    }
    return {'version': 1, 'project': str(root), 'facts': facts, 'sections': sections}


_TITLES = {'bootstrap': 'Next steps', 'first_task': 'Next steps', 'choices': 'This project', 'references': 'References'}


def render_project_guide(guide: dict) -> str:
    lines = [f"Cardine guide: {guide['project']}"]
    for key, entries in guide['sections'].items():
        lines.append(f"\n{_TITLES.get(key, key.replace('_', ' ').title())}:")
        lines.extend(f'- {entry}' for entry in entries)
    return '\n'.join(lines)
