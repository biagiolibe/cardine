"""Pure snapshot access and digests, independent of record parsing and writers."""
from __future__ import annotations

import hashlib
import json
from cardine.shared.errors import CardineError


def contract_hash(contract):
    if contract is None:
        return None
    encoded = json.dumps(contract, sort_keys=True, separators=(",", ":")).encode('utf-8')
    return 'sha256:' + hashlib.sha256(encoded).hexdigest()


# Human intent is frozen at creation and shared by all runtime readers.
HUMAN_CONTRACT_FIELDS = ("dependencies", "title", "priority", "phase", "origin",
                         "deliverables", "authority", "recordPath")


def frozen_human_fields(state):
    """Require a complete snapshot without ever recovering missing intent from prose.

    Old snapshots remain structurally readable by the state validator. Audit
    diagnoses them, and runtime consumers require these fields.
    Only an explicit contract update may complete them.
    """
    contract = state.get("contract", {})
    missing = [key for key in HUMAN_CONTRACT_FIELDS if key not in contract]
    if missing:
        raise CardineError("incomplete contract snapshot (missing " + ", ".join(missing)
                           + f"); run cardine task contract update {state['task_id']}")
    return {key: contract[key] for key in HUMAN_CONTRACT_FIELDS}


def snapshot_record_path(project_root, human):
    """Resolve the frozen path, including the exact lifecycle archive move."""
    from pathlib import Path
    root = Path(project_root).resolve()
    path = (root / human["recordPath"]).resolve()
    if not path.is_relative_to(root):
        raise CardineError("contract record path escapes the project")
    if not path.exists() and path.parent.name != "done":
        archive = path.parent / "done" / path.name
        if archive.is_file() and archive.resolve().is_relative_to(root):
            return archive.resolve()
    return path
