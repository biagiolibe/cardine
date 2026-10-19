"""Helpers extracted from the legacy CLI; see the module split plan."""

from __future__ import annotations

from cardine.shared.constants import LEGACY_PROTOCOL_VERSION
from cardine.shared.constants import PROTOCOL_VERSION
from cardine.shared.errors import CardineError


def check_protocol_compatibility(manifest: dict[str, object]) -> int:
    protocol_version = manifest.get("protocolVersion", LEGACY_PROTOCOL_VERSION)
    if type(protocol_version) is not int:
        raise CardineError("manifest protocolVersion must be an integer")
    if protocol_version < 1:
        raise CardineError("manifest protocolVersion must be a positive integer")
    if protocol_version > PROTOCOL_VERSION:
        raise CardineError(
            f"manifest protocolVersion {protocol_version} is newer than this Cardine CLI "
            f"supports ({PROTOCOL_VERSION}); update your Cardine checkout"
        )
    return protocol_version
