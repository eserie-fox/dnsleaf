"""Thin orchestration from workspace entries to discovery, planning, and apply."""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from dnsleaf.config.outside_workspace import OutsideWorkspaceConfig
from dnsleaf.discovery.base import DiscoveryBackend
from dnsleaf.discovery.local_ip import LocalIPDiscoveryBackend
from dnsleaf.discovery.models import DiscoveryResult, SelectionResult
from dnsleaf.discovery.pve_lxc import PVELXCDiscoveryBackend
from dnsleaf.discovery.pve_qga import PVEQGADiscoveryBackend
from dnsleaf.discovery.selectors import select_address
from dnsleaf.dns.base import DNSProvider
from dnsleaf.dns.cloudflare import CloudflareDNSProvider
from dnsleaf.dns.models import DesiredRecord, cloudflare_effective_ttl
from dnsleaf.dns.planner import plan_dns_changes
from dnsleaf.models import EntrySourceKind, IPAddressFamily, TargetKind, TargetRef
from dnsleaf.workspace.models import ManagedRecordFile, ManagedRecordSnapshot, WorkspaceEntry
from dnsleaf.workspace.reports import PruneOutcome, RecordSyncOutcome, WorkspaceRunReport
from dnsleaf.workspace.state import enabled_dns_targets, stale_records_for_desired
from dnsleaf.workspace.storage import LoadedWorkspace


class SyncRunner:
    """Serial orchestration for discovery, DNS planning, and apply."""

    def __init__(
        self,
        *,
        outside_workspace_config: OutsideWorkspaceConfig | None = None,
        discovery_backends: dict[str, DiscoveryBackend] | None = None,
        provider_factory: Callable[[LoadedWorkspace], DNSProvider],
    ) -> None:
        self._outside_workspace_config = (
            outside_workspace_config or OutsideWorkspaceConfig.from_defaults()
        )
        self._discovery_backends = discovery_backends or {}
        self._provider_factory = provider_factory

    def discover_target(
        self,
        target: TargetRef,
        *,
        family: IPAddressFamily,
        policy: str = "default",
        loaded_workspace: LoadedWorkspace | None = None,
    ) -> tuple[DiscoveryResult, SelectionResult]:
        """Discover and select an address for one target family."""

        backend = self._backend_for_kind(target.kind, loaded_workspace=loaded_workspace)
        discovery = backend.discover(target)
        return discovery, select_discovered_address(discovery, family=family, policy=policy)

    def discover_target_families(
        self,
        target: TargetRef,
        *,
        families: tuple[IPAddressFamily, ...],
        policy: str = "default",
        loaded_workspace: LoadedWorkspace | None = None,
    ) -> tuple[DiscoveryResult, dict[IPAddressFamily, SelectionResult]]:
        """Discover once and select addresses for multiple families."""

        backend = self._backend_for_kind(target.kind, loaded_workspace=loaded_workspace)
        discovery = backend.discover(target)
        return discovery, {
            family: select_discovered_address(discovery, family=family, policy=policy)
            for family in families
        }

    def run(
        self,
        loaded: LoadedWorkspace,
        *,
        managed_state: ManagedRecordFile,
        apply: bool,
        prune_managed: bool,
    ) -> WorkspaceRunReport:
        """Plan and optionally apply one workspace run."""

        desired_targets = set(enabled_dns_targets(loaded.entries_file))
        provider = self._provider_factory(loaded)
        discoveries: dict[tuple[EntrySourceKind, int | None], DiscoveryResult] = {}
        record_outcomes = [
            outcome
            for entry in loaded.entries_file.enabled_entries()
            for outcome in self._plan_entry_records(provider, loaded, entry, discoveries)
        ]

        prune_outcomes: list[PruneOutcome] = []
        if prune_managed:
            for record in stale_records_for_desired(
                managed_state,
                desired_targets=desired_targets,
            ):
                prune_outcomes.append(self._plan_prune(provider, record))

        if apply:
            record_outcomes = [
                self._apply_record_outcome(provider, outcome) for outcome in record_outcomes
            ]
            prune_outcomes = [
                self._apply_prune_outcome(provider, outcome) for outcome in prune_outcomes
            ]

        return WorkspaceRunReport(
            workspace_name=loaded.resolved_workspace.workspace_name,
            dry_run=not apply,
            record_outcomes=record_outcomes,
            prune_outcomes=prune_outcomes,
        )

    def _plan_entry_records(
        self,
        provider: DNSProvider,
        loaded: LoadedWorkspace,
        entry: WorkspaceEntry,
        discoveries: dict[tuple[EntrySourceKind, int | None], DiscoveryResult],
    ) -> list[RecordSyncOutcome]:
        if entry.source_kind is EntrySourceKind.STATIC:
            return [
                self._plan_static_record(provider, loaded, entry, family)
                for family in entry.concrete_families()
            ]
        return self._plan_dynamic_records(provider, loaded, entry, discoveries)

    def _plan_dynamic_records(
        self,
        provider: DNSProvider,
        loaded: LoadedWorkspace,
        entry: WorkspaceEntry,
        discoveries: dict[tuple[EntrySourceKind, int | None], DiscoveryResult],
    ) -> list[RecordSyncOutcome]:
        target = entry.to_target_ref()
        key = (entry.source_kind, entry.source_id)
        if key not in discoveries:
            backend = self._backend_for_kind(target.kind, loaded_workspace=loaded)
            discoveries[key] = backend.discover(target)
        discovery = discoveries[key]
        selections = {
            family: select_discovered_address(
                discovery, family=family, policy=entry.selection_policy or "default"
            )
            for family in entry.concrete_families()
        }
        outcomes: list[RecordSyncOutcome] = []
        for family in entry.concrete_families():
            selection = selections[family]
            if discovery.error is not None:
                outcomes.append(
                    RecordSyncOutcome(
                        entry_name=entry.name,
                        source_kind=entry.source_kind,
                        source_id=entry.source_id,
                        family=family,
                        fqdn=entry.fqdn,
                        record_type=family.record_type,
                        value_source="dynamic",
                        discovery=discovery,
                        selection=selection,
                        selection_status=selection.status,
                        selection_reason=selection.reason,
                        status="error",
                        message=discovery.error,
                    )
                )
                continue

            if selection.selected is None:
                outcomes.append(
                    RecordSyncOutcome(
                        entry_name=entry.name,
                        source_kind=entry.source_kind,
                        source_id=entry.source_id,
                        family=family,
                        fqdn=entry.fqdn,
                        record_type=family.record_type,
                        value_source="dynamic",
                        discovery=discovery,
                        selection=selection,
                        selection_status=selection.status,
                        selection_reason=selection.reason,
                        status="skipped",
                        message=selection.reason,
                    )
                )
                continue

            outcomes.append(
                self._plan_desired_record(
                    provider=provider,
                    loaded=loaded,
                    entry=entry,
                    family=family,
                    value_source="dynamic",
                    value=selection.selected.address,
                    discovery=discovery,
                    selection=selection,
                    selection_status=selection.status,
                    selection_reason=selection.reason,
                )
            )
        return outcomes

    def _plan_static_record(
        self,
        provider: DNSProvider,
        loaded: LoadedWorkspace,
        entry: WorkspaceEntry,
        family: IPAddressFamily,
    ) -> RecordSyncOutcome:
        value = entry.static_value_for_family(family)
        if value is None:
            return RecordSyncOutcome(
                entry_name=entry.name,
                source_kind=entry.source_kind,
                source_id=entry.source_id,
                family=family,
                fqdn=entry.fqdn,
                record_type=family.record_type,
                value_source="static",
                selection_status="static",
                selection_reason="missing static value",
                status="error",
                message=f"static {family.value} value is missing",
            )
        return self._plan_desired_record(
            provider=provider,
            loaded=loaded,
            entry=entry,
            family=family,
            value_source="static",
            value=value,
            discovery=None,
            selection=None,
            selection_status="static",
            selection_reason="explicit static value",
        )

    def _plan_desired_record(
        self,
        *,
        provider: DNSProvider,
        loaded: LoadedWorkspace,
        entry: WorkspaceEntry,
        family: IPAddressFamily,
        value_source: Literal["dynamic", "static"],
        value: str,
        discovery: DiscoveryResult | None,
        selection: SelectionResult | None,
        selection_status: str | None,
        selection_reason: str | None,
    ) -> RecordSyncOutcome:
        proxied = entry.effective_proxied(loaded.resolved_workspace.default_proxied)
        desired = DesiredRecord(
            provider=loaded.resolved_workspace.provider,
            fqdn=entry.fqdn,
            record_type=family.record_type,
            value=value,
            ttl=cloudflare_effective_ttl(
                entry.effective_ttl(loaded.resolved_workspace.default_ttl),
                proxied,
            ),
            proxied=proxied,
        )

        try:
            current_records = provider.list_records(entry.fqdn, family.record_type)
            plan = plan_dns_changes(current_records=current_records, desired_record=desired)
        except Exception as exc:
            return RecordSyncOutcome(
                entry_name=entry.name,
                source_kind=entry.source_kind,
                source_id=entry.source_id,
                family=family,
                fqdn=entry.fqdn,
                record_type=family.record_type,
                value_source=value_source,
                discovery=discovery,
                selection=selection,
                selection_status=selection_status,
                selection_reason=selection_reason,
                selected_value=value,
                desired_record=desired,
                status="error",
                message=str(exc),
            )

        final_record = None
        if len(plan.changes) == 1 and plan.changes[0].action == "noop" and current_records:
            final_record = current_records[0]

        return RecordSyncOutcome(
            entry_name=entry.name,
            source_kind=entry.source_kind,
            source_id=entry.source_id,
            family=family,
            fqdn=entry.fqdn,
            record_type=family.record_type,
            value_source=value_source,
            discovery=discovery,
            selection=selection,
            selection_status=selection_status,
            selection_reason=selection_reason,
            selected_value=value,
            desired_record=desired,
            current_records=current_records,
            plan=plan,
            status="planned",
            message="changes planned" if plan.has_changes() else "already in sync",
            final_record=final_record,
        )

    def _plan_prune(self, provider: DNSProvider, record: ManagedRecordSnapshot) -> PruneOutcome:
        if record.record_id is None:
            return PruneOutcome(
                entry_name=record.entry_name,
                fqdn=record.fqdn,
                record_type=record.record_type,
                record_id=None,
                value=record.value,
                status="skipped",
                message="managed record has no record_id; prune is skipped safely",
            )

        try:
            current_records = provider.list_records(record.fqdn, record.record_type)
        except Exception as exc:
            return PruneOutcome(
                entry_name=record.entry_name,
                fqdn=record.fqdn,
                record_type=record.record_type,
                record_id=record.record_id,
                value=record.value,
                status="error",
                message=str(exc),
            )

        current_record = next(
            (item for item in current_records if item.record_id == record.record_id),
            None,
        )
        if current_record is None:
            return PruneOutcome(
                entry_name=record.entry_name,
                fqdn=record.fqdn,
                record_type=record.record_type,
                record_id=record.record_id,
                value=record.value,
                status="confirmed_absent",
                message="managed record is already absent from the provider",
            )

        plan = plan_dns_changes(current_records=[current_record], desired_record=None)
        return PruneOutcome(
            entry_name=record.entry_name,
            fqdn=record.fqdn,
            record_type=record.record_type,
            record_id=record.record_id,
            value=record.value,
            plan=plan,
            status="planned",
            message="managed record should be pruned",
        )

    def _apply_record_outcome(
        self,
        provider: DNSProvider,
        outcome: RecordSyncOutcome,
    ) -> RecordSyncOutcome:
        if outcome.plan is None or outcome.status != "planned":
            return outcome
        if not outcome.plan.has_changes():
            return outcome.model_copy(
                update={
                    "applied": False,
                    "final_record": outcome.final_record,
                    "message": "already in sync",
                }
            )

        final_record = outcome.final_record
        try:
            for change in outcome.plan.changes:
                if change.action == "noop":
                    if change.current is not None:
                        final_record = change.current
                    continue
                result = provider.apply_change(change)
                if result is not None:
                    final_record = result
        except Exception as exc:
            return outcome.model_copy(update={"status": "error", "message": str(exc)})

        return outcome.model_copy(
            update={
                "applied": True,
                "final_record": final_record,
                "message": "applied",
            }
        )

    def _apply_prune_outcome(
        self,
        provider: DNSProvider,
        outcome: PruneOutcome,
    ) -> PruneOutcome:
        if outcome.status == "confirmed_absent":
            return outcome
        if outcome.plan is None or outcome.status != "planned":
            return outcome
        try:
            for change in outcome.plan.changes:
                if change.action == "noop":
                    continue
                provider.apply_change(change)
        except Exception as exc:
            return outcome.model_copy(update={"status": "error", "message": str(exc)})
        return outcome.model_copy(
            update={"status": "applied", "applied": True, "message": "pruned"}
        )

    def _backend_for_kind(
        self,
        kind: TargetKind,
        *,
        loaded_workspace: LoadedWorkspace | None,
    ) -> DiscoveryBackend:
        timeout = (
            loaded_workspace.resolved_workspace.discovery.timeout_seconds
            if loaded_workspace is not None
            else self._outside_workspace_config.discovery.timeout_seconds
        )
        configured = self._discovery_backends.get(kind.value)
        if configured is not None:
            return configured
        if kind is TargetKind.LOCAL:
            return LocalIPDiscoveryBackend(timeout_seconds=timeout)
        if kind is TargetKind.LXC:
            if loaded_workspace is not None:
                return PVELXCDiscoveryBackend(
                    timeout_seconds=timeout,
                    pct_bin=loaded_workspace.resolved_workspace.paths.pct_bin,
                    shell_bin=loaded_workspace.resolved_workspace.paths.shell_bin,
                )
            return PVELXCDiscoveryBackend(
                timeout_seconds=timeout,
                pct_bin=self._outside_workspace_config.paths.pct_bin,
                shell_bin=self._outside_workspace_config.paths.shell_bin,
            )
        if kind is TargetKind.VM:
            if loaded_workspace is not None:
                return PVEQGADiscoveryBackend(
                    timeout_seconds=timeout,
                    qm_bin=loaded_workspace.resolved_workspace.paths.qm_bin,
                )
            return PVEQGADiscoveryBackend(
                timeout_seconds=timeout,
                qm_bin=self._outside_workspace_config.paths.qm_bin,
            )
        raise KeyError(f"no discovery backend registered for kind {kind.value}")


def build_runner(
    outside_workspace_config: OutsideWorkspaceConfig | None = None,
) -> SyncRunner:
    """Build the default workspace runner."""

    return SyncRunner(
        outside_workspace_config=outside_workspace_config,
        provider_factory=lambda loaded: _build_provider(loaded),
    )


def _build_provider(loaded: LoadedWorkspace) -> DNSProvider:
    if loaded.resolved_workspace.provider != "cloudflare":
        raise KeyError(f"unsupported DNS provider: {loaded.resolved_workspace.provider}")
    return CloudflareDNSProvider(loaded.resolved_workspace.cloudflare_provider_config())


def select_discovered_address(
    discovery: DiscoveryResult, *, family: IPAddressFamily, policy: str
) -> SelectionResult:
    """Select independently without changing the shared raw discovery snapshot."""

    if discovery.error is not None:
        return SelectionResult(
            target=discovery.target,
            family=family,
            policy=policy,
            status="no_candidate",
            selected=None,
            remaining_candidates=[],
            filtered_out=[],
            not_selected=[],
            reason=f"discovery failed: {discovery.error}",
        )
    return select_address(discovery, family=family, policy=policy)
