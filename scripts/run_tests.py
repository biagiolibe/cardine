#!/usr/bin/env python3
"""Run Meridian's unittest suite in deterministic, disjoint shards."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
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
FAILURE_BLOCK = re.compile(r"^(?:FAIL|ERROR): .*\n^-{5,}\n.*?^-{5,}$", re.MULTILINE | re.DOTALL)


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
        if header:
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
                **(os.environ if environment is None else environment),
                "TMPDIR": str(private / "tmp"),
                "MERIDIAN_TEST_SHARD": f"{position}/{len(commands)}",
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


def run_parallel(
    requested: int,
    tests_directory: Path = TESTS_DIRECTORY,
    command_for: Callable[[int, int, Path], Sequence[str]] = shard_command,
    environment: dict[str, str] | None = None,
) -> int:
    """Run the suite as concurrent shards and print one combined, ordered report."""
    tests = discover_tests(tests_directory)
    total, digest = coverage(tests)
    workers = max(1, min(requested or default_workers(), MAX_WORKERS, total))
    started = time.monotonic()
    scratch = Path(tempfile.mkdtemp(prefix="meridian-tests-"))
    try:
        results = run_shards([command_for(i, workers, tests_directory) for i in range(1, workers + 1)], scratch, environment)
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
    print(
        f"{'OK' if ok else 'FAILED'} workers={workers} ran={ran} failures={failures} errors={errors} "
        f"skipped={skipped} time={elapsed:.1f}s"
    )
    print(f"coverage total={total} digest={digest} shards={workers} selected={selected}", flush=True)
    return 0 if ok else 1


def main(arguments: list[str] | None = None) -> int:
    options = parser().parse_args(arguments)
    # `python -m unittest` puts the working directory on sys.path; a script run
    # puts only scripts/, so tests that import `tests.*` need the root as well.
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    if options.parallel is not None:
        return run_parallel(options.parallel, options.tests_directory)
    tests = discover_tests(options.tests_directory)
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
    outcome = unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(selected))
    print(
        f"result ran={outcome.testsRun} failures={len(outcome.failures)} errors={len(outcome.errors)} "
        f"skipped={len(outcome.skipped)}",
        flush=True,
    )
    return 0 if outcome.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
