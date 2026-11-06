"""Conversion remains pure and produces usable task creation input."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cardine.adopt.records import translate_record
from cardine.tasks.contract import resolve_task_contract
from cardine.tasks.creation import create_task
from project_config_support import write_project_config
from task_contract_support import contract_record, VALIDATION


class AdoptRecordsTest(unittest.TestCase):
    def record(self):
        return (contract_record().replace('## Dependencies\nnone',
                '## Dependencies\n- Depends on: `002`, `003`')
                .replace('## Expected code surface\nChange the documented deliverable only.\n', '')
                .replace('- `task-check`: `python3 -c \'pass\'`', '- `python3 -c \'pass\'`'))

    def test_translation_contract_and_creation(self):
        source = self.record()
        result = translate_record(source, open_ids={'001', '002'}, closed_ids={'003'})
        self.assertEqual(result.diagnostics, ())
        self.assertEqual(result.dropped_dependencies, ('003',))
        self.assertIn('- `docs/result.md`', result.text)
        self.assertEqual(result, translate_record(source, open_ids={'001', '002'}, closed_ids={'003'}))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            write_project_config(root, 'lean', validation=deepcopy(VALIDATION))
            identity = SimpleNamespace(canonical_id='001', task_path=root / 'tasks/001.md')
            contract = resolve_task_contract(root, '001', text=result.text, identity=identity)
            self.assertEqual(contract['dependencies'], ['002'])
            self.assertEqual(contract['expectedCodeSurface'], ['docs/result.md'])
            # Create the prerequisite first, as required by task new.
            create_task(root, '002', contract_record('002'))
            create_task(root, '001', result.text)
            self.assertTrue((root / '.cardine/tasks/001.json').is_file())

    def test_created_record_starts_with_profile_without_reconcile(self):
        import os
        import subprocess
        from unittest.mock import patch
        from cardine.lifecycle.commands import execution_start
        from cardine.worktree.checkout import prepare_task_worktree
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve() / 'project'
            root.mkdir()
            home = Path(tmp).resolve() / 'home'
            home.mkdir()
            env = {'HOME': str(home), 'CARDINE_WORKTREE_ROOT': str(Path(tmp).resolve() / 'worktrees')}
            with patch.dict(os.environ, env):
                def git(*args):
                    subprocess.run(['git', *args], cwd=root, check=True, capture_output=True)
                git('init', '-q', '-b', 'main')
                git('config', 'user.name', 'Test')
                git('config', 'user.email', 'test@example.invalid')
                write_project_config(root, 'lean', validation=deepcopy(VALIDATION))
                (root / 'docs').mkdir()
                profile = b'profile\n'
                (root / 'docs/EXECUTION_EVIDENCE_PROFILE.md').write_bytes(profile)
                source = self.record().replace('`002`, `003`', 'None')
                result = translate_record(source, open_ids={'001'}, closed_ids=set(), profile=profile)
                self.assertEqual(result.diagnostics, ())
                create_task(root, '001', result.text)
                git('add', '.')
                git('commit', '-qm', 'Create task')
                previous = Path.cwd()
                try:
                    os.chdir(root)
                    worker = Path(prepare_task_worktree('001', None, root)['worktree'])
                    os.chdir(worker)
                    self.assertEqual(execution_start(worker, '001')['status'], 'in_progress')
                finally:
                    os.chdir(previous)

    def test_diagnostics_never_invent_untranslatable_values(self):
        for source, expected in [
            (self.record().replace('`docs/result.md`', '`../outside`'), 'Relevant Files'),
            (self.record().replace('`docs/result.md`', 'Some source files'), 'Relevant Files'),
            (self.record().replace("python3 -c 'pass'", 'meridian audit --project .'), 'no translatable commands'),
            (self.record().replace('`002`, `003`', '`unknown`'), 'unknown dependencies'),
            (self.record().replace('## Out of scope', '## Other'), 'missing Out of scope'),
        ]:
            with self.subTest(expected=expected):
                result = translate_record(source, open_ids={'001', '002'}, closed_ids={'003'})
                self.assertIsNone(result.text)
                self.assertIn(expected, ' '.join(result.diagnostics))

    def test_validation_prose_and_dropped_commands(self):
        source = self.record().replace(
            "- `python3 -c 'pass'`",
            "- `first`: `echo first`\n- `meridian audit --project .`\n"
            "- `last`: `echo last`\n\nA paragraph follows.\n")
        result = translate_record(source, open_ids={'001', '002'}, closed_ids={'003'})
        self.assertEqual(result.diagnostics, ())
        self.assertEqual(result.dropped_validation, ('meridian audit --project .',))
        self.assertIn("- `first`: `echo first`\n- `last`: `echo last`\n\nA paragraph follows.\n", result.text)

    def test_indented_and_malformed_validation_entries(self):
        for entry, expected in (("  - `echo indented`", 'no translatable commands'),
                                ("- echo malformed", 'cannot translate')):
            with self.subTest(entry=entry):
                source = self.record().replace("- `python3 -c 'pass'`", entry)
                result = translate_record(source, open_ids={'001', '002'}, closed_ids={'003'})
                self.assertIn(expected, ' '.join(result.diagnostics))

    def test_profile_revision_is_derived_from_supplied_bytes(self):
        import hashlib
        profile = b'profile contents\n'
        result = translate_record(self.record(), open_ids={'001', '002'}, closed_ids={'003'}, profile=profile)
        self.assertIn('sha256:' + hashlib.sha256(profile).hexdigest(), result.text)
        self.assertIn('- Execution commands: `required via cardine execution`', result.text)
