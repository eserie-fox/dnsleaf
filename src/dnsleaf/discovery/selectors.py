"""Address selection policies."""

from __future__ import annotations

from ipaddress import IPv4Address, IPv6Address, ip_address

from dnsleaf.discovery.models import (
    AddressCandidate,
    CandidateDisposition,
    DiscoveryResult,
    SelectionResult,
)
from dnsleaf.models import IPAddressFamily, SelectedAddress
from dnsleaf.util.ip import (
    has_embedded_eui64,
    looks_temporary_or_privacy,
    unusable_ipv4_reason,
    unusable_ipv6_reason,
)

_UNUSABLE_IPV6_FLAGS = {"dadfailed", "deprecated", "tentative"}


def select_address(
    result: DiscoveryResult,
    *,
    family: IPAddressFamily,
    policy: str = "default",
) -> SelectionResult:
    """Select the best DNS address for one family from discovery candidates."""

    if policy != "default":
        raise ValueError(f"unsupported selection policy: {policy}")

    candidates = [candidate for candidate in result.candidates if candidate.family is family]
    filtered_out: list[CandidateDisposition] = []
    usable: list[AddressCandidate] = []
    for candidate in candidates:
        unusable_reason = _unusable_reason(candidate)
        if unusable_reason is not None:
            filtered_out.append(CandidateDisposition(candidate=candidate, reason=unusable_reason))
            continue
        usable.append(candidate)

    if not usable:
        return SelectionResult(
            target=result.target,
            family=family,
            policy=policy,
            status="no_candidate",
            remaining_candidates=[],
            filtered_out=filtered_out,
            not_selected=[],
            reason=f"no usable {family.value} candidate remains after filtering",
        )

    if family is IPAddressFamily.IPV4:
        return _select_ipv4(
            result=result,
            policy=policy,
            usable=usable,
            filtered_out=filtered_out,
        )
    return _select_ipv6(
        result=result,
        policy=policy,
        usable=usable,
        filtered_out=filtered_out,
    )


def _select_ipv4(
    *,
    result: DiscoveryResult,
    policy: str,
    usable: list[AddressCandidate],
    filtered_out: list[CandidateDisposition],
) -> SelectionResult:
    if len(usable) == 1:
        return _selected_result(
            result=result,
            policy=policy,
            candidate=usable[0],
            reason="only remaining usable ipv4 candidate",
            filtered_out=filtered_out,
            not_selected=[],
        )

    cidr_32 = [candidate for candidate in usable if candidate.prefix_length == 32]
    if cidr_32:
        if len(cidr_32) == 1:
            selected_candidate = cidr_32[0]
            return _selected_result(
                result=result,
                policy=policy,
                candidate=selected_candidate,
                reason="preferred explicit /32 candidate",
                filtered_out=filtered_out,
                not_selected=[
                    CandidateDisposition(
                        candidate=candidate,
                        reason="lower priority than selected /32 candidate",
                    )
                    for candidate in usable
                    if candidate != selected_candidate
                ],
            )
        return SelectionResult(
            target=result.target,
            family=IPAddressFamily.IPV4,
            policy=policy,
            status="ambiguous",
            remaining_candidates=cidr_32,
            filtered_out=filtered_out,
            not_selected=[],
            reason="multiple /32 ipv4 candidates remain; refusing to guess",
        )

    return SelectionResult(
        target=result.target,
        family=IPAddressFamily.IPV4,
        policy=policy,
        status="ambiguous",
        remaining_candidates=usable,
        filtered_out=filtered_out,
        not_selected=[],
        reason="multiple public ipv4 candidates remain and none can be preferred safely",
    )


def _select_ipv6(
    *,
    result: DiscoveryResult,
    policy: str,
    usable: list[AddressCandidate],
    filtered_out: list[CandidateDisposition],
) -> SelectionResult:
    if len(usable) == 1:
        selected_candidate = usable[0]
        return _selected_result(
            result=result,
            policy=policy,
            candidate=selected_candidate,
            reason="only remaining usable candidate",
            filtered_out=filtered_out,
            not_selected=[],
        )

    cidr_128 = [candidate for candidate in usable if candidate.prefix_length == 128]
    if cidr_128:
        if len(cidr_128) == 1:
            selected_candidate = cidr_128[0]
            return _selected_result(
                result=result,
                policy=policy,
                candidate=selected_candidate,
                reason="preferred explicit /128 candidate",
                filtered_out=filtered_out,
                not_selected=[
                    CandidateDisposition(
                        candidate=candidate,
                        reason="lower priority than selected /128 candidate",
                    )
                    for candidate in usable
                    if candidate != selected_candidate
                ],
            )
        return SelectionResult(
            target=result.target,
            family=IPAddressFamily.IPV6,
            policy=policy,
            status="ambiguous",
            remaining_candidates=cidr_128,
            filtered_out=filtered_out,
            not_selected=[],
            reason="multiple /128 candidates remain; refusing to guess",
        )

    stable_candidates = [candidate for candidate in usable if _is_stable_ipv6_candidate(candidate)]
    if len(stable_candidates) == 1:
        selected_candidate = stable_candidates[0]
        return _selected_result(
            result=result,
            policy=policy,
            candidate=selected_candidate,
            reason="single stable candidate remains after filtering",
            filtered_out=filtered_out,
            not_selected=[
                CandidateDisposition(
                    candidate=candidate,
                    reason="deprioritized as likely temporary/privacy address",
                )
                for candidate in usable
                if candidate != selected_candidate
            ],
        )

    if len(stable_candidates) > 1:
        return SelectionResult(
            target=result.target,
            family=IPAddressFamily.IPV6,
            policy=policy,
            status="ambiguous",
            remaining_candidates=stable_candidates,
            filtered_out=filtered_out,
            not_selected=[],
            reason="multiple stable global candidates remain; refusing to guess",
        )

    return SelectionResult(
        target=result.target,
        family=IPAddressFamily.IPV6,
        policy=policy,
        status="ambiguous",
        remaining_candidates=usable,
        filtered_out=filtered_out,
        not_selected=[],
        reason="multiple global candidates remain and none can be preferred safely",
    )


def _unusable_reason(candidate: AddressCandidate) -> str | None:
    parsed = ip_address(candidate.address)
    if isinstance(parsed, IPv4Address):
        return unusable_ipv4_reason(parsed)
    base_reason = unusable_ipv6_reason(parsed)
    if base_reason is not None:
        return base_reason
    return _unusable_ipv6_flag_reason(candidate)


def _unusable_ipv6_flag_reason(candidate: AddressCandidate) -> str | None:
    for flag in candidate.flags:
        normalized_flag = flag.lower()
        if normalized_flag in _UNUSABLE_IPV6_FLAGS:
            return normalized_flag
    return None


def _is_stable_ipv6_candidate(candidate: AddressCandidate) -> bool:
    address = IPv6Address(candidate.address)
    if candidate.prefix_length == 128:
        return True
    if has_embedded_eui64(address):
        return True
    return not looks_temporary_or_privacy(address, candidate.prefix_length)


def _selected_result(
    *,
    result: DiscoveryResult,
    policy: str,
    candidate: AddressCandidate,
    reason: str,
    filtered_out: list[CandidateDisposition],
    not_selected: list[CandidateDisposition],
) -> SelectionResult:
    selected = SelectedAddress(
        target=result.target,
        family=candidate.family,
        address=candidate.address,
        prefix_length=candidate.prefix_length,
        interface=candidate.interface,
        selection_policy=policy,
        source=candidate.source,
        reason=reason,
    )
    return SelectionResult(
        target=result.target,
        family=candidate.family,
        policy=policy,
        status="selected",
        selected=selected,
        remaining_candidates=[candidate],
        filtered_out=filtered_out,
        not_selected=not_selected,
        reason=reason,
    )
