"""Shared constants helpers extracted from the legacy CLI."""

from __future__ import annotations

from cardine.shared.layout import PRODUCT_NAMES

import re
from pathlib import Path


# Default-value exports for the legacy adapter; readers use names() at call time.
MANIFEST_PATH = PRODUCT_NAMES.manifest_path

VALIDATION_EVIDENCE_SCHEMA_PATH = Path("schemas/validation-evidence-v1.schema.json")

VALIDATION_EXIT_PASSED = 0

VALIDATION_EXIT_PENDING = 1

VALIDATION_EXIT_FAILED = 2

CAPABILITY_CATALOG_VERSION = 1

CAPABILITY_CATALOG_PATH = Path("capabilities/catalog-v1.json")

BASELINES_PATH = PRODUCT_NAMES.baselines_path


# Bump only when the manifest's shape or semantics change in a way that an
# older CLI cannot safely read. Add backward-compatible fields without a bump.
PROTOCOL_VERSION = 2

LEGACY_PROTOCOL_VERSION = 1

WORKFLOW_MODES = ("single",)

INSTALLATION_FORMS = ("managed-copy", "shared-source", "declaration-only")

# Profiles whose managed copies are verified byte-for-byte even when a file
# carries capability markers. A consumer profile verifies marker-bearing files by
# their marker regions, so project text outside the blocks never fails it.
STRICT_DIGEST_PROFILES = frozenset({"cardine-self-hosting"})

# Managed paths whose body a project owns or extends by design. A digest check
# never applies to them.
PROJECT_EDITABLE_MANAGED_PATHS = frozenset(
    {
        "AGENTS.md",
        "CLAUDE.md",
        "docs/ARCHITECTURE_DECISIONS.md",
        "docs/EXECUTION_EVIDENCE_PROFILE.md",
        "tasks/QUEUE.md",
    }
)

INSTALLATION_STATES = ("INSTALLED", "MISSING", "DRIFTED", "NOT_APPLICABLE")

HOST_ACTIVATION_STATES = ("ENFORCED", "ADVISORY", "UNSUPPORTED", "UNVERIFIED", "NOT_APPLICABLE")

VERIFICATION_STATES = ("PASS", "ADVISORY", "UNVERIFIED", "NOT_APPLICABLE", "FAIL")

AUDIT_STATES = VERIFICATION_STATES

LATEST_RELEASE_URL = "https://api.github.com/repos/biagiolibe/cardine/releases/latest"

LATEST_RELEASE_TIMEOUT_SECONDS = 3.0

LATEST_RELEASE_RESPONSE_LIMIT = 1024 * 1024

SELF_CHECK_UPDATE_AVAILABLE = 10

SELF_CHECK_UNKNOWN = 11

# Protocol v2 introduces capability declarations but keeps them optional for
# legacy locked projects. A future protocol can make the declaration explicit
# by advancing this boundary without changing the compatibility result below.
CAPABILITY_DECLARATION_REQUIRED_PROTOCOL = 3


MARKER_BEGIN = "CARDINE:BEGIN"

MARKER_END = "<!-- CARDINE:END -->"

CLAUDE_AGENTS_POINTER_MARKER = "<!-- CARDINE:CLAUDE-AGENTS-POINTER v1 -->"

CAPABILITY_MARKER = re.compile(rf"<!-- {MARKER_BEGIN} capability=([a-z0-9-]+) v(\d+) -->")

MARKED_BLOCK = re.compile(
    rf"<!-- {MARKER_BEGIN} capability=([a-z0-9-]+) v(\d+) -->\n?.*?{re.escape(MARKER_END)}",
    re.DOTALL,
)

ENTRY_ROUTER_PATH = Path("docs/workflows/ENTRY_ROUTER.md")

ENTRY_ROUTER_MAP_PATH = Path("docs/workflows/ENTRY_ROUTER_MAP.json")

ENTRY_ROUTER_OVERLAYS = {
    "AGENTS.md": Path("docs/workflows/ENTRY_ROUTER.AGENTS.overlay.md"),
    "CLAUDE.md": Path("docs/workflows/ENTRY_ROUTER.CLAUDE.overlay.md"),
}

ENTRY_ROUTER_BUDGET_BYTES = 2048

ENTRY_ROUTER_ROUTES = {
    "status-design": "docs/workflows/STATUS_DESIGN.md",
    "proceed": "docs/workflows/IMPLEMENTATION.md",
    "review": "docs/workflows/REVIEW.md",
    "address-review": "docs/workflows/REMEDIATION.md",
    "lifecycle-accept": "docs/LIFECYCLE_ORCHESTRATION.md",
    "audit": "docs/AUDIT_PROMPT_READ_ONLY.md",
}

ENTRY_ROUTER_SAFEGUARDS = {
    "status-design": ("status",),
    "proceed": ("git status --short", "validation"),
    "review": ("approve", "changes_requested"),
    "address-review": ("changes_requested", "in_progress"),
    "lifecycle-accept": ("lifecycle", "accept"),
    "audit": ("audit",),
}

CONTEXT_SIZE_CONFIG_PATH = PRODUCT_NAMES.context_size_config_path

CONTEXT_SIZE_POLICY_PATH = Path("docs/CONTEXT_READING_POLICY.md")

CONTEXT_PHASE_READS_BLOCK = re.compile(
    rf"<!-- {MARKER_BEGIN} capability=phase-reads v\d+ -->(.*?){re.escape(MARKER_END)}", re.DOTALL
)

CONTEXT_PHASE_READ_LINE = re.compile(r"^- At ([^:\n]+): (.+)$", re.MULTILINE)

CONTEXT_SIZE_ROLES = {
    "single": ("status", "design", "implementation", "review", "remediation", "lifecycle"),
}

USAGE_HOSTS = ("codex", "claude")

USAGE_PRIVACY_BOUNDARY = (
    "Privacy: reads only timestamps, session metadata, and token counters; "
    "never prints, stores, or transmits message text, tool arguments, file contents, or paths."
)

USAGE_ADAPTER_NOTES = {
    "codex": "Codex rollout JSONL adapter (observed token_count event schema, 2026-10-03).",
    "claude": "Claude Code project JSONL adapter (observed assistant usage schema, 2026-10-04; input = input_tokens + cache_read_input_tokens + cache_creation_input_tokens).",
}

TASK_IDENTITY_PATH = PRODUCT_NAMES.task_identity_path

PROJECT_DECLARATION_PATH = PRODUCT_NAMES.project_declaration_path
