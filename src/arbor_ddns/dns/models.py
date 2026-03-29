"""DNS domain models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from arbor_ddns.util.ip import normalize_ipv6


class DNSRecord(BaseModel):
    """A provider-side DNS record."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    fqdn: str
    record_type: str
    value: str
    ttl: int = Field(ge=1)
    record_id: str | None = None

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

    @field_validator("value")
    @classmethod
    def _normalize_value(cls, value: str) -> str:
        return normalize_ipv6(value)


class DesiredRecord(BaseModel):
    """Desired single-record DNS state."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    fqdn: str
    record_type: str
    value: str
    ttl: int = Field(ge=1)

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

    @field_validator("value")
    @classmethod
    def _normalize_value(cls, value: str) -> str:
        return normalize_ipv6(value)


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
