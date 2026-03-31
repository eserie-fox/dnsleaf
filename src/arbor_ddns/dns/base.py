"""DNS provider abstractions."""

from __future__ import annotations

from abc import ABC, abstractmethod

from arbor_ddns.dns.models import DNSRecord, PlannedChange, ProviderVerification, SyncPlan


class DNSProvider(ABC):
    """Abstract DNS provider interface."""

    name: str

    @abstractmethod
    def list_records(self, fqdn: str, record_type: str | None = None) -> list[DNSRecord]:
        """Return current records matching the target name and type."""

    @abstractmethod
    def apply_change(self, change: PlannedChange) -> DNSRecord | None:
        """Apply a single planned change."""

    @abstractmethod
    def verify(self) -> ProviderVerification:
        """Verify connectivity and permissions for the provider."""

    def apply_plan(self, plan: SyncPlan) -> list[DNSRecord | None]:
        """Apply all non-noop changes in order."""

        results: list[DNSRecord | None] = []
        for change in plan.changes:
            if change.action == "noop":
                continue
            results.append(self.apply_change(change))
        return results
