"""Receipt coverage, explicit clone authority, concurrency and killed-writer replay."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from cardine.lifecycle import receipts
from cardine.shared.errors import CardineError
from cardine.tasks.contract_update import update_task_contract
from cardine.tasks.creation import create_task
from cardine.tasks.state import validate_task_state
from project_config_support import write_project_config
from task_contract_support import contract_record, VALIDATION

ROOT = Path(__file__).resolve().parents[1]
POINTS = ('before_intent', 'after_intent', 'before_staged_pair', 'after_staged_pair',
          'before_state_replace', 'after_state_replace', 'before_result_receipt', 'after_result_receipt')


class RunReceiptsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        write_project_config(self.root, 'lean', validation=deepcopy(VALIDATION))
        self.text = contract_record()
        self.record = self.root / 'tasks/001.md'
        self.path = self.root / '.cardine/tasks/001.json'

    def create(self):
        return create_task(self.root, '001', self.text)

    def state(self):
        return json.loads(self.path.read_bytes())

    def revise(self):
        self.record.write_text(self.text.replace('## Objective', 'Review: required\n## Objective'))
        return update_task_contract(self.root, '001')

    def git(self, *args, root=None):
        return subprocess.check_output(['git', '-C', str(root or self.root), *args],
                                       stderr=subprocess.DEVNULL, text=True).strip()

    def init_git(self):
        self.git('init', '-b', 'main')
        self.git('config', 'user.name', 'Receipt Test')
        self.git('config', 'user.email', 'receipt@example.test')
        self.git('add', '.')
        self.git('commit', '-m', 'Initial policy')

    def kill(self, point, *, revision=False):
        proposal = self.root / 'proposal.txt'
        proposal.write_text(self.text)
        script = '''
import os, sys
from pathlib import Path
from cardine.lifecycle import receipts
from cardine.tasks.creation import create_task
from cardine.tasks.contract_update import update_task_contract
def stop(name):
    if name == sys.argv[2]: os._exit(77)
receipts.boundary = stop
root = Path(sys.argv[1])
if sys.argv[3] == 'revision':
    update_task_contract(root, '001')
else:
    create_task(root, '001', (root / 'proposal.txt').read_text())
'''
        result = subprocess.run([sys.executable, '-c', script, str(self.root), point,
                                 'revision' if revision else 'creation'],
                                env={**os.environ, 'PYTHONPATH': str(ROOT / 'src')},
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 77, result.stderr)

    def test_creation_killed_before_and_after_all_four_boundaries(self):
        for point in POINTS:
            with self.subTest(point=point), tempfile.TemporaryDirectory() as directory:
                self.root = Path(directory).resolve()
                self.record = self.root / 'tasks/001.md'
                self.path = self.root / '.cardine/tasks/001.json'
                write_project_config(self.root, 'lean', validation=deepcopy(VALIDATION))
                self.kill(point)
                intent = receipts._intent_path(self.root, '001')
                before = receipts._load_intent(intent)['state'] if intent.exists() else None
                self.create()  # Same operation, same input, no recovery switch.
                state = self.state()
                receipts.verify_receipts(self.root, state)
                self.assertEqual(len(state['run']['receipts']), 1)
                self.assertEqual(state['transitions'], [])
                if before is not None:
                    self.assertEqual(state, before)
                self.assertEqual(self.record.read_text(), self.text)
                self.assertFalse(intent.exists())
                self.assertEqual(list(self.root.rglob('*.stage')), [])

    def test_revision_killed_before_and_after_all_four_boundaries(self):
        for point in POINTS:
            with self.subTest(point=point), tempfile.TemporaryDirectory() as directory:
                self.root = Path(directory).resolve()
                self.record = self.root / 'tasks/001.md'
                self.path = self.root / '.cardine/tasks/001.json'
                write_project_config(self.root, 'lean', validation=deepcopy(VALIDATION))
                self.create()
                original = self.state()['run']['receipts'][0]
                self.record.write_text(self.text.replace('## Objective', 'Review: required\n## Objective'))
                self.kill(point, revision=True)
                update_task_contract(self.root, '001')
                state = self.state()
                receipts.verify_receipts(self.root, state)
                self.assertEqual(len(state['run']['receipts']), 2)
                self.assertEqual(state['run']['receipts'][0], original)
                self.assertEqual(state['run']['receipts'][1]['predecessor'], original['digest'])
                self.assertEqual(len(state['contract_history']), 1)
                self.assertFalse(update_task_contract(self.root, '001')['updated'])
                self.assertEqual(self.state(), state)

    def test_changed_staged_bytes_fail_closed_and_keep_foreign_files(self):
        self.kill('after_staged_pair')
        intent = receipts._load_intent(receipts._intent_path(self.root, '001'))
        staged = self.root / intent['files']['tasks/001.md']['staged']
        staged.write_text('foreign bytes')
        foreign = self.root / 'unrelated.txt'
        foreign.write_text('keep me')
        with self.assertRaisesRegex(CardineError, 'changed staged bytes'):
            self.create()
        self.assertFalse(self.record.exists())
        self.assertFalse(self.path.exists())
        self.assertEqual(staged.read_text(), 'foreign bytes')
        self.assertEqual(foreign.read_text(), 'keep me')

    def test_changed_proposal_and_changed_published_bytes_refuse_replay(self):
        self.kill('before_state_replace')
        before = self.record.read_bytes()
        with self.assertRaisesRegex(CardineError, 'different command'):
            update_task_contract(self.root, '001')
        self.text += '\nChanged input.\n'
        with self.assertRaisesRegex(CardineError, 'changed creation input'):
            self.create()
        self.assertEqual(self.record.read_bytes(), before)
        self.text = before.decode()
        self.record.write_text('foreign record')
        with self.assertRaisesRegex(CardineError, 'changed (file|staged bytes)'):
            self.create()
        self.assertEqual(self.record.read_text(), 'foreign record')

    def test_changed_source_refuses_replay(self):
        self.init_git()
        self.kill('after_intent')
        (self.root / 'unrelated').write_text('new source')
        self.git('add', 'unrelated')
        self.git('commit', '-m', 'Concurrent source')
        with self.assertRaisesRegex(CardineError, 'source changed'):
            self.create()
        self.assertFalse(self.record.exists())

    def test_state_contract_and_record_edits_are_uncovered(self):
        self.create()
        original = self.state()
        for coherent in (False, True):
            state = deepcopy(original)
            state['contract']['options']['validationRetryLimit'] += 1
            if coherent:
                # Schema-valid, internally coherent changes still lack a writer result.
                state['contract']['options']['review'] = 'required'
            validate_task_state(state, '001', 'single')
            with self.assertRaisesRegex(CardineError, 'changed contract'):
                receipts.verify_receipts(self.root, state)
        self.record.write_text(self.text + '\nforeign\n')
        with self.assertRaisesRegex(CardineError, 'artifact'):
            receipts.verify_receipts(self.root, original)
        self.record.write_text(self.text)
        state = deepcopy(original)
        state['transitions'] = [dict(at='2026-10-23T00:00:00Z', commit='a'*40,
                                     **{'from': 'queued', 'to': 'in_progress'})]
        state['status'] = 'in_progress'
        validate_task_state(state, '001', 'single')
        with self.assertRaisesRegex(CardineError, 'changed state'):
            receipts.verify_receipts(self.root, state)

    def test_chain_tampering_missing_receipts_and_fabricated_result_refuse(self):
        self.create()
        self.revise()
        original = self.state()
        for mutation in ('chain', 'missing', 'result'):
            state = deepcopy(original)
            if mutation == 'chain':
                state['run']['receipts'][1]['predecessor'] = 'f'*64
            elif mutation == 'missing':
                state.pop('run')
            else:
                state['run']['receipts'][0]['result'] = 'invented'
            with self.subTest(mutation=mutation), self.assertRaises((ValueError, CardineError)):
                receipts.verify_receipts(self.root, state)

    def test_policy_and_runtime_override_cannot_authorize_themselves(self):
        self.create()
        authority = receipts.require_authority(self.root)
        policy = self.root / '.cardine/project.json'
        original = policy.read_bytes()
        write_project_config(self.root, 'lean', validation=deepcopy(VALIDATION),
                             taskDefaults={'review': 'not_required'})
        with self.assertRaisesRegex(CardineError, 'reauthorization'):
            receipts.verify_receipts(self.root, self.state())
        from cardine.tasks.contract import resolve_task_contract
        coherent = self.state()
        coherent['contract'] = resolve_task_contract(self.root, '001', text=self.text)
        validate_task_state(coherent, '001', 'single')
        with self.assertRaisesRegex(CardineError, 'reauthorization'):
            receipts.verify_receipts(self.root, coherent)
        with self.assertRaisesRegex(CardineError, 'reauthorization'):
            create_task(self.root, '002', contract_record('002'))
        policy.write_bytes(original)
        with self.assertRaisesRegex(CardineError, 'changed contract'):
            receipts.verify_receipts(self.root, coherent)
        with patch.object(receipts, 'observed_authority', return_value=dict(authority, runtime='f'*64)):
            with self.assertRaisesRegex(CardineError, 'reauthorization'):
                receipts.verify_receipts(self.root, self.state())
        with patch.dict(os.environ, {'CARDINE_WORKTREE_ROOT': str(self.root / 'foreign-root')}):
            with self.assertRaisesRegex(CardineError, 'reauthorization'):
                receipts.verify_receipts(self.root, self.state())
        # Environment runtime labels do not select or bless a different runtime.
        with patch.dict(os.environ, {'CARDINE_RUNTIME': '/foreign/runtime'}):
            self.assertEqual(receipts.require_authority(self.root), authority)
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            module = runtime / 'src/cardine/lifecycle/receipts.py'
            module.parent.mkdir(parents=True)
            module.write_text('foreign runtime')
            with patch.object(receipts, '__file__', str(module)):
                with self.assertRaisesRegex(CardineError, 'reauthorization'):
                    receipts.verify_receipts(self.root, self.state())

    def test_clone_requires_explicit_policy_acceptance_and_never_imports_state(self):
        self.init_git()
        self.create()
        accepted_main = receipts.require_authority(self.root)['accepted_main']
        self.git('add', '.')
        self.git('commit', '-m', 'Portable receipt')
        with tempfile.TemporaryDirectory() as directory:
            clone = Path(directory) / 'clone'
            subprocess.run(['git', 'clone', '-q', str(self.root), str(clone)], check=True)
            state = json.loads((clone / '.cardine/tasks/001.json').read_bytes())
            with self.assertRaisesRegex(CardineError, 'reauthorization'):
                receipts.verify_receipts(clone, state, portable=True)
            observed = dict(receipts.observed_authority(clone), accepted_main=accepted_main)
            receipts.authorize_project(clone, accepted=observed)
            receipts.verify_receipts(clone, state, portable=True)
            with self.assertRaisesRegex(CardineError, 'reauthorization'):
                receipts.verify_receipts(clone, state)
            imported = receipts.reauthorize_task(clone, '001')
            receipts.verify_receipts(clone, imported)
            self.assertEqual(len(imported['run']['receipts']), 2)
            self.assertEqual(receipts.reauthorize_task(clone, '001'), imported)
            state.pop('run')
            with self.assertRaisesRegex(CardineError, 'missing completed'):
                receipts.verify_receipts(clone, state, portable=True)
            (clone / '.cardine/receipt-authority.json').unlink()
            with self.assertRaisesRegex(CardineError, 'reauthorization'):
                create_task(clone, '002', contract_record('002'))

    def test_live_foreign_writer_and_unsafe_paths_refuse_without_effects(self):
        self.create()
        before = self.path.read_bytes()
        with receipts.task_lock(self.root, '001'), ThreadPoolExecutor() as pool:
            future = pool.submit(lambda: update_task_contract(self.root, 'task-001'))
            with self.assertRaisesRegex(CardineError, 'live foreign operation'):
                future.result()
        self.assertEqual(self.path.read_bytes(), before)
        from cardine.tasks.state import read_task_state
        read_bytes = Path.read_text
        def start_during_read(path, *args, **kwargs):
            result = read_bytes(path, *args, **kwargs)
            if path == self.path:
                receipts._intent_path(self.root, '001').write_text('reader barrier')
            return result
        with patch.object(Path, 'read_text', start_during_read):
            with self.assertRaisesRegex(CardineError, 'creation changed during read'):
                read_task_state(self.root, '001', 'single',
                                stop_factory=lambda code, detail, **kw: CardineError(detail))
        receipts._intent_path(self.root, '001').unlink()
        for path in ('../outside', '/absolute', '.'):
            with self.assertRaises(CardineError):
                receipts.safe_path(self.root, path)
        with tempfile.TemporaryDirectory() as directory:
            (self.root / 'link').symlink_to(directory)
            with self.assertRaisesRegex(CardineError, 'symlink'):
                receipts.safe_path(self.root, 'link/state')
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_foreign_state_at_result_boundary_is_never_replaced(self):
        self.create()
        self.record.write_text(self.text.replace('Priority: P1', 'Priority: P0'))
        def foreign(name):
            if name == 'before_result_receipt':
                self.path.write_text('foreign state')
        with patch.object(receipts, 'boundary', side_effect=foreign):
            with self.assertRaisesRegex(CardineError, 'state changed before result'):
                update_task_contract(self.root, '001')
        self.assertEqual(self.path.read_text(), 'foreign state')
        self.assertTrue(receipts.pending_operation(self.root, '001'))
        with self.assertRaisesRegex(CardineError, 'changed file'):
            update_task_contract(self.root, '001')
        self.assertEqual(self.path.read_text(), 'foreign state')

    def test_task_branch_policy_cannot_pin_itself_as_accepted_main(self):
        self.init_git()
        self.git('switch', '-c', 'task-001')
        write_project_config(self.root, 'lean', validation=deepcopy(VALIDATION),
                             taskDefaults={'review': 'not_required'})
        with self.assertRaisesRegex(CardineError, 'policy differs from accepted main'):
            self.create()
        self.assertFalse(self.record.exists())
        self.assertFalse(self.path.exists())
        self.assertFalse((self.root / '.cardine/receipt-authority.json').exists())

    def test_authority_acceptance_and_observation_are_explicit_and_read_only(self):
        observed = receipts.observed_authority(self.root)
        self.assertEqual(receipts.observed_authority(self.root), observed)
        self.assertFalse((self.root / '.cardine/receipt-authority.json').exists())
        with self.assertRaisesRegex(CardineError, 'reauthorization'):
            receipts.require_authority(self.root)
        with self.assertRaisesRegex(CardineError, 'accept'):
            receipts.authorize_project(self.root, accepted=dict(observed, policy='f'*64))
        receipts.authorize_project(self.root, accepted=observed)
        self.assertEqual(receipts.require_authority(self.root), observed)


PUBLICATION_ALLOWLIST = {'integration/finalize.py': ["receipts._durable(target, base64.b64decode(output['content'], validate=True))"],
 'integration/merge.py': ['_write_json_atomic(integration_path, staged, exclusive=True)',
                          '_write_json_atomic(lease_path, lease, exclusive=True)'],
 'lifecycle/receipts.py': ['_durable(path, encoded(accepted))',
                           '_durable(path, encoded(dict(value, digest=digest(encoded(value)))))',
                           "_durable(path, encoded(intent['pending_state']))",
                           '_durable(path, final_bytes)',
                           '_durable(path, source.read_bytes())',
                           "_durable(safe_path(root, item['staged']), base64.b64decode(item['content'], "
                           'validate=True))',
                           "os.fdopen(descriptor, 'a')",
                           'os.link(source, path)',
                           'os.open(guard, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 384)',
                           "path.open('a')",
                           'write_state_bytes(path, content)'],
 'lifecycle/validation.py': ["path.open('a')"],
 'shared/atomic.py': ["os.fdopen(descriptor, 'wb')",
                      'os.link(temporary, path)',
                      'os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 384)',
                      'os.replace(temporary, path)'],
 'shared/journal.py': ['os.open(journal, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 420)',
                       'os.replace(journal, directory / names().journal_rotated_name)'],
 'shared/jsonio.py': ["os.fdopen(descriptor, 'wb')",
                      "os.fdopen(descriptor, 'wb')",
                      'os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 384)',
                      'os.replace(temporary, path)'],
 'tasks/contract_update.py': ['_write_json_atomic(path, state)'],
 'tasks/creation.py': ["guard.open('a')"],
 'tasks/importer.py': ["path.open('x', encoding='utf-8')"],
 'tasks/preflight.py': ["task_file.write_text(reconciled, encoding='utf-8')"],
 'tasks/state_core.py': ["os.fdopen(descriptor, 'wb')", 'os.replace(temporary, path)'],
 'tasks/status_render.py': ["os.fdopen(descriptor, 'wb')",
                            'os.replace(restore, path)',
                            'os.replace(source, target)'],
 'templates/files.py': ["capped_path.write_text(capped_text, encoding='utf-8')"],
 'templates/manifest.py': ["destination.write_text(output.decode('utf-8'), encoding='utf-8')"],
 'templates/merge.py': ['output.write_bytes(process.stdout)', 'shutil.copyfile(item.source, destination)'],
 'worktree/preparation.py': ["path.open('a')",
                             'receipts._durable(state_path, receipts.encoded(after))',
                             'receipts._durable(state_path, receipts.encoded(lifecycle))']}


# Explicit recipes make a newly registered kind fail until its writer mode is
# chosen. Fixture kinds remain supported for existing external test callers.
WRITER_RECIPES = {
    **{kind: (kind, False) for kind in (
        'creation', 'contract_revision', 'reauthorization', 'ci-push', 'ci-result',
        'candidate-validation', 'landing_state', 'task-validation',
        'implementation-delivery', 'validation-command',
        'fixture', 'fixture-surface', 'layout-fixture', 'fixture-allowance',
        'fixture-review-policy', 'fixture-issued-review', 'fixture-missing-observation',
        'fixture-baseline', 'fixture-contract-revision', 'foreign-command',
        'fixture-change', 'fixture-validation')},
    **{kind: (kind + ':' + 'a' * 64, False) for kind in (
        'transition', 'spike_outcome', 'host-launch', 'cancel', 'abort',
        'abort-result', 'review-submit')},
    'review_verdict': ('review_verdict:' + 'a' * 64, True),
}


def retry_writer(root, proposal):
    """Retry the same writer transaction, including its completed-result case."""
    from cardine.tasks.state_core import state_path
    with receipts.task_lock(root, '001'):
        if receipts.pending_operation(root, '001'):
            return receipts.replay_operation(root, '001', kind=proposal['kind'])
        current = json.loads(state_path(root, '001').read_bytes())
        if current['run'].get('reviewRecordedAt') == proposal['state']['run']['reviewRecordedAt']:
            return current
        return receipts.write_operation(root, '001', proposal['state'],
            previous=proposal['previous'], kind=proposal['kind'],
            files={'writer-output.txt': proposal['content'].encode()},
            state_first=proposal['state_first'])


class ReceiptWriterProofTest(unittest.TestCase):
    def kill_writer(self, root, proposal_path, point):
        script = '''
import json, os, sys
from pathlib import Path
from cardine.lifecycle import receipts
from test_run_receipts import retry_writer
receipts.boundary = lambda name: os._exit(77) if name == sys.argv[3] else None
retry_writer(Path(sys.argv[1]), json.loads(Path(sys.argv[2]).read_text()))
'''
        result = subprocess.run([sys.executable, '-c', script, str(root), str(proposal_path), point],
            env={**os.environ, 'PYTHONPATH': os.pathsep.join((str(ROOT / 'src'), str(ROOT / 'tests')))},
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 77, result.stderr)

    def test_every_registered_kind_has_an_explicit_writer_recipe(self):
        self.assertEqual(set(WRITER_RECIPES), receipts.OPERATION_KINDS)

    def prove_kind(self, family):
        fixture = RunReceiptsTest()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.init_git()
        fixture.create()
        root = fixture.root
        head = fixture.git('rev-parse', 'HEAD')
        commits = fixture.git('rev-list', '--count', 'HEAD')
        foreign = root / 'foreign.txt'
        foreign.write_bytes(b'preserve foreign bytes\n')
        foreign_stage = fixture.path.parent / '.foreign.stage'
        foreign_stage.write_bytes(b'not this transaction\n')
        proposal_path = root.parent / (root.name + '-writer-proposal.json')
        self.addCleanup(proposal_path.unlink, missing_ok=True)
        sequence = 0

        def proposal(kind, state_first):
            nonlocal sequence
            sequence += 1
            previous = fixture.state()
            state = deepcopy(previous)
            state['run']['reviewRecordedAt'] = f'2026-10-27T00:{sequence // 60:02d}:{sequence % 60:02d}Z'
            return dict(kind=kind, state_first=state_first, previous=previous,
                        state=state, content=f'projection {sequence}\n')

        kind, state_first = WRITER_RECIPES[family]
        # Observe the product seam, rather than maintaining a second list of
        # boundaries. A new exposed boundary is automatically killed too.
        observed = []
        with patch.object(receipts, 'boundary', side_effect=observed.append):
            retry_writer(root, proposal(kind, state_first))
        self.assertTrue(observed, family)
        self.assertEqual(len(observed), len(set(observed)), family)
        for point in observed:
            with self.subTest(kind=family, point=point):
                item = proposal(kind, state_first)
                proposal_path.write_text(json.dumps(item))
                original_receipts = item['previous']['run']['receipts']
                self.kill_writer(root, proposal_path, point)
                result = retry_writer(root, item)
                self.assertEqual(retry_writer(root, item), result)
                receipts.verify_receipts(root, result)
                self.assertEqual(result['run']['receipts'][:-1], original_receipts)
                self.assertEqual(len(result['run']['receipts']), len(original_receipts) + 1)
                self.assertEqual(result['run']['receipts'][-1]['kind'], kind)
                self.assertEqual(result['run']['reviewRecordedAt'], item['state']['run']['reviewRecordedAt'])
                self.assertEqual((root / 'writer-output.txt').read_text(), item['content'])
                self.assertEqual(fixture.git('rev-parse', 'HEAD'), head)
                self.assertEqual(fixture.git('rev-list', '--count', 'HEAD'), commits)
                self.assertEqual(foreign.read_bytes(), b'preserve foreign bytes\n')
                self.assertEqual(foreign_stage.read_bytes(), b'not this transaction\n')
                self.assertFalse(receipts.pending_operation(root, '001'))
                self.assertEqual(list(root.rglob('*.stage')), [foreign_stage])

    def test_unknown_operation_kind_refuses_before_any_write(self):
        fixture = RunReceiptsTest()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.create()
        before = {p.relative_to(fixture.root): p.read_bytes()
                  for p in fixture.root.rglob('*') if p.is_file()}
        with receipts.task_lock(fixture.root, '001'), self.assertRaisesRegex(CardineError, 'operation kind'):
            receipts.write_operation(fixture.root, '001', fixture.state(),
                                     previous=fixture.state(), kind='unregistered-operation')
        self.assertEqual({p.relative_to(fixture.root): p.read_bytes()
                          for p in fixture.root.rglob('*') if p.is_file()}, before)

    def test_task_state_publication_has_no_new_writer_bypass(self):
        # Inventory actual publication primitives, including imported aliases.
        # Every operational state/result publication is in receipts._finish.
        # The other existing sinks publish policy/templates, lifecycle metadata,
        # sparse import/upgrade input (not receipt authority), or restore bytes
        # already covered by a receipt. A new sink needs an explicit review;
        # merely adding a new operation cannot silently add a direct state write.
        import ast

        def publications(source):
            tree = ast.parse(source)
            aliases = {}
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    for item in node.names:
                        aliases[item.asname or item.name] = item.name
            calls = []
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                name = node.func.attr if isinstance(node.func, ast.Attribute) else (
                    aliases.get(node.func.id, node.func.id) if isinstance(node.func, ast.Name) else '')
                owner = (aliases.get(node.func.value.id, node.func.value.id)
                         if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) else '')
                publish = name in ('write_text', 'write_bytes', 'write_state_bytes', '_write_json_atomic', '_durable')
                publish |= owner in ('os', 'shutil', 'json') and name in (
                    'replace', 'rename', 'link', 'copy', 'copy2', 'copyfile', 'dump')
                if name in ('open', 'fdopen'):
                    offset = 0 if isinstance(node.func, ast.Attribute) and owner != 'os' and name == 'open' else 1
                    modes = list(node.args[offset:]) + [k.value for k in node.keywords if k.arg == 'mode']
                    publish |= any(isinstance(mode, ast.Constant) and isinstance(mode.value, str)
                                   and any(c in mode.value for c in 'wax+') for mode in modes)
                    publish |= any(isinstance(part, ast.Attribute) and part.attr in (
                        'O_WRONLY', 'O_RDWR', 'O_CREAT', 'O_TRUNC', 'O_APPEND')
                        for mode in modes for part in ast.walk(mode))
                if publish:
                    calls.append(ast.unparse(node))
            return sorted(calls)

        observed = {}
        for path in sorted((ROOT / 'src/cardine').rglob('*.py')):
            relative = path.relative_to(ROOT / 'src/cardine')
            if 'legacy' in relative.parts:
                continue
            calls = publications(path.read_text())
            if calls:
                observed[relative.as_posix()] = calls
        allowed = PUBLICATION_ALLOWLIST
        self.assertEqual(observed, allowed)
        # Exercise the guard itself: common direct and aliased bypasses are
        # publication sites, even when nobody calls the new operation in a test.
        for source in (
            "state_path(root, task_id).write_text(payload)",
            "_write_json_atomic(path, updated)",
            "from cardine.tasks.state_core import write_state_bytes as bypass\nbypass(path, payload)",
            "with path.open('w') as handle: handle.write(payload)",
            "import os as fs\nfs.open(path, fs.O_WRONLY | fs.O_CREAT)",
        ):
            with self.subTest(bypass=source):
                self.assertTrue(publications(source))


# Separate cases let the existing runner distribute the writer proof across
# shards without changing scheduling or repeating full operation fixtures.
for _family in sorted(receipts.OPERATION_KINDS):
    setattr(ReceiptWriterProofTest, f'test_writer_{_family.replace("-", "_")}_converges',
            lambda self, family=_family: self.prove_kind(family))


if __name__ == '__main__':
    unittest.main()
