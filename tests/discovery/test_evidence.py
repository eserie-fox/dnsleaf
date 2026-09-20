"""Strict selection consumes generic facts, without Windows transport objects."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from dnsleaf.discovery.models import (
    AddressCandidate,
    AddressEvidence,
    CorrelatedEvidence,
    DiscoveryResult,
)
from dnsleaf.discovery.selectors import select_address
from dnsleaf.models import IPAddressFamily, TargetKind, TargetRef


def raw():
    return DiscoveryResult(
        target=TargetRef(kind=TargetKind.VM, id=201),
        backend="pve_qga",
        candidates=[
            AddressCandidate(
                family=IPAddressFamily.IPV6,
                interface="adapter",
                address="2001:4860:1234::1",
                prefix_length=64,
                source="pve_qga",
                hardware_address="52:54:00:12:34:56",
            ),
            AddressCandidate(
                family=IPAddressFamily.IPV6,
                interface="adapter",
                address="2001:4860:1234::2",
                prefix_length=128,
                source="pve_qga",
                hardware_address="52:54:00:12:34:56",
            ),
        ],
    )


def evidence(result):
    return CorrelatedEvidence(
        source="synthetic",
        status="complete",
        reason="correlated",
        observations=[
            AddressEvidence(
                candidate=c,
                interface_identity="525400123456",
                dhcp_origin="dhcp" if i == 0 else "non_dhcp",
                preferred=True,
                skip_as_source=False,
                provenance="synthetic",
            )
            for i, c in enumerate(result.candidates)
        ],
    )


def select(result, facts):
    return select_address(
        result, family=IPAddressFamily.IPV6, policy="require-dhcpv6", evidence=facts
    )


def test_generic_strict_facts_select_dhcp64_without_native_fields_or_heuristics():
    result = raw()
    original = result.model_dump()
    facts = evidence(result)
    selected = select(result, facts)
    assert selected.selected and selected.selected.address == result.candidates[0].address
    assert selected.selected.prefix_length == 64
    assert all(not observation.source_details for observation in facts.observations)
    assert result.model_dump() == original


@pytest.mark.parametrize(
    "field,value",
    [
        ("dhcp_origin", "unknown"),
        ("preferred", None),
        ("skip_as_source", None),
        ("interface_identity", ""),
    ],
)
def test_unknown_facts_on_other_candidate_cannot_manufacture_uniqueness(field, value):
    result = raw()
    facts = evidence(result)
    facts.observations[1] = facts.observations[1].model_copy(update={field: value})
    assert select(result, facts).status == "ambiguous"


@pytest.mark.parametrize("field", ["preferred", "skip_as_source"])
@pytest.mark.parametrize("value", ["false", "true", 0, 1])
def test_generic_boolean_facts_are_strict(field, value):
    data = evidence(raw()).observations[0].model_dump() | {field: value}
    with pytest.raises(ValidationError):
        AddressEvidence.model_validate(data)


def test_duplicate_and_conflicting_generic_observations():
    result = raw()
    facts = evidence(result)
    facts.observations.append(facts.observations[0].model_copy())
    assert select(result, facts).status == "selected"
    facts.observations[-1] = facts.observations[-1].model_copy(update={"skip_as_source": True})
    assert select(result, facts).status == "ambiguous"


def test_missing_or_unmatched_facts_refuse():
    result = raw()
    facts = evidence(result)
    facts.observations.pop()
    assert select(result, facts).status == "ambiguous"
    facts = evidence(result)
    result.candidates.pop()
    assert select(result, facts).status == "ambiguous"
