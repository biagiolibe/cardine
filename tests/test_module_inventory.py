"""Reusable extraction gates against the committed pre-split inventory."""

from __future__ import annotations

import ast
from collections import defaultdict
import json
from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]


def definitions(tree):
    """Yield module-level definitions, excluding imported compatibility names."""
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            yield node.name
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                for item in ast.walk(target):
                    if isinstance(item, ast.Name) and isinstance(item.ctx, ast.Store):
                        yield item.id


def package_graph():
    paths = sorted((ROOT / "src/cardine").rglob("*.py"))
    modules = {
        str(path.relative_to(ROOT / "src").with_suffix("")).replace("/", ".").removesuffix(".__init__"): path
        for path in paths
    }
    graph = {name: set() for name in modules}
    for name, path in modules.items():
        package = name if path.name == "__init__.py" else name.rpartition(".")[0]
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            candidates = []
            if isinstance(node, ast.Import):
                candidates = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                if node.level:
                    parts = package.split(".")
                    base = ".".join(parts[:len(parts) - node.level + 1] + ([base] if base else []))
                candidates = [base, *(base + "." + alias.name for alias in node.names)]
            graph[name].update(candidate for candidate in candidates if candidate in modules)
    return graph


class ModuleInventoryTest(unittest.TestCase):
    def test_baseline_bindings_have_exactly_one_definition(self):
        baseline = json.loads((ROOT / "tests/fixtures/module_split_baseline.json").read_text())
        self.assertEqual(baseline["commit"], "ceb84fdd88d2e0819ab42f6b1d6e5266fffff8fd")
        self.assertEqual(len(baseline["bindings"]), 506)
        owners = defaultdict(list)
        paths = [ROOT / "scripts/meridian.py", *sorted((ROOT / "src/cardine").rglob("*.py"))]
        for path in paths:
            for name in definitions(ast.parse(path.read_text(encoding="utf-8"))):
                # The console already had its own main before extraction; the
                # baseline inventories only the Meridian CLI main binding.
                if path == ROOT / "src/cardine/console/entry.py" and name == "main":
                    name = "console.main"
                owners[name].append(str(path.relative_to(ROOT)))
        for binding in baseline["bindings"]:
            with self.subTest(name=binding["name"]):
                self.assertEqual(len(owners[binding["name"]]), 1, owners[binding["name"]])

    def test_package_import_graph_has_no_cycle(self):
        graph = package_graph()
        visited = set()

        def visit(name, stack):
            self.assertNotIn(name, stack, " -> ".join([*stack, name]))
            if name in visited:
                return
            for dependency in sorted(graph[name]):
                visit(dependency, [*stack, name])
            visited.add(name)

        for name in graph:
            visit(name, [])

    def test_all_tracked_python_files_fit_line_budget(self):
        tracked = subprocess.check_output(
            ["git", "ls-files", "--", "src", "scripts", "tests"],
            cwd=ROOT, text=True,
        ).splitlines()
        for name in sorted(set(tracked)):
            if name.endswith(".py"):
                with self.subTest(path=name):
                    self.assertLessEqual(len((ROOT / name).read_text().splitlines()), 1500)

    def test_compatibility_adapters_have_no_implementation(self):
        for name in ("meridian.py", "project_console.py", "task_state.py", "console_workflow.py"):
            with self.subTest(adapter=name):
                tree = ast.parse((ROOT / "scripts" / name).read_text(encoding="utf-8"))
                self.assertEqual(list(definitions(tree)), [])
                imports = [node.module for node in tree.body if isinstance(node, ast.ImportFrom)]
                self.assertTrue(any(module and module.startswith("cardine.") for module in imports))
                self.assertFalse(any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                                      ast.ClassDef, ast.Lambda))
                                     for node in ast.walk(tree)))
