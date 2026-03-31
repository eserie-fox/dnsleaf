"""Thin orchestration from workspace entries to discovery, planning, and apply."""

from __future__ import annotations

from collections.abc import Callable

from pydantic import BaseModel, ConfigDict, Field

from arbor_ddns.config import AppConfig
from arbor_ddns.discovery.base import DiscoveryBackend
from arbor_ddns.discovery.models import DiscoveryResult, SelectionResult
from arbor_ddns.discovery.pve_lxc import PVELXCDiscoveryBackend
from arbor_ddns.discovery.pve_qga import PVEQGADiscoveryBackend
from arbor_ddns.discovery.selectors import select_address
from arbor_ddns.dns.base import DNSProvider
from arbor_ddns.dns.cloudflare import CloudflareDNSProvider
from arbor_ddns.dns.models import DesiredRecord, DNSRecord, SyncPlan
from arbor_ddns.dns.planner import plan_dns_changes
from arbor_ddns.models import TargetKind, TargetRef
from arbor_ddns.workspace.models import ManagedRecordFile, ManagedRecordSnapshot, WorkspaceEntry
from arbor_ddns.workspace.state import stale_records_for_desired
from arbor_ddns.workspace.storage import LoadedWorkspace


class EntrySyncOutcome(BaseModel):
    """Outcome for one managed workspace entry."""

    model_config = ConfigDict(extra="forbid")

    entry_name: str
    source_kind: TargetKind
    source_id: int
    fqdn: str
    record_type: str
    discovery: DiscoveryResult
    selection: SelectionResult
    selection_status: str
    selection_reason: str
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
    """Collection of per-entry and prune outcomes."""

    model_config = ConfigDict(extra="forbid")

    workspace_name: str
    dry_run: bool
    entry_outcomes: list[EntrySyncOutcome] = Field(default_factory=list)
    prune_outcomes: list[PruneOutcome] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    def has_errors(self) -> bool:
        """Return whether any entry or prune outcome failed."""

        return any(outcome.status == "error" for outcome in self.entry_outcomes) or any(
            outcome.status == "error" for outcome in self.prune_outcomes
        )


class SyncRunner:
    """Serial orchestration for discovery, DNS planning, and apply."""

    def __init__(
        self,
        *,
        app_config: AppConfig,
        discovery_backends: dict[str, DiscoveryBackend],
        provider_factory: Callable[[LoadedWorkspace], DNSProvider],
    ) -> None:
        self._app_config = app_config
        self._discovery_backends = discovery_backends
        self._provider_factory = provider_factory

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
        entry_outcomes = [
            self._plan_entry(provider, loaded, entry)
            for entry in loaded.entries_file.enabled_entries()
        ]

        prune_outcomes: list[PruneOutcome] = []
        if prune_managed:
            enabled_descriptors = {
                entry.descriptor for entry in loaded.entries_file.enabled_entries()
            }
            for record in stale_records_for_desired(
                managed_state,
                enabled_descriptors=enabled_descriptors,
            ):
                prune_outcomes.append(self._plan_prune(provider, record))

        if apply:
            entry_outcomes = [
                self._apply_entry_outcome(provider, outcome) for outcome in entry_outcomes
            ]
            prune_outcomes = [
                self._apply_prune_outcome(provider, outcome) for outcome in prune_outcomes
            ]

        return WorkspaceRunReport(
            workspace_name=loaded.resolved_workspace.workspace_name,
            dry_run=not apply,
            entry_outcomes=entry_outcomes,
            prune_outcomes=prune_outcomes,
        )

    def _plan_entry(
        self,
        provider: DNSProvider,
        loaded: LoadedWorkspace,
        entry: WorkspaceEntry,
    ) -> EntrySyncOutcome:
        discovery, selection = self.discover_target(
            entry.to_target_ref(),
            policy=entry.selection_policy,
        )
        if discovery.error is not None:
            return EntrySyncOutcome(
                entry_name=entry.name,
                source_kind=entry.source_kind,
                source_id=entry.source_id,
                fqdn=entry.fqdn,
                record_type=entry.record_type,
                discovery=discovery,
                selection=selection,
                selection_status=selection.status,
                selection_reason=selection.reason,
                status="error",
                message=discovery.error,
            )

        if selection.selected is None:
            return EntrySyncOutcome(
                entry_name=entry.name,
                source_kind=entry.source_kind,
                source_id=entry.source_id,
                fqdn=entry.fqdn,
                record_type=entry.record_type,
                discovery=discovery,
                selection=selection,
                selection_status=selection.status,
                selection_reason=selection.reason,
                status="skipped",
                message=selection.reason,
            )

        desired = DesiredRecord(
            provider=loaded.resolved_workspace.provider,
            fqdn=entry.fqdn,
            record_type=entry.record_type,
            value=selection.selected.address,
            ttl=entry.effective_ttl(loaded.resolved_workspace.default_ttl),
            proxied=entry.effective_proxied(loaded.resolved_workspace.default_proxied),
        )

        try:
            current_records = provider.list_records(entry.fqdn, entry.record_type)
        except Exception as exc:
            return EntrySyncOutcome(
                entry_name=entry.name,
                source_kind=entry.source_kind,
                source_id=entry.source_id,
                fqdn=entry.fqdn,
                record_type=entry.record_type,
                discovery=discovery,
                selection=selection,
                selection_status=selection.status,
                selection_reason=selection.reason,
                selected_value=selection.selected.address,
                desired_record=desired,
                status="error",
                message=str(exc),
            )

        plan = plan_dns_changes(current_records=current_records, desired_record=desired)
        final_record = None
        if len(plan.changes) == 1 and plan.changes[0].action == "noop" and current_records:
            final_record = current_records[0]

        return EntrySyncOutcome(
            entry_name=entry.name,
            source_kind=entry.source_kind,
            source_id=entry.source_id,
            fqdn=entry.fqdn,
            record_type=entry.record_type,
            discovery=discovery,
            selection=selection,
            selection_status=selection.status,
            selection_reason=selection.reason,
            selected_value=selection.selected.address,
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

    def _apply_entry_outcome(
        self,
        provider: DNSProvider,
        outcome: EntrySyncOutcome,
    ) -> EntrySyncOutcome:
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

    def _backend_for_kind(self, kind: TargetKind) -> DiscoveryBackend:
        try:
            return self._discovery_backends[kind.value]
        except KeyError as exc:
            raise KeyError(f"no discovery backend registered for kind {kind.value}") from exc


def build_runner(app_config: AppConfig) -> SyncRunner:
    """Build the default workspace runner."""

    discovery_backends: dict[str, DiscoveryBackend] = {
        TargetKind.LXC.value: PVELXCDiscoveryBackend(
            pct_bin=app_config.discovery.pct_bin,
            shell_bin=app_config.discovery.shell_bin,
        ),
        TargetKind.VM.value: PVEQGADiscoveryBackend(
            qm_bin=app_config.discovery.qm_bin,
        ),
    }
    return SyncRunner(
        app_config=app_config,
        discovery_backends=discovery_backends,
        provider_factory=lambda loaded: _build_provider(loaded),
    )


def _build_provider(loaded: LoadedWorkspace) -> DNSProvider:
    if loaded.resolved_workspace.provider != "cloudflare":
        raise KeyError(f"unsupported DNS provider: {loaded.resolved_workspace.provider}")
    return CloudflareDNSProvider(loaded.resolved_workspace.cloudflare_provider_config())
