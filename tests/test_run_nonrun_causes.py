"""Non-run cause audit and disposable interruption diagnostics (RE2c).

No test installs real host configuration. Classification never retries apply;
SR1 owns pinned reconciliation of installation effects.
"""
from __future__ import annotations

import ast
import contextlib
import errno
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from cardine_cli_support import ROOT
from cardine import cli
from cardine.hosts import codex
from cardine.shared.constants import ENTRY_ROUTER_PATH, PROTOCOL_VERSION
from cardine.shared.errors import CardineStop
from cardine.shared.journal import LifecycleJournalEntry
from cardine.shared.models import ManagedFile, PlanItem
from cardine.stops.nonrun import NONRUN_CAUSES, diagnostic_invocation, os_stop_code
from cardine.stops.registry import load_stop_registry
from cardine.templates.upgrade_support import missing_generated_outputs, print_plan
import test_self_update as updater


class NonrunCausesTest(unittest.TestCase):
    def test_registry_matches_the_nonrun_cause_audit(self):
        registry = load_stop_registry()
        for code, (resolution, reason) in NONRUN_CAUSES.items():
            with self.subTest(code=code):
                self.assertEqual(registry[code]['resolution'], resolution)
                self.assertEqual(registry[code]['human_decision'], resolution == 'guardrail')
                self.assertTrue(reason)
        self.assertNotIn('SELF_UPDATE_NON_FF', registry)

    def test_every_updater_emitter_is_audited_including_dynamic_forwarding(self):
        tree = ast.parse((ROOT / 'src/cardine/release/update.py').read_text())
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Name) and node.func.id == 'refuse']
        codes = {node.args[0].value for node in calls if isinstance(node.args[0], ast.Constant)}
        self.assertEqual(codes, {code for code in NONRUN_CAUSES if code.startswith('SELF_UPDATE_')})
        forwarding = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                      and isinstance(node.func, ast.Name) and node.func.id == 'stop_error']
        self.assertEqual(len(forwarding), 2)
        self.assertTrue(all(node.args[0].id == 'code' for node in forwarding))
        self.assertEqual(sum(isinstance(node.args[0], ast.Name) for node in calls), 1)
        self.assertFalse(any(value == 'deferred' and 'RE2c' in reason
                             for value, reason in __import__('cardine.stops.causes', fromlist=['EMITTER_CAUSES']).EMITTER_CAUSES.values()))

    def test_errno_and_invocation_are_both_required_for_nonhuman_causes(self):
        for number, expected in ((errno.ENOENT, 'OS_PATH_MISSING'),
                                 (errno.EBUSY, 'OS_PATH_BUSY'), (errno.ETXTBSY, 'OS_PATH_BUSY'),
                                 (errno.EACCES, 'OS_ACCESS_FAILED'), (errno.EPERM, 'OS_ACCESS_FAILED'),
                                 (errno.EIO, 'OS_ACCESS_FAILED'), (errno.EEXIST, 'OS_ACCESS_FAILED')):
            for diagnostic in (True, False):
                error = OSError(number, 'measured failure', '/disposable/path')
                for _ in range(2):
                    self.assertEqual(os_stop_code(error, diagnostic=diagnostic),
                                     expected if diagnostic else 'OS_ACCESS_FAILED')
        for argv, safe in ((['setup', '--check'], True), (['setup', '--apply'], False),
                           (['upgrade', '--check'], True), (['upgrade', '--apply'], False),
                           (['codex', 'configure', '--check'], True),
                           (['codex', 'configure', '--apply'], False),
                           (['self-update', '--apply'], False)):
            self.assertEqual(diagnostic_invocation(cli.build_parser().parse_args(argv)), safe)

    def test_cli_read_only_os_catches_preserve_exact_command_and_permission_guardrail(self):
        for number, code in ((errno.ENOENT, 'OS_PATH_MISSING'), (errno.EBUSY, 'OS_PATH_BUSY'),
                             (errno.EACCES, 'OS_ACCESS_FAILED')):
            stderr = io.StringIO()
            argv = ['cardine', 'codex', 'configure', '--check', '--config', '/tmp/a b;input.toml']
            with patch.object(sys, 'argv', argv), patch.object(cli, 'plan_codex_configuration',
                    side_effect=OSError(number, 'injected')), contextlib.redirect_stderr(stderr):
                self.assertEqual(cli._run_cli(LifecycleJournalEntry()), 2)
            self.assertIn(code, stderr.getvalue())
            if number != errno.EACCES:
                self.assertIn("--config '/tmp/a b;input.toml'", stderr.getvalue())
                self.assertNotIn('--apply', stderr.getvalue())

    def test_missing_generated_output_is_planned_without_writes_or_consent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / ENTRY_ROUTER_PATH
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text('# Consumer router\n')
            plan = [PlanItem(ManagedFile(source, Path('AGENTS.md')), 'router', 'generated')]
            before = source.read_bytes()
            for _ in range(2):
                self.assertEqual(missing_generated_outputs(root, plan), ('AGENTS.md',))
                self.assertFalse((root / 'AGENTS.md').exists())
                self.assertEqual(source.read_bytes(), before)
            (root / 'AGENTS.md').write_text('foreign edit')
            self.assertEqual(missing_generated_outputs(root, plan), ())
            self.assertEqual((root / 'AGENTS.md').read_text(), 'foreign edit')
            (root / 'AGENTS.md').unlink()
            (root / 'AGENTS.md').symlink_to(root / 'foreign-missing')
            self.assertEqual(missing_generated_outputs(root, plan), ())
            self.assertTrue((root / 'AGENTS.md').is_symlink())
            source.unlink()
            with self.assertRaisesRegex(Exception, 'source is missing'):
                missing_generated_outputs(root, plan)

    def test_router_requirement_and_content_conflict_keep_owner_guardrail(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for action, problems in (('conflict', ()), ('router', ('consumer trigger missing',))):
                plan = [PlanItem(ManagedFile(root / 'source', Path('AGENTS.md')), action,
                                 'consumer requirement', problems)]
                self.assertEqual(missing_generated_outputs(root, plan), ())
                self.assertEqual(list(root.iterdir()), [])

    def test_damaged_host_markers_are_not_repaired_by_classification(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'rules'
            path.write_text('# MERIDIAN:BEGIN codex-user-rules v1\nforeign rules\n')
            before = path.read_bytes()
            for _ in range(2):
                with self.assertRaises(CardineStop) as error:
                    codex.plan_codex_user_rules(path)
                self.assertEqual(error.exception.code, 'COMMAND_REFUSED')
                self.assertEqual(path.read_bytes(), before)

    def test_plugin_owner_route_is_stable_and_never_runs_manager(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / '.claude/plugins/cache/meridian/release'
            for _ in range(2):
                with patch.object(updater.owner_release_update, 'git_output') as git:
                    with self.assertRaises(CardineStop) as error:
                        updater.owner_release_update.run_self_update(root, apply=True)
                    self.assertEqual(error.exception.code, 'SELF_UPDATE_PLUGIN_CACHE')
                    self.assertTrue(str(error.exception).endswith('resume: /plugin marketplace update meridian'))
                    git.assert_not_called()
                self.assertFalse(root.exists())

    def test_invalid_argument_is_failing_work_without_git_or_network(self):
        with patch.object(updater.owner_release_update, 'git_output') as git:
            for _ in range(2):
                with self.assertRaises(CardineStop) as error:
                    updater.owner_release_update.run_self_update(Path('/tmp/absent'), target_tag='--bad')
                self.assertEqual(error.exception.code, 'SELF_UPDATE_INPUT_INVALID')
            git.assert_not_called()

    def test_update_interruption_residue_is_only_diagnosed(self):
        # Kill before/after each existing update boundary. Re-run the identical
        # diagnostic twice: refs, HEAD, foreign work and counters stay unchanged.
        # Replaying apply with a newly selected release is intentionally SR1.
        for boundary in ('fetch', 'merge', 'verify'):
            for side in ('before', 'after'):
                with self.subTest(boundary=boundary, side=side):
                    fixture = updater.SelfUpdateTest()
                    fixture.setUp()
                    try:
                        foreign = fixture.base / 'foreign'
                        foreign.write_text('preserve')
                        script = r'''
import io, json, os, signal, sys
from pathlib import Path
from cardine.release import update
root=Path(sys.argv[1]).resolve(); boundary=sys.argv[2]; side=sys.argv[3]
original=update.git_output
reads=0
def kill(): os.kill(os.getpid(), signal.SIGKILL)
def git(path,*args):
    global reads
    match = path == root and ((boundary == 'fetch' and args[:1] == ('fetch',)) or
                             (boundary == 'merge' and args[:1] == ('merge',)))
    if path == root and args == ('rev-parse','HEAD'):
        reads += 1
        match = boundary == 'verify' and reads == 2
    if match and side == 'before': kill()
    result=original(path,*args)
    if match and side == 'after': kill()
    return result
update.git_output=git
update.run_self_update(root,apply=True,urlopen_fn=lambda *a,**k: io.BytesIO(json.dumps(
 {'tag_name':'v1.3.0','body':'Template-changing release: test'}).encode()))
'''
                        env = {**os.environ, 'PYTHONPATH': str(ROOT / 'src')}
                        killed = subprocess.run([sys.executable, '-c', script, str(fixture.root), boundary, side],
                                                env=env, capture_output=True, text=True)
                        self.assertEqual(killed.returncode, -signal.SIGKILL, killed.stderr)
                        refs = fixture.git(fixture.root, 'show-ref')
                        head = fixture.git(fixture.root, 'rev-parse', 'HEAD')
                        self.assertEqual(fixture.run_update(), 0)
                        self.assertEqual(fixture.run_update(), 0)
                        self.assertEqual(fixture.git(fixture.root, 'show-ref'), refs)
                        self.assertEqual(fixture.git(fixture.root, 'rev-parse', 'HEAD'), head)
                        self.assertEqual(foreign.read_text(), 'preserve')
                        self.assertFalse((fixture.root / '.cardine').exists())
                    finally:
                        fixture.doCleanups()

    def test_updater_os_causes_preserve_apply_guardrail(self):
        fixture = updater.SelfUpdateTest()
        fixture.setUp()
        try:
            for apply in (False, True):
                for number, code in ((errno.ENOENT, 'OS_PATH_MISSING'),
                                     (errno.EBUSY, 'OS_PATH_BUSY'), (errno.EACCES, 'OS_ACCESS_FAILED')):
                    with patch.object(updater.owner_release_update, 'git_output',
                                      side_effect=OSError(number, 'injected')):
                        with self.assertRaises(CardineStop) as error:
                            fixture.run_update(apply=apply)
                    self.assertEqual(error.exception.code, 'OS_ACCESS_FAILED' if apply else code)
        finally:
            fixture.doCleanups()

    def test_host_interruption_is_diagnosed_without_apply_or_foreign_loss(self):
        for boundary in ('backup', 'temporary', 'replace'):
            for side in ('before', 'after'):
                with self.subTest(boundary=boundary, side=side), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    config = root / 'config.toml'
                    config.write_text('# foreign settings\nmodel = "test"\n')
                    foreign = root / 'foreign'
                    foreign.write_text('preserve')
                    script = r'''
import os, signal, sys
from pathlib import Path
from cardine.hosts import codex
root=Path(sys.argv[1]); boundary=sys.argv[2]; side=sys.argv[3]
def wrap(original):
    def call(*args,**kwargs):
        if side == 'before': os.kill(os.getpid(),signal.SIGKILL)
        result=original(*args,**kwargs)
        if side == 'after': os.kill(os.getpid(),signal.SIGKILL)
        return result
    return call
if boundary == 'backup': codex._write_exclusive_backup=wrap(codex._write_exclusive_backup)
if boundary == 'temporary': codex.tempfile.mkstemp=wrap(codex.tempfile.mkstemp)
if boundary == 'replace': codex.os.replace=wrap(codex.os.replace)
plan=codex.plan_codex_configuration(root/'config.toml',root/'worktrees')
codex.apply_codex_configuration(plan)
'''
                    killed = subprocess.run([sys.executable, '-c', script, str(root), boundary, side],
                                            env={**os.environ, 'PYTHONPATH': str(ROOT / 'src')},
                                            capture_output=True, text=True)
                    self.assertEqual(killed.returncode, -signal.SIGKILL, killed.stderr)
                    snapshot = {p.name: p.read_bytes() for p in root.iterdir() if p.is_file()}
                    results = [codex.plan_codex_configuration(config, root / 'worktrees') for _ in range(2)]
                    self.assertEqual(results[0], results[1])
                    self.assertEqual(results[0].status,
                                     'ready' if (boundary, side) == ('replace', 'after') else 'approval-required')
                    self.assertEqual(snapshot, {p.name: p.read_bytes() for p in root.iterdir() if p.is_file()})
                    self.assertEqual(foreign.read_text(), 'preserve')

    def test_upgrade_interruption_only_resolves_generated_residue(self):
        for boundary in ('managed', 'generated', 'baseline', 'manifest'):
            for side in ('before', 'after'):
                with self.subTest(boundary=boundary, side=side), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    project = root / 'project'
                    framework = root / 'framework'
                    project.mkdir()
                    framework.mkdir()
                    (framework / 'VERSION').write_text('1.2.0\n')
                    (framework / 'migrations').mkdir()
                    (framework / 'capabilities').mkdir()
                    (framework / 'capabilities/catalog-v1.json').write_text(json.dumps(
                        {'catalogVersion': 1, 'capabilities': {}, 'profiles': {}}))
                    source = framework / 'source'
                    source.write_text('released managed output\n')
                    router = project / ENTRY_ROUTER_PATH
                    router.parent.mkdir(parents=True, exist_ok=True)
                    router.write_text('# Consumer router\n')
                    (project / 'foreign').write_text('preserve')
                    script = r'''
import os,signal,sys
from pathlib import Path
from cardine.templates import upgrade
from cardine.shared.models import ManagedFile,PlanItem
from cardine.shared.constants import PROTOCOL_VERSION
root=Path(sys.argv[1]);boundary=sys.argv[2];side=sys.argv[3]
project=root/'project';framework=root/'framework'
files=[ManagedFile(framework/'source',Path('README.md'))]
plan=[PlanItem(files[0],'add','released output')]
manifest={'protocolVersion':PROTOCOL_VERSION,'workflowMode':'single',
          'frameworkVersion':'1.1.0','workflowBaselineVersion':'1.1.0',
          'managedFiles':{},'appliedMigrations':[]}
# Router route-map requirements belong to a full project fixture; keep this
# focused on actual managed/generated/baseline/manifest write boundaries.
upgrade.audit_entry_router=lambda root: []
original_copy=upgrade.shutil.copyfile
original_write=Path.write_text
def around(match,operation):
    if match and side=='before':os.kill(os.getpid(),signal.SIGKILL)
    result=operation()
    if match and side=='after':os.kill(os.getpid(),signal.SIGKILL)
    return result
def copy(source,target,*a,**kw):
    target=Path(target)
    match=(boundary=='managed' and target==project/'README.md') or (
           boundary=='baseline' and 'baselines' in target.parts)
    return around(match,lambda:original_copy(source,target,*a,**kw))
def write(path,*a,**kw):
    match=(boundary=='generated' and path==project/'AGENTS.md') or (
           boundary=='manifest' and path.name=='manifest.json')
    return around(match,lambda:original_write(path,*a,**kw))
upgrade.shutil.copyfile=copy
Path.write_text=write
upgrade.apply_plan(project,framework,manifest,plan,project/'.cardine/baselines/1.1.0',
                   managed_files_override=files)
'''
                    killed = subprocess.run([sys.executable, '-c', script, str(root), boundary, side],
                                            env={**os.environ, 'PYTHONPATH': str(ROOT / 'src')},
                                            capture_output=True, text=True)
                    self.assertEqual(killed.returncode, -signal.SIGKILL, killed.stdout + killed.stderr)
                    snapshot = {p.relative_to(project): p.read_bytes()
                                for p in project.rglob('*') if p.is_file()}
                    plan = [PlanItem(ManagedFile(source, Path('AGENTS.md')), 'router', 'generated')]
                    first = missing_generated_outputs(project, plan)
                    self.assertEqual(missing_generated_outputs(project, plan), first)
                    self.assertEqual(snapshot, {p.relative_to(project): p.read_bytes()
                                               for p in project.rglob('*') if p.is_file()})
                    self.assertEqual((project / 'foreign').read_text(), 'preserve')


    def test_generated_output_diagnostic_preserves_the_selected_framework(self):
        with tempfile.TemporaryDirectory(prefix="nonrun source ") as directory:
            root = Path(directory)
            project = root / 'project'
            framework = root / 'framework'
            framework.mkdir()
            (framework / 'VERSION').write_text('1.2.0\n')
            (framework / 'migrations').mkdir()
            source = project / ENTRY_ROUTER_PATH
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text('# Consumer router\n')
            plan = [PlanItem(ManagedFile(source, Path('AGENTS.md')), 'router', 'generated')]
            manifest = {'protocolVersion': PROTOCOL_VERSION, 'workflowMode': 'single',
                        'frameworkVersion': '1.1.0'}
            outputs = []
            for _ in range(2):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    print_plan(project, manifest, framework, plan)
                outputs.append(output.getvalue())
            self.assertEqual(outputs[0], outputs[1])
            self.assertIn('UPGRADE_OUTPUT_PENDING', outputs[0])
            self.assertIn("--framework-root '" + str(framework.resolve()) + "'", outputs[0])
            self.assertNotIn('UPGRADE_BLOCKED', outputs[0])
            self.assertFalse((project / 'AGENTS.md').exists())
