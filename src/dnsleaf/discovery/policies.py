"""Selection-policy validation shared by configuration and discovery commands."""

from dnsleaf.models import IPAddressFamily


def validate_selection_policy(
    policy: str, *, source_kind: str, families: tuple[IPAddressFamily, ...]
) -> None:
    """Reject unsupported policies before discovery or provider construction."""

    if policy not in {"default", "windows-dhcpv6"}:
        raise ValueError(f"unsupported selection policy: {policy}")
    if policy == "windows-dhcpv6" and (source_kind != "vm" or IPAddressFamily.IPV6 not in families):
        raise ValueError("windows-dhcpv6 requires source_kind=vm and family=ipv6 or both")
