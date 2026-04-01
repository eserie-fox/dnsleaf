"""Workspace models and reports."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from arbor_ddns.config.merge import deep_merge
from arbor_ddns.config.scaffold import (
    load_entries_scaffold_defaults,
    load_workspace_scaffold_defaults,
)
from arbor_ddns.config.shared import DiscoveryCommandPaths
from arbor_ddns.dns.cloudflare import CloudflareProviderConfig
from arbor_ddns.logging.config import ArborDDNSLoggingConfig, ResolvedArborDDNSLoggingConfig
from arbor_ddns.models import EntryAddressFamily, EntrySourceKind, IPAddressFamily, TargetRef
from arbor_ddns.util.ip import normalize_ip

WORKSPACE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
ENTRY_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def _validate_name(value: str, *, pattern: re.Pattern[str], field_name: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{field_name} must not be blank")
    if pattern.fullmatch(stripped) is None:
        raise ValueError(
            f"{field_name} must match {pattern.pattern} and remain stable for file/state usage"
        )
    return stripped


class WorkspaceSystemdConfig(BaseModel):
    """Workspace-level systemd settings."""

    model_config = ConfigDict(extra="forbid")

    service_name: str | None = None
    timer_name: str | None = None
    on_boot_sec: str
    on_unit_active_sec: str
    run_sync_after_apply: bool

    @field_validator("service_name", "timer_name")
    @classmethod
    def _strip_optional_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("on_boot_sec", "on_unit_active_sec")
    @classmethod
    def _validate_non_empty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("systemd duration values must not be blank")
        return stripped

    def resolved_service_name(self, workspace_name: str) -> str:
        """Return the effective systemd service name."""

        return self.service_name or f"arbor-ddns-{workspace_name}"

    def resolved_timer_name(self, workspace_name: str) -> str:
        """Return the effective systemd timer name."""

        return self.timer_name or f"arbor-ddns-{workspace_name}"


class WorkspaceApplyConfig(BaseModel):
    """Workspace-level apply settings."""

    model_config = ConfigDict(extra="forbid")

    prune_managed_records: bool


class WorkspaceRuntimePaths(DiscoveryCommandPaths):
    """Workspace-scoped execution paths and command locations."""

    systemctl_bin: str
    systemd_unit_dir: str

    @field_validator("systemctl_bin", "systemd_unit_dir")
    @classmethod
    def _validate_non_empty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("workspace paths values must not be blank")
        return stripped

    def resolved_systemd_unit_dir(self, workspace_root: Path) -> Path:
        """Resolve the configured systemd unit directory against the workspace root."""

        raw_path = Path(self.systemd_unit_dir).expanduser()
        if raw_path.is_absolute():
            return raw_path.resolve()
        return (workspace_root / raw_path).resolve()

    def resolve(self, workspace_root: Path) -> ResolvedWorkspaceRuntimePaths:
        """Resolve runtime-only path values."""

        return ResolvedWorkspaceRuntimePaths(
            pct_bin=self.pct_bin,
            qm_bin=self.qm_bin,
            shell_bin=self.shell_bin,
            systemctl_bin=self.systemctl_bin,
            systemd_unit_dir=str(self.resolved_systemd_unit_dir(workspace_root)),
        )


class WorkspaceConfig(BaseModel):
    """User-maintained workspace source config."""

    model_config = ConfigDict(extra="forbid")

    config_version: int
    workspace_name: str
    provider: str
    zone_name: str
    zone_id: str | None = None
    api_token_file: str
    default_ttl: int = Field(ge=1)
    default_proxied: bool
    paths: WorkspaceRuntimePaths
    systemd: WorkspaceSystemdConfig
    apply: WorkspaceApplyConfig
    arbor_ddns_logging: ArborDDNSLoggingConfig

    @field_validator("config_version")
    @classmethod
    def _validate_config_version(cls, value: int) -> int:
        if value != 3:
            raise ValueError("workspace config_version must be exactly 3")
        return value

    @field_validator("workspace_name")
    @classmethod
    def _validate_workspace_name(cls, value: str) -> str:
        return _validate_name(value, pattern=WORKSPACE_NAME_RE, field_name="workspace_name")

    @field_validator("provider")
    @classmethod
    def _validate_provider(cls, value: str) -> str:
        stripped = value.strip()
        if stripped != "cloudflare":
            raise ValueError("workspace provider must be cloudflare")
        return stripped

    @field_validator("zone_name", "api_token_file")
    @classmethod
    def _validate_non_empty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("value must not be blank")
        return stripped

    @field_validator("zone_id")
    @classmethod
    def _strip_optional_zone_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    def resolved_api_token_file(self, workspace_root: Path) -> Path:
        """Resolve the token file path relative to the workspace root."""

        raw_path = Path(self.api_token_file).expanduser()
        if raw_path.is_absolute():
            return raw_path
        return (workspace_root / raw_path).resolve()

    def resolved_service_name(self) -> str:
        """Return the effective systemd service name."""

        return self.systemd.resolved_service_name(self.workspace_name)

    def resolved_timer_name(self) -> str:
        """Return the effective systemd timer name."""

        return self.systemd.resolved_timer_name(self.workspace_name)

    @classmethod
    def scaffold_defaults(cls, workspace_name: str) -> WorkspaceConfig:
        """Build the typed default `workspace.yaml` model for one workspace name."""

        workspace_mapping = deep_merge(
            load_workspace_scaffold_defaults(),
            {"workspace_name": workspace_name},
        )
        return cls.model_validate(workspace_mapping)

    def resolve(self, workspace_root: Path) -> ResolvedWorkspace:
        """Resolve runtime-only workspace values."""

        return ResolvedWorkspace(
            workspace_root=str(workspace_root.resolve()),
            workspace_name=self.workspace_name,
            provider=self.provider,
            zone_name=self.zone_name,
            zone_id=self.zone_id,
            api_token_file=str(self.resolved_api_token_file(workspace_root)),
            default_ttl=self.default_ttl,
            default_proxied=self.default_proxied,
            paths=self.paths.resolve(workspace_root),
            systemd=ResolvedWorkspaceSystemdConfig(
                service_name=self.resolved_service_name(),
                timer_name=self.resolved_timer_name(),
                on_boot_sec=self.systemd.on_boot_sec,
                on_unit_active_sec=self.systemd.on_unit_active_sec,
                run_sync_after_apply=self.systemd.run_sync_after_apply,
            ),
            apply=self.apply,
            arbor_ddns_logging=self.arbor_ddns_logging.resolve(workspace_root),
        )


class WorkspaceEntry(BaseModel):
    """User-maintained entry config."""

    model_config = ConfigDict(extra="forbid")

    name: str
    source_kind: EntrySourceKind
    family: EntryAddressFamily
    fqdn: str
    enabled: bool
    source_id: int | None = Field(default=None, ge=1)
    selection_policy: str | None = None
    ttl: int | None = Field(default=None, ge=1)
    proxied: bool | None = None
    description: str | None = None
    static_ipv4: str | None = None
    static_ipv6: str | None = None

    @field_validator("name")
    @classmethod
    def _validate_entry_name(cls, value: str) -> str:
        return _validate_name(value, pattern=ENTRY_NAME_RE, field_name="entry name")

    @field_validator("fqdn")
    @classmethod
    def _validate_fqdn(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("fqdn must not be blank")
        return stripped

    @field_validator("selection_policy")
    @classmethod
    def _normalize_selection_policy(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("description")
    @classmethod
    def _strip_optional_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("static_ipv4", "static_ipv6")
    @classmethod
    def _normalize_static_ip(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            return None
        return normalize_ip(stripped)

    @model_validator(mode="after")
    def _validate_source_shape(self) -> Self:
        if self.source_kind is EntrySourceKind.STATIC:
            if self.source_id is not None:
                raise ValueError("static entries must not define source_id")
            if self.selection_policy is not None:
                raise ValueError("static entries must not define selection_policy")
            if (
                self.family in {EntryAddressFamily.IPV4, EntryAddressFamily.BOTH}
                and self.static_ipv4 is None
            ):
                raise ValueError("static_ipv4 is required for static ipv4/both entries")
            if (
                self.family in {EntryAddressFamily.IPV6, EntryAddressFamily.BOTH}
                and self.static_ipv6 is None
            ):
                raise ValueError("static_ipv6 is required for static ipv6/both entries")
        else:
            if self.source_id is None:
                raise ValueError("dynamic lxc/vm entries require source_id")
            if self.selection_policy is None:
                raise ValueError("dynamic lxc/vm entries require selection_policy")
            if self.static_ipv4 is not None or self.static_ipv6 is not None:
                raise ValueError("dynamic lxc/vm entries must not define static IP values")
        return self

    def to_target_ref(self) -> TargetRef:
        """Return the discovery target for this entry."""

        if self.source_id is None:
            raise ValueError("static entries do not have a discovery target")
        return TargetRef(kind=self.source_kind.to_target_kind(), id=self.source_id)

    def effective_ttl(self, default_ttl: int) -> int:
        """Return the entry-specific TTL, or the workspace default."""

        return self.ttl if self.ttl is not None else default_ttl

    def effective_proxied(self, default_proxied: bool) -> bool:
        """Return the entry-specific proxied flag, or the workspace default."""

        return self.proxied if self.proxied is not None else default_proxied

    def concrete_families(self) -> tuple[IPAddressFamily, ...]:
        """Return the concrete record families managed by this entry."""

        return self.family.concrete_families()

    def descriptor_for_record_type(self, record_type: str) -> str:
        """Return the stable descriptor used in managed-record state."""

        return f"{self.name}|{self.fqdn}|{record_type}"

    def descriptors(self) -> set[str]:
        """Return all managed-record descriptors for this entry."""

        return {
            self.descriptor_for_record_type(family.record_type)
            for family in self.concrete_families()
        }

    def static_value_for_family(self, family: IPAddressFamily) -> str | None:
        """Return the static value configured for one family."""

        if family is IPAddressFamily.IPV4:
            return self.static_ipv4
        return self.static_ipv6

    @property
    def source_descriptor(self) -> str:
        """Return a compact source descriptor for logs and CLI output."""

        if self.source_kind is EntrySourceKind.STATIC:
            return "static"
        return f"{self.source_kind.value}/{self.source_id}"


class EntriesFile(BaseModel):
    """Container for `entries.yaml`."""

    model_config = ConfigDict(extra="forbid")

    config_version: int
    entries: list[WorkspaceEntry] = Field(default_factory=list)

    @field_validator("config_version")
    @classmethod
    def _validate_config_version(cls, value: int) -> int:
        if value != 2:
            raise ValueError("entries config_version must be exactly 2")
        return value

    @model_validator(mode="after")
    def _validate_unique_names(self) -> Self:
        seen: set[str] = set()
        duplicates: list[str] = []
        for entry in self.entries:
            if entry.name in seen:
                duplicates.append(entry.name)
            seen.add(entry.name)
        if duplicates:
            joined = ", ".join(sorted(set(duplicates)))
            raise ValueError(f"duplicate entry names are not allowed: {joined}")
        return self

    def enabled_entries(self) -> list[WorkspaceEntry]:
        """Return enabled entries only."""

        return [entry for entry in self.entries if entry.enabled]

    def get(self, name: str) -> WorkspaceEntry | None:
        """Return a named entry if present."""

        for entry in self.entries:
            if entry.name == name:
                return entry
        return None

    @classmethod
    def scaffold_defaults(cls) -> EntriesFile:
        """Build the typed default `entries.yaml` model."""

        return cls.model_validate(load_entries_scaffold_defaults())


class ResolvedWorkspaceSystemdConfig(BaseModel):
    """Runtime-resolved systemd config."""

    model_config = ConfigDict(extra="forbid")

    service_name: str
    timer_name: str
    on_boot_sec: str
    on_unit_active_sec: str
    run_sync_after_apply: bool


class ResolvedWorkspaceRuntimePaths(BaseModel):
    """Runtime-resolved workspace execution paths."""

    model_config = ConfigDict(extra="forbid")

    pct_bin: str
    qm_bin: str
    shell_bin: str
    systemctl_bin: str
    systemd_unit_dir: str

    def resolved_systemd_unit_dir(self) -> Path:
        """Return the absolute systemd unit directory."""

        return Path(self.systemd_unit_dir)

class ResolvedWorkspace(BaseModel):
    """Runtime-resolved workspace config."""

    model_config = ConfigDict(extra="forbid")

    workspace_root: str
    workspace_name: str
    provider: str
    zone_name: str
    zone_id: str | None
    api_token_file: str
    default_ttl: int
    default_proxied: bool
    paths: ResolvedWorkspaceRuntimePaths
    systemd: ResolvedWorkspaceSystemdConfig
    apply: WorkspaceApplyConfig
    arbor_ddns_logging: ResolvedArborDDNSLoggingConfig

    def cloudflare_provider_config(self) -> CloudflareProviderConfig:
        """Build a Cloudflare provider config from the resolved workspace."""

        return CloudflareProviderConfig(
            enabled=True,
            zone_name=self.zone_name,
            zone_id=self.zone_id,
            api_token_file=self.api_token_file,
            timeout_seconds=10.0,
            proxied=self.default_proxied,
            ttl=self.default_ttl,
        )


class DesiredRecordSpec(BaseModel):
    """Static desired-record declaration used by `render`."""

    model_config = ConfigDict(extra="forbid")

    entry_name: str
    provider: str
    fqdn: str
    family: IPAddressFamily
    record_type: str
    ttl: int
    proxied: bool
    source_kind: EntrySourceKind
    source_id: int | None
    selection_policy: str | None
    enabled: bool
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

        return [
            cls(
                entry_name=entry.name,
                provider=workspace.provider,
                fqdn=entry.fqdn,
                family=family,
                record_type=family.record_type,
                ttl=entry.effective_ttl(workspace.default_ttl),
                proxied=entry.effective_proxied(workspace.default_proxied),
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


class ValidationReport(BaseModel):
    """Successful workspace validation summary."""

    model_config = ConfigDict(extra="forbid")

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

    model_config = ConfigDict(extra="forbid")

    workspace_root: str
    workspace_name: str
    effective_workspace_file: str
    desired_records_file: str
    service_unit_file: str
    timer_unit_file: str
    desired_record_count: int


class EntryMutationResult(BaseModel):
    """Entry mutation result."""

    model_config = ConfigDict(extra="forbid")

    operation: str
    changed: bool
    message: str
    entry: WorkspaceEntry | None = None
    removed_name: str | None = None


class ManagedRecordSnapshot(BaseModel):
    """State tracked for a previously managed remote DNS record."""

    model_config = ConfigDict(extra="forbid")

    workspace_name: str
    entry_name: str
    fqdn: str
    record_type: str
    record_id: str | None = None
    value: str
    ttl: int = Field(ge=1)
    proxied: bool | None = None
    state: Literal["active", "stale"]
    first_managed_at: str
    last_seen_at: str

    @property
    def descriptor(self) -> str:
        """Return the stable state descriptor."""

        return f"{self.entry_name}|{self.fqdn}|{self.record_type}"


class ManagedRecordFile(BaseModel):
    """Container for `state/managed-records.json`."""

    model_config = ConfigDict(extra="forbid")

    config_version: int = 1
    records: list[ManagedRecordSnapshot] = Field(default_factory=list)


class LastApplyState(BaseModel):
    """Recorded `apply` state."""

    model_config = ConfigDict(extra="forbid")

    applied_at: str
    workspace_name: str
    service_name: str
    timer_name: str
    unit_dir: str
    prune_managed: bool
    immediate_sync_requested: bool
    immediate_sync_ran: bool


class SystemdUnitStatus(BaseModel):
    """systemd unit status summary."""

    model_config = ConfigDict(extra="forbid")

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

    model_config = ConfigDict(extra="forbid")

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
    runtime_log_file: str
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

    model_config = ConfigDict(extra="forbid")

    name: str
    status: Literal["ok", "warn", "error"]
    message: str


class DoctorReport(BaseModel):
    """Read-only health report for a workspace."""

    model_config = ConfigDict(extra="forbid")

    workspace_root: str
    checks: list[DoctorCheck] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Return whether the report contains no error-level checks."""

        return all(check.status != "error" for check in self.checks)


class UninstallReport(BaseModel):
    """Workspace uninstall summary."""

    model_config = ConfigDict(extra="forbid")

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
