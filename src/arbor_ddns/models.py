"""Shared domain models."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from arbor_ddns.util.ip import normalize_ipv6


class TargetKind(StrEnum):
    """Supported PVE guest kinds."""

    LXC = "lxc"
    VM = "vm"


class TargetRef(BaseModel):
    """Identity of a discoverable guest."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: TargetKind
    id: int = Field(ge=1)


class InventoryEntry(BaseModel):
    """A single sync target definition."""

    model_config = ConfigDict(extra="forbid")

    kind: TargetKind
    id: int = Field(ge=1)
    fqdn: str
    provider: str
    selection_policy: str
    enabled: bool

    @field_validator("fqdn", "provider", "selection_policy")
    @classmethod
    def _validate_non_empty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("value must not be blank")
        return stripped

    def to_target_ref(self) -> TargetRef:
        """Return the target identity for discovery."""

        return TargetRef(kind=self.kind, id=self.id)


class SelectedAddress(BaseModel):
    """Address selected for DNS AAAA synchronization."""

    model_config = ConfigDict(extra="forbid")

    target: TargetRef
    address: str
    prefix_length: int = Field(ge=0, le=128)
    interface: str
    selection_policy: str
    source: str
    reason: str

    @field_validator("address")
    @classmethod
    def _normalize_address(cls, value: str) -> str:
        return normalize_ipv6(value)
