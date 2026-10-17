"""Tests for the deterministic sharded unittest runner."""

from __future__ import annotations

import hashlib
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_tests.py"
SPEC = importlib.util.spec_from_file_location("run_tests", SCRIPT)
assert SPEC and SPEC.loader
runner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runner
SPEC.loader.exec_module(runner)


class ShardedTestRunnerTest(unittest.TestCase):
    def make_suite(self, names: list[str]) -> Path:
        directory = Path(tempfile.mkdtemp())
        for name in names:
            (directory / f"test_{directory.name}_{name}.py").write_text(
                "import unittest\n"
                "class GeneratedTest(unittest.TestCase):\n"
                "    def test_value(self):\n"
                "        self.assertTrue(True)\n",
                encoding="utf-8",
            )
        return directory

    def run_script(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *arguments],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_shards_are_disjoint_and_cover_the_generated_suite(self) -> None:
        directory = self.make_suite(["gamma", "alpha", "beta", "delta", "epsilon"])
        self.addCleanup(lambda: __import__("shutil").rmtree(directory))
        tests = runner.discover_tests(directory)
        identifiers = [test.id() for test in tests]
        shards = [
            {test.id() for position, test in enumerate(tests) if position % 3 == shard}
            for shard in range(3)
        ]

        self.assertEqual(identifiers, sorted(identifiers))
        self.assertEqual(set().union(*shards), set(identifiers))
        self.assertEqual(sum(len(shard) for shard in shards), len(identifiers))

    def test_adding_a_test_changes_the_digest(self) -> None:
        directory = self.make_suite(["first"])
        self.addCleanup(lambda: __import__("shutil").rmtree(directory))
        _, original = runner.coverage(runner.discover_tests(directory))
        (directory / f"test_{directory.name}_second.py").write_text(
            "import unittest\nclass Extra(unittest.TestCase):\n    def test_value(self): pass\n",
            encoding="utf-8",
        )
        _, changed = runner.coverage(runner.discover_tests(directory))

        self.assertNotEqual(original, changed)

    def test_coverage_uses_newline_joined_sorted_ids(self) -> None:
        directory = self.make_suite(["zeta", "alpha"])
        self.addCleanup(lambda: __import__("shutil").rmtree(directory))
        tests = runner.discover_tests(directory)
        expected = hashlib.sha256("\n".join(test.id() for test in tests).encode()).hexdigest()

        self.assertEqual(runner.coverage(tests), (2, expected))

    def test_list_prints_coverage_without_running_tests(self) -> None:
        result = self.run_script("--list")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(result.stdout, r"^total=\d+ digest=[0-9a-f]{64}\n$")
        self.assertEqual(result.stderr, "")

    def test_invalid_shards_exit_with_usage_status(self) -> None:
        for shard in ("0/4", "5/4", "a/b"):
            with self.subTest(shard=shard):
                result = self.run_script("--shard", shard)
                self.assertEqual(result.returncode, 2)
                self.assertIn("usage:", result.stderr)
        missing = self.run_script("--shard")
        self.assertEqual(missing.returncode, 2)
        self.assertIn("usage:", missing.stderr)

    def test_empty_shard_exits_with_status_two(self) -> None:
        result = self.run_script("--shard", "9999/9999")

        self.assertEqual(result.returncode, 2)
        self.assertIn("selects no tests", result.stderr)
        self.assertRegex(result.stdout, r"^shard=9999/9999 total=\d+ selected=0 digest=[0-9a-f]{64}\n$")


class ParallelTestRunnerTest(unittest.TestCase):
    def make_suite(self, bodies: list[str]) -> Path:
        directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, directory, True)
        for position, body in enumerate(bodies):
            (directory / f"test_generated_{position:02d}.py").write_text(
                "import os, signal, unittest\n"
                "class GeneratedTest(unittest.TestCase):\n"
                f"    def test_value(self):\n        {body}\n",
                encoding="utf-8",
            )
        return directory

    def run_parallel(self, directory: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--tests-directory", str(directory), *arguments],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    @staticmethod
    def stable(output: str) -> str:
        output = re.sub(r"time=[0-9.]+s", "time=T", output)
        return re.sub(r"Ran (\d+) tests? in [0-9.]+s", r"Ran \1 tests in Ts", output)

    def test_stable_ignores_inner_unittest_timing(self) -> None:
        first = "Ran 1 test in 0.000s\nFAILED workers=4 time=0.1s\n"
        second = "Ran 1 test in 0.001s\nFAILED workers=4 time=0.2s\n"
        self.assertEqual(self.stable(first), self.stable(second))
        self.assertNotEqual(self.stable(first), self.stable(second.replace("Ran 1", "Ran 2")))

    def test_worker_counts_one_above_shards_and_above_ceiling(self) -> None:
        small = self.make_suite(["pass"] * 3)
        large = self.make_suite(["pass"] * (runner.MAX_WORKERS + 4))
        cases = [(small, "1", 1), (small, "50", 3), (large, "50", runner.MAX_WORKERS), (large, "3", 3)]
        for directory, requested, expected in cases:
            with self.subTest(requested=requested, expected=expected):
                result = self.run_parallel(directory, "--parallel", requested)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn(f"workers={expected} ", result.stdout)
                self.assertIn(f"shards={expected} ", result.stdout)

    def test_default_workers_follow_cpu_count_within_the_ceiling(self) -> None:
        self.assertGreaterEqual(runner.default_workers(), 1)
        self.assertLessEqual(runner.default_workers(), runner.MAX_WORKERS)
        directory = self.make_suite(["pass"] * (runner.MAX_WORKERS + 4))
        result = self.run_parallel(directory, "--parallel")
        self.assertIn(f"workers={runner.default_workers()} ", result.stdout)

    def test_invalid_worker_counts_exit_with_usage_status(self) -> None:
        for value in ("0", "-2", "x"):
            with self.subTest(value=value):
                result = self.run_parallel(self.make_suite(["pass"]), "--parallel", value)
                self.assertEqual(result.returncode, 2)
                self.assertIn("usage:", result.stderr)

    def test_coverage_proof_matches_list_and_the_union_of_shards(self) -> None:
        directory = self.make_suite(["pass"] * 7)
        listed = self.run_parallel(directory, "--list").stdout.strip()
        total, digest = re.fullmatch(r"total=(\d+) digest=([0-9a-f]{64})", listed).groups()
        for workers in (1, 2, 3, 7, 9):
            with self.subTest(workers=workers):
                combined = self.run_parallel(directory, "--parallel", str(workers)).stdout
                effective = min(workers, int(total))
                self.assertIn(
                    f"coverage total={total} digest={digest} shards={effective} selected={total}", combined
                )
                selected = 0
                for index in range(1, effective + 1):
                    shard = self.run_parallel(directory, "--shard", f"{index}/{effective}").stdout
                    header = re.search(r"^shard=\d+/\d+ total=(\d+) selected=(\d+) digest=(\w+)$", shard, re.M)
                    self.assertEqual((header[1], header[3]), (total, digest))
                    selected += int(header[2])
                self.assertEqual(selected, int(total))

    def test_passing_run_prints_a_short_summary_and_is_repeatable(self) -> None:
        directory = self.make_suite(["pass"] * 6)
        outputs = [self.run_parallel(directory, "--parallel", "3") for _ in range(3)]
        for result in outputs:
            self.assertEqual(result.returncode, 0)
            self.assertEqual(len(result.stdout.splitlines()), 2)
            self.assertRegex(result.stdout, r"^OK workers=3 ran=6 failures=0 errors=0 skipped=0 time=[0-9.]+s\n")
        self.assertEqual(len({self.stable(result.stdout) for result in outputs}), 1)

    def test_failing_shards_are_shown_first_in_shard_order_and_bounded(self) -> None:
        failure = "self.fail('boom ' + 'x' * 10)"
        directory = self.make_suite([failure, "pass", failure, "pass"])
        outputs = [self.run_parallel(directory, "--parallel", "4") for _ in range(2)]
        result = outputs[0]

        self.assertEqual(result.returncode, 1)
        self.assertLess(result.stdout.index("--- shard 1/4"), result.stdout.index("--- shard 3/4"))
        self.assertNotIn("--- shard 2/4", result.stdout)
        self.assertLess(result.stdout.index("--- shard 3/4"), result.stdout.index("FAILED workers=4"))
        self.assertIn("failures=2", result.stdout)
        self.assertLessEqual(len(result.stdout.splitlines()), 2 * (runner.FAILURE_LINES + 1) + 2)
        self.assertEqual(self.stable(outputs[0].stdout), self.stable(outputs[1].stdout))

    def test_bounded_output_keeps_the_tail(self) -> None:
        text = "\n".join(str(number) for number in range(200))
        shown = runner.bounded(text, 5).splitlines()
        self.assertEqual(shown, ["... 195 earlier lines omitted ...", "195", "196", "197", "198", "199"])

    def test_failing_shard_keeps_diagnostics_before_a_long_output_tail(self) -> None:
        directory = self.make_suite(["pass"])
        sys.modules.pop("test_generated_00", None)
        self.addCleanup(sys.modules.pop, "test_generated_00", None)
        total, digest = runner.coverage(runner.discover_tests(directory))
        blocks = (
            "FAIL: test_value (test_generated_00.GeneratedTest.test_value)\n"
            "----------------------------------------------------------------------\n"
            "Traceback (most recent call last):\n"
            "  File \"generated.py\", line 1, in test_value\n"
            "AssertionError: boom\n"
            "----------------------------------------------------------------------\n"
            "ERROR: test_error (test_generated_00.GeneratedTest.test_error)\n"
            "----------------------------------------------------------------------\n"
            "Traceback (most recent call last):\n"
            "  File \"generated.py\", line 2, in test_error\n"
            "RuntimeError: boom\n"
            "----------------------------------------------------------------------"
        )
        noise = "\n".join(f"unrelated output {number}" for number in range(runner.FAILURE_LINES + 10))
        output = (
            f"shard=1/1 total={total} selected=1 digest={digest}\n{blocks}\n{noise}\n"
            "result ran=1 failures=1 errors=1 skipped=0\n"
        )

        def command(_index: int, _count: int, _directory: Path) -> list[str]:
            return [sys.executable, "-c", f"import sys; sys.stdout.write({output!r}); sys.exit(1)"]

        with mock.patch("sys.stdout", new_callable=__import__("io").StringIO) as captured:
            status = runner.run_parallel(1, directory, command)

        report = captured.getvalue()
        self.assertEqual(status, 1)
        self.assertIn("FAIL: test_value", report)
        self.assertIn("AssertionError: boom", report)
        self.assertIn("ERROR: test_error", report)
        self.assertIn("RuntimeError: boom", report)
        self.assertNotIn("unrelated output 0", report)
        self.assertIn("unrelated output 69", report)
        self.assertLess(report.index("RuntimeError: boom"), report.index("result ran=1 failures=1 errors=1 skipped=0"))

    def test_shard_without_a_result_keeps_its_bounded_tail(self) -> None:
        directory = self.make_suite(["pass"])
        sys.modules.pop("test_generated_00", None)
        self.addCleanup(sys.modules.pop, "test_generated_00", None)
        output = "\n".join(f"tail line {number}" for number in range(runner.FAILURE_LINES + 10))

        def command(_index: int, _count: int, _directory: Path) -> list[str]:
            code = f"import os, sys; sys.stdout.write({output!r}); sys.stdout.flush(); os.kill(os.getpid(), 9)"
            return [sys.executable, "-c", code]

        with mock.patch("sys.stdout", new_callable=__import__("io").StringIO) as captured:
            status = runner.run_parallel(1, directory, command)

        report = captured.getvalue()
        self.assertEqual(status, 1)
        self.assertIn("... 10 earlier lines omitted ...", report)
        self.assertNotIn("tail line 0", report)
        self.assertIn("tail line 69", report)

    def test_a_killed_shard_fails_the_run(self) -> None:
        directory = self.make_suite(["pass", "os.kill(os.getpid(), signal.SIGKILL)", "pass"])
        result = self.run_parallel(directory, "--parallel", "3")

        self.assertEqual(result.returncode, 1)
        self.assertIn("shard 2/3 killed by signal 9", result.stdout)
        self.assertIn("FAILED workers=3", result.stdout)

    def test_a_shard_with_a_different_proof_fails_the_run(self) -> None:
        directory = self.make_suite(["pass", "pass"])
        header = "shard={i}/{n} total=2 selected=1 digest=" + "0" * 64

        def command(index: int, count: int, _: Path) -> list[str]:
            script = f"print({header.format(i=index, n=count)!r}); print('result ran=1 failures=0 errors=0 skipped=0')"
            return [sys.executable, "-c", script]

        with mock.patch("sys.stdout", new_callable=__import__("io").StringIO) as captured:
            status = runner.run_parallel(2, directory, command)

        self.assertEqual(status, 1)
        self.assertIn("reported a different coverage proof", captured.getvalue())

    def test_each_shard_gets_a_private_temporary_directory(self) -> None:
        scratch = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, scratch, True)
        code = "import os; print(os.environ['TMPDIR'], os.environ['MERIDIAN_TEST_SHARD'])"
        results = runner.run_shards([[sys.executable, "-c", code]] * 3, scratch, dict(os.environ))

        temporary = [result.output.split()[0] for result in results]
        self.assertEqual(len(set(temporary)), 3)
        for position, path in enumerate(temporary, start=1):
            self.assertTrue(path.startswith(str(scratch)))
            self.assertIn(f"{position}/3", results[position - 1].output)

    def test_tests_do_not_share_ports_global_git_config_or_process_environment(self) -> None:
        patterns = {
            "socket use": re.compile(r"\bsocket\.|\.bind\(\("),
            "global or system git config": re.compile(r"--(global|system)\b"),
            "environment assignment": re.compile(r"os\.environ\[[^\]]+\]\s*=|os\.putenv|os\.environ\.(update|setdefault)"),
        }
        for path in sorted((ROOT / "tests").glob("test_*.py")):
            if path == Path(__file__).resolve():
                continue
            text = path.read_text(encoding="utf-8")
            for name, pattern in patterns.items():
                with self.subTest(file=path.name, check=name):
                    self.assertIsNone(pattern.search(text))
