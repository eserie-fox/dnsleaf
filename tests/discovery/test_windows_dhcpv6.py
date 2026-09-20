"""Synthetic DHCPv6/RA inventories, never captured from a production Guest."""

import pytest

from dnsleaf.discovery.selectors import select_address
from dnsleaf.discovery.windows import parse_windows_metadata
from dnsleaf.models import IPAddressFamily
from tests.windows_fixtures import (
    DHCP,
    LINK,
    MAC,
    RANDOM,
    metadata_wire,
    synthetic_inventory,
    synthetic_metadata,
)


def test_reported_two_128_limitation_remains_ambiguous_by_default() -> None:
    result = select_address(synthetic_inventory(), family=IPAddressFamily.IPV6)
    assert result.status == "ambiguous"
    assert result.selected is None
    assert result.reason == "multiple /128 candidates remain; refusing to guess"
    assert {c.address for c in result.remaining_candidates} == {
        "2001:4860:1234::a",
        "2001:4860:1234::b",
    }


def strict(raw=None, records=None):
    return select_address(
        raw if raw is not None else synthetic_inventory(),
        family=IPAddressFamily.IPV6,
        policy="windows-dhcpv6",
        windows_evidence=parse_windows_metadata(
            metadata_wire(records if records is not None else synthetic_metadata())
        ),
    )


def test_strict_selects_corroborated_dhcp_and_preserves_snapshots() -> None:
    raw = synthetic_inventory()
    original = raw.model_dump()
    records = synthetic_metadata()
    evidence = parse_windows_metadata(metadata_wire(records))
    original_evidence = evidence.model_dump()
    selected = select_address(
        raw, family=IPAddressFamily.IPV6, policy="windows-dhcpv6", windows_evidence=evidence
    )
    assert selected.selected and selected.selected.address == DHCP
    assert selected.reason == "unique eligible Windows-reported DHCPv6 address corroborated by QGA"
    assert {c.candidate.address for c in selected.not_selected} == {RANDOM, LINK}
    assert "RouterAdvertisement/Random" in selected.not_selected[0].reason
    assert {c.reason for c in selected.filtered_out} == {"loopback", "link_local"}
    assert raw.model_dump() == original
    assert evidence.model_dump() == original_evidence
    assert select_address(raw, family=IPAddressFamily.IPV6).status == "ambiguous"


def test_one_raw_128_is_not_proof_of_dhcp() -> None:
    raw = synthetic_inventory()
    raw.candidates = raw.candidates[:1]
    result = select_address(raw, family=IPAddressFamily.IPV6, policy="windows-dhcpv6")
    assert result.selected is None and result.status == "ambiguous"
    assert "evidence is required" in result.reason
    assert strict(raw, []).selected is None


def test_dhcp_64_beats_ra_128_by_evidence() -> None:
    raw = synthetic_inventory()
    raw.candidates[0].prefix_length = 64
    records = synthetic_metadata()
    records[0]["PrefixLength"] = 64
    selected = strict(raw, records)
    assert selected.selected and selected.selected.address == DHCP
    assert selected.selected.prefix_length == 64


@pytest.mark.parametrize("across_adapters", [False, True])
@pytest.mark.parametrize("reverse", [False, True])
def test_multiple_dhcp_addresses_ambiguous_regardless_of_order(across_adapters, reverse) -> None:
    raw = synthetic_inventory()
    records = synthetic_metadata()
    records[1].update(PrefixOrigin="Dhcp", SuffixOrigin="Dhcp")
    if across_adapters:
        raw.candidates[1].hardware_address = "52:54:00:65:43:21"
        raw.candidates[1].interface = "Ethernet 2"
        records[1].update(
            HardwareAddress="52-54-00-65-43-21", InterfaceIndex=13, InterfaceAlias="Ethernet 2"
        )
    if reverse:
        raw.candidates.reverse()
        records.reverse()
    selection = strict(raw, records)
    assert selection.status == "ambiguous" and selection.selected is None
    assert {c.address for c in selection.remaining_candidates} == {DHCP, RANDOM}


@pytest.mark.parametrize(
    "patch",
    [
        {"PrefixOrigin": "RouterAdvertisement", "SuffixOrigin": "Random"},
        {"AddressState": "Deprecated"},
        {"AddressState": "Tentative"},
        {"AddressState": "Duplicate"},
        {"AddressState": "Invalid"},
        {"SkipAsSource": True},
    ],
)
def test_complete_but_ineligible_evidence_has_no_candidate(patch) -> None:
    records = synthetic_metadata()
    records[0].update(patch)
    selection = strict(records=records)
    assert selection.status == "no_candidate" and selection.selected is None
    assert len(selection.not_selected) == 3


@pytest.mark.parametrize(
    "field,value",
    [
        ("PrefixOrigin", "Unknown"),
        ("SuffixOrigin", "Unknown"),
        ("AddressState", "Unknown"),
        ("SkipAsSource", "false"),
        ("SkipAsSource", 0),
        ("SkipAsSource", None),
        ("InterfaceIndex", True),
        ("PrefixLength", "128"),
        ("IPAddress", "not-an-address"),
    ],
)
def test_untrusted_field_is_never_confirmed_evidence(field, value) -> None:
    records = synthetic_metadata()
    records[1][field] = value  # A confirmed DHCP plus an unclassified second candidate.
    selection = strict(records=records)
    assert selection.selected is None
    assert selection.supplementary and selection.supplementary.status == "error"
    assert field in (selection.supplementary.error or "")


@pytest.mark.parametrize("field", list(synthetic_metadata()[0]))
def test_missing_fields_cannot_establish_uniqueness(field) -> None:
    records = synthetic_metadata()
    del records[1][field]
    assert strict(records=records).selected is None


@pytest.mark.parametrize(
    "change",
    [
        "removed_metadata",
        "removed_raw",
        "added_metadata",
        "changed_prefix",
        "wrong_mac",
        "missing_mac",
        "invalid_mac",
        "raw_missing_mac",
        "conflicting_duplicate",
        "changed_index",
        "same_index_different_mac",
        "qga_duplicate_conflict",
        "parsing_issue",
    ],
)
def test_snapshot_or_identity_inconsistency_refuses_selection(change) -> None:
    raw = synthetic_inventory()
    records = synthetic_metadata()
    if change == "removed_metadata":
        records.pop(1)
    elif change == "removed_raw":
        raw.candidates.pop(0)  # Supplementary DHCP is absent from QGA.
    elif change == "added_metadata":
        records.append({**records[0], "IPAddress": "2001:4860:1234::d"})
    elif change == "changed_prefix":
        records[1]["PrefixLength"] = 64
    elif change == "wrong_mac":
        for record in records:
            record["HardwareAddress"] = "52:54:00:65:43:21"
    elif change == "missing_mac":
        records[1]["HardwareAddress"] = None
    elif change == "invalid_mac":
        records[1]["HardwareAddress"] = "00:00:00:00:00:00"
    elif change == "raw_missing_mac":
        raw.candidates[1].hardware_address = None
    elif change == "conflicting_duplicate":
        records.append({**records[0], "SkipAsSource": True})
    elif change == "changed_index":
        records[1]["InterfaceIndex"] = 13
    elif change == "same_index_different_mac":
        records[1]["HardwareAddress"] = "52:54:00:65:43:21"
    elif change == "qga_duplicate_conflict":
        raw.candidates.append(raw.candidates[0].model_copy(update={"prefix_length": 64}))
    else:
        raw.parsing_issues = ["invalid QGA address item"]
    selection = strict(raw, records)
    assert selection.status == "ambiguous" and selection.selected is None
    assert "correlation refused" in selection.reason or "parsing" in selection.reason


def test_identical_duplicates_and_normalized_identity_are_safe() -> None:
    raw = synthetic_inventory()
    raw.candidates.append(raw.candidates[0].model_copy())
    records = synthetic_metadata()
    records.append(dict(records[0]))
    for record in records:
        record["HardwareAddress"] = MAC.upper().replace(":", "-")
        record["InterfaceAlias"] = "Renamed display alias"
    records[0]["IPAddress"] = "2001:4860:1234:0:0:0:0:a"
    selected = strict(raw, records)
    assert selected.selected and selected.selected.address == DHCP


def test_duplicate_aliases_do_not_override_proven_hardware_identity() -> None:
    raw = synthetic_inventory()
    records = synthetic_metadata()
    raw.candidates[1].hardware_address = "52:54:00:65:43:21"
    records[1].update(HardwareAddress="52:54:00:65:43:21", InterfaceIndex=13)
    selected = strict(raw, records)
    assert selected.selected and selected.selected.address == DHCP


def test_unusable_addresses_do_not_require_hardware_identity() -> None:
    raw = synthetic_inventory()
    records = synthetic_metadata()
    for record in records[3:]:
        record["HardwareAddress"] = None
    raw.candidates[3].hardware_address = None
    assert strict(raw, records).selected is not None


def test_probe_failure_never_falls_back_to_single_raw_128() -> None:
    raw = synthetic_inventory()
    raw.candidates = raw.candidates[:1]
    failed = parse_windows_metadata('{"pid": 77}')
    selection = select_address(
        raw, family=IPAddressFamily.IPV6, policy="windows-dhcpv6", windows_evidence=failed
    )
    assert selection.selected is None and selection.supplementary == failed


def test_complete_empty_inventory_has_no_candidate() -> None:
    raw = synthetic_inventory()
    raw.candidates = []
    assert strict(raw, []).status == "no_candidate"
    assert strict(raw, synthetic_metadata()).status == "ambiguous"


def test_duplicate_raw_hardware_on_different_interfaces_refuses() -> None:
    raw = synthetic_inventory()
    raw.candidates[1].interface = "Different adapter"
    selection = strict(raw)
    assert selection.status == "ambiguous" and "different interfaces" in selection.reason
