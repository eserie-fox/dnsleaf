"""High-level workspace service layer."""

from __future__ import annotations

import os
import shutil
from datetime import UTC, datetime
from logging import LoggerAdapter
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from arbor_ddns.config import AppConfig
from arbor_ddns.dns.cloudflare import CloudflareDNSProvider
from arbor_ddns.dns.models import ProviderVerification
from arbor_ddns.sync.runner import SyncRunner, WorkspaceRunReport, build_runner
from arbor_ddns.systemd import SystemdManager
from arbor_ddns.util.process import CommandResult, command_available
from arbor_ddns.workspace.models import (
    DoctorCheck,
    DoctorReport,
    LastApplyState,
    ManagedRecordFile,
    ManagedRecordSnapshot,
    RenderArtifacts,
    UninstallReport,
    ValidationReport,
    WorkspaceStatus,
)
from arbor_ddns.workspace.runtime_logging import close_workspace_logger, workspace_command_logger
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

        loaded, logger = self._load_workspace_with_logger(workspace_dir, command_name="validate")
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
        logger.info(
            "validated zone=%s entries=%d enabled=%d",
            report.zone_name,
            report.entry_count,
            report.enabled_entry_count,
        )
        return report

    def render_workspace(self, workspace_dir: str | Path) -> RenderArtifacts:
        """Render workspace artifacts."""

        loaded, logger = self._load_workspace_with_logger(workspace_dir, command_name="render")
        report = self._renderer.render(loaded)
        logger.info(
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

        loaded, logger = self._load_workspace_with_logger(workspace_dir, command_name="plan")
        managed_state = load_managed_records(loaded.paths)
        try:
            report = self._runner.run(
                loaded,
                managed_state=managed_state,
                apply=False,
                prune_managed=self._resolve_prune_managed(loaded, prune_managed),
            )
        except Exception:
            logger.exception("plan failed")
            raise
        self._log_run_report(logger, report)
        return report

    def sync_once(
        self,
        workspace_dir: str | Path,
        *,
        apply: bool,
        prune_managed: bool | None = None,
    ) -> WorkspaceRunReport:
        """Run one sync cycle for a workspace."""

        command_name = "sync-once-apply" if apply else "sync-once"
        loaded, logger = self._load_workspace_with_logger(workspace_dir, command_name=command_name)
        managed_state = load_managed_records(loaded.paths)
        try:
            report = self._runner.run(
                loaded,
                managed_state=managed_state,
                apply=apply,
                prune_managed=self._resolve_prune_managed(loaded, prune_managed),
            )
        except Exception:
            logger.exception("sync run failed")
            raise
        if apply:
            updated_state = self._reconcile_managed_state(loaded, managed_state, report)
            write_managed_records(loaded.paths, updated_state)
            logger.info("managed_state_updated records=%d", len(updated_state.records))
        self._log_run_report(logger, report)
        return report

    def apply_workspace(
        self,
        workspace_dir: str | Path,
        *,
        prune_managed: bool | None = None,
        run_sync: bool | None = None,
    ) -> ApplyReport:
        """Validate, render, install/update systemd units, and optionally sync once."""

        loaded, logger = self._load_workspace_with_logger(workspace_dir, command_name="apply")
        render_report = self._renderer.render(loaded)
        installed_service, installed_timer = self._systemd_manager.install_rendered_units(
            loaded.paths,
            loaded.resolved_workspace,
        )
        self._systemd_manager.daemon_reload()
        self._systemd_manager.enable_restart_timer(loaded.resolved_workspace.systemd.timer_name)
        logger.info(
            "systemd_installed service=%s timer=%s service_unit=%s timer_unit=%s",
            loaded.resolved_workspace.systemd.service_name,
            loaded.resolved_workspace.systemd.timer_name,
            installed_service,
            installed_timer,
        )

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
        logger.info(
            "apply_completed prune_managed=%s immediate_sync_requested=%s immediate_sync_ran=%s",
            report.prune_managed,
            report.immediate_sync_requested,
            report.immediate_sync_ran,
        )
        return report

    def provider_verify(self, workspace_dir: str | Path) -> ProviderVerification:
        """Verify Cloudflare token, zone lookup, and DNS listing access."""

        loaded, logger = self._load_workspace_with_logger(
            workspace_dir,
            command_name="provider-verify",
        )
        provider = CloudflareDNSProvider(loaded.resolved_workspace.cloudflare_provider_config())
        try:
            report = provider.verify()
        except Exception:
            logger.exception("provider verification failed")
            raise
        logger.info(
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
            runtime_dir_exists=paths.runtime_dir.exists(),
            runtime_log_file=str(paths.runtime_log_file),
            runtime_log_file_exists=paths.runtime_log_file.exists(),
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
                status="ok" if _path_write_target_available(paths.runtime_log_file) else "warn",
                message=f"runtime log file: {paths.runtime_log_file}",
            )
        )

        logger: LoggerAdapter | None = None
        if paths.runtime_dir.exists():
            logger = workspace_command_logger(
                loaded.paths,
                workspace_name=loaded.resolved_workspace.workspace_name,
                command_name="doctor",
            )
        if logger is not None:
            for check in checks:
                if check.status != "ok":
                    logger.warning(
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
        logger = workspace_command_logger(
            loaded.paths,
            workspace_name=loaded.resolved_workspace.workspace_name,
            command_name="uninstall",
        )
        report = UninstallReport(
            workspace_root=str(loaded.paths.root),
            workspace_name=loaded.resolved_workspace.workspace_name,
            service_name=loaded.resolved_workspace.systemd.service_name,
            timer_name=loaded.resolved_workspace.systemd.timer_name,
            systemctl_available=self._systemd_manager.systemctl_available(),
        )
        logger.info("uninstall_started purge=%s", purge)

        if report.systemctl_available:
            service_stop = self._systemd_manager.stop_service(report.service_name, check=False)
            if service_stop.returncode == 0:
                report.service_stopped = True
            else:
                report.warnings.append(
                    _systemctl_warning("stop service", report.service_name, service_stop)
                )

            timer_stop = self._systemd_manager.stop_timer(report.timer_name, check=False)
            if timer_stop.returncode == 0:
                report.timer_stopped = True
            else:
                report.warnings.append(
                    _systemctl_warning("stop timer", report.timer_name, timer_stop)
                )

            timer_disable = self._systemd_manager.disable_timer(report.timer_name, check=False)
            if timer_disable.returncode == 0:
                report.timer_disabled = True
            else:
                report.warnings.append(
                    _systemctl_warning("disable timer", report.timer_name, timer_disable)
                )
        else:
            report.warnings.append("systemctl is not available; skipped stop/disable/daemon-reload")

        removed_service = self._systemd_manager.remove_installed_unit(report.service_name, "service")
        report.service_unit_removed = removed_service is not None
        if removed_service is not None:
            report.removed_paths.append(str(removed_service))
        else:
            report.warnings.append(
                f"service unit already absent: "
                f"{self._systemd_manager.installed_unit_path(report.service_name, 'service')}"
            )

        removed_timer = self._systemd_manager.remove_installed_unit(report.timer_name, "timer")
        report.timer_unit_removed = removed_timer is not None
        if removed_timer is not None:
            report.removed_paths.append(str(removed_timer))
        else:
            report.warnings.append(
                f"timer unit already absent: "
                f"{self._systemd_manager.installed_unit_path(report.timer_name, 'timer')}"
            )

        if report.systemctl_available:
            daemon_reload = self._systemd_manager.daemon_reload(check=False)
            if daemon_reload.returncode == 0:
                report.daemon_reloaded = True
            else:
                report.warnings.append(
                    _systemctl_warning("daemon-reload", "systemd", daemon_reload)
                )

            service_reset = self._systemd_manager.reset_failed(
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

        logger.info(
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
            logger.warning("warning=%s", warning)

        close_workspace_logger(logger)
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
        report.manual_cleanup_hint = f"rm -rf {loaded.paths.root}"
        return report

    def _resolve_prune_managed(self, loaded: LoadedWorkspace, override: bool | None) -> bool:
        if override is None:
            return loaded.resolved_workspace.apply.prune_managed_records
        return override

    def _load_workspace_with_logger(
        self,
        workspace_dir: str | Path,
        *,
        command_name: str,
        runtime_validate: bool = True,
    ) -> tuple[LoadedWorkspace, LoggerAdapter]:
        loaded = self._storage.load(workspace_dir)
        logger = workspace_command_logger(
            loaded.paths,
            workspace_name=loaded.resolved_workspace.workspace_name,
            command_name=command_name,
        )
        logger.info("command_started workspace_root=%s", loaded.paths.root)
        if runtime_validate:
            try:
                self._storage.validate_loaded(loaded)
            except Exception:
                logger.exception("runtime validation failed")
                raise
        return loaded, logger

    def _log_run_report(self, logger: LoggerAdapter, report: WorkspaceRunReport) -> None:
        logger.info(
            "run_summary dry_run=%s entries=%d prune_candidates=%d warnings=%d",
            report.dry_run,
            len(report.entry_outcomes),
            len(report.prune_outcomes),
            len(report.warnings),
        )
        for outcome in report.entry_outcomes:
            actions = "-"
            if outcome.plan is not None:
                actions = ",".join(change.action for change in outcome.plan.changes)
            log_fn = logger.error if outcome.status == "error" else logger.info
            log_fn(
                "entry=%s fqdn=%s type=%s selection=%s selected=%s action=%s status=%s message=%s",
                outcome.entry_name,
                outcome.fqdn,
                outcome.record_type,
                outcome.selection_status,
                outcome.selected_value or "-",
                actions,
                outcome.status,
                outcome.message,
            )
        for outcome in report.prune_outcomes:
            actions = "-"
            if outcome.plan is not None:
                actions = ",".join(change.action for change in outcome.plan.changes)
            log_fn = logger.error if outcome.status == "error" else logger.info
            log_fn(
                "prune_entry=%s fqdn=%s type=%s record_id=%s action=%s status=%s message=%s",
                outcome.entry_name,
                outcome.fqdn,
                outcome.record_type,
                outcome.record_id or "-",
                actions,
                outcome.status,
                outcome.message,
            )
        for warning in report.warnings:
            logger.warning("warning=%s", warning)

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


def _systemctl_warning(action: str, unit_name: str, result: CommandResult) -> str:
    detail = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
    return f"could not {action} for {unit_name}: {detail}"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()
