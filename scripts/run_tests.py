#!/usr/bin/env python3
"""Run Cardine's unittest suite in deterministic, disjoint shards."""

from __future__ import annotations

import argparse
import hashlib
import difflib
import json
import os
import re
import shutil
import shlex
import subprocess
import sys
import tempfile
import time
import unittest
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from contextlib import contextmanager
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TESTS_DIRECTORY = ROOT / "tests"
SCRIPT = Path(__file__).resolve()
# Ceiling on concurrent shard processes: beyond it the suite's subprocess-heavy
# tests contend for the same cores and the wall time stops improving.
MAX_WORKERS = 8
# Lines of a failing shard's output that a combined report prints.
FAILURE_LINES = 60
HEADER = re.compile(r"^shard=(\d+)/(\d+) total=(\d+) selected=(\d+) digest=([0-9a-f]{64})$")
RESULT = re.compile(r"^result ran=(\d+) failures=(\d+) errors=(\d+) skipped=(\d+)$", re.MULTILINE)
COVERAGE = re.compile(r"^coverage total=(\d+) digest=([0-9a-f]{64})", re.MULTILINE)
FAILURE_BLOCK = re.compile(r"^(?:FAIL|ERROR): .*\n^-{5,}\n.*?^-{5,}$", re.MULTILINE | re.DOTALL)


@contextmanager
# MERIDIAN-INSTALLATION-CHECK
def reject_path_meridian():
    """Fail the current test even when a nested hook swallows a PATH command's exit."""
    with tempfile.TemporaryDirectory(prefix="installation-guard-") as directory:
        root = Path(directory)
        marker = root / "called"
        # MERIDIAN-INSTALLATION-CHECK
        executable = root / "meridian"
        executable.write_text(
            "#!/bin/sh\nprintf '%s\\n' \"$*\" >> " + shlex.quote(str(marker)) + "\nexit 97\n",
            encoding="utf-8",
        )
        executable.chmod(0o755)
        previous = os.environ.get("PATH")
        os.environ["PATH"] = str(root) + os.pathsep + (previous or os.defpath)

        class InstallationCheckResult(unittest.TextTestResult):
            def stopTest(self, test):
                if marker.exists():
                    try:
                        # MERIDIAN-INSTALLATION-CHECK
                        raise AssertionError("test spawned meridian through PATH: " + marker.read_text())
                    except AssertionError:
                        self.addFailure(test, sys.exc_info())
                    marker.unlink()
                super().stopTest(test)

        try:
            yield InstallationCheckResult
        finally:
            if previous is None:
                os.environ.pop("PATH", None)
            else:
                os.environ["PATH"] = previous


def iter_tests(suite: unittest.TestSuite) -> Iterable[unittest.TestCase]:
    """Yield individual test cases from a possibly nested unittest suite."""
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from iter_tests(item)
        else:
            yield item


def discover_tests(tests_directory: Path = TESTS_DIRECTORY) -> list[unittest.TestCase]:
    """Discover tests and return them sorted by their stable unittest id."""
    # A fresh loader avoids the top-level directory that Python 3.11 keeps on
    # the shared default loader after an earlier discovery in the same process.
    discovered = unittest.TestLoader().discover(str(tests_directory))
    return sorted(iter_tests(discovered), key=lambda test: test.id())


def coverage(tests: list[unittest.TestCase]) -> tuple[int, str]:
    """Return the test count and SHA-256 proof for a sorted test list."""
    identifiers = "\n".join(test.id() for test in tests)
    return len(tests), hashlib.sha256(identifiers.encode("utf-8")).hexdigest()


def parse_shard(value: str) -> tuple[int, int]:
    """Parse a one-based shard I/N, rejecting invalid bounds."""
    try:
        index_text, count_text = value.split("/", 1)
        index = int(index_text)
        count = int(count_text)
    except ValueError as error:
        raise argparse.ArgumentTypeError("shard must be I/N with positive integers") from error
    if index < 1 or count < 1 or index > count:
        raise argparse.ArgumentTypeError("shard must be I/N where 1 <= I <= N")
    return index, count


def parse_workers(value: str) -> int:
    """Parse an explicit worker count, rejecting anything below one."""
    try:
        workers = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("workers must be a positive integer") from error
    if workers < 1:
        raise argparse.ArgumentTypeError("workers must be a positive integer")
    return workers


def default_workers() -> int:
    """Return the CPU count bounded by the documented ceiling."""
    return max(1, min(os.cpu_count() or 1, MAX_WORKERS))


def parser() -> argparse.ArgumentParser:
    argument_parser = argparse.ArgumentParser(description=__doc__)
    group = argument_parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--shard", type=parse_shard, metavar="I/N")
    group.add_argument("--list", action="store_true", help="print coverage without running tests")
    group.add_argument(
        "--parallel",
        nargs="?",
        const=0,
        type=parse_workers,
        metavar="N",
        help=f"run N shards concurrently (default: CPU count, at most {MAX_WORKERS})",
    )
    argument_parser.add_argument(
        "--clean-clone",
        action="store_true",
        help="with --parallel, validate a shallow clone of the committed HEAD instead of this working tree",
    )
    selection = argument_parser.add_mutually_exclusive_group()
    selection.add_argument("--last-failed", action="store_true", help="rerun the recorded failing tests")
    selection.add_argument("--module", action="append", default=[], help="select a module, path, class, or test ID (repeatable)")
    argument_parser.add_argument("--selection-file", type=Path, help=argparse.SUPPRESS)
    argument_parser.add_argument("--failure-record", type=Path, help=argparse.SUPPRESS)
    argument_parser.add_argument("--failed-output", type=Path, help=argparse.SUPPRESS)
    argument_parser.add_argument("--tests-directory", type=Path, default=TESTS_DIRECTORY, help=argparse.SUPPRESS)
    return argument_parser


@dataclass
class ShardResult:
    index: int
    returncode: int
    output: str
    header: tuple[int, int, int, int, str] | None = None  # index, count, total, selected, digest
    counts: tuple[int, int, int, int] | None = None

    @property
    def passed(self) -> bool:
        return self.returncode == 0 and self.counts is not None and self.counts[1] == 0 and self.counts[2] == 0


def parse_shard_output(index: int, returncode: int, output: str) -> ShardResult:
    """Extract the header and result lines a shard prints; missing lines stay None."""
    result = ShardResult(index, returncode, output)
    for line in output.splitlines():
        header = HEADER.match(line)
        if header and result.header is None:
            result.header = (int(header[1]), int(header[2]), int(header[3]), int(header[4]), header[5])
        counts = RESULT.match(line)
        if counts:
            result.counts = tuple(int(value) for value in counts.groups())  # type: ignore[assignment]
    return result


def shard_command(index: int, count: int, tests_directory: Path) -> list[str]:
    command = [sys.executable, str(SCRIPT), "--shard", f"{index}/{count}"]
    if tests_directory != TESTS_DIRECTORY:
        command += ["--tests-directory", str(tests_directory)]
    return command


def isolated_environment(environment: Mapping[str, str]) -> dict[str, str]:
    """Keep test roots independent and exclude retired framework variables."""
    return {
        key: value for key, value in environment.items()
        # MERIDIAN-INSTALLATION-CHECK
        if key != "CARDINE_ROOT" and not key.startswith("MERIDIAN_")
    }


def run_shards(
    commands: Sequence[Sequence[str]], scratch: Path, environment: dict[str, str] | None = None
) -> list[ShardResult]:
    """Run every command concurrently, each with a private TMPDIR, and collect results in order."""
    processes: list[tuple[subprocess.Popen[bytes], Path]] = []
    try:
        for position, command in enumerate(commands, start=1):
            private = scratch / f"shard-{position}"
            (private / "tmp").mkdir(parents=True)
            output_path = private / "output.txt"
            shard_environment = {
                **isolated_environment(os.environ if environment is None else environment),
                "TMPDIR": str(private / "tmp"),
                "CARDINE_TEST_SHARD": f"{position}/{len(commands)}",
            }
            with output_path.open("wb") as output:
                process = subprocess.Popen(
                    list(command), stdout=output, stderr=subprocess.STDOUT, env=shard_environment, cwd=ROOT
                )
            processes.append((process, output_path))
        results = []
        for position, (process, output_path) in enumerate(processes, start=1):
            returncode = process.wait()
            results.append(
                parse_shard_output(position, returncode, output_path.read_text(encoding="utf-8", errors="replace"))
            )
        return results
    except BaseException:
        for process, _ in processes:
            if process.poll() is None:
                process.kill()
                process.wait()
        raise


def bounded(output: str, limit: int = FAILURE_LINES) -> str:
    """Keep the last `limit` lines, where unittest prints its failure diagnostics."""
    lines = output.splitlines()
    if len(lines) <= limit:
        return "\n".join(lines)
    return "\n".join([f"... {len(lines) - limit} earlier lines omitted ..."] + lines[-limit:])


def failure_report(output: str) -> str:
    """Keep bounded context while preserving every unittest diagnostic block.

    Unittest places each failure or error between separator lines.  Those
    blocks name the test and contain its traceback, so they must not be lost
    merely because a shard emits extensive output after them.
    """
    blocks = [match.group(0) for match in FAILURE_BLOCK.finditer(output)]
    if not blocks:
        return bounded(output)

    summaries = list(RESULT.finditer(output))
    summary = summaries[-1].group(0) if summaries else None
    context = FAILURE_BLOCK.sub("", output)
    context = RESULT.sub("", context)
    sections = [section for section in (bounded(context).strip(), *blocks, summary) if section]
    return "\n".join(sections)


FULL_COMMAND = "python3 scripts/run_tests.py --parallel --clean-clone"
RETRY_COMMAND = "python3 scripts/run_tests.py --parallel --last-failed"


def failure_record(source: Path = ROOT) -> Path:
    """Resolve the per-worktree Git directory, never the shared common directory."""
    result = git(source, "rev-parse", "--absolute-git-dir")
    if result.returncode:
        raise ValueError(result.stderr.strip())
    return Path(result.stdout.strip()) / "cardine-last-failed.txt"


def write_failures(record: Path, identifiers: Iterable[str]) -> None:
    record.write_text("".join(identifier + "\n" for identifier in sorted(set(identifiers))), encoding="utf-8")


def select_tests(tests: list[unittest.TestCase], modules: Sequence[str]) -> list[unittest.TestCase]:
    identifiers = {test.id(): test for test in tests}
    chosen = set()
    existing = sorted({identifier.split(".")[0] for identifier in identifiers})
    for name in modules:
        normalized = name.replace("\\", "/").removeprefix("tests/").removeprefix("tests.")
        if normalized.endswith(".py"):
            normalized = normalized[:-3]
        matches = {identifier for identifier in identifiers if identifier == normalized or identifier.startswith(normalized + ".")}
        if not matches:
            closest = difflib.get_close_matches(normalized.split(".")[0], existing, n=3, cutoff=0)
            raise ValueError(f"unknown selection {name!r}; closest modules: {', '.join(closest)}")
        chosen.update(matches)
    return [test for test in tests if test.id() in chosen]


def run_parallel(
    requested: int,
    tests_directory: Path = TESTS_DIRECTORY,
    command_for: Callable[[int, int, Path], Sequence[str]] = shard_command,
    environment: dict[str, str] | None = None,
    selection: list[unittest.TestCase] | None = None,
    selection_label: str = "",
    record: Path | None = None,
) -> int:
    """Run the suite as concurrent shards and print one combined, ordered report."""
    tests = discover_tests(tests_directory)
    full_total = len(tests)
    if selection is not None:
        tests = selection
    total, digest = coverage(tests)
    workers = max(1, min(requested or default_workers(), MAX_WORKERS, total))
    started = time.monotonic()
    scratch = Path(tempfile.mkdtemp(prefix="cardine-tests-"))
    try:
        commands = [list(command_for(i, workers, tests_directory)) for i in range(1, workers + 1)]
        if selection is not None:
            selection_file = scratch / "selection.json"
            selection_file.write_text(json.dumps([test.id() for test in tests]), encoding="utf-8")
            for command in commands:
                command.extend(["--selection-file", str(selection_file)])
        failure_files = [scratch / f"failures-{i}.json" for i in range(workers)]
        if record is not None:
            for command, path in zip(commands, failure_files):
                command.extend(["--failed-output", str(path)])
        results = run_shards(commands, scratch, environment)
        if record is not None:
            identifiers = [identifier for path in failure_files if path.exists()
                           for identifier in json.loads(path.read_text(encoding="utf-8"))]
            write_failures(record, identifiers)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    elapsed = time.monotonic() - started

    problems = []
    selected = 0
    for result in results:
        if result.counts is None or result.returncode < 0:
            how = f"killed by signal {-result.returncode}" if result.returncode < 0 else f"exited {result.returncode} without a result"
            problems.append(f"shard {result.index}/{workers} {how}")
        if result.header is None:
            continue
        shard_index, _, shard_total, shard_selected, shard_digest = result.header
        selected += shard_selected
        if (shard_total, shard_digest, shard_index) != (total, digest, result.index):
            problems.append(f"shard {result.index}/{workers} reported a different coverage proof")
    if selected != total and not any("different coverage" in p or "killed" in p or "without a result" in p for p in problems):
        problems.append(f"shards selected {selected} tests, expected {total}")

    counted = [result.counts for result in results if result.counts]
    ran, failures, errors, skipped = (sum(column) for column in zip(*counted)) if counted else (0, 0, 0, 0)
    failed = [result for result in results if not result.passed]
    ok = not failed and not problems and ran == total

    for result in failed:
        print(f"--- shard {result.index}/{workers} (exit {result.returncode}) ---")
        print(failure_report(result.output) if result.counts is not None else bounded(result.output))
    for problem in problems:
        print(f"problem: {problem}")
    if selection is not None:
        print(f"PARTIAL selection={selection_label} ran={ran} total={full_total} failures={failures} errors={errors}")
        if ok:
            print(FULL_COMMAND)
    else:
        print(
            f"{'OK' if ok else 'FAILED'} workers={workers} ran={ran} failures={failures} errors={errors} "
            f"skipped={skipped} time={elapsed:.1f}s"
        )
        print(f"coverage total={total} digest={digest} shards={workers} selected={selected}", flush=True)
        if not ok:
            print(RETRY_COMMAND)
    return 0 if ok else 1


def git(source: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(source), *arguments], text=True, capture_output=True, check=False)


def run_clean_clone(requested: int, source: Path = ROOT) -> int:
    """Validate the committed HEAD of `source` in a throwaway shallow clone.

    The clone holds only tracked files and the last commit, which is what a CI
    checkout sees, so it catches untracked-file dependencies and checks that
    need history. A dirty tree is refused so the result always names a commit.
    """
    dirty = git(source, "status", "--porcelain", "--untracked-files=no")
    if dirty.returncode != 0 or dirty.stdout.strip():
        print("clean-clone refused: the working tree has uncommitted changes; commit them first")
        return 2
    commit = git(source, "rev-parse", "HEAD").stdout.strip()
    scratch = Path(tempfile.mkdtemp(prefix="cardine-clean-clone-"))
    clone = scratch / "clone"
    environment = isolated_environment(os.environ)
    environment["TMPDIR"] = str(scratch)
    total, digest, outcome = "unknown", "unknown", "FAILED"
    try:
        cloned = subprocess.run(
            ["git", "clone", "--quiet", "--depth", "1", "--no-local", str(source), str(clone)],
            text=True,
            capture_output=True,
            check=False,
        )
        if cloned.returncode != 0:
            print(f"clean-clone could not clone: {cloned.stderr.strip()}")
        else:
            parallel = ["--parallel"] + ([str(requested)] if requested else [])
            parallel += ["--failure-record", str(failure_record(source))]
            steps = (["scripts/check_repository.py"], ["scripts/run_tests.py", *parallel])
            for step in steps:
                finished = subprocess.run(
                    [sys.executable, *step], cwd=clone, env=environment, text=True, capture_output=True, check=False
                )
                print(finished.stdout, end="")
                print(finished.stderr, end="", file=sys.stderr)
                proof = COVERAGE.search(finished.stdout)
                if proof:
                    total, digest = proof[1], proof[2]
                if finished.returncode != 0:
                    break
            else:
                outcome = "OK"
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    print(f"clean-clone commit={commit} total={total} digest={digest} outcome={outcome}", flush=True)
    return 0 if outcome == "OK" else 1


def main(arguments: list[str] | None = None) -> int:
    options = parser().parse_args(arguments)
    partial = options.last_failed or bool(options.module)
    if partial and (options.parallel is None or options.clean_clone):
        parser().error("--last-failed and --module require --parallel and cannot be combined with --clean-clone")
    if options.clean_clone:
        if options.parallel is None:
            parser().error("--clean-clone requires --parallel")
        return run_clean_clone(options.parallel)
    # Tests select their own framework roots; do not inherit the launcher's.
    for key in tuple(os.environ):
        # MERIDIAN-INSTALLATION-CHECK
        if key == "CARDINE_ROOT" or key.startswith("MERIDIAN_"):
            os.environ.pop(key)
    # `python -m unittest` puts the working directory on sys.path; a script run
    # puts only scripts/, so tests that import `tests.*` need the root as well.
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    if options.parallel is not None:
        record = options.failure_record or failure_record()
        tests = discover_tests(options.tests_directory)
        selection = None
        label = ""
        if options.module:
            try:
                selection = select_tests(tests, options.module)
            except ValueError as error:
                parser().error(str(error))
            label = "module:" + ",".join(options.module)
        elif options.last_failed:
            recorded = record.read_text(encoding="utf-8").splitlines() if record.exists() else []
            available = {test.id() for test in tests}
            for missing in sorted(set(recorded) - available):
                print(f"recorded test no longer exists; skipped: {missing}")
            selection = [test for test in tests if test.id() in recorded]
            label = "last-failed"
            if not selection:
                write_failures(record, [])
                print(f"PARTIAL selection=last-failed ran=0 total={len(tests)} failures=0 errors=0")
                print(FULL_COMMAND)
                return 2
        return run_parallel(options.parallel, options.tests_directory, selection=selection, selection_label=label, record=record)
    tests = discover_tests(options.tests_directory)
    if options.selection_file:
        selected_ids = set(json.loads(options.selection_file.read_text(encoding="utf-8")))
        tests = [test for test in tests if test.id() in selected_ids]
    total, digest = coverage(tests)
    if options.list:
        print(f"total={total} digest={digest}", flush=True)
        return 0

    index, count = options.shard
    selected = [test for position, test in enumerate(tests) if position % count == index - 1]
    print(
        f"shard={index}/{count} total={total} selected={len(selected)} digest={digest}",
        flush=True,
    )
    if not selected:
        parser().error(f"shard {index}/{count} selects no tests")
    # MERIDIAN-INSTALLATION-CHECK
    with reject_path_meridian() as result_class:
        outcome = unittest.TextTestRunner(verbosity=2, resultclass=result_class).run(unittest.TestSuite(selected))
    if options.failed_output:
        identifiers = {getattr(test, "test_case", test).id() for test, _ in outcome.failures + outcome.errors}
        options.failed_output.write_text(json.dumps(sorted(identifiers)), encoding="utf-8")
    print(
        f"result ran={outcome.testsRun} failures={len(outcome.failures)} errors={len(outcome.errors)} "
        f"skipped={len(outcome.skipped)}",
        flush=True,
    )
    return 0 if outcome.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
