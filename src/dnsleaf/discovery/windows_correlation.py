"""Correlate Windows observations with raw QGA and normalize their proven facts."""

from __future__ import annotations

import re
from ipaddress import IPv6Address
from typing import Literal

from dnsleaf.discovery.models import (
    AddressCandidate,
    AddressEvidence,
    CorrelatedEvidence,
    DiscoveryResult,
)
from dnsleaf.discovery.windows import WindowsAddressEvidence, WindowsMetadataResult
from dnsleaf.models import IPAddressFamily
from dnsleaf.util.ip import unusable_ipv6_reason


def _hardware_identity(value: str | None) -> str:
    if (
        value is None
        or re.fullmatch(
            r"(?:[0-9a-fA-F]{12}|(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}|(?:[0-9a-fA-F]{2}-){5}[0-9a-fA-F]{2})",
            value,
        )
        is None
    ):
        raise ValueError("missing or invalid hardware/MAC identity; aliases alone cannot correlate")
    normalized = value.replace(":", "").replace("-", "").lower()
    if normalized in {"000000000000", "ffffffffffff"}:
        raise ValueError("unusable hardware/MAC identity")
    return normalized


def _correlate(
    usable: list[AddressCandidate], evidence: WindowsMetadataResult
) -> list[tuple[AddressCandidate, WindowsAddressEvidence]]:
    raw: dict[tuple[str, str], AddressCandidate] = {}
    raw_interfaces: dict[str, str] = {}
    for candidate in usable:
        mac = _hardware_identity(candidate.hardware_address)
        if mac in raw_interfaces and raw_interfaces[mac] != candidate.interface:
            raise ValueError("QGA reports the same hardware identity on different interfaces")
        raw_interfaces[mac] = candidate.interface
        key = (mac, candidate.address)
        if key in raw and raw[key] != candidate:
            raise ValueError(f"conflicting QGA observations for {candidate.address}")
        raw[key] = candidate

    windows: dict[tuple[str, str], WindowsAddressEvidence] = {}
    indices: dict[int, str] = {}
    hardware: dict[str, int] = {}
    for observation in evidence.addresses:
        if unusable_ipv6_reason(IPv6Address(observation.address)) is not None:
            continue
        mac = _hardware_identity(observation.hardware_address)
        index = observation.interface_index
        if (index in indices and indices[index] != mac) or (
            mac in hardware and hardware[mac] != index
        ):
            raise ValueError("inconsistent Windows InterfaceIndex/hardware identity")
        indices[index] = mac
        hardware[mac] = index
        key = (mac, observation.address)
        if key in windows and windows[key] != observation:
            raise ValueError(f"conflicting Windows metadata for {observation.address}")
        windows[key] = observation

    missing = raw.keys() - windows.keys()
    extra = windows.keys() - raw.keys()
    if missing or extra:
        detail = []
        if missing:
            detail.append(
                "QGA addresses missing matching Windows evidence: "
                + ", ".join(sorted(address for _, address in missing))
            )
        if extra:
            detail.append(
                "Windows addresses missing matching QGA evidence: "
                + ", ".join(sorted(address for _, address in extra))
            )
        raise ValueError("; ".join(detail) + "; snapshots or interface identity may have changed")
    pairs = []
    for key, candidate in raw.items():
        observation = windows[key]
        if candidate.prefix_length != observation.prefix_length:
            raise ValueError(f"QGA/Windows prefix mismatch for {candidate.address}")
        pairs.append((candidate, observation))
    return pairs


def correlate_windows_evidence(
    result: DiscoveryResult, metadata: WindowsMetadataResult
) -> CorrelatedEvidence:
    """Normalize only after the full relevant inventory has been corroborated."""
    if metadata.status == "error":
        return CorrelatedEvidence(
            source="windows-powershell",
            status="error",
            error_stage=metadata.error_stage,
            reason=metadata.error or "supplementary acquisition failed",
        )
    try:
        if result.parsing_issues:
            raise ValueError(
                "incomplete QGA address parsing; cannot establish evidence completeness"
            )
        usable = [
            c
            for c in result.candidates
            if c.family is IPAddressFamily.IPV6
            and unusable_ipv6_reason(IPv6Address(c.address)) is None
        ]
        pairs = _correlate(usable, metadata)
    except ValueError as exc:
        return CorrelatedEvidence(
            source="windows-powershell",
            status="incomplete",
            error_stage="correlation",
            reason=str(exc),
        )
    observations = []
    for candidate, native in pairs:
        origin: Literal["dhcp", "non_dhcp", "unknown"]
        if native.prefix_origin == "Dhcp" and native.suffix_origin == "Dhcp":
            origin = "dhcp"
        elif native.prefix_origin == "Other" or native.suffix_origin == "Other":
            origin = "unknown"
        else:
            origin = "non_dhcp"
        observations.append(
            AddressEvidence(
                candidate=candidate,
                interface_identity=_hardware_identity(native.hardware_address),
                dhcp_origin=origin,
                preferred=native.address_state == "Preferred",
                skip_as_source=native.skip_as_source,
                provenance="windows-powershell",
                source_details={
                    "PrefixOrigin": native.prefix_origin,
                    "SuffixOrigin": native.suffix_origin,
                    "AddressState": native.address_state,
                },
            )
        )
    return CorrelatedEvidence(
        source="windows-powershell",
        status="complete",
        observations=observations,
        reason="address and interface inventories corroborated",
    )
