"""Shared domain models."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from arbor_ddns.util.ip import normalize_ip, record_type_for_family


class TargetKind(StrEnum):
    """Supported PVE guest kinds."""

    LXC = "lxc"
    VM = "vm"


class EntrySourceKind(StrEnum):
    """Supported workspace entry source kinds."""

    LXC = "lxc"
    VM = "vm"
    STATIC = "static"

    def to_target_kind(self) -> TargetKind:
        """Return the dynamic discovery target kind."""

        if self is EntrySourceKind.LXC:
            return TargetKind.LXC
        if self is EntrySourceKind.VM:
            return TargetKind.VM
        raise ValueError("static entries do not map to a discovery target")


class IPAddressFamily(StrEnum):
    """Concrete IP families supported by discovery and sync."""

    IPV4 = "ipv4"
    IPV6 = "ipv6"

    @property
    def record_type(self) -> str:
        """Return the DNS record type for this family."""

        return record_type_for_family(self.value)


class EntryAddressFamily(StrEnum):
    """Workspace entry family intent."""

    IPV4 = "ipv4"
    IPV6 = "ipv6"
    BOTH = "both"

    def concrete_families(self) -> tuple[IPAddressFamily, ...]:
        """Return the concrete record families this entry manages."""

        if self is EntryAddressFamily.IPV4:
            return (IPAddressFamily.IPV4,)
        if self is EntryAddressFamily.IPV6:
            return (IPAddressFamily.IPV6,)
        return (IPAddressFamily.IPV4, IPAddressFamily.IPV6)


class TargetRef(BaseModel):
    """Identity of a discoverable guest."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: TargetKind
    id: int = Field(ge=1)


class SelectedAddress(BaseModel):
    """Address selected for DNS synchronization."""

    model_config = ConfigDict(extra="forbid")

    target: TargetRef
    family: IPAddressFamily
    address: str
    prefix_length: int = Field(ge=0, le=128)
    interface: str
    selection_policy: str
    source: str
    reason: str

    @field_validator("address")
    @classmethod
    def _normalize_address(cls, value: str) -> str:
        return normalize_ip(value)

    @model_validator(mode="after")
    def _validate_prefix_for_family(self) -> SelectedAddress:
        if self.family is IPAddressFamily.IPV4 and self.prefix_length > 32:
            raise ValueError("ipv4 prefix length must be <= 32")
        return self

    @property
    def record_type(self) -> str:
        """Return the DNS record type for this selected address."""

        return self.family.record_type
