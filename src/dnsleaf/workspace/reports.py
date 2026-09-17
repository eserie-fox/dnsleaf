"""Operation results and diagnostic reports, independent of service execution."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool

from dnsleaf.discovery.models import DiscoveryResult, SelectionResult
from dnsleaf.dns.models import DesiredRecord, DNSRecord, SyncPlan, cloudflare_effective_ttl
from dnsleaf.models import EntrySourceKind, IPAddressFamily
from dnsleaf.workspace.models import LastApplyState, ResolvedWorkspace, WorkspaceEntry


class DesiredRecordSpec(BaseModel):
    """Static desired-record declaration used by `render`."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    entry_name: str
    provider: str
    fqdn: str
    family: IPAddressFamily
    record_type: str
    ttl: int
    proxied: StrictBool | None = None
    source_kind: EntrySourceKind
    source_id: int | None
    selection_policy: str | None
    enabled: StrictBool
    value_source: Literal["dynamic", "static"]
    static_value: str | None = None
    description: str | None = None

    @classmethod
    def from_entry(
        cls,
        *,
        workspace: ResolvedWorkspace,
        entry: WorkspaceEntry,
    ) -> list[DesiredRecordSpec]:
        """Build renderable desired-record specs for one entry."""

        proxied = entry.effective_proxied(workspace.default_proxied)
        ttl = cloudflare_effective_ttl(entry.effective_ttl(workspace.default_ttl), proxied)
        return [
            cls(
                entry_name=entry.name,
                provider=workspace.provider,
                fqdn=entry.fqdn,
                family=family,
                record_type=family.record_type,
                ttl=ttl,
                proxied=proxied,
                source_kind=entry.source_kind,
                source_id=entry.source_id,
                selection_policy=entry.selection_policy,
                enabled=entry.enabled,
                value_source="static" if entry.source_kind is EntrySourceKind.STATIC else "dynamic",
                static_value=entry.static_value_for_family(family),
                description=entry.description,
            )
            for family in entry.concrete_families()
        ]

    def render_mapping(self) -> dict[str, object]:
        """Return the JSON mapping used for rendered desired-record output."""

        payload = self.model_dump(mode="json", exclude_none=True)
        payload["proxied"] = self.proxied
        return payload


class ValidationReport(BaseModel):
    """Successful workspace validation summary."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    workspace_root: str
    workspace_name: str
    provider: str
    zone_name: str
    zone_id: str | None
    token_file: str
    entry_count: int
    enabled_entry_count: int


class RenderArtifacts(BaseModel):
    """Render output summary."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    workspace_root: str
    workspace_name: str
    effective_workspace_file: str
    desired_records_file: str
    service_unit_file: str
    timer_unit_file: str
    desired_record_count: int


class EntryMutationResult(BaseModel):
    """Entry mutation result."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    operation: str
    changed: bool
    message: str
    entry: WorkspaceEntry | None = None
    removed_name: str | None = None


class SystemdUnitStatus(BaseModel):
    """systemd unit status summary."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    unit_name: str
    available: bool
    load_state: str | None = None
    unit_file_state: str | None = None
    active_state: str | None = None
    sub_state: str | None = None
    fragment_path: str | None = None
    note: str | None = None


class WorkspaceStatus(BaseModel):
    """Aggregated workspace status."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    workspace_root: str
    workspace_name: str | None
    provider: str | None
    zone_name: str | None
    zone_id: str | None
    token_file: str | None
    systemd_unit_dir: str | None = None
    entry_count: int
    enabled_entry_count: int
    rendered_artifacts: dict[str, bool]
    runtime_dir_exists: bool
    runtime_log_file: str | None
    runtime_log_file_exists: bool
    runtime_log_symlink_target: str | None = None
    managed_active_count: int
    managed_stale_count: int
    last_apply: LastApplyState | None = None
    service_status: SystemdUnitStatus
    timer_status: SystemdUnitStatus
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class DoctorCheck(BaseModel):
    """Single doctor check item."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    name: str
    status: Literal["ok", "warn", "error"]
    message: str


class DoctorReport(BaseModel):
    """Read-only health report for a workspace."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    workspace_root: str
    checks: list[DoctorCheck] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Return whether the report contains no error-level checks."""

        return all(check.status != "error" for check in self.checks)


class UninstallReport(BaseModel):
    """Workspace uninstall summary."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    workspace_root: str
    workspace_name: str | None
    service_name: str
    timer_name: str
    systemctl_available: bool
    service_stopped: bool = False
    timer_stopped: bool = False
    timer_disabled: bool = False
    service_unit_removed: bool = False
    timer_unit_removed: bool = False
    daemon_reloaded: bool = False
    service_reset_failed: bool = False
    timer_reset_failed: bool = False
    removed_paths: list[str] = Field(default_factory=list)
    kept_paths: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    purged: bool = False
    manual_cleanup_hint: str | None = None


class RecordSyncOutcome(BaseModel):
    """Outcome for one concrete record managed by a workspace entry."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

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

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

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

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

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


class ApplyReport(BaseModel):
    """Apply workflow summary."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    workspace_root: str
    workspace_name: str
    service_name: str
    timer_name: str
    installed_service_unit: str
    installed_timer_unit: str
    prune_managed: bool
    immediate_sync_requested: bool
    immediate_sync_ran: bool
    render: RenderArtifacts
    sync_report: WorkspaceRunReport | None = None
