"""AliDNS provider stub."""

from __future__ import annotations

import httpx

from arbor_ddns.config import AliDNSProviderConfig
from arbor_ddns.dns.base import DNSProvider
from arbor_ddns.dns.models import DNSRecord, PlannedChange


class AliDNSProvider(DNSProvider):
    """AliDNS provider skeleton for future API integration."""

    name = "alidns"

    def __init__(
        self,
        config: AliDNSProviderConfig,
        *,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._config = config
        self._http_client = http_client or httpx.Client(timeout=10.0)

    def list_records(self, fqdn: str, record_type: str = "AAAA") -> list[DNSRecord]:
        raise NotImplementedError("AliDNS API integration is not implemented in phase 1")

    def apply_change(self, change: PlannedChange) -> DNSRecord | None:
        raise NotImplementedError("AliDNS API integration is not implemented in phase 1")

