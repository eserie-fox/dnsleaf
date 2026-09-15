from __future__ import annotations

import json
import logging
from collections.abc import Sequence

import pytest

from dnsleaf.discovery.parser import parse_qga_interfaces
from dnsleaf.discovery.pve_qga import PVEQGADiscoveryBackend
from dnsleaf.models import TargetKind, TargetRef
from dnsleaf.util.process import CommandResult


def test_pve_qga_backend_parses_network_interfaces() -> None:
    payload = {
        "result": [
            {
                "name": "ens18",
                "ip-addresses": [
                    {
                        "ip-address-type": "ipv6",
                        "ip-address": "2001:4860:abcd:1234::458",
                        "prefix": 128,
                    },
                    {
                        "ip-address-type": "ipv6",
                        "ip-address": "2001:4860:abcd:1234:e27f:4076:f737:e75a",
                        "prefix": 64,
                    },
                    {"ip-address-type": "ipv4", "ip-address": "93.184.216.34", "prefix": 32},
                ],
            }
        ]
    }

    def fake_runner(args: Sequence[str], *, check: bool = True) -> CommandResult:
        assert args == ["qm", "agent", "201", "network-get-interfaces"]
        return CommandResult(args=tuple(args), returncode=0, stdout=json.dumps(payload), stderr="")

    backend = PVEQGADiscoveryBackend(runner=fake_runner)

    result = backend.discover(TargetRef(kind=TargetKind.VM, id=201))

    assert result.error is None
    assert [candidate.cidr for candidate in result.candidates] == [
        "2001:4860:abcd:1234::458/128",
        "2001:4860:abcd:1234:e27f:4076:f737:e75a/64",
        "93.184.216.34/32",
    ]


def test_pve_qga_backend_skips_invalid_interfaces_and_address_items(caplog) -> None:
    payload = {
        "result": [
            {
                "name": "ens18",
                "ip-addresses": [
                    {"ip-address-type": "ipv4", "ip-address": "93.184.216.34", "prefix": 32},
                    {"ip-address-type": "ipv6", "ip-address": "2001:4860:abcd:1234::458"},
                    "broken-address",
                ],
            },
            "broken-interface",
            {
                "name": "ens19",
                "ip-addresses": "broken-list",
            },
            {
                "name": "ens20",
                "ip-addresses": [
                    {
                        "ip-address-type": "ipv6",
                        "ip-address": "2001:4860:abcd:1234::999",
                        "prefix": 128,
                    }
                ],
            },
        ]
    }

    def fake_runner(args: Sequence[str], *, check: bool = True) -> CommandResult:
        assert args == ["qm", "agent", "201", "network-get-interfaces"]
        return CommandResult(args=tuple(args), returncode=0, stdout=json.dumps(payload), stderr="")

    backend = PVEQGADiscoveryBackend(runner=fake_runner)

    with caplog.at_level(logging.WARNING, logger="dnsleaf.discovery.parser"):
        result = backend.discover(TargetRef(kind=TargetKind.VM, id=201))

    assert result.error is None
    assert [candidate.cidr for candidate in result.candidates] == [
        "93.184.216.34/32",
        "2001:4860:abcd:1234::999/128",
    ]
    assert "Skipping QGA interface ens18 address item 1" in caplog.text
    assert "Skipping QGA interface ens18 address item 2" in caplog.text
    assert "Skipping QGA interface entry at index 1" in caplog.text
    assert "Skipping QGA interface ens19: ip-addresses must be a list" in caplog.text


def test_parse_qga_interfaces_rejects_malformed_top_level_payload() -> None:
    with pytest.raises(ValueError, match="payload must be a list"):
        parse_qga_interfaces({"result": "not-a-list"})
