"""Exercise self-update against local remotes without network access."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch, ANY
from urllib.error import URLError, HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import cardine_cli
from cardine import cli as owner_cli
from cardine.release import update as owner_release_update
from cardine.shared import journal as owner_shared_journal
import cardine.shared.errors as shared_errors
from cardine.hosts import codex as owner_hosts_codex


class SelfUpdateTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.remote = self.base / 'remote'
        self.remote.mkdir()
        self.git(self.remote, 'init', '-b', 'stable')
        self.git(self.remote, 'config', 'user.email', 'test@example.com')
        self.git(self.remote, 'config', 'user.name', 'Test')
        self.commit(self.remote, '1.2.1')
        self.root = self.base / 'checkout'
        self.git(self.base, 'clone', str(self.remote), str(self.root))
        self.commit(self.remote, '1.3.0')
        self.output = ''

    def git(self, root, *args):
        return subprocess.run(['git', '-C', str(root), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def commit(self, root, version):
        (root / 'VERSION').write_text(version + '\n')
        self.git(root, 'add', 'VERSION')
        self.git(root, 'commit', '-m', version)
        self.git(root, 'tag', 'v' + version)

    def opener(self, request, timeout):
        tag = request.full_url.rsplit('/', 1)[-1]
        if tag == 'latest':
            tag = 'v1.3.0'
        return io.BytesIO(json.dumps({'tag_name': tag,
                        'body': 'Template-changing release: example'}).encode())

    def run_update(self, **kwargs):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = owner_release_update.run_self_update(self.root, urlopen_fn=self.opener, **kwargs)
        self.output = output.getvalue()
        return result

    def detach(self):
        self.git(self.root, 'switch', '--detach', 'v1.2.1')

    def assert_refused(self, code, **kwargs):
        before = self.git(self.root, 'show-ref')
        head = self.git(self.root, 'rev-parse', 'HEAD')
        with self.assertRaises(shared_errors.CardineStop) as error:
            self.run_update(**kwargs)
        self.assertEqual(error.exception.code, code)
        self.assertEqual(self.git(self.root, 'show-ref'), before)
        self.assertEqual(self.git(self.root, 'rev-parse', 'HEAD'), head)

    def test_plan_stable_and_tag_does_not_fetch(self):
        for detached in (False, True):
            if detached:
                self.detach()
            before = self.git(self.root, 'show-ref')
            self.assertEqual(self.run_update(), 0)
            self.assertEqual(self.git(self.root, 'show-ref'), before)
            for text in ('Current: 1.2.1', 'Target: 1.3.0', 'minor', 'template-changing',
                         'releases/tag/v1.3.0', 'git fetch --no-tags'):
                self.assertIn(text, self.output)
            self.assertIn('switch --detach' if detached else 'merge --ff-only', self.output)
            self.assertIn('Plan\n', self.output)
            self.assertNotIn('Next steps', self.output)
            self.assertNotIn('\x1b', self.output)

    def test_apply_stable(self):
        self.assertEqual(self.run_update(apply=True), 0)
        self.assertEqual(self.git(self.root, 'branch', '--show-current'), 'stable')
        self.assertEqual(self.git(self.root, 'rev-parse', 'HEAD'), self.git(self.remote, 'rev-parse', 'v1.3.0'))
        self.assertIn('Restart running Claude Code and Codex', self.output)
        for text in ('Apply', 'Next steps', 'authorize --check', 'authorize --apply', 'upgrade --check', 'upgrade --apply', 'commit', 'doctor --project'):
            self.assertIn(text, self.output)
        self.assertNotIn('\x1b', self.output)

    def test_apply_tag_and_rollback(self):
        self.detach()
        self.assertEqual(self.run_update(apply=True), 0)
        self.assertEqual(self.run_update(apply=True, target_tag='v1.2.1'), 0)
        self.assertEqual(self.git(self.root, 'rev-parse', 'HEAD'), self.git(self.root, 'rev-parse', 'v1.2.1'))
        self.assertEqual(self.git(self.root, 'branch', '--show-current'), '')
        self.assertIn('patch', self.output)

    def test_dirty_tracked_and_untracked(self):
        for path in ('VERSION', 'untracked'):
            original = (self.root / path).read_bytes() if (self.root / path).exists() else None
            (self.root / path).write_text('dirty')
            self.assert_refused('SELF_UPDATE_DIRTY', apply=True)
            if original is None:
                (self.root / path).unlink()
            else:
                (self.root / path).write_bytes(original)

    def test_development_branches(self):
        for name in ('main', 'feature'):
            self.git(self.root, 'switch', '-c', name)
            self.assert_refused('SELF_UPDATE_BRANCH', apply=True)

    def test_stable_explicit_target(self):
        self.assert_refused('SELF_UPDATE_BRANCH', apply=True, target_tag='v1.2.1')

    def test_non_fast_forward(self):
        self.git(self.root, 'config', 'user.email', 'test@example.com')
        self.git(self.root, 'config', 'user.name', 'Test')
        self.commit(self.root, '1.2.2')
        self.assert_refused('SELF_UPDATE_TARGET', apply=True)

    def test_invalid_missing_and_mismatched_tags(self):
        self.detach()
        for tag in ('main', 'v1.9.9', '--upload-pack=bad'):
            self.assert_refused('SELF_UPDATE_TARGET' if tag == 'v1.9.9' else 'SELF_UPDATE_INPUT_INVALID', apply=True, target_tag=tag)
        self.git(self.remote, 'tag', 'v1.9.0')
        self.assert_refused('SELF_UPDATE_TARGET', apply=True, target_tag='v1.9.0')

    def test_stable_not_at_release(self):
        self.commit(self.remote, '1.3.1')
        self.assert_refused('SELF_UPDATE_TARGET', apply=True)

    def test_untagged_detached(self):
        self.detach()
        self.git(self.root, 'tag', '-d', 'v1.2.1')
        self.assert_refused('SELF_UPDATE_VERIFY', apply=True)

    def test_plugin_cache(self):
        with self.assertRaises(shared_errors.CardineStop) as error:
            owner_release_update.run_self_update(self.base / '.claude/plugins/cache/cardine/1.3.0', apply=True)
        self.assertEqual(error.exception.code, 'SELF_UPDATE_PLUGIN_CACHE')
        self.assertTrue(str(error.exception).endswith('resume: claude plugin marketplace remove cardine && claude plugin marketplace add biagiolibe/cardine#v<version> && claude plugin install cardine@cardine'))

    def test_post_apply_verification(self):
        original = cardine_cli.read_raw_version
        calls = []
        def read(root):
            calls.append(root)
            return original(root) if len(calls) == 1 else '0.0.0'
        with patch.object(owner_release_update, 'read_raw_version', side_effect=read):
            with self.assertRaises(shared_errors.CardineStop) as error:
                self.run_update(apply=True)
        self.assertEqual(error.exception.code, 'SELF_UPDATE_VERIFY')
        self.assertIn('recovery: git -C', str(error.exception))
        self.assertIn('switch --detach v1.3.0', str(error.exception))

    def test_offline_check(self):
        before = self.git(self.root, 'show-ref')
        with patch.object(self, 'opener', side_effect=URLError('offline')):
            self.assertEqual(self.run_update(), 11)
        self.assertIn('Latest: unknown', self.output)
        self.assertEqual(self.git(self.root, 'show-ref'), before)

    def test_unrecognized_kind_line_explains_exit(self):
        def opener(request, timeout):
            return io.BytesIO(json.dumps({'tag_name': 'v1.3.0', 'body': 'No kind here'}).encode())
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = owner_release_update.run_self_update(self.root, urlopen_fn=opener)
        self.assertEqual(result, 11)
        text = output.getvalue()
        self.assertIn('Latest: unknown (release body has no recognized kind line)', text)
        self.assertIn('Exit 11 means', text)
        self.assertIn('releases', text)
        self.assertIn('git switch --detach v<version>', text)

    def test_unpublished_tag(self):
        self.detach()
        with patch.object(self, 'opener', side_effect=HTTPError('url', 404, 'missing', {}, None)):
            self.assert_refused('SELF_UPDATE_TARGET', apply=True, target_tag='v1.2.1')

    def test_managed_rules_do_not_allow_apply(self):
        self.assertNotIn('self-update', owner_hosts_codex.CODEX_USER_RULES)

    def test_cli_uses_own_checkout_and_requires_explicit_mode(self):
        with patch.object(sys, 'argv', ['cardine', '--framework-root', str(self.root),
                                      'self-update', '--check']), patch.object(
                owner_release_update, 'run_self_update', return_value=0) as update:
            self.assertEqual(owner_cli._run_cli(owner_shared_journal.LifecycleJournalEntry()), 0)
        update.assert_called_once_with(Path(cardine_cli.__file__).resolve().parents[1],
                                       apply=False, target_tag=None, finish=ANY)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            owner_cli.build_parser().parse_args(['self-update'])



class InstallerUpdateTest(unittest.TestCase):
    def opener(self, request, timeout):
        tag = request.full_url.rsplit('/', 1)[-1]
        tag = 'v2.0.0' if tag == 'latest' else tag
        return io.BytesIO(json.dumps({'tag_name': tag, 'body': 'Template-changing release: example'}).encode())

    def test_detection(self):
        from cardine.release.installer import detect_installer
        base = Path('/h/.local/pipx/venvs/cardine/lib/python3/site-packages/cardine')
        self.assertEqual(detect_installer(base, None), 'pipx')
        self.assertEqual(detect_installer(Path('/h/.local/share/uv/tools/cardine/lib/cardine'), None), 'uv')
        self.assertEqual(detect_installer(Path('/x/site-packages/cardine'), None), 'unknown')
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / '.git').mkdir()
            self.assertEqual(detect_installer(base, Path(directory)), 'clone')

    def update(self, kind, runner, **kwargs):
        from cardine.release.installer import run_installer_update
        lines = []
        result = run_installer_update(kind, '1.0.0', urlopen_fn=self.opener, runner=runner,
                                      out=lines.append, **kwargs)
        return result, lines

    def test_targets_and_preview_runs_nothing(self):
        for kind, prefix in (('pipx', ['pipx', 'install', '--force']), ('uv', ['uv', 'tool', 'install', '--force'])):
            for target, tag in ((None, 'v2.0.0'), ('v1.5.0', 'v1.5.0')):
                calls = []
                result, lines = self.update(kind, calls.append, apply=False, target_tag=target)
                self.assertIsNone(result)
                self.assertEqual(calls, [])
                self.assertIn(' '.join(prefix) + f' git+https://github.com/biagiolibe/cardine@{tag}', ' '.join(lines))
                calls = []
                result, _ = self.update(kind, lambda argv: calls.append(argv) or 0, apply=True, target_tag=target)
                self.assertEqual(result, tag[1:])
                self.assertEqual(calls, [prefix + [f'git+https://github.com/biagiolibe/cardine@{tag}']])

    def test_plain_output_and_captured_installer_output(self):
        from cardine.release.installer import run_installer_update
        from cardine.shared.errors import CardineError
        for apply in (False, True):
            lines = []
            run_installer_update('pipx', '1.0.0', apply=apply, urlopen_fn=self.opener,
                runner=lambda argv: subprocess.CompletedProcess(argv, 0, 'hidden output', ''), out=lines.append)
            text = '\n'.join(lines)
            self.assertIn('Plan', text)
            self.assertNotIn('hidden output', text)
            self.assertNotIn('\x1b', text)
            self.assertEqual('Next steps' in text, apply)
            if apply:
                for phrase in ('Apply', 'authorize --check', 'authorize --apply', 'upgrade --check', 'upgrade --apply', 'commit', 'doctor --project'):
                    self.assertIn(phrase, text)
        lines = []
        with self.assertRaises(CardineError):
            run_installer_update('pipx', '1.0.0', apply=True, urlopen_fn=self.opener,
                runner=lambda argv: subprocess.CompletedProcess(argv, 3, 'failure output', ''), out=lines.append)
        self.assertIn('failure output', '\n'.join(lines))

    def test_runtime_release_omits_upgrade(self):
        from cardine.release.update import finish_update
        lines = []
        finish_update('1.0.1', 'runtime-only', out=lines.append)
        self.assertNotIn('cardine upgrade', '\n'.join(lines))
        self.assertIn('cardine doctor', '\n'.join(lines))

    def test_failures_precede_alignment(self):
        from cardine.shared.errors import CardineError
        with self.assertRaises(CardineError):
            self.update('pipx', lambda argv: 3, apply=True)
        with self.assertRaises(CardineError):
            self.update('pipx', lambda argv: 0, apply=True, target_tag='main')
        from cardine.release.installer import run_installer_update
        calls = []
        with patch.object(self, 'opener', side_effect=URLError('offline')), self.assertRaises(CardineError):
            run_installer_update('uv', '1.0.0', apply=True, urlopen_fn=self.opener, runner=calls.append, out=print)
        self.assertEqual(calls, [])

    def test_unrecognized_kind_line_explains_exit(self):
        from cardine.release.installer import ReleaseUnresolved, run_installer_update
        def opener(request, timeout):
            return io.BytesIO(json.dumps({'tag_name': 'v2.0.0', 'body': 'No kind here'}).encode())
        lines = []
        with self.assertRaises(ReleaseUnresolved):
            run_installer_update('pipx', '1.0.0', apply=False, urlopen_fn=opener, out=lines.append)
        text = '\n'.join(lines)
        self.assertIn('Latest: unknown (release body has no recognized kind line)', text)
        self.assertIn('Exit 11 means', text)
        self.assertIn("pipx install --force 'git+https://github.com/biagiolibe/cardine@v<version>'", text)

    def test_stale_runtime_report_is_read_only(self):
        from cardine.release.installer import stale_runtime_report
        from cardine.lifecycle import receipts
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'my project'
            root.mkdir()
            lines = []
            self.assertFalse(stale_runtime_report(root, out=lines.append))
            path = receipts._local_authority_path(root)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('{}')
            self.assertTrue(stale_runtime_report(root, out=lines.append))
            self.assertIn(f"cardine authorize --apply --project '{root.resolve()}'", lines[-1])
            self.assertEqual(path.read_text(), '{}')
        self.assertFalse(stale_runtime_report(None))

    def test_plugin_alignment(self):
        from cardine.hosts.claude import align_claude_plugin
        from cardine.shared.errors import CardineError
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            registry = home / '.claude/plugins/installed_plugins.json'
            def write(version):
                registry.parent.mkdir(parents=True, exist_ok=True)
                registry.write_text(json.dumps({'plugins': {'cardine@cardine': [{'version': version}]}}))
            add = ['claude', 'plugin', 'marketplace', 'add', 'biagiolibe/cardine#v2.0.0']
            install = ['claude', 'plugin', 'install', 'cardine@cardine']
            remove = ['claude', 'plugin', 'marketplace', 'remove', 'cardine']
            found = lambda name: '/bin/claude'
            calls = []
            run = lambda argv: calls.append(argv) or 0
            self.assertEqual(align_claude_plugin(home, '2.0.0', runner=run, which=found, out=lambda t: None), 'aligned')
            self.assertEqual(calls, [add, install])
            write('2.0.0')
            calls.clear()
            self.assertEqual(align_claude_plugin(home, '2.0.0', runner=run, which=found, out=lambda t: None), 'match')
            self.assertEqual(calls, [])
            write('1.0.0')
            align_claude_plugin(home, '2.0.0', runner=run, which=found, out=lambda t: None)
            self.assertEqual(calls, [remove, add, install])
            lines = []
            calls.clear()
            self.assertEqual(align_claude_plugin(home, '2.0.0', runner=run, which=lambda n: None, out=lines.append), 'printed')
            self.assertEqual(calls, [])
            self.assertIn('  claude plugin install cardine@cardine', lines)
            outcomes = iter([0, 5, 0, 0, 0])
            failing = lambda argv: next(outcomes)
            with self.assertRaises(CardineError) as error:
                align_claude_plugin(home, '2.0.0', runner=failing, which=found, out=lambda t: None)
            self.assertIn('exit 5', str(error.exception))
            self.assertEqual(align_claude_plugin(home, '2.0.0', runner=failing, which=found, out=lambda t: None), 'aligned')


if __name__ == '__main__':
    unittest.main()
