"""Decision 13 ratchet: remove known text gates; never add another one.

Keys are (repository path, qualified function, rule, name), without line
numbers. A key is one reader kind per function, not one occurrence. The
legacy import boundary is enforced by the existing legacy import-graph test.
"""

from __future__ import annotations

import ast
from fnmatch import fnmatchcase
from pathlib import Path
import re
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
Key = tuple[str, str, str, str]
NAMED_READERS = frozenset({
    "read_task_field", "_contract_field", "task_contract_options",
    "validation_commands", "require_named_validation_commands", "contract_digest",
    "record_status", "record_review", "handoff_status", "latest_review_verdict",
    "parse_queue", "_queue_task_rows", "_governed_completion_row", "check_handoff",
    "authority_entries", "resolve_task_contract", "resolve_human_fields",
    # Inventory readers with generic path parameters still need protection.
    "threshold_for", "final_message",
})
PATH_WORDS = ("task_path", "handoff_path", "review_path", "queue_path", "plan_path",
              "report", "record")
RESULT_OPTIONS = ("*-exit-code", "--accepted", "--*behavioral-surface",
                  "--*-dependency", "--full-validation-required")


def named_reader(name: str) -> bool:
    return name in NAMED_READERS or "host_impact_" in name


def product_sources(root: Path) -> list[Path]:
    """Include script imports transitively, so a new helper cannot evade scope."""
    paths = set((root / "src/cardine").rglob("*.py"))
    pending = list(paths)
    while pending:
        path = pending.pop()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            modules = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                if not node.level:
                    modules = [node.module or ""]
                    if node.module == "scripts":
                        modules.extend(alias.name for alias in node.names)
            for module in modules:
                candidate = root / "scripts" / (module.removeprefix("scripts.").replace(".", "/") + ".py")
                if candidate.is_file() and candidate not in paths:
                    paths.add(candidate)
                    pending.append(candidate)
    return sorted(paths)


class TextReaders(ast.NodeVisitor):
    def __init__(self, path: str, tree: ast.AST):
        self.path = path
        self.scope: list[str] = []
        self.findings: set[Key] = set()
        # Imported aliases still reference the original reader. Also follow
        # simple function aliases (reader = owner.read_task_field).
        self.aliases = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    self.aliases[alias.asname or alias.name] = alias.name
        assignments = [node for node in ast.walk(tree) if isinstance(node, ast.Assign)]
        for _ in range(len(assignments) + 1):
            before = dict(self.aliases)
            for node in assignments:
                name = self.reference_name(node.value)
                if name and named_reader(name):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            self.aliases[target.id] = name
            if before == self.aliases:
                break

    def reference_name(self, node: ast.AST) -> str | None:
        if isinstance(node, ast.Name):
            return self.aliases.get(node.id, node.id)
        if isinstance(node, ast.Attribute):
            return node.attr
        return None

    def add(self, rule: str, name: str):
        self.findings.add((self.path, ".".join(self.scope) or "<module>", rule, name))

    def visit_FunctionDef(self, node):
        # Defaults and decorators execute in the outer scope.
        for item in [*node.decorator_list, node.args, *getattr(node, "type_params", [])]:
            self.visit(item)
        if node.returns is not None:
            self.visit(node.returns)
        self.scope.append(node.name)
        for item in node.body:
            self.visit(item)
        self.scope.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node):
        for item in [*node.decorator_list, *node.bases, *node.keywords]:
            self.visit(item)
        self.scope.append(node.name)
        for item in node.body:
            self.visit(item)
        self.scope.pop()

    def visit_If(self, node):
        # Exempt precisely the task-new branch, never all of CLI main.
        self.visit(node.test)
        creation = ast.dump(node.test, include_attributes=False) == ast.dump(
            ast.parse('arguments.task_command == "new"', mode="eval").body,
            include_attributes=False,
        )
        if creation:
            self.scope.append("task_new")
        for item in node.body:
            self.visit(item)
        if creation:
            self.scope.pop()
        for item in node.orelse:
            self.visit(item)

    def visit_ImportFrom(self, node):
        for alias in node.names:
            if named_reader(alias.name):
                self.add("named-reader", alias.name)

    def visit_Name(self, node):
        name = self.reference_name(node)
        if isinstance(node.ctx, ast.Load) and name and named_reader(name):
            self.add("named-reader", name)

    def visit_Attribute(self, node):
        if isinstance(node.ctx, ast.Load) and named_reader(node.attr):
            self.add("named-reader", node.attr)
        self.generic_visit(node)

    def visit_Call(self, node):
        name = self.reference_name(node.func)
        if name == "add_argument":
            for argument in node.args:
                if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                    if any(fnmatchcase(argument.value, pattern) for pattern in RESULT_OPTIONS):
                        self.add("declared-result", f"{ast.unparse(node.func.value)}:{argument.value}")
        expression = None
        operation = name
        if isinstance(node.func, ast.Attribute) and name in ("read_text", "open"):
            expression = node.func.value
        elif name == "open" and node.args:
            expression = node.args[0]
        elif any(isinstance(item, ast.Constant) and item.value == "show"
                 for arg in node.args for item in ast.walk(arg)):
            expression = ast.Tuple(elts=node.args, ctx=ast.Load())
            operation = "git-show"
        if expression is not None:
            text = ast.unparse(expression)
            for word in PATH_WORDS:
                if word in text:
                    self.add("disk-text", f"{operation}:{word}")
        self.generic_visit(node)


def scan(root: Path) -> set[Key]:
    findings = set()
    for path in product_sources(root):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        visitor = TextReaders(path.relative_to(root).as_posix(), tree)
        visitor.visit(tree)
        findings.update(visitor.findings)
    return findings


# Creation includes an explicitly requested contract revision. The diagnostic
# exception reads prose only to report drift; it cannot affect a gate. Function
# and key exemptions stay narrow: a runtime call to a creation helper violates it.
ALLOWLIST = {
    "contract-creation": {
        "files": {"src/cardine/tasks/creation.py"},
        "functions": {
            ("src/cardine/tasks/contract.py", "_contract_field"),
            ("src/cardine/tasks/contract.py", "task_contract_options"),
            ("src/cardine/tasks/contract.py", "resolve_task_contract"),
            ("src/cardine/tasks/contract.py", "resolve_human_fields"),
            ("src/cardine/tasks/contract_update.py", "update_task_contract"),
            ("src/cardine/cli.py", "_run_cli.task_new"),
        },
        "keys": {
            ("src/cardine/tasks/contract_update.py", "<module>", "named-reader", "resolve_task_contract"),
        },
    },
    "managed-text-integrity": {
        "files": {"src/cardine/templates/**", "src/cardine/hosts/codex.py"},
        "functions": set(),
        "keys": {
            # Snapshot/record integrity diagnostics are advisory only. Exact
            # keys keep every other runtime read in this module prohibited.
            ("src/cardine/tasks/audit.py", "audit_task_state_projections", "disk-text", "read_text:record"),
            ("src/cardine/tasks/audit.py", "<module>", "named-reader", "resolve_human_fields"),
            ("src/cardine/tasks/audit.py", "audit_task_state_projections", "named-reader", "resolve_human_fields"),
            ("src/cardine/tasks/preflight.py", "<module>", "named-reader", "contract_digest"),
            ("src/cardine/tasks/preflight.py", "execution_preflight", "named-reader", "contract_digest"),
        },
    },
    "legacy": {"files": {"src/cardine/legacy/**"}, "functions": set(), "keys": set()},
}


def allowed(key: Key) -> bool:
    path, function, _, _ = key
    return any(
        any(fnmatchcase(path, pattern) for pattern in group["files"])
        or (path, function) in group["functions"] or key in group["keys"]
        for group in ALLOWLIST.values()
    )


# One inventory entry per stable key; these rows may only be removed as their
# destination tasks land. Imports are references too, so obsolete imports
# must be removed along with callers. No runtime discovery populates this table.
# This is a conservative syntactic inventory: the review append read belongs
# to T-25's review text, even though the inventory excludes it as a decision.
# Likewise validation_commands parameters are retained under T-38/T-39.
# A shared key (for example Class and Deliverable in _spike_disallowed_paths)
# stays until every reference of that reader kind in the function is gone.
KNOWN_VIOLATIONS: dict[Key, str] = {
    ('scripts/codex_read_guard.py', 'decision', 'named-reader', 'threshold_for'): 'T-46',
    ('scripts/stop_audit.py', 'audit', 'named-reader', 'final_message'): 'T-47',
    ('src/cardine/cli.py', '<module>', 'named-reader', 'check_handoff'): 'T-19',
    ('src/cardine/cli.py', '_run_cli', 'named-reader', 'check_handoff'): 'T-19',
    ('src/cardine/cli.py', 'build_parser', 'declared-result', 'worktree_advance:--accepted'): 'T-39',
    ('src/cardine/cli.py', 'build_parser', 'declared-result', 'worktree_advance:--candidate-exit-code'): 'T-40',
    ('src/cardine/cli.py', 'build_parser', 'declared-result', 'worktree_advance:--validation-exit-code'): 'T-39',
    ('src/cardine/cli.py', 'build_parser', 'declared-result', 'worktree_evidence:--accepted'): 'T-38',
    ('src/cardine/cli.py', 'build_parser', 'declared-result', 'worktree_evidence:--full-validation-required'): 'T-38',
    ('src/cardine/cli.py', 'build_parser', 'declared-result', 'worktree_evidence:--main-advanced-behavioral-surface'): 'T-38',
    ('src/cardine/cli.py', 'build_parser', 'declared-result', 'worktree_evidence:--main-advanced-dependency'): 'T-38',
    ('src/cardine/cli.py', 'build_parser', 'declared-result', 'worktree_evidence:--task-behavioral-surface'): 'T-38',
    ('src/cardine/cli.py', 'build_parser', 'declared-result', 'worktree_evidence:--task-dependency'): 'T-38',
    ('src/cardine/cli.py', 'build_parser', 'declared-result', 'worktree_evidence:--validation-exit-code'): 'T-38',
    ('src/cardine/console/snapshot.py', '<module>', 'named-reader', 'handoff_status'): 'T-24',
    ('src/cardine/console/snapshot.py', '<module>', 'named-reader', 'latest_review_verdict'): 'T-25',
    ('src/cardine/console/snapshot.py', '<module>', 'named-reader', 'parse_queue'): 'T-32',
    ('src/cardine/console/snapshot.py', '<module>', 'named-reader', 'read_task_field'): 'T-13',
    ('src/cardine/console/snapshot.py', '<module>', 'named-reader', 'record_review'): 'T-34',
    ('src/cardine/console/snapshot.py', '<module>', 'named-reader', 'record_status'): 'T-33',
    ('src/cardine/console/snapshot.py', '_branch_facts', 'named-reader', 'handoff_status'): 'T-24',
    ('src/cardine/console/snapshot.py', '_branch_facts', 'named-reader', 'latest_review_verdict'): 'T-25',
    ('src/cardine/console/snapshot.py', '_branch_facts', 'named-reader', 'parse_queue'): 'T-32',
    ('src/cardine/console/snapshot.py', '_branch_facts', 'named-reader', 'record_status'): 'T-33',
    ('src/cardine/console/snapshot.py', '_build_snapshot', 'named-reader', 'parse_queue'): 'T-32',
    ('src/cardine/console/snapshot.py', '_build_snapshot', 'named-reader', 'record_review'): 'T-34',
    ('src/cardine/console/snapshot.py', '_build_snapshot', 'named-reader', 'record_status'): 'T-33',
    ('src/cardine/console/snapshot.py', '_read_console_state', 'named-reader', 'read_task_field'): 'T-13',
    ('src/cardine/integration/evidence.py', 'check_validation_evidence', 'disk-text', 'read_text:record'): 'T-44',
    ('src/cardine/integration/evidence.py', 'record_task_evidence', 'named-reader', 'validation_commands'): 'T-38',
    ('src/cardine/integration/merge.py', '<module>', 'named-reader', 'read_task_field'): 'T-13',
    ('src/cardine/integration/merge.py', '_integration_task_state', 'disk-text', 'git-show:record'): 'T-13',
    ('src/cardine/integration/merge.py', '_integration_task_state', 'named-reader', 'read_task_field'): 'T-13',
    ('src/cardine/integration/merge.py', '_spike_disallowed_paths', 'disk-text', 'git-show:record'): 'T-16',
    ('src/cardine/integration/merge.py', '_spike_disallowed_paths', 'named-reader', 'read_task_field'): 'T-16',
    ('src/cardine/integration/merge.py', 'cleanup_task_worktree', 'disk-text', 'read_text:task_path'): 'T-13',
    ('src/cardine/integration/merge.py', 'cleanup_task_worktree', 'named-reader', 'read_task_field'): 'T-13',
    ('src/cardine/lifecycle/closure.py', 'advance_task_closure', 'named-reader', 'validation_commands'): 'T-39',
    ('src/cardine/lifecycle/commands.py', '<module>', 'named-reader', 'read_task_field'): 'T-13',
    ('src/cardine/lifecycle/commands.py', 'execution_start', 'disk-text', 'read_text:task_path'): 'T-13',
    ('src/cardine/lifecycle/commands.py', 'execution_start', 'named-reader', 'read_task_field'): 'T-13',
    ('src/cardine/lifecycle/commands.py', 'execution_start', 'named-reader', 'resolve_task_contract'): 'T-02',
    ('src/cardine/lifecycle/execution.py', '<module>', 'named-reader', 'read_task_field'): 'T-13',
    ('src/cardine/lifecycle/execution.py', '<module>', 'named-reader', 'validation_commands'): 'T-15',
    ('src/cardine/lifecycle/execution.py', '_execution_state', 'named-reader', 'read_task_field'): 'T-13',
    ('src/cardine/lifecycle/execution.py', '_execution_worktree', 'disk-text', 'git-show:task_path'): 'T-07',
    ('src/cardine/lifecycle/execution.py', '_execution_worktree', 'disk-text', 'read_text:task_path'): 'T-07',
    ('src/cardine/lifecycle/execution.py', 'delivery_readiness', 'disk-text', 'read_text:task_path'): 'T-15',
    ('src/cardine/lifecycle/execution.py', 'delivery_readiness', 'named-reader', 'validation_commands'): 'T-15',
    ('src/cardine/review/verdict.py', '<module>', 'named-reader', 'read_task_field'): 'T-13',
    ('src/cardine/review/verdict.py', 'record_review_verdict', 'disk-text', 'read_text:review_path'): 'T-25',
    ('src/cardine/review/verdict.py', 'record_review_verdict', 'disk-text', 'read_text:task_path'): 'T-13',
    ('src/cardine/review/verdict.py', 'record_review_verdict', 'named-reader', 'read_task_field'): 'T-13',
    ('src/cardine/tasks/contract.py', '<module>', 'named-reader', 'require_named_validation_commands'): 'T-15',
    ('src/cardine/tasks/contract.py', '<module>', 'named-reader', 'validation_commands'): 'T-15',
    ('src/cardine/tasks/contract.py', 'check_handoff', 'disk-text', 'read_text:report'): 'T-19',
    ('src/cardine/tasks/contract.py', 'host_impact_required_profiles', 'named-reader', 'host_impact_field'): 'T-03',
    ('src/cardine/tasks/contract.py', 'validate_host_impact_declaration', 'named-reader', 'host_impact_field'): 'T-03',
    ('src/cardine/tasks/contract.py', 'validate_host_impact_declaration', 'named-reader', 'host_impact_required_profiles'): 'T-03',
    ('src/cardine/tasks/contract.py', 'validate_host_impact_declaration', 'named-reader', 'host_impact_section'): 'T-03',
    ('src/cardine/tasks/contract.py', 'verify_execution_evidence', 'named-reader', 'validation_commands'): 'T-15',
    ('src/cardine/tasks/contract.py', 'verify_host_impact_completion_evidence', 'named-reader', 'host_impact_section'): 'T-04',
    ('src/cardine/tasks/contract.py', 'verify_host_impact_completion_evidence', 'named-reader', 'validate_host_impact_declaration'): 'T-04',
    ('src/cardine/tasks/evidence.py', 'require_named_validation_commands', 'named-reader', 'validation_commands'): 'T-15',
    ('src/cardine/tasks/identity.py', '<module>', 'named-reader', 'read_task_field'): 'T-13',
    ('src/cardine/tasks/importer.py', '<module>', 'named-reader', '_queue_task_rows'): 'T-31',
    ('src/cardine/tasks/importer.py', '<module>', 'named-reader', 'read_task_field'): 'T-31',
    ('src/cardine/tasks/importer.py', '<module>', 'named-reader', 'resolve_task_contract'): 'T-31',
    ('src/cardine/tasks/importer.py', 'import_task_states', 'disk-text', 'read_text:queue_path'): 'T-31',
    ('src/cardine/tasks/importer.py', 'import_task_states', 'disk-text', 'read_text:review_path'): 'T-31',
    ('src/cardine/tasks/importer.py', 'import_task_states', 'disk-text', 'read_text:task_path'): 'T-31',
    ('src/cardine/tasks/importer.py', 'import_task_states', 'named-reader', '_queue_task_rows'): 'T-31',
    ('src/cardine/tasks/importer.py', 'import_task_states', 'named-reader', 'read_task_field'): 'T-31',
    ('src/cardine/tasks/importer.py', 'import_task_states', 'named-reader', 'record_status'): 'T-31',
    ('src/cardine/tasks/importer.py', 'import_task_states', 'named-reader', 'resolve_task_contract'): 'T-31',
    ('src/cardine/tasks/importer.py', 'legacy_identity_context', 'disk-text', 'read_text:queue_path'): 'T-31',
    ('src/cardine/tasks/preflight.py', '<module>', 'named-reader', 'check_handoff'): 'T-19',
    ('src/cardine/tasks/preflight.py', '<module>', 'named-reader', 'read_task_field'): 'T-13',
    ('src/cardine/tasks/preflight.py', '<module>', 'named-reader', 'require_named_validation_commands'): 'T-15',
    ('src/cardine/tasks/preflight.py', '<module>', 'named-reader', 'validate_host_impact_declaration'): 'T-03',
    ('src/cardine/tasks/preflight.py', '<module>', 'named-reader', 'validation_commands'): 'T-15',
    ('src/cardine/tasks/preflight.py', '<module>', 'named-reader', 'verify_host_impact_completion_evidence'): 'T-04',
    ('src/cardine/tasks/preflight.py', 'execution_contract', 'named-reader', 'require_named_validation_commands'): 'T-15',
    ('src/cardine/tasks/preflight.py', 'execution_contract', 'named-reader', 'validation_commands'): 'T-15',
    ('src/cardine/tasks/preflight.py', 'execution_preflight', 'named-reader', 'read_task_field'): 'T-13',
    ('src/cardine/tasks/preflight.py', 'execution_preflight', 'named-reader', 'require_named_validation_commands'): 'T-15',
    ('src/cardine/tasks/preflight.py', 'execution_preflight', 'named-reader', 'validate_host_impact_declaration'): 'T-03',
    ('src/cardine/tasks/preflight.py', 'readiness_check', 'named-reader', 'check_handoff'): 'T-19',
    ('src/cardine/tasks/preflight.py', 'readiness_check', 'named-reader', 'verify_host_impact_completion_evidence'): 'T-04',
    ('src/cardine/tasks/recording.py', '<module>', 'named-reader', 'validation_commands'): 'T-15',
    ('src/cardine/tasks/recording.py', 'run_validation', 'named-reader', 'validation_commands'): 'T-15',
    ('src/cardine/tasks/transitions.py', '<module>', 'named-reader', 'read_task_field'): 'T-13',
    ('src/cardine/tasks/transitions.py', 'transition_task_state', 'disk-text', 'read_text:task_path'): 'T-13',
    ('src/cardine/tasks/transitions.py', 'transition_task_state', 'named-reader', 'read_task_field'): 'T-13',
    ('src/cardine/tasks/transitions.py', 'transition_task_state', 'named-reader', 'resolve_task_contract'): 'T-02',
    ('src/cardine/worktree/checkout.py', 'inspect_task_worktree', 'disk-text', 'read_text:handoff_path'): 'T-23',
}


def ratchet_errors(findings: set[Key], known: dict[Key, str], inventory: str) -> list[str]:
    violations = {key for key in findings if not allowed(key)}
    ids = set(re.findall(r"^\| (T-\d+) \|", inventory, re.MULTILINE))
    errors = []
    for key in sorted(violations - known.keys()):
        errors.append(f"new reader: {key!r}")
    for key in sorted(known.keys() - violations):
        errors.append(f"stale violation: {key!r}")
    for key, entry in sorted(known.items()):
        if entry not in ids:
            errors.append(f"unknown inventory ID: {entry} for {key!r}")
    return errors


class TextGateTest(unittest.TestCase):
    def test_product_text_readers_match_ratchet(self):
        self.assertEqual(ratchet_errors(scan(ROOT), KNOWN_VIOLATIONS,
                                       (ROOT / "docs/TEXT_GATE_INVENTORY.md").read_text()), [])


class TextGateScannerTest(unittest.TestCase):
    def tree(self, files: dict[str, str]) -> Path:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        for name, source in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source, encoding="utf-8")
        return root

    def test_new_reader_fails_in_synthetic_tree(self):
        root = self.tree({"src/cardine/new.py":
                          "def gate(record):\n    return record.read_text()\n"})
        self.assertEqual(ratchet_errors(scan(root), {}, ""), [
            "new reader: ('src/cardine/new.py', 'gate', 'disk-text', 'read_text:record')"])

    def test_stale_row_fails_after_reader_is_removed(self):
        root = self.tree({"src/cardine/new.py": "def gate():\n    return True\n"})
        key = ("src/cardine/new.py", "gate", "named-reader", "read_task_field")
        self.assertEqual(ratchet_errors(scan(root), {key: "T-13"}, "| T-13 | fields |"),
                         [f"stale violation: {key!r}"])
        self.assertEqual(ratchet_errors(scan(root), {}, "| T-13 | fields |"), [])

    def test_unknown_inventory_id_fails_with_matching_reader(self):
        root = self.tree({"src/cardine/new.py":
                          "def gate(text):\n    return read_task_field(text, 'Class')\n"})
        key = ("src/cardine/new.py", "gate", "named-reader", "read_task_field")
        self.assertEqual(ratchet_errors(scan(root), {key: "T-99"}, "| T-13 | fields |"),
                         [f"unknown inventory ID: T-99 for {key!r}"])
        self.assertEqual(ratchet_errors(scan(root), {key: "T-13"}, "| T-13 | fields |"), [])

    def test_named_references_aliases_and_qualified_functions(self):
        source = ("from owner import read_task_field as field\n"
                  "class Gate:\n"
                  "    async def check(self):\n"
                  "        def nested():\n"
                  "            reader = owner.host_impact_new_reader\n"
                  "            return reader('text')\n"
                  "        return field, owner.parse_queue\n")
        root = self.tree({"src/cardine/new.py": source})
        findings = scan(root)
        self.assertEqual(findings, {
            ("src/cardine/new.py", "<module>", "named-reader", "read_task_field"),
            ("src/cardine/new.py", "Gate.check", "named-reader", "read_task_field"),
            ("src/cardine/new.py", "Gate.check", "named-reader", "parse_queue"),
            ("src/cardine/new.py", "Gate.check.nested", "named-reader", "host_impact_new_reader"),
        })
        (root / "src/cardine/new.py").write_text("\n\n# Lines are not identities.\n" + source)
        self.assertEqual(scan(root), findings)

    def test_disk_rules_cover_every_path_word_and_read_form(self):
        forms = ("{path}.read_text()", "open({path}).read()", "{path}.open().read()",
                 "git(root, 'show', f'HEAD:{{{path}}}')",
                 "subprocess.run(['git', 'show', f'HEAD:{{{path}}}'])")
        for word in PATH_WORDS:
            for form in forms:
                with self.subTest(word=word, form=form):
                    root = self.tree({"src/cardine/new.py":
                                      "def gate():\n    return " + form.format(path=word) + "\n"})
                    operation = "git-show" if "show" in form else "read_text" if "read_text" in form else "open"
                    self.assertIn(("src/cardine/new.py", "gate", "disk-text", f"{operation}:{word}"), scan(root))
        root = self.tree({"src/cardine/new.py":
                          "def config(path):\n    return path.read_text()\n"})
        self.assertEqual(scan(root), set())

    def test_all_declared_result_patterns_and_multiple_options(self):
        options = ("--validation-exit-code", "--candidate-exit-code", "--new-exit-code",
                   "--accepted", "--task-behavioral-surface", "--main-advanced-behavioral-surface",
                   "--task-dependency", "--main-advanced-dependency", "--full-validation-required")
        source = "def parser():\n" + "".join(
            f"    parser.add_argument('-x', {option!r})\n" for option in options)
        source += "    parser.add_argument('--output')\n"
        root = self.tree({"src/cardine/new.py": source})
        self.assertEqual(scan(root), {
            ("src/cardine/new.py", "parser", "declared-result", f"parser:{option}") for option in options})

    def test_script_imports_are_transitive_and_unimported_scripts_are_excluded(self):
        root = self.tree({
            "src/cardine/new.py": "import helper\n",
            "scripts/helper.py": "from scripts import second\n",
            "scripts/second.py": "def gate(report):\n    return report.read_text()\n",
            "scripts/unused.py": "this is not Python!",
        })
        self.assertEqual([path.relative_to(root).as_posix() for path in product_sources(root)],
                         ["scripts/helper.py", "scripts/second.py", "src/cardine/new.py"])
        self.assertEqual(scan(root), {
            ("scripts/second.py", "gate", "disk-text", "read_text:report")})
        self.assertEqual({path.relative_to(ROOT).as_posix() for path in product_sources(ROOT)
                          if path.is_relative_to(ROOT / "scripts")},
                         {"scripts/codex_read_guard.py", "scripts/stop_audit.py"})

    def test_allowlist_has_only_three_classes_and_creation_is_branch_scoped(self):
        self.assertFalse(allowed(("src/cardine/tasks/audit.py", "runtime", "disk-text", "read_text:record")))
        self.assertFalse(allowed(("src/cardine/tasks/audit.py", "audit_task_state_projections", "named-reader", "read_task_field")))
        self.assertFalse(allowed(("src/cardine/tasks/contract_update.py", "runtime", "named-reader", "resolve_human_fields")))
        self.assertEqual(set(ALLOWLIST), {"contract-creation", "managed-text-integrity", "legacy"})
        root = self.tree({
            "src/cardine/cli.py":
                "def _run_cli(arguments):\n"
                "    if arguments.task_command == 'new':\n"
                "        text = arguments.record.read_text()\n"
                "    else:\n"
                "        text = arguments.record.read_text()\n",
            "src/cardine/tasks/contract.py":
                "def resolve_task_contract(identity):\n"
                "    return identity.task_path.read_text()\n"
                "def runtime(text):\n    return task_contract_options(text)\n",
            "src/cardine/legacy/snapshot.py": "value = record.read_text()\n",
            "src/cardine/templates/check.py": "value = report.read_text()\n",
        })
        findings = scan(root)
        self.assertEqual({key for key in findings if not allowed(key)}, {
            ("src/cardine/cli.py", "_run_cli", "disk-text", "read_text:record"),
            ("src/cardine/tasks/contract.py", "runtime", "named-reader", "task_contract_options"),
        })
        self.assertEqual(len(findings), 6)
        self.assertFalse(allowed(("src/cardine/shared/context.py", "context_size_report",
                                  "named-reader", "authority_entries")))


if __name__ == "__main__":
    unittest.main()
