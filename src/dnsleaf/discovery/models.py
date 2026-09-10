"""Models used by discovery backends and selectors."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from dnsleaf.models import IPAddressFamily, SelectedAddress, TargetRef
from dnsleaf.util.ip import normalize_ip


class AddressCandidate(BaseModel):
    """A discovered IP candidate."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    family: IPAddressFamily
    interface: str
    address: str
    prefix_length: int = Field(ge=0, le=128)
    source: str
    scope: str | None = None
    flags: list[str] = Field(default_factory=list)

    @field_validator("address")
    @classmethod
    def _normalize_address(cls, value: str) -> str:
        return normalize_ip(value)

    @model_validator(mode="after")
    def _validate_prefix_for_family(self) -> AddressCandidate:
        if self.family is IPAddressFamily.IPV4 and self.prefix_length > 32:
            raise ValueError("ipv4 prefix length must be <= 32")
        return self

    @property
    def cidr(self) -> str:
        """Return the normalized CIDR representation."""

        return f"{self.address}/{self.prefix_length}"

    @property
    def record_type(self) -> str:
        """Return the DNS record type for this candidate."""

        return self.family.record_type


class CandidateDisposition(BaseModel):
    """Information about a candidate that was filtered or not selected."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    candidate: AddressCandidate
    reason: str


class DiscoveryResult(BaseModel):
    """Raw candidate discovery output."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    target: TargetRef
    backend: str
    candidates: list[AddressCandidate] = Field(default_factory=list)
    error: str | None = None

    @property
    def ok(self) -> bool:
        """Return whether discovery succeeded."""

        return self.error is None


class SelectionResult(BaseModel):
    """Address selection outcome for one family."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    target: TargetRef
    family: IPAddressFamily
    policy: str
    status: Literal["selected", "ambiguous", "no_candidate"]
    selected: SelectedAddress | None = None
    remaining_candidates: list[AddressCandidate] = Field(default_factory=list)
    filtered_out: list[CandidateDisposition] = Field(default_factory=list)
    not_selected: list[CandidateDisposition] = Field(default_factory=list)
    reason: str
