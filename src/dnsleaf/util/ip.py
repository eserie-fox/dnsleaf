"""IP normalization and classification helpers."""

from __future__ import annotations

from ipaddress import (
    IPv4Address,
    IPv6Address,
    IPv6Interface,
    ip_address,
    ip_interface,
    ip_network,
)
from typing import Literal

CGNAT_NETWORK = ip_network("100.64.0.0/10")
ULA_NETWORK = ip_network("fc00::/7")


def parse_ip_interface(
    value: str,
) -> tuple[IPv4Address | IPv6Address, int, Literal["ipv4", "ipv6"]]:
    """Parse a CIDR string into address, prefix length, and family."""

    interface = ip_interface(value)
    family = family_for_ip(interface.ip)
    return interface.ip, interface.network.prefixlen, family


def normalize_ip(value: str) -> str:
    """Return the canonical textual form of an IP address."""

    return str(ip_address(value))


def family_for_ip(value: IPv4Address | IPv6Address) -> Literal["ipv4", "ipv6"]:
    """Return the family for a concrete IP address object."""

    if isinstance(value, IPv4Address):
        return "ipv4"
    return "ipv6"


def family_for_record_type(record_type: str) -> Literal["ipv4", "ipv6"]:
    """Map a DNS record type to its IP family."""

    normalized = record_type.strip().upper()
    if normalized == "A":
        return "ipv4"
    if normalized == "AAAA":
        return "ipv6"
    raise ValueError(f"unsupported record type for IP family: {record_type}")


def record_type_for_family(family: Literal["ipv4", "ipv6"] | str) -> str:
    """Map an IP family to its DNS record type."""

    if family == "ipv4":
        return "A"
    return "AAAA"


def is_unique_local(address: IPv6Address) -> bool:
    """Return whether the address is inside RFC 4193 space."""

    return address in ULA_NETWORK


def is_cgnat(address: IPv4Address) -> bool:
    """Return whether the address is inside RFC 6598 shared space."""

    return address in CGNAT_NETWORK


def unusable_ipv4_reason(address: IPv4Address) -> str | None:
    """Return a selector-facing reason if an address should not become DNS A."""

    if address.is_loopback:
        return "loopback"
    if address.is_link_local:
        return "link_local"
    if address.is_multicast:
        return "multicast"
    if address.is_unspecified:
        return "unspecified"
    if is_cgnat(address):
        return "shared"
    if address.is_private:
        return "private"
    if not address.is_global:
        return "not_global"
    return None


def unusable_ipv6_reason(address: IPv6Address) -> str | None:
    """Return a selector-facing reason if an address should not become DNS AAAA."""

    if address.is_loopback:
        return "loopback"
    if address.is_link_local:
        return "link_local"
    if is_unique_local(address):
        return "unique_local"
    if address.is_multicast:
        return "multicast"
    if address.is_unspecified:
        return "unspecified"
    if not address.is_global:
        return "not_global"
    return None


def has_embedded_eui64(address: IPv6Address) -> bool:
    """Detect the classic MAC-derived ff:fe pattern in the IID."""

    interface_identifier = address.packed[8:]
    return interface_identifier[3:5] == b"\xff\xfe"


def looks_temporary_or_privacy(address: IPv6Address, prefix_length: int) -> bool:
    """Heuristic for privacy-style IPv6 addresses."""

    if prefix_length == 128:
        return False
    if has_embedded_eui64(address):
        return False
    return True


def parse_ipv6_interface(value: str) -> tuple[IPv6Address, int]:
    """Parse an IPv6 CIDR string into address and prefix length."""

    interface = IPv6Interface(value)
    return interface.ip, interface.network.prefixlen


def normalize_ipv6(value: str) -> str:
    """Return the canonical textual form of an IPv6 address."""

    return normalize_ip(value)
