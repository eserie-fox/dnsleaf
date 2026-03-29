from __future__ import annotations

from arbor_ddns.discovery.models import AddressCandidate, DiscoveryResult
from arbor_ddns.discovery.selectors import select_address
from arbor_ddns.models import TargetKind, TargetRef


def _candidate(address: str, prefix_length: int, *, interface: str = "eth0") -> AddressCandidate:
    return AddressCandidate(
        interface=interface,
        address=address,
        prefix_length=prefix_length,
        source="test",
    )


def _result(candidates: list[AddressCandidate]) -> DiscoveryResult:
    return DiscoveryResult(
        target=TargetRef(kind=TargetKind.LXC, id=101),
        backend="test",
        candidates=candidates,
    )


def test_selector_filters_ula_and_selects_global_candidate() -> None:
    selection = select_address(
        _result(
            [
                _candidate("2408:8266:5003:506a:be24:11ff:fefb:7700", 64, interface="eth0"),
                _candidate("fd42:42:42:42::1", 112, interface="tun0"),
            ]
        )
    )

    assert selection.status == "selected"
    assert selection.selected is not None
    assert selection.selected.address == "2408:8266:5003:506a:be24:11ff:fefb:7700"
    assert selection.filtered_out[0].reason == "unique_local"


def test_selector_prefers_128_over_stable_64() -> None:
    selection = select_address(
        _result(
            [
                _candidate("2408:8266:5003:506a::3d6", 128),
                _candidate("2408:8266:5003:506a:be24:11ff:feeb:aba3", 64),
            ]
        )
    )

    assert selection.status == "selected"
    assert selection.selected is not None
    assert selection.selected.prefix_length == 128
    assert selection.not_selected[0].reason == "lower priority than selected /128 candidate"


def test_selector_prefers_128_and_filters_link_local_for_vm_sample() -> None:
    selection = select_address(
        _result(
            [
                _candidate("2408:8266:5003:506a::458", 128, interface="ens18"),
                _candidate("2408:8266:5003:506a:e27f:4076:f737:e75a", 64, interface="ens18"),
                _candidate("2408:8266:5003:506a:9d54:1c94:fbb1:b5ee", 64, interface="ens18"),
                _candidate("2408:8266:5003:506a:be24:11ff:fee8:826", 64, interface="ens18"),
                _candidate("fe80::be24:11ff:fee8:826", 64, interface="ens18"),
            ]
        )
    )

    assert selection.status == "selected"
    assert selection.selected is not None
    assert selection.selected.address == "2408:8266:5003:506a::458"
    assert {item.reason for item in selection.filtered_out} == {"link_local"}


def test_selector_returns_ambiguous_for_multiple_random_global_64s() -> None:
    selection = select_address(
        _result(
            [
                _candidate("2408:8266:5003:506a:e27f:4076:f737:e75a", 64),
                _candidate("2408:8266:5003:506a:9d54:1c94:fbb1:b5ee", 64),
            ]
        )
    )

    assert selection.status == "ambiguous"
    assert selection.selected is None
    assert "none can be preferred safely" in selection.reason

