"""High-level workspace service layer."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from arbor_ddns.config import AppConfig
from arbor_ddns.dns.cloudflare import CloudflareDNSProvider
from arbor_ddns.dns.models import ProviderVerification
from arbor_ddns.sync.runner import SyncRunner, WorkspaceRunReport, build_runner
from arbor_ddns.systemd import SystemdManager
from arbor_ddns.util.process import command_available
from arbor_ddns.workspace.models import (
    DoctorCheck,
    DoctorReport,
    LastApplyState,
    ManagedRecordFile,
    ManagedRecordSnapshot,
    RenderArtifacts,
    ValidationReport,
    WorkspaceStatus,
)
from arbor_ddns.workspace.renderer import WorkspaceRenderer
from arbor_ddns.workspace.state import (
    load_last_apply,
    load_managed_records,
    managed_record_counts,
    write_last_apply,
    write_managed_records,
)
from arbor_ddns.workspace.storage import LoadedWorkspace, WorkspaceStorage


class ApplyReport(BaseModel):
    """Apply workflow summary."""

    model_config = ConfigDict(extra="forbid")

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


class WorkspaceService:
    """Workspace-oriented facade for CLI and future programmatic callers."""

    def __init__(
        self,
        *,
        app_config: AppConfig | None = None,
        storage: WorkspaceStorage | None = None,
        renderer: WorkspaceRenderer | None = None,
        systemd_manager: SystemdManager | None = None,
        runner: SyncRunner | None = None,
    ) -> None:
        self._app_config = app_config or AppConfig.from_defaults()
        self._storage = storage or WorkspaceStorage(self._app_config)
        self._systemd_manager = systemd_manager or SystemdManager(self._app_config)
        self._renderer = renderer or WorkspaceRenderer(self._systemd_manager)
        self._runner = runner or build_runner(self._app_config)

    def init_workspace(self, workspace_dir: str | Path) -> Path:
        """Create a new workspace directory."""

        return self._storage.scaffold(workspace_dir).root

    def validate_workspace(self, workspace_dir: str | Path) -> ValidationReport:
        """Validate workspace source config and runtime-only references."""

        loaded = self._storage.validate(workspace_dir)
        return ValidationReport(
            workspace_root=str(loaded.paths.root),
            workspace_name=loaded.resolved_workspace.workspace_name,
            provider=loaded.resolved_workspace.provider,
            zone_name=loaded.resolved_workspace.zone_name,
            zone_id=loaded.resolved_workspace.zone_id,
            token_file=loaded.resolved_workspace.api_token_file,
            entry_count=len(loaded.entries_file.entries),
            enabled_entry_count=len(loaded.entries_file.enabled_entries()),
        )

    def render_workspace(self, workspace_dir: str | Path) -> RenderArtifacts:
        """Render workspace artifacts."""

        loaded = self._storage.validate(workspace_dir)
        return self._renderer.render(loaded)

    def plan_workspace(
        self,
        workspace_dir: str | Path,
        *,
        prune_managed: bool | None = None,
    ) -> WorkspaceRunReport:
        """Run a live dry-run plan for a workspace."""

        loaded = self._storage.validate(workspace_dir)
        managed_state = load_managed_records(loaded.paths)
        return self._runner.run(
            loaded,
            managed_state=managed_state,
            apply=False,
            prune_managed=self._resolve_prune_managed(loaded, prune_managed),
        )

    def sync_once(
        self,
        workspace_dir: str | Path,
        *,
        apply: bool,
        prune_managed: bool | None = None,
    ) -> WorkspaceRunReport:
        """Run one sync cycle for a workspace."""

        loaded = self._storage.validate(workspace_dir)
        managed_state = load_managed_records(loaded.paths)
        report = self._runner.run(
            loaded,
            managed_state=managed_state,
            apply=apply,
            prune_managed=self._resolve_prune_managed(loaded, prune_managed),
        )
        if apply:
            updated_state = self._reconcile_managed_state(loaded, managed_state, report)
            write_managed_records(loaded.paths, updated_state)
        return report

    def apply_workspace(
        self,
        workspace_dir: str | Path,
        *,
        prune_managed: bool | None = None,
        run_sync: bool | None = None,
    ) -> ApplyReport:
        """Validate, render, install/update systemd units, and optionally sync once."""

        loaded = self._storage.validate(workspace_dir)
        render_report = self._renderer.render(loaded)
        installed_service, installed_timer = self._systemd_manager.install_rendered_units(
            loaded.paths,
            loaded.resolved_workspace,
        )
        self._systemd_manager.daemon_reload()
        self._systemd_manager.enable_restart_timer(loaded.resolved_workspace.systemd.timer_name)

        immediate_sync_requested = (
            loaded.resolved_workspace.systemd.run_sync_after_apply
            if run_sync is None
            else run_sync
        )
        sync_report: WorkspaceRunReport | None = None
        if immediate_sync_requested:
            sync_report = self.sync_once(
                loaded.paths.root,
                apply=True,
                prune_managed=self._resolve_prune_managed(loaded, prune_managed),
            )

        write_last_apply(
            loaded.paths,
            LastApplyState(
                applied_at=_utc_now(),
                workspace_name=loaded.resolved_workspace.workspace_name,
                service_name=loaded.resolved_workspace.systemd.service_name,
                timer_name=loaded.resolved_workspace.systemd.timer_name,
                unit_dir=str(self._app_config.systemd.resolved_unit_dir()),
                prune_managed=self._resolve_prune_managed(loaded, prune_managed),
                immediate_sync_requested=immediate_sync_requested,
                immediate_sync_ran=sync_report is not None,
            ),
        )

        return ApplyReport(
            workspace_root=str(loaded.paths.root),
            workspace_name=loaded.resolved_workspace.workspace_name,
            service_name=loaded.resolved_workspace.systemd.service_name,
            timer_name=loaded.resolved_workspace.systemd.timer_name,
            installed_service_unit=str(installed_service),
            installed_timer_unit=str(installed_timer),
            prune_managed=self._resolve_prune_managed(loaded, prune_managed),
            immediate_sync_requested=immediate_sync_requested,
            immediate_sync_ran=sync_report is not None,
            render=render_report,
            sync_report=sync_report,
        )

    def provider_verify(self, workspace_dir: str | Path) -> ProviderVerification:
        """Verify Cloudflare token, zone lookup, and DNS listing access."""

        loaded = self._storage.validate(workspace_dir)
        provider = CloudflareDNSProvider(loaded.resolved_workspace.cloudflare_provider_config())
        return provider.verify()

    def status_workspace(self, workspace_dir: str | Path) -> WorkspaceStatus:
        """Aggregate workspace, state, and systemd status."""

        errors: list[str] = []
        warnings: list[str] = []
        workspace_name: str | None = None
        provider: str | None = None
        zone_name: str | None = None
        zone_id: str | None = None
        token_file: str | None = None
        entry_count = 0
        enabled_entry_count = 0
        service_name = "unknown"
        timer_name = "unknown"

        paths = self._storage.paths_for(workspace_dir)
        try:
            loaded = self._storage.load(workspace_dir)
            workspace_name = loaded.resolved_workspace.workspace_name
            provider = loaded.resolved_workspace.provider
            zone_name = loaded.resolved_workspace.zone_name
            zone_id = loaded.resolved_workspace.zone_id
            token_file = loaded.resolved_workspace.api_token_file
            entry_count = len(loaded.entries_file.entries)
            enabled_entry_count = len(loaded.entries_file.enabled_entries())
            service_name = loaded.resolved_workspace.systemd.service_name
            timer_name = loaded.resolved_workspace.systemd.timer_name
        except Exception as exc:
            errors.append(str(exc))

        managed_state = load_managed_records(paths)
        active_count, stale_count = managed_record_counts(managed_state)
        last_apply = load_last_apply(paths)

        return WorkspaceStatus(
            workspace_root=str(paths.root),
            workspace_name=workspace_name,
            provider=provider,
            zone_name=zone_name,
            zone_id=zone_id,
            token_file=token_file,
            entry_count=entry_count,
            enabled_entry_count=enabled_entry_count,
            rendered_artifacts={
                "effective_workspace": paths.effective_workspace_file.exists(),
                "desired_records": paths.desired_records_file.exists(),
                "service_unit": (paths.rendered_systemd_dir / f"{service_name}.service").exists(),
                "timer_unit": (paths.rendered_systemd_dir / f"{timer_name}.timer").exists(),
            },
            managed_active_count=active_count,
            managed_stale_count=stale_count,
            last_apply=last_apply,
            service_status=self._systemd_manager.status(service_name, "service"),
            timer_status=self._systemd_manager.status(timer_name, "timer"),
            warnings=warnings,
            errors=errors,
        )

    def doctor_workspace(self, workspace_dir: str | Path) -> DoctorReport:
        """Run non-destructive health checks against a workspace."""

        paths = self._storage.paths_for(workspace_dir)
        checks: list[DoctorCheck] = []

        checks.append(
            DoctorCheck(
                name="workspace_dir",
                status="ok" if paths.root.exists() and paths.root.is_dir() else "error",
                message=f"workspace root: {paths.root}",
            )
        )
        checks.append(
            DoctorCheck(
                name="workspace_yaml",
                status="ok" if paths.workspace_file.exists() else "error",
                message=f"workspace.yaml: {paths.workspace_file}",
            )
        )
        checks.append(
            DoctorCheck(
                name="entries_yaml",
                status="ok" if paths.entries_file.exists() else "error",
                message=f"entries.yaml: {paths.entries_file}",
            )
        )

        try:
            loaded = self._storage.load(paths.root)
        except Exception as exc:
            checks.append(DoctorCheck(name="workspace_load", status="error", message=str(exc)))
            return DoctorReport(workspace_root=str(paths.root), checks=checks)

        token_path = Path(loaded.resolved_workspace.api_token_file)
        token_status: Literal["ok", "warn", "error"] = "ok"
        token_message = f"token file: {token_path}"
        if not token_path.exists():
            token_status = "error"
            token_message = f"token file does not exist: {token_path}"
        elif not token_path.is_file():
            token_status = "error"
            token_message = f"token path is not a file: {token_path}"
        else:
            try:
                if not token_path.read_text(encoding="utf-8").strip():
                    token_status = "error"
                    token_message = f"token file is empty: {token_path}"
            except OSError as exc:
                token_status = "error"
                token_message = f"token file is not readable: {token_path}: {exc}"
        checks.append(DoctorCheck(name="token_file", status=token_status, message=token_message))

        for command_name in (
            loaded.app_config.discovery.pct_bin,
            loaded.app_config.discovery.qm_bin,
            loaded.app_config.systemd.systemctl_bin,
        ):
            checks.append(
                DoctorCheck(
                    name=f"command:{command_name}",
                    status="ok" if command_available(command_name) else "warn",
                    message=f"command lookup: {command_name}",
                )
            )

        checks.append(
            DoctorCheck(
                name="systemd_unit_dir",
                status="ok" if self._systemd_manager.unit_dir_writable() else "warn",
                message=f"systemd unit dir: {self._app_config.systemd.resolved_unit_dir()}",
            )
        )

        return DoctorReport(workspace_root=str(paths.root), checks=checks)

    def _resolve_prune_managed(self, loaded: LoadedWorkspace, override: bool | None) -> bool:
        if override is None:
            return loaded.resolved_workspace.apply.prune_managed_records
        return override

    def _reconcile_managed_state(
        self,
        loaded: LoadedWorkspace,
        state: ManagedRecordFile,
        report: WorkspaceRunReport,
    ) -> ManagedRecordFile:
        enabled_descriptors = {entry.descriptor for entry in loaded.entries_file.enabled_entries()}
        records_by_descriptor = {record.descriptor: record for record in state.records}
        now = _utc_now()

        for record in records_by_descriptor.values():
            record.state = "active" if record.descriptor in enabled_descriptors else "stale"
            record.last_seen_at = now

        for outcome in report.entry_outcomes:
            if outcome.final_record is None:
                continue
            descriptor = f"{outcome.entry_name}|{outcome.fqdn}|{outcome.record_type}"
            existing = records_by_descriptor.get(descriptor)
            first_managed_at = existing.first_managed_at if existing is not None else now
            records_by_descriptor[descriptor] = ManagedRecordSnapshot(
                workspace_name=loaded.resolved_workspace.workspace_name,
                entry_name=outcome.entry_name,
                fqdn=outcome.fqdn,
                record_type=outcome.record_type,
                record_id=outcome.final_record.record_id,
                value=outcome.final_record.value,
                ttl=outcome.final_record.ttl,
                proxied=outcome.final_record.proxied,
                state="active",
                first_managed_at=first_managed_at,
                last_seen_at=now,
            )

        removed_descriptors: set[str] = set()
        for prune_outcome in report.prune_outcomes:
            if prune_outcome.status not in {"applied", "confirmed_absent"}:
                continue
            descriptor = (
                f"{prune_outcome.entry_name}|{prune_outcome.fqdn}|{prune_outcome.record_type}"
            )
            removed_descriptors.add(descriptor)

        return ManagedRecordFile(
            records=[
                record
                for descriptor, record in sorted(records_by_descriptor.items())
                if descriptor not in removed_descriptors
            ]
        )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()
