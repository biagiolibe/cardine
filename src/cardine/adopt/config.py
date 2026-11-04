"""Map observed Meridian configuration to Cardine's declaration."""
from __future__ import annotations

import hashlib

from cardine.shared.project import parse_project_declaration


def map_config(legacy, *, name, slug, validation, ci="none"):
    """Map only declared inputs; callers supply the otherwise unknowable baseline."""
    preset = "governed" if legacy.mode == "governed-sdd" else "lean"
    config = {"version": 1, "project": {"name": name, "slug": slug},
              "preset": preset, "taskIdentity": {"mode": legacy.identity_mode}, "ci": ci}
    if legacy.declaration and "taskDefaults" in legacy.declaration:
        config["taskDefaults"] = legacy.declaration["taskDefaults"]
    if validation is not None:
        mapped = {"commands": dict(validation["commands"]), "baseline": list(validation["baseline"]),
                  "candidate": {key: list(value) for key, value in validation["candidate"].items()}}
        candidate = legacy.candidate_validation
        if candidate and candidate.get("state") == "declared":
            outcomes = candidate.get("outcomes")
            if not isinstance(outcomes, dict) or set(outcomes) != {"REUSE", "BOUNDED", "FULL"}:
                raise ValueError("invalid candidate validation outcomes")
            for outcome, commands in outcomes.items():
                if not isinstance(commands, list) or not all(isinstance(c, str) and c.strip() for c in commands):
                    raise ValueError(f"invalid candidate validation commands for {outcome}")
                mapped["candidate"][outcome] = []
                for command in commands:
                    ident = "adopt-" + hashlib.sha256(command.encode()).hexdigest()[:16]
                    mapped["commands"][ident] = command
                    mapped["candidate"][outcome].append(ident)
        config["validation"] = mapped
    return parse_project_declaration(config)


def validate_flow_targets(value):
    """Validate the flow target fields consumed by Cardine before copying."""
    if not isinstance(value, dict) or type(value.get("version")) is not int or value["version"] != 1:
        raise ValueError("flow targets must be a version 1 object")
    for key, limit in (("unbacked_blocks", "max"), ("lead_time_regression", "max_percent"),
                       ("friction_share", "max_percent")):
        if key not in value:
            continue
        entry = value[key]
        if not isinstance(entry, dict) or type(entry.get("window")) is not int or entry["window"] < 1:
            raise ValueError(f"{key}.window must be a positive integer")
        number = entry.get(limit)
        if type(number) not in (int, float) or number < 0:
            raise ValueError(f"{key}.{limit} must be a non-negative number")
    return value
