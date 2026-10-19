#!/usr/bin/env python3
"""Development commands; no compatibility promise for this internal interface."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cardine.shared.errors import MeridianError, MeridianStop
from cardine.stops.render import stop_error
from cardine.shared.flow import flow_report, format_flow_report
from cardine.templates.adoption import bootstrap_capability_profile
from cardine.templates.audit import profile_doctor
from cardine.templates.generator import CLAUDE_MD_SHARED_ANCHOR, generated_outputs
from cardine.worktree.storage import _verified_lifecycle_project


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--framework-root", type=Path, default=ROOT)
    commands = parser.add_subparsers(dest="command", required=True)
    profile = commands.add_parser("profile", help="inspect or bootstrap a capability profile")
    operations = profile.add_subparsers(dest="operation", required=True)
    for name in ("doctor", "bootstrap"):
        operation = operations.add_parser(name)
        operation.add_argument("profile_id")
        operation.add_argument("--project", type=Path, default=Path.cwd())
        if name == "bootstrap":
            action = operation.add_mutually_exclusive_group(required=True)
            action.add_argument("--check", action="store_true")
            action.add_argument("--apply", action="store_true")
    report = commands.add_parser("report", help="read lifecycle journal reports")
    flow = report.add_subparsers(dest="operation", required=True).add_parser("flow")
    flow.add_argument("--project", type=Path)
    flow.add_argument("--since")
    flow.add_argument("--format", choices=("json", "text"), default="text")
    generate = commands.add_parser("generate-entry-routers", help="generate consumer entry routers or workflow CLAUDE.md shared bodies")
    generate.add_argument("--mode", choices=tuple(CLAUDE_MD_SHARED_ANCHOR))
    generate.add_argument("--project", type=Path, default=Path.cwd())
    action = generate.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true")
    action.add_argument("--write", action="store_true")
    commands.add_parser("agent-evals", help="run agent evaluations", add_help=False)
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # Forward the evaluation runner's complete argument grammar, including help.
    if argv and argv[0] == "agent-evals":
        from run_agent_evals import main as eval_main
        return eval_main(argv[1:])
    arguments = build_parser().parse_args(argv)
    framework = arguments.framework_root.resolve()
    try:
        if arguments.command == "profile":
            project = arguments.project.resolve()
            if arguments.operation == "doctor":
                return profile_doctor(project, framework, arguments.profile_id)
            manifest = bootstrap_capability_profile(project, framework, arguments.profile_id, apply=arguments.apply)
            print(json.dumps(manifest["capabilityProfiles"][arguments.profile_id], indent=2, sort_keys=True))
        elif arguments.command == "report":
            report = flow_report(_verified_lifecycle_project(arguments.project), arguments.since)
            print(json.dumps(report, sort_keys=True) if arguments.format == "json" else format_flow_report(report))
        else:
            outputs = generated_outputs(framework, arguments.project.resolve(), arguments.mode)
            if arguments.check:
                drifted = [path for path, text in outputs.items() if not path.is_file() or path.read_text(encoding="utf-8") != text]
                if drifted:
                    if arguments.mode:
                        print(f"STALE {drifted[0]}: does not match AGENTS.md-generated output.", file=sys.stderr)
                    else:
                        print("STALE generated entry router(s): " + ", ".join(path.name for path in drifted), file=sys.stderr)
                    return 2
                print(f"CLAUDE.md ({arguments.mode}) matches the generator's output." if arguments.mode else "Generated entry routers match their canonical source.")
            else:
                for path, text in outputs.items():
                    path.write_text(text, encoding="utf-8")
                print(f"Regenerated {next(iter(outputs))}." if arguments.mode else "Generated AGENTS.md and CLAUDE.md from ENTRY_ROUTER.md.")
        return 0
    except MeridianStop as error:
        print(error, file=sys.stderr)
        return 2
    except MeridianError as error:
        print(stop_error("COMMAND_REFUSED", str(error)), file=sys.stderr)
        return 2
    except OSError as error:
        print(stop_error("OS_ACCESS_FAILED", str(error)), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
