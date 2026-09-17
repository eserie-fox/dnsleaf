"""Workspace configuration, resolved values and persisted state models."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    field_validator,
    model_validator,
)

from dnsleaf.config.merge import deep_merge
from dnsleaf.config.resources import read_yaml_mapping
from dnsleaf.config.scaffold import (
    load_entries_defaults,
    load_workspace_defaults,
)
from dnsleaf.config.shared import DiscoveryCommandPaths, DiscoveryConfig
from dnsleaf.dns.cloudflare import CloudflareProviderConfig
from dnsleaf.dns.identity import dns_target
from dnsleaf.dns.models import (
    TTLSetting,
    normalize_ttl_setting,
    resolve_ttl_setting,
)
from dnsleaf.logging.config import DnsleafLoggingConfig, ResolvedDnsleafLoggingConfig
from dnsleaf.models import EntryAddressFamily, EntrySourceKind, IPAddressFamily, TargetRef
from dnsleaf.util.ip import normalize_ip

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

    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    service_name: str | None
    timer_name: str | None
    on_boot_sec: str
    on_unit_active_sec: str
    run_sync_after_apply: bool

    @field_validator("service_name", "timer_name")
    @classmethod
    def _strip_optional_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validate_name(value, pattern=ENTRY_NAME_RE, field_name="systemd unit name")

    @field_validator("on_boot_sec", "on_unit_active_sec")
    @classmethod
    def _validate_non_empty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("systemd duration values must not be blank")
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("systemd durations must not contain control characters")
        return stripped

    def resolved_service_name(self, workspace_name: str) -> str:
        """Return the effective systemd service name."""

        return self.service_name or f"dnsleaf-{workspace_name}"

    def resolved_timer_name(self, workspace_name: str) -> str:
        """Return the effective systemd timer name."""

        return self.timer_name or f"dnsleaf-{workspace_name}"


class WorkspaceApplyConfig(BaseModel):
    """Workspace-level apply settings."""

    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

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

    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    config_version: int
    workspace_name: str
    provider: str
    zone_name: str
    zone_id: str | None
    api_token_file: str
    default_ttl: TTLSetting
    default_proxied: bool | None
    discovery: DiscoveryConfig
    paths: WorkspaceRuntimePaths
    systemd: WorkspaceSystemdConfig
    apply: WorkspaceApplyConfig
    dnsleaf_logging: DnsleafLoggingConfig

    @field_validator("config_version")
    @classmethod
    def _validate_config_version(cls, value: int) -> int:
        if value != 4:
            raise ValueError("workspace config_version must be exactly 4")
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

    @field_validator("default_ttl", mode="before")
    @classmethod
    def _normalize_default_ttl(cls, value: object) -> TTLSetting:
        if isinstance(value, str) and value != "auto":
            raise ValueError("YAML TTL must be an integer or 'auto'")
        return normalize_ttl_setting(value)

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
    def from_defaults(cls) -> WorkspaceConfig:
        """Load formal defaults without resolving runtime paths."""

        return cls.from_mapping({})

    @classmethod
    def from_file(cls, path: str | Path) -> WorkspaceConfig:
        """Merge one YAML override over package defaults, then validate."""

        return cls.from_mapping(read_yaml_mapping(path))

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> WorkspaceConfig:
        """Merge mappings recursively; replace lists and scalar values."""

        return cls.model_validate(
            deep_merge(
                {
                    "discovery": DiscoveryConfig.from_defaults().model_dump(),
                    **load_workspace_defaults(),
                },
                data,
            )
        )

    @classmethod
    def scaffold_defaults(cls, workspace_name: str) -> WorkspaceConfig:
        """Build the typed default `workspace.yaml` model for one workspace name."""

        return cls.from_mapping({"workspace_name": workspace_name})

    def resolve(self, workspace_root: Path) -> ResolvedWorkspace:
        """Resolve runtime-only workspace values."""

        return ResolvedWorkspace(
            workspace_root=str(workspace_root.resolve()),
            workspace_name=self.workspace_name,
            provider=self.provider,
            zone_name=self.zone_name,
            zone_id=self.zone_id,
            api_token_file=str(self.resolved_api_token_file(workspace_root)),
            default_ttl=resolve_ttl_setting(self.default_ttl),
            default_proxied=self.default_proxied,
            paths=self.paths.resolve(workspace_root),
            discovery=self.discovery,
            systemd=ResolvedWorkspaceSystemdConfig(
                service_name=self.resolved_service_name(),
                timer_name=self.resolved_timer_name(),
                on_boot_sec=self.systemd.on_boot_sec,
                on_unit_active_sec=self.systemd.on_unit_active_sec,
                run_sync_after_apply=self.systemd.run_sync_after_apply,
            ),
            apply=self.apply,
            dnsleaf_logging=self.dnsleaf_logging.resolve(workspace_root),
        )


class WorkspaceEntry(BaseModel):
    """User-maintained entry config."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    name: str
    source_kind: EntrySourceKind
    family: EntryAddressFamily
    fqdn: str
    enabled: StrictBool
    source_id: StrictInt | None = Field(default=None, ge=1)
    selection_policy: str | None = None
    ttl: TTLSetting | None = None
    proxied: StrictBool | None = None
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

    @field_validator("ttl", mode="before")
    @classmethod
    def _normalize_ttl(cls, value: object) -> TTLSetting | None:
        if value is None:
            return None
        if isinstance(value, str) and value != "auto":
            raise ValueError("YAML TTL must be an integer or 'auto'")
        return normalize_ttl_setting(value)

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
        elif self.source_kind is EntrySourceKind.LOCAL:
            if self.source_id is not None:
                raise ValueError("dynamic local entries must not define source_id")
            if self.selection_policy is None:
                raise ValueError("dynamic local entries require selection_policy")
            if self.static_ipv4 is not None or self.static_ipv6 is not None:
                raise ValueError("dynamic local entries must not define static IP values")
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

        if self.source_kind is EntrySourceKind.LOCAL:
            return TargetRef(kind=self.source_kind.to_target_kind(), id=None)
        if self.source_id is None:
            raise ValueError("static entries do not have a discovery target")
        return TargetRef(kind=self.source_kind.to_target_kind(), id=self.source_id)

    def effective_ttl(self, default_ttl: int) -> int:
        """Return the entry-specific TTL, or the workspace default."""

        if self.ttl is None:
            return default_ttl
        return resolve_ttl_setting(self.ttl)

    def effective_proxied(self, default_proxied: bool | None) -> bool | None:
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
        if self.source_kind is EntrySourceKind.LOCAL:
            return "local"
        return f"{self.source_kind.value}/{self.source_id}"


class EntriesFile(BaseModel):
    """Container for `entries.yaml`."""

    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    config_version: int
    entries: list[WorkspaceEntry]

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

    @model_validator(mode="after")
    def _validate_unique_targets(self) -> Self:
        owners: dict[tuple[str, str], str] = {}
        for entry in self.enabled_entries():
            for family in entry.concrete_families():
                target = dns_target(entry.fqdn, family.record_type)
                if target in owners:
                    raise ValueError(
                        f"enabled entries {owners[target]!r} and {entry.name!r} "
                        f"both manage {target[0]} {target[1]}"
                    )
                owners[target] = entry.name
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
    def from_defaults(cls) -> EntriesFile:
        """Load formal entries defaults."""

        return cls.model_validate(load_entries_defaults())

    @classmethod
    def from_file(cls, path: str | Path) -> EntriesFile:
        """Load defaults plus one YAML entries override."""

        return cls.from_mapping(read_yaml_mapping(path))

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> EntriesFile:
        """Require an explicit operator-supplied list before merging defaults."""

        if not isinstance(data, Mapping) or "entries" not in data:
            raise ValueError(
                "entries document must be a mapping with an explicit 'entries' field; "
                "use entries: [] for an intentionally empty list"
            )

        return cls.model_validate(deep_merge(load_entries_defaults(), data))

    @classmethod
    def scaffold_defaults(cls) -> EntriesFile:
        """Build the typed default `entries.yaml` model."""

        return cls.from_defaults()


class ResolvedWorkspaceSystemdConfig(BaseModel):
    """Runtime-resolved systemd config."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    service_name: str
    timer_name: str
    on_boot_sec: str
    on_unit_active_sec: str
    run_sync_after_apply: bool


class ResolvedWorkspaceRuntimePaths(BaseModel):
    """Runtime-resolved workspace execution paths."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

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

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    workspace_root: str
    workspace_name: str
    provider: str
    zone_name: str
    zone_id: str | None
    api_token_file: str
    default_ttl: int
    default_proxied: bool | None
    discovery: DiscoveryConfig
    paths: ResolvedWorkspaceRuntimePaths
    systemd: ResolvedWorkspaceSystemdConfig
    apply: WorkspaceApplyConfig
    dnsleaf_logging: ResolvedDnsleafLoggingConfig

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


class ManagedRecordSnapshot(BaseModel):
    """State tracked for a previously managed remote DNS record."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    workspace_name: str
    entry_name: str
    fqdn: str
    record_type: str
    record_id: str | None = None
    value: str
    ttl: int = Field(ge=1)
    proxied: StrictBool | None = None
    state: Literal["active", "stale"]
    first_managed_at: str
    last_seen_at: str

    @property
    def descriptor(self) -> str:
        """Return the stable state descriptor."""

        return f"{self.entry_name}|{self.fqdn}|{self.record_type}"


class ManagedRecordFile(BaseModel):
    """Container for `state/managed-records.json`."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    config_version: int = 1
    records: list[ManagedRecordSnapshot] = Field(default_factory=list)


class LastApplyState(BaseModel):
    """Recorded `apply` state."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    applied_at: str
    workspace_name: str
    service_name: str
    timer_name: str
    unit_dir: str
    prune_managed: bool
    immediate_sync_requested: bool
    immediate_sync_ran: bool
