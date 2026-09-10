"""Parsers for discovery command outputs."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from dnsleaf.discovery.models import AddressCandidate
from dnsleaf.models import IPAddressFamily
from dnsleaf.util.ip import parse_ip_interface

LOGGER = logging.getLogger(__name__)
_ADDRESS_RECORD_RE = re.compile(r"^\d+:\s+(?P<interface>\S+)(?P<rest>.*)$")
_TAIL_METADATA_KEYS = {"brd", "metric", "peer", "preferred_lft", "proto", "valid_lft"}


def parse_ip_addr_output(output: str, *, source: str = "ip_addr") -> list[AddressCandidate]:
    """Parse Linux `ip -o addr show` output."""

    candidates: list[AddressCandidate] = []
    for interface, record in _normalize_ip_addr_records(output):
        parsed = _parse_ip_addr_record(record, interface=interface)
        if parsed is None:
            continue
        address, prefix_length, family, scope, flags = parsed
        candidates.append(
            AddressCandidate(
                family=IPAddressFamily(family),
                interface=interface,
                address=str(address),
                prefix_length=prefix_length,
                source=source,
                scope=scope,
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

    data = _unwrap_qga_payload(payload)
    candidates: list[AddressCandidate] = []
    for interface_index, interface_data in enumerate(data):
        candidates.extend(
            _parse_qga_interface_entry(
                interface_data,
                interface_index=interface_index,
                source=source,
            )
        )
    return candidates


def _unwrap_qga_payload(payload: str | dict[str, Any] | list[dict[str, Any]]) -> list[Any]:
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
    return data


def _parse_qga_interface_entry(
    interface_data: Any,
    *,
    interface_index: int,
    source: str,
) -> list[AddressCandidate]:
    if not isinstance(interface_data, dict):
        LOGGER.warning(
            "Skipping QGA interface entry at index %s: expected object, got %s",
            interface_index,
            type(interface_data).__name__,
        )
        return []

    interface_name = str(
        interface_data.get("name")
        or interface_data.get("interface-name")
        or interface_data.get("device")
        or f"interface#{interface_index}"
    )
    ip_addresses = interface_data.get("ip-addresses", [])
    if not isinstance(ip_addresses, list):
        LOGGER.warning(
            "Skipping QGA interface %s: ip-addresses must be a list",
            interface_name,
        )
        return []

    candidates: list[AddressCandidate] = []
    for address_index, ip_data in enumerate(ip_addresses):
        candidate = _parse_qga_address_item(
            interface_name,
            address_index=address_index,
            ip_data=ip_data,
            source=source,
        )
        if candidate is not None:
            candidates.append(candidate)
    return candidates


def _parse_qga_address_item(
    interface_name: str,
    *,
    address_index: int,
    ip_data: Any,
    source: str,
) -> AddressCandidate | None:
    if not isinstance(ip_data, dict):
        LOGGER.warning(
            "Skipping QGA interface %s address item %s: expected object, got %s",
            interface_name,
            address_index,
            type(ip_data).__name__,
        )
        return None

    ip_address_type = ip_data.get("ip-address-type")
    if ip_address_type not in {"ipv4", "ipv6"}:
        return None

    address = ip_data.get("ip-address")
    prefix = ip_data.get("prefix")
    if not isinstance(address, str) or not isinstance(prefix, int):
        LOGGER.warning(
            "Skipping QGA interface %s address item %s: %s entry is missing address/prefix",
            interface_name,
            address_index,
            ip_address_type,
        )
        return None

    try:
        parsed_address, prefix_length, family = parse_ip_interface(f"{address}/{prefix}")
    except ValueError as exc:
        LOGGER.warning(
            "Skipping QGA interface %s address item %s: %s",
            interface_name,
            address_index,
            exc,
        )
        return None

    return AddressCandidate(
        family=IPAddressFamily(family),
        interface=interface_name,
        address=str(parsed_address),
        prefix_length=prefix_length,
        source=source,
        scope=None,
        flags=[],
    )


def _normalize_ip_addr_records(output: str) -> list[tuple[str, str]]:
    records: list[tuple[str, str]] = []
    current_interface: str | None = None
    current_record: str | None = None

    def flush_current() -> None:
        nonlocal current_record
        if current_interface is None or current_record is None:
            current_record = None
            return
        records.append((current_interface, current_record.replace("\\", " ").strip()))
        current_record = None

    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        header_match = _ADDRESS_RECORD_RE.match(line)
        if header_match is not None:
            flush_current()
            current_interface = (
                header_match.group("interface").split("@", maxsplit=1)[0].rstrip(":")
            )
            remainder = header_match.group("rest").strip()
            if _contains_address_tokens(remainder):
                normalized_remainder = remainder.rstrip("\\").rstrip()
                current_record = f"{current_interface} {normalized_remainder}"
            continue

        if current_interface is None:
            continue

        if line.startswith(("inet ", "inet6 ")):
            flush_current()
            normalized_line = line.rstrip("\\").rstrip()
            current_record = f"{current_interface} {normalized_line}"
            continue

        if current_record is None:
            continue

        normalized_record = current_record.rstrip("\\").rstrip()
        normalized_continuation = line.lstrip("\\").strip()
        current_record = f"{normalized_record} {normalized_continuation}"

    flush_current()
    return records


def _contains_address_tokens(line: str) -> bool:
    tokens = line.split()
    return any(token in {"inet", "inet6"} for token in tokens)


def _parse_ip_addr_record(
    line: str,
    *,
    interface: str,
) -> tuple[object, int, str, str | None, list[str]] | None:
    tokens = line.split()
    kind_index = next((idx for idx, token in enumerate(tokens) if token in {"inet", "inet6"}), -1)
    if kind_index < 0:
        if _contains_address_tokens(line):
            raise ValueError(f"unable to parse ip addr output line: {line}")
        return None
    if kind_index + 1 >= len(tokens):
        raise ValueError(f"unable to parse ip addr output line: {line}")

    cidr = tokens[kind_index + 1]
    address, prefix_length, family = parse_ip_interface(cidr)
    scope, flags = _parse_ip_addr_tail(tokens[kind_index + 2 :], interface=interface)
    return address, prefix_length, family, scope, flags


def _parse_ip_addr_tail(tokens: list[str], *, interface: str) -> tuple[str | None, list[str]]:
    scope: str | None = None
    flags: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index].rstrip("\\")
        if not token:
            index += 1
            continue
        if token == "scope" and index + 1 < len(tokens):
            scope = tokens[index + 1].rstrip("\\")
            index += 2
            continue
        if token in _TAIL_METADATA_KEYS:
            index += 2
            continue
        if token == interface:
            index += 1
            continue
        flags.append(token)
        index += 1
    return scope, flags
