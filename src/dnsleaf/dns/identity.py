"""Canonical DNS target identity shared by validation and state."""


def dns_target(fqdn: str, record_type: str) -> tuple[str, str]:
    """Identify a DNS target within the workspace's configured zone."""

    return fqdn.strip().rstrip(".").lower(), record_type.strip().upper()
