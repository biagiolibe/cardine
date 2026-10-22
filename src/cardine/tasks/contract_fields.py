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


# These fields are creation input. Readers migrate separately in task 080.
HUMAN_CONTRACT_FIELDS = ("dependencies", "title", "priority", "phase", "origin",
                         "deliverables", "authority", "recordPath")


def frozen_human_fields(state):
    """Require a complete snapshot without ever recovering missing intent from prose.

    Old snapshots remain structurally readable by the pre-080 readers. Audit
    diagnoses them, and this accessor is the strict boundary for new consumers.
    Only an explicit contract update may complete them.
    """
    contract = state.get("contract", {})
    missing = [key for key in HUMAN_CONTRACT_FIELDS if key not in contract]
    if missing:
        raise CardineError("incomplete contract snapshot (missing " + ", ".join(missing)
                           + f"); run cardine task contract update {state['task_id']}")
    return {key: contract[key] for key in HUMAN_CONTRACT_FIELDS}

