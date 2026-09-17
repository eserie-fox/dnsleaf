"""Shared config sub-models used across workspace and outside-workspace config."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from dnsleaf.config.merge import deep_merge
from dnsleaf.config.resources import read_json_mapping


class DiscoveryCommandPaths(BaseModel):
    """Shared discovery command locations."""

    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    pct_bin: str
    qm_bin: str
    shell_bin: str

    @field_validator("pct_bin", "qm_bin", "shell_bin")
    @classmethod
    def _validate_non_empty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("command paths must not be blank")
        return stripped


class DiscoveryConfig(BaseModel):
    """Limits shared by all address discovery commands."""

    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    timeout_seconds: float = Field(gt=0, allow_inf_nan=False)

    @classmethod
    def from_defaults(cls) -> DiscoveryConfig:
        """Load package defaults."""
        return cls.from_mapping({})

    @classmethod
    def from_file(cls, path: str | Path) -> DiscoveryConfig:
        """Load defaults plus a JSON override."""
        return cls.from_mapping(read_json_mapping(path))

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> DiscoveryConfig:
        """Merge one override into the shared default limit."""
        return cls.model_validate(
            deep_merge(read_json_mapping("pkg://dnsleaf/config_defaults/discovery.json"), data)
        )
