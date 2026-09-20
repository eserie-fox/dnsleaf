"""Models used by discovery backends and selectors."""

from __future__ import annotations

from ipaddress import IPv6Address
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
    hardware_address: str | None = None
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
    error_stage: Literal["execution", "parsing"] | None = None
    parsing_issues: list[str] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Return whether discovery succeeded."""

        return self.error is None


class WindowsAddressEvidence(BaseModel):
    """One Windows-reported IPv6 observation, before correlation with QGA."""

    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    address: str = Field(alias="IPAddress")
    prefix_length: int = Field(alias="PrefixLength", ge=0, le=128)
    interface_index: int = Field(alias="InterfaceIndex", ge=1)
    interface_alias: str = Field(alias="InterfaceAlias")
    hardware_address: str | None = Field(alias="HardwareAddress")
    prefix_origin: Literal["Other", "Manual", "WellKnown", "Dhcp", "RouterAdvertisement"] = Field(
        alias="PrefixOrigin"
    )
    suffix_origin: Literal["Other", "Manual", "WellKnown", "Dhcp", "Link", "Random"] = Field(
        alias="SuffixOrigin"
    )
    address_state: Literal["Invalid", "Tentative", "Duplicate", "Deprecated", "Preferred"] = Field(
        alias="AddressState"
    )
    skip_as_source: bool = Field(alias="SkipAsSource")

    @field_validator("address")
    @classmethod
    def _normalize_ipv6(cls, value: str) -> str:
        address = IPv6Address(value)
        if "%" in value and not address.is_link_local:
            raise ValueError("scope identifier on non-link-local IPv6")
        return str(address).split("%", 1)[0]

    @property
    def ineligible_reason(self) -> str | None:
        """Explain policy exclusion without inferring lifetime or reachability."""

        if self.prefix_origin != "Dhcp" or self.suffix_origin != "Dhcp":
            return f"Windows origins are {self.prefix_origin}/{self.suffix_origin}, not Dhcp/Dhcp"
        if self.address_state != "Preferred":
            return f"Windows AddressState is {self.address_state}, not Preferred"
        if self.skip_as_source:
            return "Windows SkipAsSource is true"
        return None


class WindowsMetadataResult(BaseModel):
    """Supplementary probe outcome; it never replaces the raw QGA inventory."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    source: Literal["qm_guest_exec"] = "qm_guest_exec"
    status: Literal["ok", "error"]
    addresses: list[WindowsAddressEvidence] = Field(default_factory=list)
    error_stage: Literal["execution", "protocol"] | None = None
    error: str | None = None


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
    supplementary: WindowsMetadataResult | None = None
