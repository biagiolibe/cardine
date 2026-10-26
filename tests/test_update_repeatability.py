"""Kill non-run updates at each fetch/apply/verification boundary in fake roots."""
import contextlib
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

import test_self_update
from cardine.lifecycle import receipts
from cardine.release import update
from cardine.shared.errors import CardineStop

ROOT = Path(__file__).resolve().parents[1]
BOUNDARIES = tuple(when + '_update_' + effect for effect in ('fetch', 'apply', 'verify')
                   for when in ('before', 'after'))
CHILD = '''
import io, json, os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1] + '/scripts')
import cardine_cli
from cardine.lifecycle import receipts
from cardine.release.update import run_self_update
root, seam, latest, requested = Path(sys.argv[2]), sys.argv[3], sys.argv[4], json.loads(sys.argv[5])
def boundary(name):
    if name == seam:
        os._exit(93)
def opener(request, timeout):
    tag = request.full_url.rsplit('/', 1)[-1]
    if tag == 'latest':
        tag = latest
    return io.BytesIO(json.dumps(dict(tag_name=tag, body='Template-changing release: test')).encode())
receipts.boundary = boundary
raise SystemExit(run_self_update(root, apply=True, target_tag=requested, urlopen_fn=opener))
'''


class UpdateRepeatabilityTest(unittest.TestCase):
    def fixture(self):
        fixture = test_self_update.SelfUpdateTest()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        return fixture

    def child(self, f, boundary='', latest='v1.3.0', requested=None):
        return subprocess.run([sys.executable, '-c', CHILD, str(ROOT), str(f.root),
                               boundary, latest, json.dumps(requested)],
                              capture_output=True, text=True, timeout=30)

    def test_kills_resume_pinned_target_even_when_latest_advances(self):
        for detached in (False, True):
            for boundary in BOUNDARIES:
                with self.subTest(detached=detached, boundary=boundary):
                    f = self.fixture()
                    if detached:
                        f.detach()
                    foreign = f.base / 'foreign-work'
                    foreign.write_text('preserve this')
                    target = f.git(f.remote, 'rev-parse', 'HEAD')
                    self.assertEqual(self.child(f, boundary).returncode, 93)
                    path = receipts.nonrun_path(f.root, 'self-update')
                    interrupted = receipts._load_intent(path)
                    self.assertEqual(interrupted['target'], target)
                    self.assertIsNone(interrupted['result'])
                    f.commit(f.remote, '1.4.0')
                    result = self.child(f, latest='v1.4.0')
                    self.assertEqual(result.returncode, 0, result.stderr)
                    final = receipts._load_intent(path)
                    self.assertEqual(final['operation_id'], interrupted['operation_id'])
                    self.assertEqual(final['target'], target)
                    self.assertEqual(final['result'], dict(head=target, version='1.3.0', verified=True))
                    self.assertEqual(set(final['effects'].values()), {'done'})
                    self.assertEqual(f.git(f.root, 'rev-parse', 'HEAD'), target)
                    self.assertEqual(f.git(f.root, 'branch', '--show-current'), '' if detached else 'stable')
                    self.assertEqual(f.git(f.root, 'rev-list', '--count', 'HEAD'), '2')
                    self.assertEqual(f.git(f.root, 'reflog', '--format=%H').splitlines().count(target), 1)
                    self.assertEqual(f.git(f.root, 'status', '--porcelain'), '')
                    self.assertEqual(foreign.read_text(), 'preserve this')

    def test_explicit_target_rollback_retries_original_operation(self):
        for boundary in BOUNDARIES:
            with self.subTest(boundary=boundary):
                f = self.fixture()
                f.detach()
                self.assertEqual(f.run_update(apply=True), 0)
                self.assertEqual(self.child(f, boundary, requested='v1.2.1').returncode, 93)
                result = self.child(f, requested='v1.2.1')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual((f.root / 'VERSION').read_text(), '1.2.1\n')

    def test_changed_input_and_foreign_owner_at_every_effect(self):
        for boundary in BOUNDARIES:
            for change in ('remote', 'owner'):
                with self.subTest(boundary=boundary, change=change):
                    f = self.fixture()
                    def inject(name):
                        if name != boundary:
                            return
                        if change == 'remote':
                            f.git(f.root, 'remote', 'set-url', 'origin', str(f.base / 'foreign'))
                        else:
                            path = receipts.nonrun_path(f.root, 'self-update')
                            intent = receipts._load_intent(path)
                            intent['owner']['root'] = str(f.base / 'foreign')
                            receipts._save_intent(path, intent)
                    with patch.object(receipts, 'boundary', side_effect=inject):
                        with self.assertRaises(CardineStop) as error:
                            f.run_update(apply=True)
                    self.assertEqual(error.exception.code, 'SELF_UPDATE_VERIFY')
                    path = receipts.nonrun_path(f.root, 'self-update')
                    self.assertIsNone(receipts._load_intent(path)['result'])
                    refs = f.git(f.root, 'show-ref')
                    with self.assertRaises(CardineStop):
                        f.run_update(apply=True)
                    self.assertEqual(f.git(f.root, 'show-ref'), refs)

    def test_dirty_retry_preserves_tracked_and_untracked_work(self):
        for boundary in BOUNDARIES:
            for name in ('VERSION', 'foreign-work'):
                with self.subTest(boundary=boundary, name=name):
                    f = self.fixture()
                    self.assertEqual(self.child(f, boundary).returncode, 93)
                    (f.root / name).write_text('foreign edits\n')
                    path = receipts.nonrun_path(f.root, 'self-update')
                    before = path.read_bytes()
                    refs = f.git(f.root, 'show-ref')
                    with self.assertRaises(CardineStop) as error:
                        f.run_update(apply=True)
                    self.assertEqual(error.exception.code, 'SELF_UPDATE_DIRTY')
                    self.assertEqual((f.root / name).read_text(), 'foreign edits\n')
                    self.assertEqual(path.read_bytes(), before)
                    self.assertEqual(f.git(f.root, 'show-ref'), refs)

    def test_changed_requested_target_and_source_are_rejected(self):
        for change in ('request', 'head', 'branch', 'receipt'):
            with self.subTest(change=change):
                f = self.fixture()
                f.detach()
                self.assertEqual(self.child(f, 'before_update_fetch').returncode, 93)
                path = receipts.nonrun_path(f.root, 'self-update')
                if change == 'head':
                    f.git(f.root, 'config', 'user.email', 'test@example.com')
                    f.git(f.root, 'config', 'user.name', 'Test')
                    f.git(f.root, 'commit', '--allow-empty', '-m', 'Foreign work')
                    f.git(f.root, 'tag', '-f', 'v1.2.1')
                elif change == 'branch':
                    f.git(f.root, 'switch', 'stable')
                elif change == 'receipt':
                    path.write_bytes(path.read_bytes().replace(b'1.3.0', b'1.4.0'))
                before = path.read_bytes()
                refs = f.git(f.root, 'show-ref')
                with self.assertRaises(CardineStop):
                    f.run_update(apply=True, **({'target_tag': 'v1.2.1'} if change == 'request' else {}))
                self.assertEqual(f.git(f.root, 'show-ref'), refs)
                self.assertEqual(path.read_bytes(), before)

    def test_plugin_owned_retry_has_no_effects(self):
        f = self.fixture()
        self.assertEqual(self.child(f, 'before_update_apply').returncode, 93)
        path = receipts.nonrun_path(f.root, 'self-update')
        before = path.read_bytes()
        plugin = f.base / 'plugins/cache/meridian/release'
        plugin.parent.mkdir(parents=True)
        f.root.rename(plugin)
        with self.assertRaises(CardineStop) as error:
            update.run_self_update(plugin, apply=True, urlopen_fn=f.opener)
        self.assertEqual(error.exception.code, 'SELF_UPDATE_PLUGIN_CACHE')
        self.assertEqual((plugin / path.relative_to(f.root.resolve())).read_bytes(), before)

    def test_live_foreign_writer_and_symlink_are_preserved(self):
        for mode in ('live', 'symlink'):
            with self.subTest(mode=mode):
                f = self.fixture()
                path = receipts.nonrun_path(f.root, 'self-update')
                path.parent.mkdir(parents=True, exist_ok=True)
                foreign = f.base / 'foreign'
                foreign.write_text('foreign bytes')
                if mode == 'symlink':
                    path.symlink_to(foreign)
                with receipts.nonrun_lock(path) if mode == 'live' else contextlib.nullcontext():
                    with self.assertRaises(CardineStop) as error:
                        f.run_update(apply=True)
                self.assertEqual(error.exception.code, 'SELF_UPDATE_VERIFY')
                self.assertEqual(foreign.read_text(), 'foreign bytes')
                self.assertEqual((f.root / 'VERSION').read_text(), '1.2.1\n')

    def test_repeated_checks_do_not_write_or_resolve_new_latest_during_retry(self):
        f = self.fixture()
        for pending in (False, True):
            if pending:
                self.assertEqual(self.child(f, 'before_update_fetch').returncode, 93)
            path = receipts.nonrun_path(f.root, 'self-update')
            before = path.read_bytes() if path.exists() else None
            refs = f.git(f.root, 'show-ref')
            with patch.object(receipts, '_durable', side_effect=AssertionError('check wrote receipt')):
                for _ in range(2):
                    with patch.object(f, 'opener', side_effect=AssertionError('retry resolved latest')) if pending else contextlib.nullcontext():
                        self.assertEqual(f.run_update(), 0)
            self.assertEqual(f.git(f.root, 'show-ref'), refs)
            self.assertEqual(path.read_bytes() if path.exists() else None, before)

    def test_foreign_checkout_receipt_is_not_adopted(self):
        first, second = self.fixture(), self.fixture()
        self.assertEqual(self.child(first, 'before_update_fetch').returncode, 93)
        original = receipts.nonrun_path(first.root, 'self-update').read_bytes()
        path = receipts.nonrun_path(second.root, 'self-update')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(original)
        with self.assertRaises(CardineStop) as error:
            second.run_update(apply=True)
        self.assertEqual(error.exception.code, 'SELF_UPDATE_VERIFY')
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual((second.root / 'VERSION').read_text(), '1.2.1\n')

    def test_pinned_tag_change_fails_closed_without_applying(self):
        f = self.fixture()
        self.assertEqual(self.child(f, 'before_update_fetch').returncode, 93)
        head = f.git(f.root, 'rev-parse', 'HEAD')
        f.commit(f.remote, '1.4.0')
        f.git(f.remote, 'tag', '-f', 'v1.3.0')
        with self.assertRaises(CardineStop) as error:
            f.run_update(apply=True)
        self.assertEqual(error.exception.code, 'SELF_UPDATE_VERIFY')
        self.assertEqual(f.git(f.root, 'rev-parse', 'HEAD'), head)
        path = receipts.nonrun_path(f.root, 'self-update')
        self.assertIsNone(receipts._load_intent(path)['result'])

    def test_applied_head_is_reconciled_without_network_or_second_switch(self):
        f = self.fixture()
        f.detach()
        self.assertEqual(self.child(f, 'after_update_apply').returncode, 93)
        f.remote.rename(f.base / 'offline')
        with patch.object(f, 'opener', side_effect=AssertionError('retry resolved latest')):
            self.assertEqual(f.run_update(apply=True), 0)
        target = f.git(f.root, 'rev-parse', 'HEAD')
        self.assertEqual(f.git(f.root, 'reflog', '--format=%H').splitlines().count(target), 1)


if __name__ == '__main__':
    unittest.main()
