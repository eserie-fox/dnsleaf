"""Thin orchestration from inventory to discovery, selection, planning, and apply."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import cast

from arbor_ddns.config import AliDNSProviderConfig, AppConfig, CloudflareProviderConfig
from arbor_ddns.discovery.base import DiscoveryBackend
from arbor_ddns.discovery.models import DiscoveryResult, SelectionResult
from arbor_ddns.discovery.pve_lxc import PVELXCDiscoveryBackend
from arbor_ddns.discovery.pve_qga import PVEQGADiscoveryBackend
from arbor_ddns.discovery.selectors import select_address
from arbor_ddns.dns.alidns import AliDNSProvider
from arbor_ddns.dns.base import DNSProvider
from arbor_ddns.dns.cloudflare import CloudflareProvider
from arbor_ddns.dns.models import DesiredRecord, SyncPlan
from arbor_ddns.dns.planner import plan_dns_changes
from arbor_ddns.models import InventoryEntry, TargetKind, TargetRef


@dataclass(slots=True)
class EntrySyncOutcome:
    """Outcome for one inventory entry or ad hoc discovery target."""

    entry: InventoryEntry | None
    discovery: DiscoveryResult
    selection: SelectionResult
    plan: SyncPlan | None
    status: str
    message: str
    applied: bool = False


@dataclass(slots=True)
class RunReport:
    """Collection of per-entry outcomes."""

    outcomes: list[EntrySyncOutcome]
    dry_run: bool

    def has_errors(self) -> bool:
        return any(outcome.status == "error" for outcome in self.outcomes)


class SyncRunner:
    """Serial orchestration for discovery and DNS planning."""

    def __init__(
        self,
        *,
        config: AppConfig,
        discovery_backends: dict[str, DiscoveryBackend],
        provider_factory: Callable[[str], DNSProvider],
    ) -> None:
        self._config = config
        self._discovery_backends = discovery_backends
        self._provider_factory = provider_factory
        self._provider_cache: dict[str, DNSProvider] = {}

    def discover_target(
        self,
        target: TargetRef,
        *,
        policy: str = "default",
    ) -> tuple[DiscoveryResult, SelectionResult]:
        """Discover and select an address for a single target."""

        backend = self._backend_for_kind(target.kind)
        discovery = backend.discover(target)
        if discovery.error is not None:
            selection = SelectionResult(
                target=target,
                policy=policy,
                status="no_candidate",
                selected=None,
                remaining_candidates=[],
                filtered_out=[],
                not_selected=[],
                reason=f"discovery failed: {discovery.error}",
            )
            return discovery, selection
        return discovery, select_address(discovery, policy=policy)

    def plan_inventory(self) -> RunReport:
        """Plan DNS synchronization for all enabled inventory entries."""

        outcomes = [self.plan_entry(entry) for entry in self._config.inventory.enabled_entries()]
        return RunReport(outcomes=outcomes, dry_run=True)

    def plan_entry(self, entry: InventoryEntry) -> EntrySyncOutcome:
        """Plan DNS synchronization for a single entry."""

        discovery, selection = self.discover_target(
            entry.to_target_ref(),
            policy=entry.selection_policy,
        )
        if discovery.error is not None:
            return EntrySyncOutcome(
                entry=entry,
                discovery=discovery,
                selection=selection,
                plan=None,
                status="error",
                message=discovery.error,
            )

        if selection.selected is None:
            return EntrySyncOutcome(
                entry=entry,
                discovery=discovery,
                selection=selection,
                plan=None,
                status="skipped",
                message=selection.reason,
            )

        desired = DesiredRecord(
            provider=entry.provider,
            fqdn=entry.fqdn,
            record_type="AAAA",
            value=selection.selected.address,
            ttl=self._config.dns.default_ttl,
        )

        try:
            provider = self._provider_for_name(entry.provider)
            current_records = provider.list_records(entry.fqdn, "AAAA")
        except NotImplementedError as exc:
            return EntrySyncOutcome(
                entry=entry,
                discovery=discovery,
                selection=selection,
                plan=None,
                status="skipped",
                message=str(exc),
            )

        plan = plan_dns_changes(current_records=current_records, desired_record=desired)
        message = "changes planned" if plan.has_changes() else "already in sync"
        return EntrySyncOutcome(
            entry=entry,
            discovery=discovery,
            selection=selection,
            plan=plan,
            status="planned",
            message=message,
        )

    def sync_once(self, *, apply: bool = False) -> RunReport:
        """Plan and optionally apply all enabled inventory entries."""

        report = self.plan_inventory()
        if not apply:
            return report

        applied_outcomes: list[EntrySyncOutcome] = []
        for outcome in report.outcomes:
            if outcome.entry is None or outcome.plan is None or not outcome.plan.has_changes():
                applied_outcomes.append(outcome)
                continue
            provider = self._provider_for_name(outcome.entry.provider)
            provider.apply_plan(outcome.plan)
            applied_outcomes.append(replace(outcome, applied=True, message="applied"))
        return RunReport(outcomes=applied_outcomes, dry_run=False)

    def _backend_for_kind(self, kind: TargetKind) -> DiscoveryBackend:
        try:
            return self._discovery_backends[kind.value]
        except KeyError as exc:
            raise KeyError(f"no discovery backend registered for kind {kind.value}") from exc

    def _provider_for_name(self, provider_name: str) -> DNSProvider:
        if provider_name not in self._provider_cache:
            self._provider_cache[provider_name] = self._provider_factory(provider_name)
        return self._provider_cache[provider_name]


def build_runner(config: AppConfig) -> SyncRunner:
    """Build the default serial runner from raw app config."""

    discovery_backends: dict[str, DiscoveryBackend] = {
        TargetKind.LXC.value: PVELXCDiscoveryBackend(
            pct_bin=config.discovery.pct_bin,
            shell_bin=config.discovery.shell_bin,
        ),
        TargetKind.VM.value: PVEQGADiscoveryBackend(
            qm_bin=config.discovery.qm_bin,
        ),
    }
    return SyncRunner(
        config=config,
        discovery_backends=discovery_backends,
        provider_factory=lambda provider_name: _build_provider(config, provider_name),
    )


def _build_provider(config: AppConfig, provider_name: str) -> DNSProvider:
    provider_config = config.provider_config(provider_name)
    if provider_name == "alidns":
        return AliDNSProvider(cast(AliDNSProviderConfig, provider_config))
    if provider_name == "cloudflare":
        return CloudflareProvider(cast(CloudflareProviderConfig, provider_config))
    raise KeyError(f"unknown provider: {provider_name}")
