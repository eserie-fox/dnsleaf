"""Outside-workspace defaults for dnsleaf."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from dnsleaf.config.merge import deep_merge
from dnsleaf.config.resources import read_json_mapping
from dnsleaf.config.shared import DiscoveryCommandPaths
from dnsleaf.logging.config import DnsleafLoggingConfig

OUTSIDE_WORKSPACE_RESOURCE_SPEC = "pkg://dnsleaf/config_defaults/outside_workspace.json"


class OutsideWorkspaceConfig(BaseModel):
    """Internal defaults used before a workspace context is available."""

    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    paths: DiscoveryCommandPaths
    dnsleaf_logging: DnsleafLoggingConfig

    @classmethod
    def from_defaults(cls) -> OutsideWorkspaceConfig:
        """Load and validate package-shipped outside-workspace defaults."""

        return cls.model_validate(_read_defaults_mapping())

    @classmethod
    def from_file(cls, path: str | Path | None) -> OutsideWorkspaceConfig:
        """Load outside-workspace defaults plus an optional JSON override file."""

        if path is None:
            return cls.from_defaults()
        override = read_json_mapping(Path(path))
        merged = deep_merge(_read_defaults_mapping(), override)
        return cls.model_validate(merged)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> OutsideWorkspaceConfig:
        """Load outside-workspace defaults plus a mapping override."""

        merged = deep_merge(_read_defaults_mapping(), dict(data))
        return cls.model_validate(merged)


def _read_defaults_mapping() -> dict[str, Any]:
    return read_json_mapping(OUTSIDE_WORKSPACE_RESOURCE_SPEC)
