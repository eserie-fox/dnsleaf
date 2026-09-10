"""High-level workspace service layer."""

from __future__ import annotations

import logging
import os
import shlex
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from dnsleaf.dns.cloudflare import CloudflareDNSProvider
from dnsleaf.dns.models import ProviderVerification
from dnsleaf.sync.runner import SyncRunner, WorkspaceRunReport, build_runner
from dnsleaf.systemd import SystemdError, SystemdManager
from dnsleaf.util.process import CommandResult, command_available
from dnsleaf.workspace.models import (
    DoctorCheck,
    DoctorReport,
    LastApplyState,
    ManagedRecordFile,
    ManagedRecordSnapshot,
    RenderArtifacts,
    SystemdUnitStatus,
    UninstallReport,
    ValidationReport,
    WorkspaceStatus,
)
from dnsleaf.workspace.renderer import WorkspaceRenderer
from dnsleaf.workspace.state import (
    load_last_apply,
    load_managed_records,
    managed_record_counts,
    write_last_apply,
    write_managed_records,
)
from dnsleaf.workspace.storage import LoadedWorkspace, WorkspaceStorage, ensure_writable_directory

LOGGER = logging.getLogger(__name__)


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


class WorkspaceService:
    """Workspace-oriented facade for CLI and future programmatic callers."""

    def __init__(
        self,
        *,
        storage: WorkspaceStorage | None = None,
        renderer: WorkspaceRenderer | None = None,
        systemd_manager: SystemdManager | None = None,
        runner: SyncRunner | None = None,
    ) -> None:
        self._storage = storage or WorkspaceStorage()
        self._systemd_manager = systemd_manager or SystemdManager()
        self._renderer = renderer or WorkspaceRenderer(self._systemd_manager)
        self._runner = runner or build_runner()

    def init_workspace(self, workspace_dir: str | Path) -> Path:
        """Create a new workspace directory."""

        created = self._storage.scaffold(workspace_dir).root
        LOGGER.info("workspace_initialized workspace_root=%s", created)
        return created

    def validate_workspace(self, workspace_dir: str | Path) -> ValidationReport:
        """Validate workspace source config and runtime-only references."""

        loaded = self._storage.validate(workspace_dir)
        LOGGER.info("command_started workspace_root=%s", loaded.paths.root)
        report = ValidationReport(
            workspace_root=str(loaded.paths.root),
            workspace_name=loaded.resolved_workspace.workspace_name,
            provider=loaded.resolved_workspace.provider,
            zone_name=loaded.resolved_workspace.zone_name,
            zone_id=loaded.resolved_workspace.zone_id,
            token_file=loaded.resolved_workspace.api_token_file,
            entry_count=len(loaded.entries_file.entries),
            enabled_entry_count=len(loaded.entries_file.enabled_entries()),
        )
        LOGGER.info(
            "validated zone=%s entries=%d enabled=%d",
            report.zone_name,
            report.entry_count,
            report.enabled_entry_count,
        )
        return report

    def render_workspace(self, workspace_dir: str | Path) -> RenderArtifacts:
        """Render workspace artifacts."""

        loaded = self._storage.validate(workspace_dir)
        LOGGER.info("command_started workspace_root=%s", loaded.paths.root)
        report = self._renderer.render(loaded)
        LOGGER.info(
            "rendered effective_workspace=%s desired_records=%s service_unit=%s timer_unit=%s",
            report.effective_workspace_file,
            report.desired_records_file,
            report.service_unit_file,
            report.timer_unit_file,
        )
        return report

    def plan_workspace(
        self,
        workspace_dir: str | Path,
        *,
        prune_managed: bool | None = None,
    ) -> WorkspaceRunReport:
        """Run a live dry-run plan for a workspace."""

        loaded = self._storage.validate(workspace_dir)
        LOGGER.info("command_started workspace_root=%s", loaded.paths.root)
        managed_state = load_managed_records(loaded.paths)
        try:
            report = self._runner.run(
                loaded,
                managed_state=managed_state,
                apply=False,
                prune_managed=self._resolve_prune_managed(loaded, prune_managed),
            )
        except Exception:
            LOGGER.exception("plan failed")
            raise
        self._log_run_report(report)
        return report

    def sync_once(
        self,
        workspace_dir: str | Path,
        *,
        apply: bool,
        prune_managed: bool | None = None,
    ) -> WorkspaceRunReport:
        """Run one sync cycle for a workspace."""

        loaded = self._storage.validate(workspace_dir)
        LOGGER.info("command_started workspace_root=%s", loaded.paths.root)
        managed_state = load_managed_records(loaded.paths)
        if apply:
            ensure_writable_directory(loaded.paths.state_dir)
        try:
            report = self._runner.run(
                loaded,
                managed_state=managed_state,
                apply=apply,
                prune_managed=self._resolve_prune_managed(loaded, prune_managed),
            )
        except Exception:
            LOGGER.exception("sync run failed")
            raise
        if apply:
            updated_state = self._reconcile_managed_state(loaded, managed_state, report)
            write_managed_records(loaded.paths, updated_state)
            LOGGER.info("managed_state_updated records=%d", len(updated_state.records))
        self._log_run_report(report)
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
        ensure_writable_directory(loaded.paths.state_dir)
        LOGGER.info("command_started workspace_root=%s", loaded.paths.root)
        render_report = self._renderer.render(loaded)
        installed_service, installed_timer = self._systemd_manager.install_rendered_units(
            loaded.paths,
            loaded.resolved_workspace,
        )
        self._systemd_manager.daemon_reload(loaded.resolved_workspace)
        self._systemd_manager.enable_restart_timer(
            loaded.resolved_workspace,
            loaded.resolved_workspace.systemd.timer_name,
        )
        LOGGER.info(
            "systemd_installed service=%s timer=%s service_unit=%s timer_unit=%s",
            loaded.resolved_workspace.systemd.service_name,
            loaded.resolved_workspace.systemd.timer_name,
            installed_service,
            installed_timer,
        )

        immediate_sync_requested = (
            loaded.resolved_workspace.systemd.run_sync_after_apply if run_sync is None else run_sync
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
                unit_dir=str(loaded.resolved_workspace.paths.resolved_systemd_unit_dir()),
                prune_managed=self._resolve_prune_managed(loaded, prune_managed),
                immediate_sync_requested=immediate_sync_requested,
                immediate_sync_ran=sync_report is not None,
            ),
        )

        report = ApplyReport(
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
        LOGGER.info(
            "apply_completed prune_managed=%s immediate_sync_requested=%s immediate_sync_ran=%s",
            report.prune_managed,
            report.immediate_sync_requested,
            report.immediate_sync_ran,
        )
        return report

    def provider_verify(self, workspace_dir: str | Path) -> ProviderVerification:
        """Verify Cloudflare token, zone lookup, and DNS listing access."""

        loaded = self._storage.validate(workspace_dir)
        LOGGER.info("command_started workspace_root=%s", loaded.paths.root)
        provider = CloudflareDNSProvider(loaded.resolved_workspace.cloudflare_provider_config())
        try:
            report = provider.verify()
        except Exception:
            LOGGER.exception("provider verification failed")
            raise
        LOGGER.info(
            "provider_verified zone_name=%s zone_id=%s record_listing_succeeded=%s",
            report.zone_name,
            report.zone_id,
            report.record_listing_succeeded,
        )
        return report

    def status_workspace(self, workspace_dir: str | Path) -> WorkspaceStatus:
        """Aggregate workspace, state, and systemd status."""

        errors: list[str] = []
        warnings: list[str] = []
        workspace_name: str | None = None
        provider: str | None = None
        zone_name: str | None = None
        zone_id: str | None = None
        token_file: str | None = None
        systemd_unit_dir: str | None = None
        entry_count = 0
        enabled_entry_count = 0
        service_name = "unknown"
        timer_name = "unknown"
        loaded: LoadedWorkspace | None = None

        paths = self._storage.paths_for(workspace_dir)
        resolved_log_file = paths.runtime_log_file
        try:
            loaded = self._storage.load(workspace_dir)
            workspace_name = loaded.resolved_workspace.workspace_name
            provider = loaded.resolved_workspace.provider
            zone_name = loaded.resolved_workspace.zone_name
            zone_id = loaded.resolved_workspace.zone_id
            token_file = loaded.resolved_workspace.api_token_file
            systemd_unit_dir = str(loaded.resolved_workspace.paths.resolved_systemd_unit_dir())
            entry_count = len(loaded.entries_file.entries)
            enabled_entry_count = len(loaded.entries_file.enabled_entries())
            service_name = loaded.resolved_workspace.systemd.service_name
            timer_name = loaded.resolved_workspace.systemd.timer_name
            resolved_log_file = _resolved_workspace_log_file(
                loaded,
                fallback=paths.runtime_log_file,
            )
        except Exception as exc:
            errors.append(str(exc))

        managed_state = load_managed_records(paths)
        active_count, stale_count = managed_record_counts(managed_state)
        last_apply = load_last_apply(paths)
        if loaded is None:
            service_status = _unavailable_unit_status(service_name, "service")
            timer_status = _unavailable_unit_status(timer_name, "timer")
        else:
            service_status = self._systemd_manager.status(
                loaded.resolved_workspace,
                service_name,
                "service",
            )
            timer_status = self._systemd_manager.status(
                loaded.resolved_workspace,
                timer_name,
                "timer",
            )

        return WorkspaceStatus(
            workspace_root=str(paths.root),
            workspace_name=workspace_name,
            provider=provider,
            zone_name=zone_name,
            zone_id=zone_id,
            token_file=token_file,
            systemd_unit_dir=systemd_unit_dir,
            entry_count=entry_count,
            enabled_entry_count=enabled_entry_count,
            rendered_artifacts={
                "effective_workspace": paths.effective_workspace_file.exists(),
                "desired_records": paths.desired_records_file.exists(),
                "service_unit": (paths.rendered_systemd_dir / f"{service_name}.service").exists(),
                "timer_unit": (paths.rendered_systemd_dir / f"{timer_name}.timer").exists(),
            },
            runtime_dir_exists=paths.runtime_dir.exists(),
            runtime_log_file=str(resolved_log_file),
            runtime_log_file_exists=_path_exists_or_symlink(resolved_log_file),
            runtime_log_symlink_target=_symlink_target(resolved_log_file),
            managed_active_count=active_count,
            managed_stale_count=stale_count,
            last_apply=last_apply,
            service_status=service_status,
            timer_status=timer_status,
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
        LOGGER.info("command_started workspace_root=%s", loaded.paths.root)

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
            loaded.resolved_workspace.paths.pct_bin,
            loaded.resolved_workspace.paths.qm_bin,
            loaded.resolved_workspace.paths.shell_bin,
            loaded.resolved_workspace.paths.systemctl_bin,
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
                status=(
                    "ok"
                    if self._systemd_manager.unit_dir_writable(loaded.resolved_workspace)
                    else "warn"
                ),
                message=(
                    "systemd unit dir: "
                    f"{loaded.resolved_workspace.paths.resolved_systemd_unit_dir()}"
                ),
            )
        )

        checks.append(
            DoctorCheck(
                name="runtime_dir",
                status="ok" if paths.runtime_dir.exists() else "warn",
                message=f"runtime dir: {paths.runtime_dir}",
            )
        )
        checks.append(
            DoctorCheck(
                name="runtime_logs_dir",
                status="ok" if paths.runtime_logs_dir.exists() else "warn",
                message=f"runtime logs dir: {paths.runtime_logs_dir}",
            )
        )
        checks.append(
            DoctorCheck(
                name="runtime_log_target",
                status=(
                    "ok"
                    if _path_write_target_available(
                        _resolved_workspace_log_file(loaded, fallback=paths.runtime_log_file)
                    )
                    else "warn"
                ),
                message=(
                    "runtime log file: "
                    f"{_resolved_workspace_log_file(loaded, fallback=paths.runtime_log_file)}"
                ),
            )
        )

        for check in checks:
            if check.status != "ok":
                LOGGER.warning(
                    "doctor_check name=%s status=%s message=%s",
                    check.name,
                    check.status,
                    check.message,
                )

        return DoctorReport(workspace_root=str(paths.root), checks=checks)

    def uninstall_workspace(
        self,
        workspace_dir: str | Path,
        *,
        purge: bool = False,
    ) -> UninstallReport:
        """Remove installed units and generated runtime artifacts for a workspace."""

        loaded = self._storage.load(workspace_dir)
        if purge:
            _assert_safe_delete_path(
                loaded.paths.root,
                workspace_root=loaded.paths.root,
                allow_workspace_root=True,
            )
        LOGGER.info("command_started workspace_root=%s", loaded.paths.root)
        report = UninstallReport(
            workspace_root=str(loaded.paths.root),
            workspace_name=loaded.resolved_workspace.workspace_name,
            service_name=loaded.resolved_workspace.systemd.service_name,
            timer_name=loaded.resolved_workspace.systemd.timer_name,
            systemctl_available=self._systemd_manager.systemctl_available(
                loaded.resolved_workspace
            ),
        )
        LOGGER.info("uninstall_started purge=%s", purge)

        if not report.systemctl_available:
            raise SystemdError("systemctl is unavailable; uninstall stopped before local cleanup")

        # Stop the trigger first. Never delete files while a unit may still be running.
        for operation, unit_name, unit_kind, action, result_field in (
            (
                "stop timer",
                report.timer_name,
                "timer",
                self._systemd_manager.stop_timer,
                "timer_stopped",
            ),
            (
                "stop service",
                report.service_name,
                "service",
                self._systemd_manager.stop_service,
                "service_stopped",
            ),
            (
                "disable timer",
                report.timer_name,
                "timer",
                self._systemd_manager.disable_timer,
                "timer_disabled",
            ),
        ):
            result = action(loaded.resolved_workspace, unit_name, check=False)
            if result.returncode != 0:
                status = self._systemd_manager.status(
                    loaded.resolved_workspace, unit_name, unit_kind
                )
                if not (
                    status.available
                    and status.load_state == "not-found"
                    and status.active_state == "inactive"
                ):
                    raise SystemdError(_systemctl_warning(operation, unit_name, result))
            setattr(report, result_field, True)

        removed_service = self._systemd_manager.remove_installed_unit(
            loaded.resolved_workspace,
            report.service_name,
            "service",
        )
        report.service_unit_removed = removed_service is not None
        if removed_service is not None:
            report.removed_paths.append(str(removed_service))
        else:
            missing_service_path = self._systemd_manager.installed_unit_path(
                loaded.resolved_workspace,
                report.service_name,
                "service",
            )
            report.warnings.append(f"service unit already absent: {missing_service_path}")

        removed_timer = self._systemd_manager.remove_installed_unit(
            loaded.resolved_workspace,
            report.timer_name,
            "timer",
        )
        report.timer_unit_removed = removed_timer is not None
        if removed_timer is not None:
            report.removed_paths.append(str(removed_timer))
        else:
            missing_timer_path = self._systemd_manager.installed_unit_path(
                loaded.resolved_workspace,
                report.timer_name,
                "timer",
            )
            report.warnings.append(f"timer unit already absent: {missing_timer_path}")

        if report.systemctl_available:
            daemon_reload = self._systemd_manager.daemon_reload(
                loaded.resolved_workspace,
                check=False,
            )
            if daemon_reload.returncode == 0:
                report.daemon_reloaded = True
            else:
                raise SystemdError(_systemctl_warning("daemon-reload", "systemd", daemon_reload))

            service_reset = self._systemd_manager.reset_failed(
                loaded.resolved_workspace,
                report.service_name,
                "service",
                check=False,
            )
            if service_reset.returncode == 0:
                report.service_reset_failed = True
            else:
                report.warnings.append(
                    _systemctl_warning("reset-failed", report.service_name, service_reset)
                )

            timer_reset = self._systemd_manager.reset_failed(
                loaded.resolved_workspace,
                report.timer_name,
                "timer",
                check=False,
            )
            if timer_reset.returncode == 0:
                report.timer_reset_failed = True
            else:
                report.warnings.append(
                    _systemctl_warning("reset-failed", report.timer_name, timer_reset)
                )

        LOGGER.info(
            "systemd_cleanup service_stopped=%s timer_stopped=%s timer_disabled=%s "
            "service_unit_removed=%s timer_unit_removed=%s daemon_reloaded=%s "
            "service_reset_failed=%s timer_reset_failed=%s",
            report.service_stopped,
            report.timer_stopped,
            report.timer_disabled,
            report.service_unit_removed,
            report.timer_unit_removed,
            report.daemon_reloaded,
            report.service_reset_failed,
            report.timer_reset_failed,
        )
        for warning in report.warnings:
            LOGGER.warning("warning=%s", warning)
        _remove_workspace_path(loaded.paths.rendered_dir, report=report)
        _remove_workspace_path(loaded.paths.runtime_dir, report=report)

        if purge:
            _remove_workspace_path(loaded.paths.root, report=report, allow_workspace_root=True)
            report.purged = True
            return report

        report.kept_paths = [
            str(path)
            for path in (
                loaded.paths.workspace_file,
                loaded.paths.entries_file,
                loaded.paths.secrets_dir,
                loaded.paths.state_dir,
            )
            if path.exists()
        ]
        report.manual_cleanup_hint = shlex.join(["rm", "-rf", "--", str(loaded.paths.root)])
        return report

    def _resolve_prune_managed(self, loaded: LoadedWorkspace, override: bool | None) -> bool:
        if override is None:
            return loaded.resolved_workspace.apply.prune_managed_records
        return override

    def _log_run_report(
        self,
        report: WorkspaceRunReport,
    ) -> None:
        LOGGER.info(
            "run_summary dry_run=%s records=%d prune_candidates=%d warnings=%d",
            report.dry_run,
            len(report.record_outcomes),
            len(report.prune_outcomes),
            len(report.warnings),
        )
        for outcome in report.record_outcomes:
            actions = "-"
            if outcome.plan is not None:
                actions = ",".join(change.action for change in outcome.plan.changes)
            log_fn = LOGGER.error if outcome.status == "error" else LOGGER.info
            log_fn(
                "entry=%s fqdn=%s type=%s family=%s source=%s selection=%s selected=%s "
                "action=%s status=%s message=%s",
                outcome.entry_name,
                outcome.fqdn,
                outcome.record_type,
                outcome.family.value,
                outcome.value_source,
                outcome.selection_status or "-",
                outcome.selected_value or "-",
                actions,
                outcome.status,
                outcome.message,
            )
        for prune_outcome in report.prune_outcomes:
            actions = "-"
            if prune_outcome.plan is not None:
                actions = ",".join(change.action for change in prune_outcome.plan.changes)
            log_fn = LOGGER.error if prune_outcome.status == "error" else LOGGER.info
            log_fn(
                "prune_entry=%s fqdn=%s type=%s record_id=%s action=%s status=%s message=%s",
                prune_outcome.entry_name,
                prune_outcome.fqdn,
                prune_outcome.record_type,
                prune_outcome.record_id or "-",
                actions,
                prune_outcome.status,
                prune_outcome.message,
            )
        for warning in report.warnings:
            LOGGER.warning("warning=%s", warning)

    def _reconcile_managed_state(
        self,
        loaded: LoadedWorkspace,
        state: ManagedRecordFile,
        report: WorkspaceRunReport,
    ) -> ManagedRecordFile:
        enabled_descriptors = {
            descriptor
            for entry in loaded.entries_file.enabled_entries()
            for descriptor in entry.descriptors()
        }
        records_by_descriptor = {record.descriptor: record for record in state.records}
        now = _utc_now()

        for record in records_by_descriptor.values():
            record.state = "active" if record.descriptor in enabled_descriptors else "stale"
            record.last_seen_at = now

        for outcome in report.record_outcomes:
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


_DANGEROUS_DELETE_PATHS = {
    Path("/"),
    Path("/boot"),
    Path("/dev"),
    Path("/etc"),
    Path("/home"),
    Path("/lib"),
    Path("/lib64"),
    Path("/opt"),
    Path("/proc"),
    Path("/root"),
    Path("/run"),
    Path("/srv"),
    Path("/sys"),
    Path("/tmp"),
    Path("/usr"),
    Path("/var"),
}


def _remove_workspace_path(
    path: Path,
    *,
    report: UninstallReport,
    allow_workspace_root: bool = False,
) -> None:
    resolved = path.resolve()
    if not resolved.exists():
        return
    _assert_safe_delete_path(
        resolved,
        workspace_root=Path(report.workspace_root),
        allow_workspace_root=allow_workspace_root,
    )
    if resolved.is_dir() and not resolved.is_symlink():
        shutil.rmtree(resolved)
    else:
        resolved.unlink()
    report.removed_paths.append(str(resolved))


def _assert_safe_delete_path(
    path: Path,
    *,
    workspace_root: Path | None = None,
    allow_workspace_root: bool = False,
) -> None:
    resolved = path.resolve()
    if resolved in _DANGEROUS_DELETE_PATHS:
        raise ValueError(f"refusing to delete dangerous path: {resolved}")
    if len(resolved.parts) <= 2:
        raise ValueError(f"refusing to delete overly broad path: {resolved}")
    if resolved == resolved.parent:
        raise ValueError(f"refusing to delete filesystem root: {resolved}")

    if workspace_root is None:
        return
    root = workspace_root.resolve()
    if resolved == root:
        if allow_workspace_root:
            return
        raise ValueError(f"refusing to delete workspace root without explicit purge: {resolved}")
    if not _is_relative_to(resolved, root):
        raise ValueError(f"refusing to delete path outside workspace root: {resolved}")


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _path_write_target_available(path: Path) -> bool:
    target = path if path.exists() else path.parent
    return target.exists() and target.is_dir() and os.access(target, os.W_OK)


def _resolved_workspace_log_file(loaded: LoadedWorkspace, *, fallback: Path) -> Path:
    resolved = loaded.resolved_workspace.dnsleaf_logging.resolved_file_path()
    return resolved if resolved is not None else fallback


def _unavailable_unit_status(unit_name: str, unit_kind: str) -> SystemdUnitStatus:
    return SystemdUnitStatus(
        unit_name=f"{unit_name}.{unit_kind}",
        available=False,
        note="workspace could not be loaded",
    )


def _path_exists_or_symlink(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _symlink_target(path: Path) -> str | None:
    if not path.is_symlink():
        return None
    return str(path.resolve())


def _systemctl_warning(action: str, unit_name: str, result: CommandResult) -> str:
    detail = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
    return f"could not {action} for {unit_name}: {detail}"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()
