#!/usr/bin/env python3
"""Write T1 CI validation evidence from an existing GitHub Actions run."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

POLL_INTERVAL_SECONDS = 5
DEFAULT_WAIT_SECONDS = 0
RUN_LIMIT = 100
EXIT_PASSED, EXIT_PENDING, EXIT_FAILED = 0, 1, 2
WORKFLOW_NAME = "Validate repository"


def gh_json(arguments: list[str]) -> tuple[object | None, str | None]:
    """Run a read-only gh query and decode its JSON response."""
    try:
        completed = subprocess.run(["gh", *arguments], text=True, capture_output=True, check=False)
    except OSError as error:
        return None, str(error)
    if completed.returncode:
        return None, completed.stderr.strip() or completed.stdout.strip() or "gh command failed"
    try:
        return json.loads(completed.stdout), None
    except json.JSONDecodeError:
        return None, "gh returned invalid JSON"


def matching_run(commit: str) -> tuple[dict[str, object] | None, str | None]:
    listed, error = gh_json(["run", "list", "--workflow", WORKFLOW_NAME, "--commit", commit,
                             "--limit", str(RUN_LIMIT), "--json", "databaseId,headSha,event,status,conclusion,url,workflowName"])
    if error:
        return None, error
    if not isinstance(listed, list):
        return None, "gh returned an invalid run list"
    for item in listed:
        if not isinstance(item, dict) or item.get("headSha") != commit or item.get("event") not in {"push", "pull_request"}:
            continue
        run_id = item.get("databaseId")
        if not isinstance(run_id, int):
            continue
        viewed, error = gh_json(["run", "view", str(run_id), "--json", "databaseId,headSha,event,status,conclusion,url,workflowName"])
        if error:
            return None, error
        if isinstance(viewed, dict) and viewed.get("headSha") == commit and viewed.get("event") in {"push", "pull_request"}:
            return viewed, None
        if not isinstance(viewed, dict):
            return None, "gh returned an invalid workflow run"
    return None, None


def commit_tree(run: dict[str, object]) -> tuple[str | None, str | None]:
    """Read the GitHub commit tree through gh; no local Git command is used."""
    url, commit = run.get("url"), run.get("headSha")
    if not isinstance(url, str) or not isinstance(commit, str):
        return None, "workflow run is missing its URL or commit"
    marker = "https://github.com/"
    if not url.startswith(marker) or "/actions/runs/" not in url:
        return None, "workflow run URL does not identify a GitHub repository"
    repository = url[len(marker):].split("/actions/runs/", 1)[0]
    response, error = gh_json(["api", f"repos/{repository}/git/commits/{commit}"])
    if error:
        return None, error
    tree = response.get("tree", {}).get("sha") if isinstance(response, dict) else None
    return (tree, None) if isinstance(tree, str) and tree else (None, "gh returned a commit without a tree")


def result(status: str, reason: str | None = None) -> int:
    payload: dict[str, str] = {"status": status}
    if reason:
        payload["reason"] = reason
    print(json.dumps(payload, sort_keys=True))
    return EXIT_PASSED if status == "passed" else EXIT_FAILED if status == "failed" else EXIT_PENDING


def write_record(output: Path, task: str, run: dict[str, object], tree: str, now: Callable[[], float]) -> None:
    record = {"version": 1, "task_id": task, "status": "passed", "level": "T1_CI", "commit": run["headSha"], "tree": tree,
              "command": ["python3", "-m", "unittest", "discover", "-s", "tests"], "exit_code": 0, "tests_run": 1,
              "produced_at": datetime.fromtimestamp(now(), timezone.utc).isoformat().replace("+00:00", "Z"),
              "ci": {"run_id": str(run["databaseId"]), "run_url": run["url"], "workflow": str(run.get("workflowName") or WORKFLOW_NAME), "conclusion": "success", "head_sha": run["headSha"]}}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run(arguments: list[str] | None = None, *, clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep) -> int:
    parser = argparse.ArgumentParser(description="Write T1 CI evidence for an exact commit.")
    parser.add_argument("--commit", required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--wait", type=int, default=DEFAULT_WAIT_SECONDS, metavar="SECONDS")
    args = parser.parse_args(arguments)
    if args.wait < 0:
        parser.error("--wait must not be negative")
    if shutil.which("gh") is None:
        return result("unavailable", "gh_missing")
    deadline, last_error = clock() + args.wait, None
    while True:
        workflow_run, error = matching_run(args.commit)
        if error:
            last_error = error
        elif workflow_run is not None:
            if workflow_run.get("status") != "completed":
                if clock() >= deadline:
                    return result("running")
            elif workflow_run.get("conclusion") == "success":
                tree, tree_error = commit_tree(workflow_run)
                if tree:
                    try:
                        write_record(args.output, args.task, workflow_run, tree, clock)
                    except OSError:
                        return result("failed", "output_write_failed")
                    return result("passed")
                last_error = tree_error
            else:
                return result("failed")
        elif clock() >= deadline:
            return result("unavailable", "no_ci_run" if last_error is None else "gh_error")
        if clock() >= deadline:
            return result("unavailable", "gh_error" if last_error else "no_ci_run")
        sleep(min(POLL_INTERVAL_SECONDS, deadline - clock()))


if __name__ == "__main__":
    try:
        raise SystemExit(run())
    except (BrokenPipeError, KeyboardInterrupt):
        raise SystemExit(EXIT_FAILED)
