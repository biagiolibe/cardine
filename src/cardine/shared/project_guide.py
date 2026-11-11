"""Read-only onboarding guidance from the resolved project declaration."""

from pathlib import Path
import shlex

from cardine.shared.errors import CardineError
from cardine.shared.git import _run_git
from cardine.shared.project import read_project_declaration

from cardine.shared.project import resolve_project_configuration


def project_guide(project: Path) -> dict:
    root = project.resolve()
    declaration = read_project_declaration(root)
    if declaration is None:
        result = _run_git(root, 'rev-parse', '--show-toplevel') if root.is_dir() else None
        if not result or result.returncode or Path(result.stdout.strip()).resolve() != root:
            raise CardineError('unsupported checkout: --project must name the root of a non-bare Git checkout')
        target = shlex.quote(str(root))
        return {
            'version': 1, 'project': str(root),
            'facts': {'configuration': 'missing'},
            'sections': {
                'bootstrap': [
                    'This Git checkout has no Cardine project declaration. Use init for a new repository with no conflicting generated paths; use adopt for an existing project. The preview reports conflicts.',
                    'Every choice has a default shown in the preview. Use --test "<command>" when test detection finds none. Repository text remains English.',
                    f'Preview with cardine init --project {target} --check or cardine adopt --project {target} --check, supplying the chosen inputs; see docs/QUICKSTART.md for complete commands. Adopt can also be rehearsed on a disposable clone.',
                    'Review the plan and missing inputs, then replace --check with --apply after consenting. If a step fails, inspect its diagnostics and applied changes, correct the cause, and resume the indicated step.',
                    f'After configuration, run cardine guide --project {target} again for host setup and the first verified landing.',
                ],
                'references': ['docs/QUICKSTART.md'],
            },
        }
    config = resolve_project_configuration(root)
    defaults = config['taskDefaults']
    ci = config.get('ci', 'none')
    target = shlex.quote(str(root))
    validation = config.get('validation')
    facts = {
        'preset': config['preset'], 'task_defaults': defaults,
        'task_identity': config['taskIdentity'], 'validation': validation,
        'ci': ci, 'host_policy': 'unverified', 'remote_ci': 'unverified',
    }
    sections = {
        'first_task': [
            'Use a Git checkout on main with a clean working tree, a Git author identity, and a writable origin; verify access and publish the initialized or adopted project on main.',
            f'Preview host setup with cardine setup --check --project {target}; apply it with cardine setup --apply --project {target} after deciding to configure the host.',
            f'Run cardine doctor --host <codex|claude> --project {target} and address diagnostics. Local configuration alone does not verify host policy.',
            'Write a task proposal with objective, acceptance criteria, dependencies, validation and expected code surface. Include Authority when required. See tasks/TASK_BLUEPRINT.md.',
            f'Register it with cardine task new <ID> --record <proposal.md> --project {target} (add --quick for a quick task). Commit and push the task record and state on main.',
            f'Run cardine run <ID> --project {target} and follow each next.command through verified landing; handle waiting and iterate outcomes as directed. Required independent review must be performed by a separate session.',
        ],
        'choices': [
            f"Preset: {config['preset']}. Resolved project task defaults: {defaults}. Per-task choices override project defaults, which override the preset; task contracts freeze the resolved choices.",
            ('Local validation is declared: ' + str(validation) if validation else 'Local validation is missing; the maintainer must declare commands before task execution.'),
            f"Review default: {defaults['review']}; Authority required: {defaults['authorityRequired']}; expected code surface required: {defaults['expectedCodeSurfaceRequired']}. The run workflow needs a bounded expected code surface even when the task option does not require one.",
            'A spike records ANSWERED or INCONCLUSIVE; only a landed ANSWERED spike satisfies a dependency. Dependencies must be satisfied before starting.',
            f"CI declaration: {ci}; CI before landing default: {defaults['ciBeforeLanding']}. The maintainer supplies the CI workflow; required checks must report on the task branch commit. Remote checks and host policy are unverified until observed.",
            f'Use cardine console --project {target} to inspect the project; setup and doctor are separate host operations.',
        ],
        'references': ['docs/QUICKSTART.md', 'tasks/TASK_BLUEPRINT.md', 'docs/RUN_COMMANDS.md'],
    }
    return {'version': 1, 'project': str(root), 'facts': facts, 'sections': sections}


def render_project_guide(guide: dict) -> str:
    lines = [f"Cardine guide: {guide['project']}"]
    for title, entries in guide['sections'].items():
        lines.append(f"\n{title.replace('_', ' ').title()}:")
        lines.extend(f'- {entry}' for entry in entries)
    return '\n'.join(lines)
