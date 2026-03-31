"""Formal runtime configuration for arbor-ddns."""

from __future__ import annotations

import json
from collections.abc import Mapping
from importlib.resources import files
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from arbor_ddns.util.json_merge import deep_merge

DEFAULTS_RESOURCE = files("arbor_ddns").joinpath("config_defaults/app.json")


class DiscoveryCommandSettings(BaseModel):
    """PVE command locations used by discovery backends."""

    model_config = ConfigDict(extra="forbid")

    pct_bin: str
    qm_bin: str
    shell_bin: str


class SystemdSettings(BaseModel):
    """systemd installation defaults."""

    model_config = ConfigDict(extra="forbid")

    systemctl_bin: str
    unit_dir: str

    @field_validator("systemctl_bin", "unit_dir")
    @classmethod
    def _validate_non_empty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("value must not be blank")
        return stripped

    def resolved_unit_dir(self) -> Path:
        """Return the configured systemd unit directory."""

        return Path(self.unit_dir).expanduser()


class WorkspaceScaffoldSystemdSettings(BaseModel):
    """Default systemd values used when scaffolding workspaces."""

    model_config = ConfigDict(extra="forbid")

    on_boot_sec: str
    on_unit_active_sec: str
    run_sync_after_apply: bool

    @field_validator("on_boot_sec", "on_unit_active_sec")
    @classmethod
    def _validate_non_empty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("value must not be blank")
        return stripped


class WorkspaceScaffoldApplySettings(BaseModel):
    """Default apply behavior used when scaffolding workspaces."""

    model_config = ConfigDict(extra="forbid")

    prune_managed_records: bool


class WorkspaceScaffoldSettings(BaseModel):
    """Starter workspace values written by `arbor-ddns init`."""

    model_config = ConfigDict(extra="forbid")

    config_version: int
    provider: str
    zone_name: str
    zone_id: str | None
    api_token_file: str
    default_ttl: int = Field(ge=1)
    default_proxied: bool
    systemd: WorkspaceScaffoldSystemdSettings
    apply: WorkspaceScaffoldApplySettings

    @field_validator("config_version")
    @classmethod
    def _validate_version(cls, value: int) -> int:
        if value < 1:
            raise ValueError("config_version must be >= 1")
        return value

    @field_validator("provider")
    @classmethod
    def _validate_provider(cls, value: str) -> str:
        stripped = value.strip()
        if stripped != "cloudflare":
            raise ValueError("only the cloudflare DNS provider is supported")
        return stripped

    @field_validator("zone_name", "api_token_file")
    @classmethod
    def _validate_non_empty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("value must not be blank")
        return stripped


class AppConfig(BaseModel):
    """Application runtime defaults."""

    model_config = ConfigDict(extra="forbid")

    config_version: int
    discovery: DiscoveryCommandSettings
    systemd: SystemdSettings
    workspace_scaffold: WorkspaceScaffoldSettings

    @field_validator("config_version")
    @classmethod
    def _validate_config_version(cls, value: int) -> int:
        if value < 1:
            raise ValueError("config_version must be >= 1")
        return value

    @classmethod
    def from_defaults(cls) -> AppConfig:
        """Load and validate package-shipped defaults."""

        return cls.model_validate(_read_defaults_mapping())

    @classmethod
    def from_file(cls, path: str | Path | None) -> AppConfig:
        """Load defaults plus an optional JSON override file."""

        if path is None:
            return cls.from_defaults()
        override = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(override, dict):
            raise TypeError("config JSON must be an object")
        merged = deep_merge(_read_defaults_mapping(), override)
        return cls.model_validate(merged)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> AppConfig:
        """Load defaults plus a mapping override."""

        merged = deep_merge(_read_defaults_mapping(), dict(data))
        return cls.model_validate(merged)


def _read_defaults_mapping() -> dict[str, Any]:
    payload = json.loads(DEFAULTS_RESOURCE.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("package defaults must be a JSON object")
    return payload
