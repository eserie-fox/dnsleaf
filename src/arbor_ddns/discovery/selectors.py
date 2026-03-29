"""Address selection policies."""

from __future__ import annotations

from ipaddress import IPv6Address

from arbor_ddns.discovery.models import (
    AddressCandidate,
    CandidateDisposition,
    DiscoveryResult,
    SelectionResult,
)
from arbor_ddns.models import SelectedAddress
from arbor_ddns.util.ip import has_embedded_eui64, looks_temporary_or_privacy, unusable_ipv6_reason


def select_address(result: DiscoveryResult, *, policy: str = "default") -> SelectionResult:
    """Select the best DNS AAAA address from discovery candidates."""

    if policy != "default":
        raise ValueError(f"unsupported selection policy: {policy}")

    filtered_out: list[CandidateDisposition] = []
    usable: list[AddressCandidate] = []
    for candidate in result.candidates:
        ip = IPv6Address(candidate.address)
        unusable_reason = unusable_ipv6_reason(ip)
        if unusable_reason is not None:
            filtered_out.append(CandidateDisposition(candidate=candidate, reason=unusable_reason))
            continue
        usable.append(candidate)

    if not usable:
        return SelectionResult(
            target=result.target,
            policy=policy,
            status="no_candidate",
            remaining_candidates=[],
            filtered_out=filtered_out,
            not_selected=[],
            reason="no globally usable IPv6 candidate remains after filtering",
        )

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
            policy=policy,
            status="ambiguous",
            remaining_candidates=cidr_128,
            filtered_out=filtered_out,
            not_selected=[],
            reason="multiple /128 candidates remain; refusing to guess",
        )

    stable_candidates = [
        candidate
        for candidate in usable
        if _is_stable_candidate(candidate)
    ]
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
            policy=policy,
            status="ambiguous",
            remaining_candidates=stable_candidates,
            filtered_out=filtered_out,
            not_selected=[],
            reason="multiple stable global candidates remain; refusing to guess",
        )

    return SelectionResult(
        target=result.target,
        policy=policy,
        status="ambiguous",
        remaining_candidates=usable,
        filtered_out=filtered_out,
        not_selected=[],
        reason="multiple global candidates remain and none can be preferred safely",
    )


def _is_stable_candidate(candidate: AddressCandidate) -> bool:
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
        address=candidate.address,
        prefix_length=candidate.prefix_length,
        interface=candidate.interface,
        selection_policy=policy,
        source=candidate.source,
        reason=reason,
    )
    return SelectionResult(
        target=result.target,
        policy=policy,
        status="selected",
        selected=selected,
        remaining_candidates=[candidate],
        filtered_out=filtered_out,
        not_selected=not_selected,
        reason=reason,
    )

