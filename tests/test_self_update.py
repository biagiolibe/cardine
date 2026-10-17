"""Exercise self-update against local remotes without network access."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import URLError, HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import meridian


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
            result = meridian.run_self_update(self.root, urlopen_fn=self.opener, **kwargs)
        self.output = output.getvalue()
        return result

    def detach(self):
        self.git(self.root, 'switch', '--detach', 'v1.2.1')

    def assert_refused(self, code, **kwargs):
        before = self.git(self.root, 'show-ref')
        head = self.git(self.root, 'rev-parse', 'HEAD')
        with self.assertRaises(meridian.MeridianStop) as error:
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
                         'releases/tag/v1.3.0', 'git fetch --tags'):
                self.assertIn(text, self.output)
            self.assertIn('switch --detach' if detached else 'merge --ff-only', self.output)

    def test_apply_stable(self):
        self.assertEqual(self.run_update(apply=True), 0)
        self.assertEqual(self.git(self.root, 'branch', '--show-current'), 'stable')
        self.assertEqual(self.git(self.root, 'rev-parse', 'HEAD'), self.git(self.remote, 'rev-parse', 'v1.3.0'))
        self.assertIn('Restart running Codex and Claude Code', self.output)
        self.assertIn('meridian upgrade --check', self.output)

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
        self.assert_refused('SELF_UPDATE_NON_FF', apply=True)

    def test_invalid_missing_and_mismatched_tags(self):
        self.detach()
        for tag in ('main', 'v1.9.9', '--upload-pack=bad'):
            self.assert_refused('SELF_UPDATE_TARGET', apply=True, target_tag=tag)
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
        with self.assertRaises(meridian.MeridianStop) as error:
            meridian.run_self_update(self.base / '.claude/plugins/cache/meridian/1.3.0', apply=True)
        self.assertEqual(error.exception.code, 'SELF_UPDATE_PLUGIN_CACHE')
        self.assertIn('/plugin marketplace update meridian', str(error.exception))

    def test_post_apply_verification(self):
        original = meridian.read_raw_version
        calls = []
        def read(root):
            calls.append(root)
            return original(root) if len(calls) == 1 else '0.0.0'
        with patch.object(meridian, 'read_raw_version', side_effect=read):
            with self.assertRaises(meridian.MeridianStop) as error:
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

    def test_unpublished_tag(self):
        self.detach()
        with patch.object(self, 'opener', side_effect=HTTPError('url', 404, 'missing', {}, None)):
            self.assert_refused('SELF_UPDATE_TARGET', apply=True, target_tag='v1.2.1')

    def test_managed_rules_do_not_allow_apply(self):
        self.assertNotIn('self-update', meridian.CODEX_USER_RULES)

    def test_cli_uses_own_checkout_and_requires_explicit_mode(self):
        with patch.object(sys, 'argv', ['meridian', '--framework-root', str(self.root),
                                      'self-update', '--check']), patch.object(
                meridian, 'run_self_update', return_value=0) as update:
            self.assertEqual(meridian._run_cli(meridian.LifecycleJournalEntry()), 0)
        update.assert_called_once_with(Path(meridian.__file__).resolve().parents[1],
                                       apply=False, target_tag=None)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            meridian.build_parser().parse_args(['self-update'])



if __name__ == '__main__':
    unittest.main()
