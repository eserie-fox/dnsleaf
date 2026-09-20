"""Pure selection requirements over normalized evidence, independent of its producer."""

from dnsleaf.discovery.models import (
    AddressCandidate,
    AddressEvidence,
    CandidateDisposition,
    CorrelatedEvidence,
    DiscoveryResult,
    SelectionResult,
)
from dnsleaf.models import IPAddressFamily, SelectedAddress


def select_required_dhcpv6(
    result: DiscoveryResult,
    *,
    usable: list[AddressCandidate],
    filtered_out: list[CandidateDisposition],
    evidence: CorrelatedEvidence | None,
) -> SelectionResult:
    selection = SelectionResult(
        target=result.target,
        family=IPAddressFamily.IPV6,
        policy="require-dhcpv6",
        status="ambiguous",
        remaining_candidates=usable,
        filtered_out=filtered_out,
        evidence=evidence,
        reason="complete correlated DHCPv6 evidence is required",
    )
    if evidence is None:
        return selection
    if evidence.status != "complete":
        selection.status = "no_candidate" if evidence.status == "error" else "ambiguous"
        selection.reason = f"evidence {evidence.error_stage or 'correlation'}: {evidence.reason}"
        return selection
    # Correlation must cover every usable candidate, even if one already looks eligible.
    facts: dict[tuple[str, str, int, str, str | None], AddressEvidence] = {}
    raw_keys = {_candidate_key(c) for c in result.candidates}
    for fact in evidence.observations:
        key = _candidate_key(fact.candidate)
        if key not in raw_keys or (key in facts and facts[key] != fact):
            selection.reason = "conflicting or unmatched normalized evidence"
            return selection
        facts[key] = fact
    eligible: list[AddressCandidate] = []
    seen: set[tuple[str, str]] = set()
    for candidate in usable:
        key = _candidate_key(candidate)
        observation = facts.get(key)
        if (
            observation is None
            or not observation.interface_identity
            or observation.dhcp_origin == "unknown"
            or (observation.preferred is None or observation.skip_as_source is None)
        ):
            selection.reason = (
                f"insufficient proven facts for {candidate.cidr} on {candidate.interface}"
            )
            return selection
        identity = (candidate.address, observation.interface_identity)
        if identity in seen:
            continue
        seen.add(identity)
        if observation.dhcp_origin != "dhcp":
            reason = "proven origin does not satisfy DHCPv6 requirement"
        elif not observation.preferred:
            reason = "address state is not preferred"
        elif observation.skip_as_source:
            reason = "skip-as-source is true"
        else:
            eligible.append(candidate)
            continue
        selection.not_selected.append(CandidateDisposition(candidate=candidate, reason=reason))
    selection.remaining_candidates = eligible
    if not eligible:
        selection.status = "no_candidate"
        selection.reason = "complete evidence contains no eligible DHCPv6 address"
    elif len(eligible) > 1:
        selection.reason = "multiple eligible DHCPv6 addresses; refusing to guess"
    else:
        candidate = eligible[0]
        selection.status = "selected"
        selection.reason = "unique eligible DHCPv6 address proven by correlated evidence"
        selection.selected = SelectedAddress(
            target=result.target,
            family=IPAddressFamily.IPV6,
            address=candidate.address,
            prefix_length=candidate.prefix_length,
            interface=candidate.interface,
            selection_policy="require-dhcpv6",
            source=candidate.source,
            reason=selection.reason,
        )
    return selection


def _candidate_key(candidate: AddressCandidate) -> tuple[str, str, int, str, str | None]:
    return (
        candidate.family.value,
        candidate.address,
        candidate.prefix_length,
        candidate.interface,
        candidate.hardware_address,
    )
