from __future__ import annotations

import json
from dataclasses import dataclass
from importlib.resources import files
from typing import Any

from watchtracker import __version__

STANDARD_CAPABILITIES = ("scalar-v1",)
ADVANCED_CAPABILITIES = ("scalar-v1", "advanced-hybrid-v1")


@dataclass(frozen=True)
class BuildManifest:
    """Immutable capabilities compiled into one PMT distribution."""

    application: str
    base_version: str
    distribution_flavor: str
    recommendation_capabilities: tuple[str, ...]
    advanced_pack_version: str | None

    def as_dict(self, *, base_version: str | None = None) -> dict[str, Any]:
        return {
            "application": self.application,
            "base_version": base_version or self.base_version,
            "distribution_flavor": self.distribution_flavor,
            "recommendation_capabilities": list(self.recommendation_capabilities),
            "advanced_pack_version": self.advanced_pack_version,
        }


def parse_build_manifest(payload: Any) -> BuildManifest:
    """Validate the signed-off distribution boundary, failing closed."""

    if not isinstance(payload, dict):
        raise RuntimeError("The packaged build manifest is invalid.")
    capabilities = payload.get("recommendation_capabilities")
    if not isinstance(capabilities, list) or not all(
        isinstance(item, str) for item in capabilities
    ):
        raise RuntimeError("The packaged build manifest is invalid.")
    manifest = BuildManifest(
        application=str(payload.get("application") or ""),
        base_version=str(payload.get("base_version") or ""),
        distribution_flavor=str(payload.get("distribution_flavor") or ""),
        recommendation_capabilities=tuple(capabilities),
        advanced_pack_version=payload.get("advanced_pack_version"),
    )
    common_valid = (
        manifest.application == "personal-media-tracker"
        and manifest.base_version == __version__
        and len(manifest.recommendation_capabilities)
        == len(set(manifest.recommendation_capabilities))
    )
    standard_valid = (
        manifest.distribution_flavor == "standard"
        and manifest.recommendation_capabilities == STANDARD_CAPABILITIES
        and manifest.advanced_pack_version is None
    )
    advanced_valid = (
        manifest.distribution_flavor == "recommendations-beta"
        and manifest.recommendation_capabilities == ADVANCED_CAPABILITIES
        and isinstance(manifest.advanced_pack_version, str)
        and bool(manifest.advanced_pack_version.strip())
    )
    if not common_valid or not (standard_valid or advanced_valid):
        raise RuntimeError("The packaged build manifest declares unsupported capabilities.")
    return manifest


def load_build_manifest() -> BuildManifest:
    resource = files("watchtracker").joinpath("distribution_manifest.json")
    return parse_build_manifest(json.loads(resource.read_text(encoding="utf-8")))


BUILD_MANIFEST = load_build_manifest()
