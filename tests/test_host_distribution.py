"""Exercise the packaged plugin, including native Claude decisions, in disposable homes."""
import json
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from cardine_cli_support import ROOT
sys.path.insert(0, str(ROOT / 'scripts'))
import build_host_plugin as plugin
from cardine.lifecycle import receipts
from cardine.shared.errors import CardineError

CHILD = '''
import os, sys, tempfile
from pathlib import Path
sys.path.insert(0, sys.argv[1] + '/scripts')
import build_host_plugin as plugin
from cardine.lifecycle import receipts
tempfile.tempdir = sys.argv[2]
def boundary(name):
    if name == sys.argv[4]: os._exit(93)
receipts.boundary = boundary
plugin.build(Path(sys.argv[3]))
'''


class HostDistributionTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.scratch = self.base / 'receipts'
        self.scratch.mkdir()
        patcher = patch.object(tempfile, 'tempdir', str(self.scratch))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.count = 0

    def home(self):
        self.count += 1
        home = self.base / f'home-{self.count}'
        home.mkdir()
        (home / 'foreign').write_text('user-owned content\n')
        return home

    def environment(self, home):
        return {**os.environ, 'HOME': str(home), 'CLAUDE_CONFIG_DIR': str(home / '.claude'),
                'DISABLE_AUTOUPDATER': '1', 'XDG_CONFIG_HOME': str(home / '.config')}

    def run_build(self, home, seam=''):
        return subprocess.run([sys.executable, '-c', CHILD, str(ROOT), str(self.scratch),
                               str(home / 'plugin'), seam], cwd=home,
                              env=self.environment(home), capture_output=True, text=True, timeout=30)

    def test_distribution_resolves_exactly_two_skills_and_five_commands_without_hooks(self):
        home = self.home()
        destination = plugin.build(home / 'plugin')
        self.assertEqual(plugin.inventory(destination), plugin.payload())
        self.assertEqual(sorted(p.name for p in (destination / 'skills').iterdir()), sorted(plugin.SKILLS))
        self.assertEqual(sorted(p.stem for p in (destination / 'commands').iterdir()), sorted(plugin.COMMANDS))
        self.assertFalse((destination / 'hooks').exists())
        self.assertNotIn('hooks', json.loads((destination / '.claude-plugin/plugin.json').read_text()))
        self.assertTrue((ROOT / 'hooks/hooks.json').is_file())

    def test_kill_before_and_after_every_copy_and_publication_converges(self):
        reference = self.home()
        self.assertEqual(self.run_build(reference).returncode, 0)
        expected = plugin.inventory(reference / 'plugin')
        names = ['assembly', *(f'copy:{name}' for name in plugin.FILES), 'publication']
        for name in names:
            for when in ('before', 'after'):
                with self.subTest(seam=f'{when}_{name}'):
                    home = self.home()
                    killed = self.run_build(home, f'{when}_{name}')
                    self.assertEqual(killed.returncode, 93, killed.stderr)
                    receipt = receipts.host_path('host-plugin', home / 'plugin')
                    intent = receipts._load_intent(receipt)
                    self.assertIsNone(intent['result'])
                    resumed = self.run_build(home)
                    self.assertEqual(resumed.returncode, 0, resumed.stderr)
                    self.assertEqual(receipts._load_intent(receipt)['operation_id'], intent['operation_id'])
                    self.assertEqual(plugin.inventory(home / 'plugin'), expected)
                    self.assertFalse((home / '.plugin.cardine-stage').exists())
                    self.assertEqual(self.run_build(home).returncode, 0)
                    self.assertEqual(plugin.inventory(home / 'plugin'), expected)
                    self.assertEqual((home / 'foreign').read_text(), 'user-owned content\n')

    def test_checks_repeat_without_writes_including_receipt(self):
        home = self.home()
        destination = plugin.build(home / 'plugin')
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.base.rglob('*') if p.is_file()}
        for _ in range(2):
            plugin.check(destination)
        self.assertEqual(before, {p: (p.read_bytes(), p.stat().st_mtime_ns)
                                  for p in self.base.rglob('*') if p.is_file()})

    def test_foreign_paths_links_and_changed_owned_files_are_preserved(self):
        for kind in ('directory', 'link', 'edited-stage', 'edited-published', 'foreign-owner'):
            with self.subTest(kind=kind):
                home = self.home()
                destination = home / 'plugin'
                if kind == 'directory':
                    destination.mkdir()
                    (destination / 'foreign').write_text('keep')
                elif kind == 'link':
                    destination.symlink_to(home / 'foreign')
                else:
                    self.assertEqual(self.run_build(home, 'after_copy:LICENSE').returncode, 93)
                    if kind == 'edited-stage':
                        (home / '.plugin.cardine-stage/LICENSE').write_text('user edit')
                    elif kind == 'edited-published':
                        self.assertEqual(self.run_build(home).returncode, 0)
                        (destination / 'LICENSE').write_text('user edit')
                    else:
                        receipt = receipts.host_path('host-plugin', destination)
                        intent = receipts._load_intent(receipt)
                        intent['owner']['digest'] = 'foreign'
                        receipts._save_intent(receipt, intent)
                before = {p: (os.readlink(p) if p.is_symlink() else p.read_bytes())
                          for p in self.base.rglob('*') if (p.is_file() or p.is_symlink())
                          and p.suffix != '.guard'}
                self.assertNotEqual(self.run_build(home).returncode, 0)
                self.assertEqual(before, {p: (os.readlink(p) if p.is_symlink() else p.read_bytes())
                                         for p in self.base.rglob('*') if (p.is_file() or p.is_symlink())
                                         and p.suffix != '.guard'})

    def test_changed_inputs_and_symlinked_stage_are_refused(self):
        home = self.home()
        self.assertEqual(self.run_build(home, 'after_copy:LICENSE').returncode, 93)
        original = plugin.payload()
        with patch.object(plugin, 'payload', return_value={**original, 'LICENSE': b'changed input'}):
            with self.assertRaises(CardineError):
                plugin.build(home / 'plugin')
        (home / '.plugin.cardine-stage/LICENSE').unlink()
        (home / '.plugin.cardine-stage/LICENSE').symlink_to(home / 'foreign')
        self.assertNotEqual(self.run_build(home).returncode, 0)
        self.assertEqual((home / 'foreign').read_text(), 'user-owned content\n')

    def test_source_checkout_is_not_an_installation_destination(self):
        with self.assertRaisesRegex(CardineError, 'outside the source checkout'):
            plugin.build(ROOT / 'distribution')

    def claude(self, home, *arguments):
        executable = shutil.which('claude')
        if executable is None:
            self.skipTest('native Claude CLI is unavailable; no host-loading claim can be made')
        return subprocess.run([executable, 'plugin', *arguments], cwd=home,
                              env=self.environment(home), capture_output=True, text=True, timeout=45)

    def test_native_host_loads_seven_entries_and_zero_hooks_across_enablement_retry(self):
        # Native install/enable owns host configuration. Product packaging never writes it.
        for when in ('before', 'after'):
            with self.subTest(interruption=when):
                home = self.home()
                destination = plugin.build(home / 'plugin')
                installed = self.claude(home, 'install', 'cardine', '--marketplace', str(destination), '--json')
                self.assertEqual(installed.returncode, 0, installed.stdout + installed.stderr)
                self.assertEqual(self.claude(home, 'disable', 'cardine@cardine').returncode, 0)
                executable = shutil.which('claude')
                child = ("import os,subprocess,sys\n"
                         "if sys.argv[1] == 'before': os._exit(93)\n"
                         "subprocess.run(sys.argv[2:], check=True)\n"
                         "os._exit(93)\n")
                killed = subprocess.run([sys.executable, '-c', child, when, executable,
                                         'plugin', 'enable', 'cardine@cardine'], cwd=home,
                                        env=self.environment(home), capture_output=True, text=True, timeout=45)
                self.assertEqual(killed.returncode, 93, killed.stderr)
                retried = self.claude(home, 'enable', 'cardine@cardine')
                if when == 'after':
                    self.assertIn('already enabled', retried.stdout + retried.stderr)
                else:
                    self.assertEqual(retried.returncode, 0, retried.stdout + retried.stderr)
                details = self.claude(home, 'details', 'cardine@cardine')
                self.assertEqual(details.returncode, 0, details.stderr)
                self.assertRegex(details.stdout, r'Skills \(7\)')
                self.assertRegex(details.stdout, r'Hooks \(0\)')
                for name in (*plugin.SKILLS, *plugin.COMMANDS):
                    self.assertIn(name, details.stdout)
                # Initialize a real host session without issuing a model request.
                # Its user hook must run once even after interrupted plugin enablement.
                calls = home / 'hook-calls'
                hook = shlex.join([sys.executable, '-c',
                                   f'from pathlib import Path; Path({str(calls)!r}).open("a").write("call\\n")'])
                settings = json.dumps({'hooks': {'SessionStart': [{'hooks': [
                    {'type': 'command', 'command': hook}]}]}})
                initialized = subprocess.run(
                    [executable, '-p', '--settings', settings, '--input-format', 'stream-json',
                     '--output-format', 'stream-json', '--verbose'],
                    input=json.dumps({'type': 'control_request', 'request_id': 'distribution-probe',
                                      'request': {'subtype': 'initialize'}}) + '\n',
                    cwd=home, env={**self.environment(home), 'ANTHROPIC_API_KEY': 'local-probe-no-request'},
                    capture_output=True, text=True, timeout=45)
                self.assertEqual(initialized.returncode, 0, initialized.stderr)
                responses = [json.loads(line) for line in initialized.stdout.splitlines()]
                response = next(item['response'] for item in responses
                                if item.get('type') == 'control_response'
                                and item['response'].get('request_id') == 'distribution-probe')
                self.assertEqual(response['subtype'], 'success')
                names = {item['name'] for item in response['response']['commands']
                         if item['name'].startswith('cardine:')}
                self.assertEqual(names, {f'cardine:{name}' for name in (*plugin.SKILLS, *plugin.COMMANDS)})
                self.assertEqual(calls.read_text().splitlines(), ['call'])
                plugin.check(destination)
                self.assertEqual((home / 'foreign').read_text(), 'user-owned content\n')


if __name__ == '__main__':
    unittest.main()
