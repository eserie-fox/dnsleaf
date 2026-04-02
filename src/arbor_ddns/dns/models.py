"""DNS domain models."""

from __future__ import annotations

from ipaddress import IPv4Address, IPv6Address, ip_address
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

AUTO_TTL = 1
TTLSetting = int | Literal["auto"]


class DNSRecord(BaseModel):
    """A provider-side DNS record."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    fqdn: str
    record_type: str
    value: str
    ttl: int = Field(ge=1)
    record_id: str | None = None
    proxied: bool | None = None

    @field_validator("record_type")
    @classmethod
    def _normalize_record_type(cls, value: str) -> str:
        normalized = value.upper().strip()
        if not normalized:
            raise ValueError("record_type must not be blank")
        return normalized

    @field_validator("fqdn", "provider")
    @classmethod
    def _validate_non_empty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("value must not be blank")
        return stripped

    @model_validator(mode="after")
    def _normalize_value(self) -> DNSRecord:
        self.value = _normalize_record_value(self.record_type, self.value)
        return self


class DesiredRecord(BaseModel):
    """Desired single-record DNS state."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    fqdn: str
    record_type: str
    value: str
    ttl: int = Field(ge=1)
    proxied: bool | None = None

    @field_validator("record_type")
    @classmethod
    def _normalize_record_type(cls, value: str) -> str:
        normalized = value.upper().strip()
        if not normalized:
            raise ValueError("record_type must not be blank")
        return normalized

    @field_validator("fqdn", "provider")
    @classmethod
    def _validate_non_empty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("value must not be blank")
        return stripped

    @model_validator(mode="after")
    def _normalize_value(self) -> DesiredRecord:
        if self.record_type not in {"A", "AAAA"}:
            raise ValueError("desired records currently only support A and AAAA")
        self.value = _normalize_record_value(self.record_type, self.value)
        return self


class PlannedChange(BaseModel):
    """A single DNS mutation or noop."""

    model_config = ConfigDict(extra="forbid")

    action: Literal["create", "update", "delete", "noop"]
    provider: str
    fqdn: str
    record_type: str
    reason: str
    current: DNSRecord | None = None
    desired: DesiredRecord | None = None


class SyncPlan(BaseModel):
    """The full plan for one DNS name and type."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    fqdn: str
    record_type: str
    desired: DesiredRecord | None = None
    changes: list[PlannedChange] = Field(default_factory=list)

    def has_changes(self) -> bool:
        """Return whether the plan contains non-noop work."""

        return any(change.action != "noop" for change in self.changes)


class ProviderVerification(BaseModel):
    """Successful provider verification details."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    token_file: str
    zone_id: str
    zone_name: str | None = None
    record_listing_succeeded: bool


def _normalize_record_value(record_type: str, value: str) -> str:
    if record_type not in {"A", "AAAA"}:
        return value.strip()

    parsed = ip_address(value)
    if record_type == "A" and not isinstance(parsed, IPv4Address):
        raise ValueError("A records require an IPv4 value")
    if record_type == "AAAA" and not isinstance(parsed, IPv6Address):
        raise ValueError("AAAA records require an IPv6 value")
    return str(parsed)


def normalize_ttl_setting(value: object) -> TTLSetting:
    """Normalize a config or CLI TTL value to an int or `auto`."""

    if isinstance(value, bool):
        raise ValueError("ttl must be a positive integer or 'auto'")
    if isinstance(value, int):
        if value < 1:
            raise ValueError("ttl must be a positive integer or 'auto'")
        return value
    if isinstance(value, str):
        stripped = value.strip().lower()
        if stripped == "auto":
            return "auto"
        if not stripped:
            raise ValueError("ttl must be a positive integer or 'auto'")
        try:
            parsed = int(stripped)
        except ValueError as exc:
            raise ValueError("ttl must be a positive integer or 'auto'") from exc
        if parsed < 1:
            raise ValueError("ttl must be a positive integer or 'auto'")
        return parsed
    raise ValueError("ttl must be a positive integer or 'auto'")


def resolve_ttl_setting(value: TTLSetting | int) -> int:
    """Return the provider-facing integer TTL."""

    normalized = normalize_ttl_setting(value)
    if normalized == "auto":
        return AUTO_TTL
    return normalized


def cloudflare_effective_ttl(ttl: TTLSetting | int, proxied: bool | None) -> int:
    """Return the effective Cloudflare TTL for the intended proxied state."""

    if proxied is True:
        return AUTO_TTL
    return resolve_ttl_setting(ttl)
