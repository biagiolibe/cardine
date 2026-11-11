"""Resolve visible bootstrap choices without executing project code."""
from __future__ import annotations

import json
from pathlib import Path
import re


def test_validation(command):
    return {"commands": {"test": command}, "baseline": ["test"],
            "candidate": {"REUSE": [], "BOUNDED": ["test"], "FULL": ["test"]}}


def detect_test(root):
    root = Path(root)
    def read(name):
        path = root / name
        return path.read_text(encoding="utf-8") if path.is_file() else ""
    if re.search(r"^test\s*:", read("Makefile"), re.MULTILINE):
        return "make test", "Makefile"
    try:
        package = json.loads(read("package.json") or "{}")
        script = package.get("scripts", {}).get("test")
        if isinstance(script, str) and not script.startswith('echo "Error: no test specified"'):
            return "npm test", "package.json"
    except (ValueError, AttributeError):
        pass
    for filename, pattern in (("pyproject.toml", r"^\s*\[tool\.pytest\.ini_options\]\s*(?:#.*)?$"),
                              ("pytest.ini", None), ("setup.cfg", r"^\s*\[tool:pytest\]"),
                              ("tox.ini", r"^\s*\[pytest\]"), ("conftest.py", None)):
        path = root / filename
        if path.is_file() and (pattern is None or re.search(pattern, read(filename), re.MULTILINE)):
            return "python3 -m pytest", filename
    if (root / "tests").is_dir():
        return "python3 -m unittest", "tests/"
    if any(root.glob("test_*.py")):
        return "python3 -m unittest", "test_*.py"
    return None, None


def resolve_choices(root, *, name=None, slug=None, preset=None, language=None,
                    task_identity=None, validation=None, test=None, installation=None):
    installed = installation or {}
    values = {"name": name, "slug": slug, "preset": preset, "language": language,
              "task_identity": task_identity, "validation": validation}
    choices = {}
    for key in ("name", "slug", "preset", "language", "task_identity"):
        value = values[key]
        source = "flag"
        if value is None:
            value = installed.get(key)
            source = "installation"
        if value is None:
            defaults = {"name": Path(root).resolve().name,
                        "slug": re.sub(r"[^a-z0-9]+", "-", str(choices.get("name", {}).get("value", "")).lower()).strip("-"),
                        "preset": "lean", "language": "English", "task_identity": "opaque"}
            value, source = defaults[key], "default"
        choices[key] = {"value": value, "source": source}
    if test is not None:
        validation = test_validation(test)
    source = "flag"
    if validation is None:
        validation = installed.get("validation")
        source = "installation"
    if validation is None:
        command, filename = detect_test(root)
        validation = test_validation(command) if command is not None else None
        source = f"detected from {filename}" if filename else "missing"
    choices["validation"] = {"value": validation, "source": source}
    return choices
