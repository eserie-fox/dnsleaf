"""Pure, conservative correlation of QGA and Windows IPv6 observations."""

from __future__ import annotations

import re
from ipaddress import IPv6Address

from dnsleaf.discovery.models import (
    AddressCandidate,
    CandidateDisposition,
    DiscoveryResult,
    SelectionResult,
    WindowsAddressEvidence,
    WindowsMetadataResult,
)
from dnsleaf.models import IPAddressFamily, SelectedAddress
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


def select_windows_dhcpv6(
    result: DiscoveryResult,
    *,
    usable: list[AddressCandidate],
    filtered_out: list[CandidateDisposition],
    evidence: WindowsMetadataResult | None,
) -> SelectionResult:
    """Require consistent inventories before asserting DHCP eligibility or uniqueness."""

    selection = SelectionResult(
        target=result.target,
        family=IPAddressFamily.IPV6,
        policy="windows-dhcpv6",
        status="ambiguous",
        remaining_candidates=usable,
        filtered_out=filtered_out,
        supplementary=evidence,
        reason="Windows DHCPv6 evidence is required; run the opted-in metadata probe",
    )
    if evidence is None:
        return selection
    if evidence.status == "error":
        selection.status = "no_candidate"
        selection.reason = f"supplementary Windows metadata failed: {evidence.error}"
        return selection
    if result.parsing_issues:
        selection.reason = "incomplete QGA address parsing; cannot establish DHCPv6 uniqueness"
        return selection
    try:
        pairs = _correlate(usable, evidence)
    except ValueError as exc:
        selection.reason = f"Windows DHCPv6 evidence correlation refused: {exc}"
        return selection

    eligible = []
    for candidate, observation in pairs:
        reason = observation.ineligible_reason
        if reason is None:
            eligible.append(candidate)
        else:
            selection.not_selected.append(CandidateDisposition(candidate=candidate, reason=reason))
    selection.remaining_candidates = eligible
    if not eligible:
        selection.status = "no_candidate"
        selection.reason = (
            "consistent evidence contains no eligible Windows-reported DHCPv6 address"
        )
    elif len(eligible) > 1:
        selection.reason = "multiple eligible Windows-reported DHCPv6 addresses; refusing to guess"
    else:
        candidate = eligible[0]
        selection.status = "selected"
        selection.reason = "unique eligible Windows-reported DHCPv6 address corroborated by QGA"
        selection.selected = SelectedAddress(
            target=result.target,
            family=IPAddressFamily.IPV6,
            address=candidate.address,
            prefix_length=candidate.prefix_length,
            interface=candidate.interface,
            selection_policy="windows-dhcpv6",
            source=candidate.source,
            reason=selection.reason,
        )
    return selection
