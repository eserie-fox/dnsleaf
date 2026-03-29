from __future__ import annotations

import json

from arbor_ddns.discovery.pve_qga import PVEQGADiscoveryBackend
from arbor_ddns.models import TargetKind, TargetRef
from arbor_ddns.util.process import CommandResult


def test_pve_qga_backend_parses_network_interfaces() -> None:
    payload = {
        "result": [
            {
                "name": "ens18",
                "ip-addresses": [
                    {
                        "ip-address-type": "ipv6",
                        "ip-address": "2408:8266:5003:506a::458",
                        "prefix": 128,
                    },
                    {
                        "ip-address-type": "ipv6",
                        "ip-address": "2408:8266:5003:506a:e27f:4076:f737:e75a",
                        "prefix": 64,
                    },
                    {"ip-address-type": "ipv4", "ip-address": "192.0.2.10", "prefix": 24},
                ],
            }
        ]
    }

    def fake_runner(args):
        assert args == ["qm", "agent", "201", "network-get-interfaces"]
        return CommandResult(args=tuple(args), returncode=0, stdout=json.dumps(payload), stderr="")

    backend = PVEQGADiscoveryBackend(runner=fake_runner)

    result = backend.discover(TargetRef(kind=TargetKind.VM, id=201))

    assert result.error is None
    assert [candidate.cidr for candidate in result.candidates] == [
        "2408:8266:5003:506a::458/128",
        "2408:8266:5003:506a:e27f:4076:f737:e75a/64",
    ]
