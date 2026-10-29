"""Kill host setup writes at every effect boundary in disposable homes and repeat the command."""
import contextlib
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from cardine_cli_support import ROOT
from cardine.hosts import claude, codex, setup, skills
from cardine.lifecycle import receipts
from cardine.shared.errors import CardineError

CHILD = '''
import os, sys, tempfile
from pathlib import Path
from cardine.hosts import setup
from cardine.lifecycle import receipts
home, seam, framework = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
tempfile.tempdir = sys.argv[4]
def boundary(name):
    if name == seam:
        os._exit(93)
receipts.boundary = boundary
plan = setup.plan_setup(None, home / 'codex/config.toml',
                        environment={'HOME': str(home), 'XDG_CONFIG_HOME': str(home / 'xdg')},
                        home=home, framework_root=framework, project_root=home / 'project')
setup.apply_setup(plan)
'''
FOREIGN_CONFIG = '# foreign settings\nmodel = "test"\n'
FOREIGN_RULES = '# user rule\nprefix_rule(pattern=["ls"], decision="allow")\n'


class HostRepeatabilityTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        (self.base / 'receipts').mkdir()
        patcher = patch.object(tempfile, 'tempdir', str(self.base / 'receipts'))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.count = 0

    def make_home(self):
        self.count += 1
        home = self.base / f'home-{self.count}' / 'home'
        (home / 'codex').mkdir(parents=True)
        (home / '.codex/rules').mkdir(parents=True)
        (home / 'project').mkdir()
        (home / 'codex/config.toml').write_text(FOREIGN_CONFIG)
        (home / '.codex/rules/default.rules').write_text(FOREIGN_RULES)
        (home / 'foreign-work').write_text('preserve this')
        return home

    def run_setup(self, home, seam=''):
        return subprocess.run([sys.executable, '-c', CHILD, str(home), seam, str(ROOT), str(self.base / 'receipts')],
                              capture_output=True, text=True, timeout=60,
                              env={**os.environ, 'HOME': str(home), 'PYTHONPATH': str(ROOT / 'src')})

    def receipt(self, home):
        return receipts.host_path('setup', home / '.cardine/worktrees')

    def tree(self, home):
        return {path.relative_to(home).as_posix():
                (('link:' + os.readlink(path)).encode() if path.is_symlink() else path.read_bytes())
                .replace(str(home).encode(), b'<home>')
                for path in sorted(home.rglob('*')) if path.is_symlink() or path.is_file()}

    def old_links(self, home):
        for directory in ('.agents/skills', '.codex/skills'):
            root = home / directory
            root.mkdir(parents=True)
            for name in skills.OLD_SKILL_NAMES:
                (root / name).symlink_to(ROOT / 'skills' / name)

    def test_old_skill_migration_replays_every_effect_and_preserves_foreign_paths(self):
        reference = self.make_home()
        self.old_links(reference)
        self.assertEqual(self.run_setup(reference).returncode, 0)
        names = sorted(receipts._load_intent(self.receipt(reference))['effects'])
        self.assertEqual(len([name for name in names if name.startswith('remove-skill:')]), 8)
        self.assertIn('skill-migration-result', names)
        expected = self.tree(reference)
        for name in names:
            for when in ('before', 'after'):
                with self.subTest(seam=f'{when}_{name}'):
                    home = self.make_home()
                    self.old_links(home)
                    self.assertEqual(self.run_setup(home, f'{when}_{name}').returncode, 93)
                    replay = self.run_setup(home)
                    self.assertEqual(replay.returncode, 0, replay.stderr)
                    self.assertEqual(self.tree(home), expected)
        for when, replacement in ((when, kind) for when in ('before', 'after')
                                  for kind in ('link', 'directory', 'copy')):
            home = self.make_home()
            self.old_links(home)
            target = home / '.agents/skills' / skills.OLD_SKILL_NAMES[0]
            seam = when + '_remove-skill:.agents/skills/' + target.name
            self.assertEqual(self.run_setup(home, seam).returncode, 93)
            target.unlink(missing_ok=True)
            if replacement == 'link':
                target.symlink_to(home / 'foreign-work')
            elif replacement == 'directory':
                target.mkdir()
            else:
                target.write_text('foreign copy')
            snapshot = self.tree(home)
            self.assertNotEqual(self.run_setup(home).returncode, 0)
            self.assertEqual(self.tree(home), snapshot)
            self.assertTrue(target.exists())

    def test_skill_migration_checks_are_read_only_and_keep_unowned_legacy_paths(self):
        home = self.make_home()
        self.old_links(home)
        foreign = home / '.agents/skills' / skills.OLD_SKILL_NAMES[0]
        foreign.unlink()
        foreign.mkdir()
        (foreign / 'SKILL.md').write_text('foreign skill copy')
        stale = home / '.codex/skills' / skills.OLD_SKILL_NAMES[1]
        stale.unlink()
        stale.symlink_to(home / 'foreign-work')
        snapshot = self.tree(home)
        for _ in range(2):
            plan = self.planned(home)
            self.assertTrue(any(str(foreign) in warning for warning in plan.warnings))
            self.assertEqual(self.tree(home), snapshot)
            self.assertFalse(self.receipt(home).exists())
        self.assertEqual(self.run_setup(home).returncode, 0)
        self.assertEqual((foreign / 'SKILL.md').read_text(), 'foreign skill copy')
        self.assertEqual(os.readlink(stale), str(home / 'foreign-work'))

    def test_symlinked_skill_roots_are_blocked_without_writing(self):
        home = self.make_home()
        outside = home / 'foreign-skills'
        outside.mkdir()
        (home / '.agents').mkdir()
        (home / '.agents/skills').symlink_to(outside)
        snapshot = self.tree(home)
        self.assertNotEqual(self.run_setup(home).returncode, 0)
        self.assertEqual(self.tree(home), snapshot)
        self.assertEqual(list(outside.iterdir()), [])

    def reference(self):
        home = self.make_home()
        self.assertEqual(self.run_setup(home).returncode, 0)
        intent = receipts._load_intent(self.receipt(home))
        self.assertEqual(set(intent['effects'].values()), {'done'})
        self.assertEqual(intent['result'], dict(done=True))
        names = sorted(intent['effects'])
        for expected in ('backup:codex-config', 'file:codex-config', 'file:codex-rules',
                         'directory:cardine-root', 'file:claude-allowlist'):
            self.assertIn(expected, names)
        self.assertTrue(any(name.startswith('symlink:skill:') for name in names))
        return home, names

    def test_kills_at_every_boundary_converge_and_preserve_user_regions(self):
        reference, names = self.reference()
        expected = self.tree(reference)
        self.assertIn(FOREIGN_RULES.encode(), expected['.codex/rules/default.rules'])
        self.assertEqual(expected['codex/config.toml.cardine.bak'], FOREIGN_CONFIG.encode())
        for name in names:
            for when in ('before', 'after'):
                with self.subTest(seam=f'{when}_{name}'):
                    home = self.make_home()
                    self.assertEqual(self.run_setup(home, f'{when}_{name}').returncode, 93)
                    interrupted = receipts._load_intent(self.receipt(home))
                    self.assertIsNone(interrupted['result'])
                    finished = self.run_setup(home)
                    self.assertEqual(finished.returncode, 0, finished.stdout + finished.stderr)
                    final = receipts._load_intent(self.receipt(home))
                    self.assertEqual(final['operation_id'], interrupted['operation_id'])
                    self.assertEqual(set(final['effects'].values()), {'done'})
                    self.assertEqual(self.tree(home), expected)
                    # Exactly one backup and no temporary residue survive repeated attempts.
                    self.assertEqual(sorted(path.name for path in (home / 'codex').iterdir()),
                                     ['config.toml', 'config.toml.cardine.bak'])
                    self.assertEqual(self.run_setup(home).returncode, 0)
                    self.assertEqual(self.tree(home), expected)

    def test_user_edits_between_a_kill_and_its_retry_are_preserved(self):
        for seam, target, edit in (
                ('after_backup:codex-config', 'codex/config.toml', '# user edit\nmodel = "other"\n'),
                ('before_file:codex-rules', '.codex/rules/default.rules', FOREIGN_RULES + '# edit\n'),
                ('before_file:claude-allowlist', 'project/.claude/settings.local.json', '{"edited": true}\n')):
            with self.subTest(seam=seam):
                home = self.make_home()
                if 'claude' in seam:
                    (home / 'project/.claude').mkdir()
                    (home / 'project/.claude/settings.local.json').write_text('{}\n')
                self.assertEqual(self.run_setup(home, seam).returncode, 93)
                (home / target).write_text(edit)
                snapshot, recorded = self.tree(home), self.receipt(home).read_bytes()
                refused = self.run_setup(home)
                self.assertNotEqual(refused.returncode, 0, refused.stdout)
                self.assertEqual(self.tree(home), snapshot)
                self.assertEqual(self.receipt(home).read_bytes(), recorded)
                self.assertIsNone(receipts._load_intent(self.receipt(home))['result'])

    def test_symlinked_host_files_are_refused_without_writing_through(self):
        for target in ('codex/config.toml', '.codex/rules/default.rules'):
            with self.subTest(target=target):
                home = self.make_home()
                outside = self.base / f'outside-{self.count}'
                outside.write_text('outside the home\n')
                (home / target).unlink()
                (home / target).symlink_to(outside)
                snapshot = self.tree(home)
                refused = self.run_setup(home)
                self.assertNotEqual(refused.returncode, 0)
                self.assertTrue((home / target).is_symlink())
                self.assertEqual(outside.read_text(), 'outside the home\n')
                self.assertEqual(self.tree(home), snapshot)

    def test_a_denied_home_leaves_a_pending_receipt_and_the_retry_converges(self):
        if os.geteuid() == 0:
            self.skipTest('directory permissions do not apply to root')
        reference, _names = self.reference()
        home = self.make_home()
        (home / 'codex').chmod(0o500)
        self.addCleanup((home / 'codex').chmod, 0o700)
        denied = self.run_setup(home)
        self.assertNotEqual(denied.returncode, 0)
        self.assertIn('PermissionError', denied.stderr)
        pending = receipts._load_intent(self.receipt(home))
        self.assertIsNone(pending['result'])
        self.assertNotEqual(set(pending['effects'].values()), {'done'})
        self.assertEqual((home / 'codex/config.toml').read_text(), FOREIGN_CONFIG)
        (home / 'codex').chmod(0o700)
        finished = self.run_setup(home)
        self.assertEqual(finished.returncode, 0, finished.stdout + finished.stderr)
        self.assertEqual(receipts._load_intent(self.receipt(home))['operation_id'], pending['operation_id'])
        self.assertEqual(self.tree(home), self.tree(reference))

    def planned(self, home):
        return setup.plan_setup(None, home / 'codex/config.toml',
                                environment={'HOME': str(home), 'XDG_CONFIG_HOME': str(home / 'xdg')},
                                home=home, framework_root=ROOT, project_root=home / 'project')

    def test_checks_and_blocked_plans_never_write_receipts_or_files(self):
        home = self.make_home()
        snapshot = self.tree(home)
        outputs = []
        for _ in range(2):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                setup.print_setup_plan(self.planned(home))
            outputs.append(output.getvalue())
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(self.tree(home), snapshot)
        self.assertEqual(list((self.base / 'receipts').rglob('*.json')), [])
        # A pending operation stays read-only under repeated checks.
        self.assertEqual(self.run_setup(home, 'after_file:codex-rules').returncode, 93)
        snapshot, recorded = self.tree(home), self.receipt(home).read_bytes()
        for _ in range(2):
            with contextlib.redirect_stdout(io.StringIO()):
                setup.print_setup_plan(self.planned(home))
        self.assertEqual((self.tree(home), self.receipt(home).read_bytes()), (snapshot, recorded))
        blocked = self.make_home()
        (blocked / 'codex/config.toml').write_text('sandbox_mode = "workspace-write"\n')
        with self.assertRaises(CardineError):
            setup.apply_setup(self.planned(blocked))
        self.assertEqual(list((blocked.parent).rglob('cardine-operations')), [])

    def test_changed_inputs_and_foreign_owner_stop_at_every_effect(self):
        reference, names = self.reference()
        for name in names:
            for when in ('before', 'after'):
                for change in ('edit', 'owner'):
                    targets = {'file:codex-config': 'codex/config.toml', 'file:codex-rules': '.codex/rules/default.rules',
                               'file:claude-allowlist': 'project/.claude/settings.local.json'}
                    if change == 'edit' and name not in targets:
                        continue
                    with self.subTest(seam=f'{when}_{name}', change=change):
                        home = self.make_home()
                        plan = self.planned(home)

                        def inject(current):
                            if current != f'{when}_{name}':
                                return
                            if change == 'owner':
                                path = self.receipt(home)
                                intent = receipts._load_intent(path)
                                intent['owner']['anchor'] = str(self.base / 'foreign')
                                receipts._save_intent(path, intent)
                            else:
                                (home / targets[name]).parent.mkdir(parents=True, exist_ok=True)
                                (home / targets[name]).write_text('foreign edit\n')

                        with patch.object(receipts, 'boundary', side_effect=inject):
                            with self.assertRaises(CardineError):
                                setup.apply_setup(plan)
                        if change == 'edit':
                            self.assertEqual((home / targets[name]).read_text(), 'foreign edit\n')
                        self.assertEqual((home / 'foreign-work').read_text(), 'preserve this')
                        self.assertIsNone(receipts._load_intent(self.receipt(home))['result'])

    def test_a_live_writer_and_a_symlinked_receipt_are_refused(self):
        home = self.make_home()
        snapshot = self.tree(home)
        started, release = threading.Event(), threading.Event()

        def hold():
            with receipts.nonrun_lock(self.receipt(home)):
                started.set()
                release.wait(30)

        holder = threading.Thread(target=hold)
        holder.start()
        self.addCleanup(holder.join)
        self.addCleanup(release.set)
        self.assertTrue(started.wait(10))
        refused = self.run_setup(home)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn('live foreign', refused.stderr)
        self.assertEqual(self.tree(home), snapshot)
        release.set()
        holder.join()
        outside = self.base / 'outside-receipt'
        outside.write_text('not a receipt\n')
        self.receipt(home).symlink_to(outside)
        refused = self.run_setup(home)
        self.assertNotEqual(refused.returncode, 0)
        self.assertEqual(outside.read_text(), 'not a receipt\n')
        self.assertEqual(self.tree(home), snapshot)

    def test_repair_backups_are_written_once_across_retries(self):
        home = self.make_home()
        config = home / 'codex/config.toml'
        plan = codex.plan_codex_configuration(config, home / 'worktrees')
        codex.apply_codex_configuration(plan)
        damaged = config.read_text().replace(codex.CODEX_MANAGED_BEGIN, '').replace(codex.CODEX_MANAGED_END, '')
        config.write_text(damaged)
        for seam in ('before_backup:codex-config', 'after_backup:codex-config',
                     'before_file:codex-config', 'after_file:codex-config'):
            with self.subTest(seam=seam):
                config.write_text(damaged)
                for backup in config.parent.glob('config.toml.cardine-repair*'):
                    backup.unlink()
                script = ('import os, sys, tempfile\nfrom pathlib import Path\n'
                          'from cardine.hosts import codex\nfrom cardine.lifecycle import receipts\n'
                          'tempfile.tempdir = sys.argv[3]\n'
                          'def boundary(name):\n    if name == sys.argv[2]: os._exit(93)\n'
                          'receipts.boundary = boundary\n'
                          'config, root = Path(sys.argv[1]), Path(sys.argv[4])\n'
                          'plan = codex.plan_codex_configuration(config, root)\n'
                          'codex.apply_codex_configuration(plan)\n')
                run = lambda name: subprocess.run(
                    [sys.executable, '-c', script, str(config), name, str(self.base / 'receipts'), str(home / 'worktrees')],
                    capture_output=True, text=True, env={**os.environ, 'PYTHONPATH': str(ROOT / 'src')})
                self.assertEqual(run(seam).returncode, 93)
                finished = run('never')
                self.assertEqual(finished.returncode, 0, finished.stdout + finished.stderr)
                backups = sorted(config.parent.glob('config.toml.cardine-repair*'))
                self.assertEqual([path.read_text() for path in backups], [damaged])
                self.assertIn(codex.CODEX_MANAGED_BEGIN, config.read_text())
                self.assertEqual(codex.plan_codex_configuration(config, home / 'worktrees').status, 'ready')

    def test_claude_allowlist_alone_is_receipt_covered(self):
        home = self.make_home()
        project = home / 'project'
        plan = claude.plan_claude_project_allowlist(project)
        self.assertTrue(claude.apply_claude_project_allowlist(plan))
        self.assertFalse(claude.apply_claude_project_allowlist(claude.plan_claude_project_allowlist(project)))
        intent = receipts._load_intent(receipts.host_path('claude-allowlist', project / '.claude/settings.local.json'))
        self.assertEqual((intent['result'], set(intent['effects'].values())), (dict(done=True), {'done'}))


if __name__ == '__main__':
    unittest.main()
