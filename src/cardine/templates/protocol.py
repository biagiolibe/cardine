"""Helpers extracted from the legacy CLI; see the module split plan."""

from __future__ import annotations

from cardine.shared.constants import LEGACY_PROTOCOL_VERSION
from cardine.shared.constants import PROTOCOL_VERSION
from cardine.shared.errors import MeridianError


def check_protocol_compatibility(manifest: dict[str, object]) -> int:
    protocol_version = manifest.get("protocolVersion", LEGACY_PROTOCOL_VERSION)
    if type(protocol_version) is not int:
        raise MeridianError("manifest protocolVersion must be an integer")
    if protocol_version < 1:
        raise MeridianError("manifest protocolVersion must be a positive integer")
    if protocol_version > PROTOCOL_VERSION:
        raise MeridianError(
            f"manifest protocolVersion {protocol_version} is newer than this Meridian CLI "
            f"supports ({PROTOCOL_VERSION}); update your Meridian checkout"
        )
    return protocol_version
