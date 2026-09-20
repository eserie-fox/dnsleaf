"""Synthetic Windows inventories and a fake PVE transport, with no live Guest data."""

from __future__ import annotations

import json
from collections.abc import Sequence
from ipaddress import ip_address
from typing import Any

from dnsleaf.discovery.models import DiscoveryResult
from dnsleaf.discovery.parser import parse_qga_interfaces
from dnsleaf.models import TargetKind, TargetRef
from dnsleaf.util.process import CommandResult, CommandTimeoutError

DHCP = "2001:4860:1234::a"
RANDOM = "2001:4860:1234::b"
LINK = "2001:4860:1234::c"
MAC = "52:54:00:12:34:56"


def synthetic_inventory() -> DiscoveryResult:
    values = [(DHCP, 128), (RANDOM, 128), (LINK, 64), ("fe80::1", 64), ("::1", 128)]
    assert all(ip_address(value).is_global for value, _ in values[:3])
    return DiscoveryResult(
        target=TargetRef(kind=TargetKind.VM, id=201),
        backend="pve_qga",
        candidates=parse_qga_interfaces(
            [
                {
                    "name": "Ethernet 以太网",
                    "hardware-address": MAC,
                    "ip-addresses": [
                        {"ip-address": value, "ip-address-type": "ipv6", "prefix": prefix}
                        for value, prefix in values
                    ],
                }
            ]
        ),
    )


def synthetic_metadata() -> list[dict[str, Any]]:
    return [
        {
            "IPAddress": c.address,
            "PrefixLength": c.prefix_length,
            "InterfaceIndex": 12,
            "InterfaceAlias": "Ethernet 以太网",
            "HardwareAddress": MAC.replace(":", "-"),
            "PrefixOrigin": "Dhcp" if c.address == DHCP else "RouterAdvertisement",
            "SuffixOrigin": "Dhcp"
            if c.address == DHCP
            else "Random"
            if c.address == RANDOM
            else "Link",
            "AddressState": "Preferred",
            "SkipAsSource": False,
        }
        for c in synthetic_inventory().candidates
    ]


def metadata_wire(records: object) -> str:
    return json.dumps(
        {
            "exited": 1,
            "exitcode": 0,
            "out-data": json.dumps({"addresses": records}, ensure_ascii=True),
        }
    )


class SyntheticWindowsCommands:
    def __init__(self) -> None:
        self.raw = synthetic_inventory()
        self.records = synthetic_metadata()
        self.metadata_output: str | None = None
        self.host_error = ""
        self.expire = False
        self.calls: list[tuple[str, ...]] = []
        self.timeouts: list[float | None] = []

    def __call__(
        self, args: Sequence[str], *, check: bool = True, timeout: float | None = None
    ) -> CommandResult:
        self.calls.append(tuple(args))
        self.timeouts.append(timeout)
        if args[1] == "agent":
            interfaces: dict[tuple[str, str | None], dict[str, Any]] = {}
            for c in self.raw.candidates:
                interface = interfaces.setdefault(
                    (c.interface, c.hardware_address),
                    {
                        "name": c.interface,
                        "hardware-address": c.hardware_address,
                        "ip-addresses": [],
                    },
                )
                interface["ip-addresses"].append(
                    {
                        "ip-address": c.address,
                        "ip-address-type": c.family.value,
                        "prefix": c.prefix_length,
                    }
                )
            return CommandResult(tuple(args), 0, json.dumps(list(interfaces.values())), "")
        assert list(args[1:3]) == ["guest", "exec"]
        if self.expire:
            raise CommandTimeoutError(args, timeout)
        return CommandResult(
            tuple(args),
            1 if self.host_error else 0,
            self.metadata_output
            if self.metadata_output is not None
            else metadata_wire(self.records),
            self.host_error,
        )
