from __future__ import annotations

from dnsleaf.discovery.models import AddressCandidate, DiscoveryResult
from dnsleaf.discovery.selectors import select_address
from dnsleaf.models import IPAddressFamily, TargetKind, TargetRef


def _candidate(
    address: str,
    prefix_length: int,
    *,
    family: IPAddressFamily,
    interface: str = "eth0",
    scope: str | None = None,
    flags: list[str] | None = None,
) -> AddressCandidate:
    return AddressCandidate(
        family=family,
        interface=interface,
        address=address,
        prefix_length=prefix_length,
        source="test",
        scope=scope,
        flags=flags or [],
    )


def _result(candidates: list[AddressCandidate]) -> DiscoveryResult:
    return DiscoveryResult(
        target=TargetRef(kind=TargetKind.LXC, id=101),
        backend="test",
        candidates=candidates,
    )


def test_ipv6_selector_filters_ula_and_selects_global_candidate() -> None:
    selection = select_address(
        _result(
            [
                _candidate(
                    "2001:4860:abcd:1234:1111:2222:3333:4444",
                    64,
                    family=IPAddressFamily.IPV6,
                    interface="eth0",
                ),
                _candidate(
                    "fd42:42:42:42::1",
                    112,
                    family=IPAddressFamily.IPV6,
                    interface="tun0",
                ),
            ]
        ),
        family=IPAddressFamily.IPV6,
    )

    assert selection.status == "selected"
    assert selection.selected is not None
    assert selection.selected.address == "2001:4860:abcd:1234:1111:2222:3333:4444"
    assert selection.filtered_out[0].reason == "unique_local"


def test_ipv6_selector_prefers_128_over_stable_64() -> None:
    selection = select_address(
        _result(
            [
                _candidate("2001:4860:abcd:1234::3d6", 128, family=IPAddressFamily.IPV6),
                _candidate(
                    "2001:4860:abcd:1234:5555:6666:7777:8888",
                    64,
                    family=IPAddressFamily.IPV6,
                ),
            ]
        ),
        family=IPAddressFamily.IPV6,
    )

    assert selection.status == "selected"
    assert selection.selected is not None
    assert selection.selected.prefix_length == 128
    assert selection.not_selected[0].reason == "lower priority than selected /128 candidate"


def test_ipv6_selector_filters_deprecated_128_and_selects_healthy_64() -> None:
    selection = select_address(
        _result(
            [
                _candidate(
                    "2001:4860:abcd:1234::3d6",
                    128,
                    family=IPAddressFamily.IPV6,
                    scope="global",
                    flags=["deprecated", "dynamic", "mngtmpaddr"],
                ),
                _candidate(
                    "2001:4860:abcd:1234:1111:2222:3333:4444",
                    64,
                    family=IPAddressFamily.IPV6,
                    scope="global",
                    flags=["dynamic", "mngtmpaddr"],
                ),
            ]
        ),
        family=IPAddressFamily.IPV6,
    )

    assert selection.status == "selected"
    assert selection.selected is not None
    assert selection.selected.address == "2001:4860:abcd:1234:1111:2222:3333:4444"
    assert [(item.candidate.cidr, item.reason) for item in selection.filtered_out] == [
        ("2001:4860:abcd:1234::3d6/128", "deprecated")
    ]


def test_ipv6_selector_filters_tentative_candidate() -> None:
    selection = select_address(
        _result(
            [
                _candidate(
                    "2001:4860:abcd:1234::99",
                    128,
                    family=IPAddressFamily.IPV6,
                    scope="global",
                    flags=["tentative"],
                ),
                _candidate(
                    "2001:4860:abcd:1234:5555:6666:7777:8888",
                    64,
                    family=IPAddressFamily.IPV6,
                    scope="global",
                    flags=["dynamic", "mngtmpaddr"],
                ),
            ]
        ),
        family=IPAddressFamily.IPV6,
    )

    assert selection.status == "selected"
    assert selection.selected is not None
    assert selection.selected.address == "2001:4860:abcd:1234:5555:6666:7777:8888"
    assert [(item.candidate.cidr, item.reason) for item in selection.filtered_out] == [
        ("2001:4860:abcd:1234::99/128", "tentative")
    ]


def test_ipv6_selector_filters_dadfailed_candidate() -> None:
    selection = select_address(
        _result(
            [
                _candidate(
                    "2001:4860:abcd:1234::77",
                    128,
                    family=IPAddressFamily.IPV6,
                    scope="global",
                    flags=["dadfailed"],
                ),
                _candidate(
                    "2001:4860:abcd:1234:1111:2222:3333:4444",
                    64,
                    family=IPAddressFamily.IPV6,
                    scope="global",
                    flags=["dynamic", "mngtmpaddr"],
                ),
            ]
        ),
        family=IPAddressFamily.IPV6,
    )

    assert selection.status == "selected"
    assert selection.selected is not None
    assert selection.selected.address == "2001:4860:abcd:1234:1111:2222:3333:4444"
    assert [(item.candidate.cidr, item.reason) for item in selection.filtered_out] == [
        ("2001:4860:abcd:1234::77/128", "dadfailed")
    ]


def test_ipv6_selector_prefers_128_and_filters_link_local_for_vm_sample() -> None:
    selection = select_address(
        _result(
            [
                _candidate(
                    "2001:4860:abcd:1234::458",
                    128,
                    family=IPAddressFamily.IPV6,
                    interface="ens18",
                ),
                _candidate(
                    "2001:4860:abcd:1234:e27f:4076:f737:e75a",
                    64,
                    family=IPAddressFamily.IPV6,
                    interface="ens18",
                ),
                _candidate(
                    "2001:4860:abcd:1234:9d54:1c94:fbb1:b5ee",
                    64,
                    family=IPAddressFamily.IPV6,
                    interface="ens18",
                ),
                _candidate(
                    "2001:4860:abcd:1234:be24:11ff:fee8:826",
                    64,
                    family=IPAddressFamily.IPV6,
                    interface="ens18",
                ),
                _candidate(
                    "fe80::be24:11ff:fee8:826",
                    64,
                    family=IPAddressFamily.IPV6,
                    interface="ens18",
                ),
            ]
        ),
        family=IPAddressFamily.IPV6,
    )

    assert selection.status == "selected"
    assert selection.selected is not None
    assert selection.selected.address == "2001:4860:abcd:1234::458"
    assert {item.reason for item in selection.filtered_out} == {"link_local"}


def test_ipv6_selector_returns_ambiguous_for_multiple_random_global_64s() -> None:
    selection = select_address(
        _result(
            [
                _candidate(
                    "2001:4860:abcd:1234:e27f:4076:f737:e75a",
                    64,
                    family=IPAddressFamily.IPV6,
                ),
                _candidate(
                    "2001:4860:abcd:1234:9d54:1c94:fbb1:b5ee",
                    64,
                    family=IPAddressFamily.IPV6,
                ),
            ]
        ),
        family=IPAddressFamily.IPV6,
    )

    assert selection.status == "ambiguous"
    assert selection.selected is None
    assert "none can be preferred safely" in selection.reason


def test_ipv4_selector_accepts_one_public_candidate() -> None:
    selection = select_address(
        _result([_candidate("93.184.216.34", 32, family=IPAddressFamily.IPV4)]),
        family=IPAddressFamily.IPV4,
    )

    assert selection.status == "selected"
    assert selection.selected is not None
    assert selection.selected.address == "93.184.216.34"


def test_ipv4_selector_filters_private_and_link_local_candidates() -> None:
    selection = select_address(
        _result(
            [
                _candidate("10.0.0.10", 24, family=IPAddressFamily.IPV4),
                _candidate("169.254.10.20", 16, family=IPAddressFamily.IPV4),
                _candidate("93.184.216.34", 32, family=IPAddressFamily.IPV4),
            ]
        ),
        family=IPAddressFamily.IPV4,
    )

    assert selection.status == "selected"
    assert selection.selected is not None
    assert selection.selected.address == "93.184.216.34"
    assert {item.reason for item in selection.filtered_out} == {"private", "link_local"}


def test_ipv4_selector_prefers_32() -> None:
    selection = select_address(
        _result(
            [
                _candidate("93.184.216.34", 32, family=IPAddressFamily.IPV4),
                _candidate("8.8.4.4", 24, family=IPAddressFamily.IPV4),
            ]
        ),
        family=IPAddressFamily.IPV4,
    )

    assert selection.status == "selected"
    assert selection.selected is not None
    assert selection.selected.prefix_length == 32


def test_ipv4_selector_returns_ambiguous_for_multiple_public_candidates() -> None:
    selection = select_address(
        _result(
            [
                _candidate("93.184.216.34", 24, family=IPAddressFamily.IPV4),
                _candidate("8.8.8.8", 24, family=IPAddressFamily.IPV4),
            ]
        ),
        family=IPAddressFamily.IPV4,
    )

    assert selection.status == "ambiguous"
    assert "multiple public ipv4 candidates remain" in selection.reason
