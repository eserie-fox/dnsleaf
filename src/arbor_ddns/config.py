"""Formal runtime configuration for arbor_ddns."""

from __future__ import annotations

import json
from collections.abc import Mapping
from importlib.resources import files
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from arbor_ddns.inventory import Inventory
from arbor_ddns.util.json_merge import deep_merge

DEFAULTS_RESOURCE = files("arbor_ddns").joinpath("config_defaults/app.json")


class DiscoveryCommandSettings(BaseModel):
    """PVE command locations used by discovery backends."""

    model_config = ConfigDict(extra="forbid")

    pct_bin: str
    qm_bin: str
    shell_bin: str


class DNSSettings(BaseModel):
    """Global DNS synchronization settings."""

    model_config = ConfigDict(extra="forbid")

    default_ttl: int = Field(ge=1)


class AliDNSProviderConfig(BaseModel):
    """AliDNS provider raw configuration."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool
    access_key_id: str | None
    access_key_secret: str | None
    region_id: str | None


class CloudflareProviderConfig(BaseModel):
    """Cloudflare provider raw configuration."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool
    api_token: str | None
    zone_id: str | None


class ProviderSettings(BaseModel):
    """Provider configuration section."""

    model_config = ConfigDict(extra="forbid")

    alidns: AliDNSProviderConfig
    cloudflare: CloudflareProviderConfig


class AppConfig(BaseModel):
    """Application configuration."""

    model_config = ConfigDict(extra="forbid")

    config_version: int
    discovery: DiscoveryCommandSettings
    dns: DNSSettings
    providers: ProviderSettings
    inventory: Inventory

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

    def provider_config(
        self,
        provider_name: str,
    ) -> AliDNSProviderConfig | CloudflareProviderConfig:
        """Return provider-specific raw config by name."""

        if provider_name == "alidns":
            return self.providers.alidns
        if provider_name == "cloudflare":
            return self.providers.cloudflare
        raise KeyError(f"unknown provider: {provider_name}")


def _read_defaults_mapping() -> dict[str, Any]:
    payload = json.loads(DEFAULTS_RESOURCE.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("package defaults must be a JSON object")
    return payload
