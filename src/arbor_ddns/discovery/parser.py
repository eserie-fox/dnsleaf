"""Parsers for PVE discovery command outputs."""

from __future__ import annotations

import json
import re
from typing import Any

from arbor_ddns.discovery.models import AddressCandidate
from arbor_ddns.models import IPAddressFamily
from arbor_ddns.util.ip import parse_ip_interface

IP_ADDR_LINE_RE = re.compile(
    r"^\d+:\s+(?P<interface>\S+)\s+"
    r"(?P<kind>inet|inet6)\s+"
    r"(?P<cidr>[^ ]+/\d+)\s+scope\s+"
    r"(?P<scope>\S+)(?:\s+(?P<flags>.*))?$"
)


def parse_lxc_ip_addr_output(output: str, *, source: str = "pve_lxc") -> list[AddressCandidate]:
    """Parse `ip -o addr show` output from an LXC guest."""

    candidates: list[AddressCandidate] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = IP_ADDR_LINE_RE.match(line)
        if match is None:
            raise ValueError(f"unable to parse ip addr output line: {line}")
        address, prefix_length, family = parse_ip_interface(match.group("cidr"))
        flags_text = match.group("flags") or ""
        flags = [flag for flag in flags_text.split() if flag]
        candidates.append(
            AddressCandidate(
                family=IPAddressFamily(family),
                interface=match.group("interface").split("@", maxsplit=1)[0],
                address=str(address),
                prefix_length=prefix_length,
                source=source,
                scope=match.group("scope"),
                flags=flags,
            )
        )
    return candidates


def parse_qga_interfaces(
    payload: str | dict[str, Any] | list[dict[str, Any]],
    *,
    source: str = "pve_qga",
) -> list[AddressCandidate]:
    """Parse `qm agent ... network-get-interfaces` output."""

    data: Any
    if isinstance(payload, str):
        data = json.loads(payload)
    else:
        data = payload

    if isinstance(data, dict):
        if "result" in data:
            data = data["result"]
        elif "return" in data:
            data = data["return"]

    if not isinstance(data, list):
        raise ValueError("QGA network-get-interfaces payload must be a list")

    candidates: list[AddressCandidate] = []
    for interface_data in data:
        if not isinstance(interface_data, dict):
            raise ValueError("QGA interface entry must be an object")
        interface_name = str(
            interface_data.get("name")
            or interface_data.get("interface-name")
            or interface_data.get("device")
            or "unknown"
        )
        ip_addresses = interface_data.get("ip-addresses", [])
        if not isinstance(ip_addresses, list):
            raise ValueError("QGA ip-addresses entry must be a list")
        for ip_data in ip_addresses:
            if not isinstance(ip_data, dict):
                raise ValueError("QGA ip-addresses item must be an object")
            ip_address_type = ip_data.get("ip-address-type")
            if ip_address_type not in {"ipv4", "ipv6"}:
                continue
            address = ip_data.get("ip-address")
            prefix = ip_data.get("prefix")
            if not isinstance(address, str) or not isinstance(prefix, int):
                raise ValueError(
                    f"QGA {ip_address_type} address entry is missing address/prefix"
                )
            parsed_address, prefix_length, family = parse_ip_interface(f"{address}/{prefix}")
            candidates.append(
                AddressCandidate(
                    family=IPAddressFamily(family),
                    interface=interface_name,
                    address=str(parsed_address),
                    prefix_length=prefix_length,
                    source=source,
                    scope=None,
                    flags=[],
                )
            )
    return candidates
