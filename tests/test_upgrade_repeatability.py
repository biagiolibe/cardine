"""Kill project upgrades at every effect boundary and repeat the same command."""
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from cardine_cli_support import CLI, ROOT
from cardine.lifecycle import receipts
from cardine.shared.errors import CardineError
from cardine.shared.models import ManagedFile, PlanItem
from cardine.templates import upgrade
from synthetic_upgrade_support import SyntheticFramework

FILES = ("PROJECT_WORKFLOW.md", "AGENTS.md", "CLAUDE.md", "LANGUAGE_POLICY.md",
         "tasks/TASK_BLUEPRINT.md", "docs/CONTEXT_READING_POLICY.md",
         "docs/EXECUTION_EVIDENCE_PROFILE.md", ".codex/rules/meridian.rules", ".codex/hooks.json")
EDITED = ("PROJECT_WORKFLOW.md", "AGENTS.md")
CHILD = '''
import os, sys
sys.path.insert(0, sys.argv[1] + '/scripts')
import cardine_cli
from cardine.lifecycle import receipts
seam = sys.argv[2]
def boundary(name):
    if name == seam:
        os._exit(93)
receipts.boundary = boundary
sys.argv = ['cardine', *sys.argv[3:]]
raise SystemExit(cardine_cli.main())
'''


class UpgradeRepeatabilityTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        (self.base / 'receipts').mkdir()
        patcher = patch.object(tempfile, 'tempdir', str(self.base / 'receipts'))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.framework = SyntheticFramework(self.base / 'framework', '2.0.0', templates={
            path: '# Synthetic policy\n' for path in FILES})
        self.template = self.base / 'template'
        self.template.mkdir()
        shutil.copytree(self.framework.root / 'templates/single', self.template, dirs_exist_ok=True)
        self.lock = self.run_cli(self.template, 'lock', '--mode', 'single')
        self.assertEqual(self.lock.returncode, 0, self.lock.stdout + self.lock.stderr)
        for path in EDITED:
            (self.template / path).write_text((self.template / path).read_text() + f'\n## Notes\n\nKeep {path}.\n')
        self.framework.migration('001-synthetic-rule', '2.1.0', capability='rule', version=1,
                                 operation='insert', content='Original rule.', paths=EDITED, mode='single')

    def copy_project(self, name):
        self.copies = getattr(self, 'copies', 0) + 1
        project = self.base / f'{name}-{self.copies}'
        shutil.copytree(self.template, project)
        (project / 'foreign-work').write_text('preserve this')
        return project

    def environment(self):
        return {**os.environ, 'TMPDIR': str(self.base / 'receipts'), 'PYTHONPATH': str(ROOT / 'src')}

    def run_cli(self, project, *arguments, seam=''):
        command = [sys.executable, '-c', CHILD, str(ROOT), seam] if seam else [sys.executable, str(CLI)]
        return subprocess.run([*command, '--framework-root', str(self.framework.root), *arguments,
                               '--project', str(project)],
                              capture_output=True, text=True, env=self.environment(), timeout=60)

    def receipt(self, project):
        return receipts.operation_path(project.resolve(), 'upgrade')

    def tree(self, project):
        return {path.relative_to(project).as_posix(): path.read_bytes().replace(str(project).encode(), b'<project>')
                for path in sorted(project.rglob('*')) if path.is_file()}

    def seams(self):
        reference = self.copy_project('reference')
        self.assertEqual(self.run_cli(reference, 'upgrade', '--apply').returncode, 0)
        intent = receipts._load_intent(self.receipt(reference))
        self.assertEqual(set(intent['effects'].values()), {'done'})
        self.assertEqual(intent['result'], dict(done=True))
        names = sorted(intent['effects'])
        self.assertIn('file:upgrade:AGENTS.md', names)
        self.assertIn('file:manifest', names)
        self.assertIn('prune-baselines', names)
        self.assertEqual(sum(name.startswith('file:baseline:') for name in names), len(FILES))
        return reference, names

    def test_kills_at_every_boundary_converge_without_duplicates_or_foreign_loss(self):
        reference, names = self.seams()
        expected = self.tree(reference)
        for name in names:
            for when in ('before', 'after'):
                with self.subTest(seam=f'{when}_{name}'):
                    project = self.copy_project('project')
                    self.assertEqual(self.run_cli(project, 'upgrade', '--apply',
                                                  seam=f'{when}_{name}').returncode, 93)
                    interrupted = receipts._load_intent(self.receipt(project))
                    self.assertIsNone(interrupted['result'])
                    result = self.run_cli(project, 'upgrade', '--apply')
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    final = receipts._load_intent(self.receipt(project))
                    self.assertEqual(final['operation_id'], interrupted['operation_id'])
                    self.assertEqual(final['result'], dict(done=True))
                    self.assertEqual(set(final['effects'].values()), {'done'})
                    got = self.tree(project)
                    self.assertEqual(got.pop('foreign-work'), b'preserve this')
                    self.assertEqual(got, {key: value for key, value in expected.items() if key != 'foreign-work'})
                    again = self.run_cli(project, 'upgrade', '--apply')
                    self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
                    self.assertEqual(receipts._load_intent(self.receipt(project))['result'], dict(done=True))

    def test_a_user_edit_after_a_partial_apply_is_preserved(self):
        # PROJECT_WORKFLOW.md is applied first; AGENTS.md is still pending when the process dies.
        for edited in ('PROJECT_WORKFLOW.md', 'AGENTS.md'):
            with self.subTest(edited=edited):
                project = self.copy_project('project')
                self.assertEqual(self.run_cli(project, 'upgrade', '--apply',
                                              seam='before_file:upgrade:AGENTS.md').returncode, 93)
                (project / edited).write_text('user edit made after the interruption\n')
                snapshot, recorded = self.tree(project), self.receipt(project).read_bytes()
                result = self.run_cli(project, 'upgrade', '--apply')
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertEqual(self.tree(project), snapshot)
                self.assertEqual(self.receipt(project).read_bytes(), recorded)
                self.assertIsNone(receipts._load_intent(self.receipt(project))['result'])
                self.assertFalse((project / '.cardine/baselines/2.1.0').exists())

    def test_pending_checks_and_changed_requests_write_nothing(self):
        project = self.copy_project('project')
        self.assertEqual(self.run_cli(project, 'upgrade', '--apply', seam='after_file:upgrade:AGENTS.md').returncode, 93)
        snapshot, recorded = self.tree(project), self.receipt(project).read_bytes()
        checks = [self.run_cli(project, 'upgrade', '--check') for _ in range(2)]
        self.assertEqual([check.returncode for check in checks], [0, 0])
        self.assertEqual(checks[0].stdout, checks[1].stdout)
        for flags in (('--owner-reconciled',), ('--stop-before-retirement',)):
            refused = self.run_cli(project, 'upgrade', '--apply', *flags)
            self.assertNotEqual(refused.returncode, 0)
            self.assertIn('unfinished upgrade operation', refused.stdout + refused.stderr)
        self.assertEqual(self.tree(project), snapshot)
        self.assertEqual(self.receipt(project).read_bytes(), recorded)

    def target(self, project, name):
        if name == 'file:manifest':
            return project / '.cardine/manifest.json'
        kind, _, relative = name[len('file:'):].partition(':')
        return project / (relative if kind == 'upgrade' else f'.cardine/baselines/2.1.0/{relative}')

    def test_changed_inputs_and_foreign_owner_stop_at_every_effect(self):
        reference, names = self.seams()
        for name in names:
            for when in ('before', 'after'):
                for change in ('edit', 'owner'):
                    if change == 'edit' and not name.startswith('file:'):
                        continue
                    with self.subTest(seam=f'{when}_{name}', change=change):
                        project = self.copy_project('project')

                        def inject(current):
                            if current != f'{when}_{name}':
                                return
                            if change == 'owner':
                                path = self.receipt(project)
                                intent = receipts._load_intent(path)
                                intent['owner']['root'] = str(self.base / 'foreign')
                                receipts._save_intent(path, intent)
                            else:
                                target = self.target(project, name)
                                target.parent.mkdir(parents=True, exist_ok=True)
                                target.write_text('foreign edit\n')

                        with patch.object(receipts, 'boundary', side_effect=inject):
                            with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(CardineError):
                                upgrade.apply_upgrade(project, self.framework.root)
                        if change == 'edit':
                            self.assertEqual(self.target(project, name).read_text(), 'foreign edit\n')
                        self.assertEqual((project / 'foreign-work').read_text(), 'preserve this')
                        self.assertIsNone(receipts._load_intent(self.receipt(project))['result'])
                        # A retry of the identical command cannot finish over the foreign state.
                        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(CardineError):
                            upgrade.apply_upgrade(project, self.framework.root)
                        if change == 'edit':
                            self.assertEqual(self.target(project, name).read_text(), 'foreign edit\n')

    def test_symlinked_managed_file_and_symlinked_receipt_are_refused(self):
        project = self.copy_project('project')
        outside = self.base / 'outside.md'
        outside.write_text('outside the project\n')
        (project / 'AGENTS.md').unlink()
        (project / 'AGENTS.md').symlink_to(outside)
        snapshot = self.tree(project)
        result = self.run_cli(project, 'upgrade', '--apply')
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertEqual(outside.read_text(), 'outside the project\n')
        self.assertTrue((project / 'AGENTS.md').is_symlink())
        self.assertEqual(self.tree(project), snapshot)
        self.assertFalse(self.receipt(project).exists())
        (project / 'AGENTS.md').unlink()
        shutil.copyfile(self.template / 'AGENTS.md', project / 'AGENTS.md')
        self.receipt(project).parent.mkdir(parents=True, exist_ok=True)
        self.receipt(project).symlink_to(outside)
        snapshot = self.tree(project)
        result = self.run_cli(project, 'upgrade', '--apply')
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.tree(project), snapshot)
        self.assertEqual(outside.read_text(), 'outside the project\n')

    def test_a_live_writer_is_a_foreign_operation(self):
        project = self.copy_project('project')
        snapshot = self.tree(project)
        started, release = threading.Event(), threading.Event()

        def hold():
            with receipts.nonrun_lock(self.receipt(project)):
                started.set()
                release.wait(30)

        holder = threading.Thread(target=hold)
        holder.start()
        self.addCleanup(holder.join)
        self.addCleanup(release.set)
        self.assertTrue(started.wait(10))
        result = self.run_cli(project, 'upgrade', '--apply')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('live foreign', result.stdout + result.stderr)
        self.assertEqual(self.tree(project), snapshot)

    def test_adoption_backups_are_written_once_and_never_replaced(self):
        script = (
            'import os, sys\nfrom pathlib import Path\n'
            'from cardine.lifecycle import receipts\n'
            'from cardine.shared.models import ManagedFile, PlanItem\nfrom cardine.templates import upgrade\n'
            'root, seam = Path(sys.argv[1]), sys.argv[2]\n'
            'def boundary(name):\n    if name == seam: os._exit(93)\n'
            'receipts.boundary = boundary\n'
            "item = PlanItem(ManagedFile(root / 'source', Path('README.md')), 'adopt-replace', 'adopt',\n"
            "                backup=Path('README.md.cardine-pre-adoption.bak'))\n"
            "manifest = {'protocolVersion': 1, 'workflowMode': 'single', 'frameworkVersion': '1.1.0',\n"
            "            'workflowBaselineVersion': '1.1.0', 'managedFiles': {}, 'appliedMigrations': []}\n"
            'upgrade.manifest_bytes = lambda manifest, framework: b"{}\\n"\n'
            'upgrade.complete_profile_surfaces = lambda *arguments: None\n'
            "upgrade.apply_plan(root / 'project', root / 'framework', manifest, [item],\n"
            "                   root / 'project/.cardine/baselines/1.1.0',\n"
            "                   managed_files_override=[ManagedFile(root / 'source', Path('README.md'))])\n"
        )
        for effect in ('backup:upgrade:README.md', 'file:upgrade:README.md'):
            for when in ('before', 'after'):
                with self.subTest(effect=effect, when=when):
                    root = self.base / f'adopt-{when}-{effect.split(":")[0]}'
                    (root / 'project').mkdir(parents=True)
                    (root / 'framework/migrations').mkdir(parents=True)
                    (root / 'framework/VERSION').write_text('1.2.0\n')
                    (root / 'source').write_text('released text\n')
                    (root / 'project/README.md').write_text('local text\n')

                    def run(seam):
                        return subprocess.run([sys.executable, '-c', script, str(root), seam],
                                              capture_output=True, text=True, env=self.environment())

                    self.assertEqual(run(f'{when}_{effect}').returncode, 93)
                    finished = run('never')
                    self.assertEqual(finished.returncode, 0, finished.stdout + finished.stderr)
                    self.assertEqual((root / 'project/README.md').read_text(), 'released text\n')
                    backup = root / 'project/README.md.cardine-pre-adoption.bak'
                    self.assertEqual(backup.read_text(), 'local text\n')
                    self.assertEqual(sorted(path.name for path in (root / 'project').glob('README.md*')),
                                     ['README.md', backup.name])


if __name__ == '__main__':
    unittest.main()
