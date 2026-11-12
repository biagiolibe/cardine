"""Cached, best-effort release notices for interactive users."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import threading

from cardine.release.version import parse_semver, semver_precedence_key
from cardine.shared.errors import CardineError


def _disabled():
    return bool(os.environ.get("CARDINE_NO_UPDATE_NOTICE")) or "CI" in os.environ


def _read(home):
    try:
        data = json.loads((Path(home) / ".cardine/update-check.json").read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        checked = datetime.fromisoformat(data["checkedAt"].replace("Z", "+00:00"))
        if checked.tzinfo is None or not isinstance(data["installed"], str):
            return None
        if data["latest"] is not None and not isinstance(data["latest"], str):
            return None
        if data["kind"] not in (None, "CLI-only", "template-changing"):
            return None
        return data
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return None


def refresh(home, installed):
    if _disabled():
        return
    from cardine.release.update import fetch_latest_release, urlopen

    latest = kind = None
    try:
        latest, kind = fetch_latest_release(installed, urlopen_fn=lambda request, **kwargs: urlopen(request, timeout=2))
    except Exception:
        pass  # A failed check is cached for the same interval as a successful one.
    data = {"checkedAt": datetime.now(timezone.utc).isoformat(), "installed": installed,
            "latest": latest, "kind": kind}
    directory = Path(home) / ".cardine"
    try:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".update-check-", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(data, stream)
            os.replace(temporary, directory / "update-check.json")
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    except OSError:
        pass


def notice(home, installed):
    if _disabled():
        return None
    data = _read(home)
    if not data or not data["latest"] or not data["kind"]:
        return None
    try:
        if semver_precedence_key(parse_semver(data["latest"])) <= semver_precedence_key(parse_semver(installed)):
            return None
    except (CardineError, TypeError):
        return None
    return (f"Cardine {data['latest']} is available (installed {installed}, "
            f"{data['kind']} release): cardine self-update --check")


def refresh_in_background(home, installed):
    if _disabled():
        return
    data = _read(home)
    if data:
        checked = datetime.fromisoformat(data["checkedAt"].replace("Z", "+00:00"))
        if datetime.now(timezone.utc) - checked < timedelta(hours=24):
            return
    try:
        process = subprocess.Popen([sys.executable, "-c",
                          "import sys; sys.path.insert(0, sys.argv.pop(1)); "
                          "from cardine.release.notice import refresh; refresh(sys.argv[1], sys.argv[2])",
                          str(Path(__file__).resolve().parents[2]), str(home), installed],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True, close_fds=True)
        threading.Thread(target=process.wait, daemon=True).start()
    except OSError:
        pass


if __name__ == "__main__":
    refresh(Path(sys.argv[1]), sys.argv[2])
