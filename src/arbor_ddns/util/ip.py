"""IPv6 normalization and classification helpers."""

from __future__ import annotations

from ipaddress import IPv6Address, IPv6Interface, ip_network

ULA_NETWORK = ip_network("fc00::/7")


def parse_ipv6_interface(value: str) -> tuple[IPv6Address, int]:
    """Parse an IPv6 CIDR string into address and prefix length."""

    interface = IPv6Interface(value)
    return interface.ip, interface.network.prefixlen


def normalize_ipv6(value: str) -> str:
    """Return the canonical textual form of an IPv6 address."""

    return str(IPv6Address(value))


def is_unique_local(address: IPv6Address) -> bool:
    """Return whether the address is inside RFC 4193 space."""

    return address in ULA_NETWORK


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
    """Heuristic for privacy-style IPv6 addresses.

    The heuristic is intentionally conservative:
    - `/128` is treated as explicitly assigned and not privacy-style.
    - addresses with an embedded EUI-64 marker are treated as stable.
    - remaining global `/64`-style addresses are treated as temporary/privacy-like.
    """

    if prefix_length == 128:
        return False
    if has_embedded_eui64(address):
        return False
    return True

