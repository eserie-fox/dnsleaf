"""Thin orchestration from workspace entries to discovery, planning, and apply."""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from arbor_ddns.config import OutsideWorkspaceConfig
from arbor_ddns.discovery.base import DiscoveryBackend
from arbor_ddns.discovery.local_ip import LocalIPDiscoveryBackend
from arbor_ddns.discovery.models import DiscoveryResult, SelectionResult
from arbor_ddns.discovery.pve_lxc import PVELXCDiscoveryBackend
from arbor_ddns.discovery.pve_qga import PVEQGADiscoveryBackend
from arbor_ddns.discovery.selectors import select_address
from arbor_ddns.dns.base import DNSProvider
from arbor_ddns.dns.cloudflare import CloudflareDNSProvider
from arbor_ddns.dns.models import DesiredRecord, DNSRecord, SyncPlan
from arbor_ddns.dns.planner import plan_dns_changes
from arbor_ddns.models import EntrySourceKind, IPAddressFamily, TargetKind, TargetRef
from arbor_ddns.workspace.models import ManagedRecordFile, ManagedRecordSnapshot, WorkspaceEntry
from arbor_ddns.workspace.state import stale_records_for_desired
from arbor_ddns.workspace.storage import LoadedWorkspace


class RecordSyncOutcome(BaseModel):
    """Outcome for one concrete record managed by a workspace entry."""

    model_config = ConfigDict(extra="forbid")

    entry_name: str
    source_kind: EntrySourceKind
    source_id: int | None
    family: IPAddressFamily
    fqdn: str
    record_type: str
    value_source: Literal["dynamic", "static"]
    discovery: DiscoveryResult | None = None
    selection: SelectionResult | None = None
    selection_status: str | None = None
    selection_reason: str | None = None
    selected_value: str | None = None
    desired_record: DesiredRecord | None = None
    current_records: list[DNSRecord] = Field(default_factory=list)
    plan: SyncPlan | None = None
    status: str
    message: str
    applied: bool = False
    final_record: DNSRecord | None = None


class PruneOutcome(BaseModel):
    """Outcome for one managed-record prune candidate."""

    model_config = ConfigDict(extra="forbid")

    entry_name: str
    fqdn: str
    record_type: str
    record_id: str | None = None
    value: str
    status: str
    message: str
    plan: SyncPlan | None = None
    applied: bool = False


class WorkspaceRunReport(BaseModel):
    """Collection of concrete record outcomes and prune outcomes."""

    model_config = ConfigDict(extra="forbid")

    workspace_name: str
    dry_run: bool
    record_outcomes: list[RecordSyncOutcome] = Field(default_factory=list)
    prune_outcomes: list[PruneOutcome] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    def has_errors(self) -> bool:
        """Return whether any record or prune outcome failed."""

        return any(outcome.status == "error" for outcome in self.record_outcomes) or any(
            outcome.status == "error" for outcome in self.prune_outcomes
        )


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
        if discovery.error is not None:
            selection = SelectionResult(
                target=target,
                family=family,
                policy=policy,
                status="no_candidate",
                selected=None,
                remaining_candidates=[],
                filtered_out=[],
                not_selected=[],
                reason=f"discovery failed: {discovery.error}",
            )
            return discovery, selection
        return discovery, select_address(discovery, family=family, policy=policy)

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
        selections: dict[IPAddressFamily, SelectionResult] = {}
        for family in families:
            if discovery.error is not None:
                selections[family] = SelectionResult(
                    target=target,
                    family=family,
                    policy=policy,
                    status="no_candidate",
                    selected=None,
                    remaining_candidates=[],
                    filtered_out=[],
                    not_selected=[],
                    reason=f"discovery failed: {discovery.error}",
                )
                continue
            selections[family] = select_address(discovery, family=family, policy=policy)
        return discovery, selections

    def run(
        self,
        loaded: LoadedWorkspace,
        *,
        managed_state: ManagedRecordFile,
        apply: bool,
        prune_managed: bool,
    ) -> WorkspaceRunReport:
        """Plan and optionally apply one workspace run."""

        provider = self._provider_factory(loaded)
        record_outcomes = [
            outcome
            for entry in loaded.entries_file.enabled_entries()
            for outcome in self._plan_entry_records(provider, loaded, entry)
        ]

        prune_outcomes: list[PruneOutcome] = []
        if prune_managed:
            enabled_descriptors = {
                descriptor
                for entry in loaded.entries_file.enabled_entries()
                for descriptor in entry.descriptors()
            }
            for record in stale_records_for_desired(
                managed_state,
                enabled_descriptors=enabled_descriptors,
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
    ) -> list[RecordSyncOutcome]:
        if entry.source_kind is EntrySourceKind.STATIC:
            return [
                self._plan_static_record(provider, loaded, entry, family)
                for family in entry.concrete_families()
            ]
        return self._plan_dynamic_records(provider, loaded, entry)

    def _plan_dynamic_records(
        self,
        provider: DNSProvider,
        loaded: LoadedWorkspace,
        entry: WorkspaceEntry,
    ) -> list[RecordSyncOutcome]:
        target = entry.to_target_ref()
        discovery, selections = self.discover_target_families(
            target,
            families=entry.concrete_families(),
            policy=entry.selection_policy or "default",
            loaded_workspace=loaded,
        )
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
        desired = DesiredRecord(
            provider=loaded.resolved_workspace.provider,
            fqdn=entry.fqdn,
            record_type=family.record_type,
            value=value,
            ttl=entry.effective_ttl(loaded.resolved_workspace.default_ttl),
            proxied=entry.effective_proxied(loaded.resolved_workspace.default_proxied),
        )

        try:
            current_records = provider.list_records(entry.fqdn, family.record_type)
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

        plan = plan_dns_changes(current_records=current_records, desired_record=desired)
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
        configured = self._discovery_backends.get(kind.value)
        if configured is not None:
            return configured
        if kind is TargetKind.LOCAL:
            return LocalIPDiscoveryBackend()
        if kind is TargetKind.LXC:
            if loaded_workspace is not None:
                return PVELXCDiscoveryBackend(
                    pct_bin=loaded_workspace.resolved_workspace.paths.pct_bin,
                    shell_bin=loaded_workspace.resolved_workspace.paths.shell_bin,
                )
            return PVELXCDiscoveryBackend(
                pct_bin=self._outside_workspace_config.paths.pct_bin,
                shell_bin=self._outside_workspace_config.paths.shell_bin,
            )
        if kind is TargetKind.VM:
            if loaded_workspace is not None:
                return PVEQGADiscoveryBackend(
                    qm_bin=loaded_workspace.resolved_workspace.paths.qm_bin,
                )
            return PVEQGADiscoveryBackend(
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
