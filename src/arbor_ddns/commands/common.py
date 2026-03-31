"""Shared CLI helpers."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import typer

from arbor_ddns.config import AppConfig
from arbor_ddns.dns.models import ProviderVerification
from arbor_ddns.models import EntryAddressFamily
from arbor_ddns.sync.runner import SyncRunner, WorkspaceRunReport, build_runner
from arbor_ddns.workspace.entries import EntryService
from arbor_ddns.workspace.models import (
    DoctorReport,
    EntryMutationResult,
    RenderArtifacts,
    UninstallReport,
    ValidationReport,
    WorkspaceEntry,
    WorkspaceStatus,
)
from arbor_ddns.workspace.service import ApplyReport, WorkspaceService

CONFIG_OPTION = typer.Option(None, "--config", "-c", help="Optional app runtime JSON override.")
WORKSPACE_OPTION = typer.Option(
    Path("."),
    "--workspace",
    "-w",
    help="Workspace directory. Defaults to the current directory.",
)
JSON_OPTION = typer.Option(False, "--json", help="Emit machine-friendly JSON.")
FAMILY_OPTION = typer.Option(
    ...,
    "--family",
    help="Address family intent: ipv4, ipv6, or both.",
)
FAMILY_BOTH_OPTION = typer.Option(
    EntryAddressFamily.BOTH,
    "--family",
    help="Address family intent: ipv4, ipv6, or both.",
)


def load_config(config_path: Path | None) -> AppConfig:
    """Load app runtime config."""

    return AppConfig.from_file(config_path)


def workspace_service(config_path: Path | None) -> WorkspaceService:
    """Build the workspace facade."""

    return WorkspaceService(app_config=load_config(config_path))


def entry_service(config_path: Path | None) -> EntryService:
    """Build the entry facade."""

    from arbor_ddns.workspace.storage import WorkspaceStorage

    return EntryService(storage=WorkspaceStorage(load_config(config_path)))


def debug_runner(config_path: Path | None) -> SyncRunner:
    """Build the low-level debug runner."""

    return build_runner(load_config(config_path))


def echo_model_or_text(
    model: Any,
    json_output: bool,
    formatter: Callable[[Any], None],
) -> None:
    """Emit JSON or formatted text."""

    if json_output:
        if hasattr(model, "model_dump"):
            typer.echo(json_payload(model.model_dump(mode="json", exclude_none=True)))
            return
        typer.echo(json_payload(model))
        return
    formatter(model)


def json_payload(payload: Any) -> str:
    """Return pretty JSON output."""

    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def exit_with_error(exc: Exception, *, json_output: bool = False) -> None:
    """Emit a CLI error and exit."""

    if json_output:
        typer.echo(json_payload({"ok": False, "error": str(exc)}), err=True)
    else:
        typer.echo(f"error={exc}", err=True)
    raise typer.Exit(code=1)


def resolve_bool_override(yes: bool, no: bool, label: str) -> bool | None:
    """Resolve mutually exclusive boolean CLI flags."""

    if yes and no:
        raise typer.BadParameter(f"cannot pass both --{label} and --no-{label}")
    if yes:
        return True
    if no:
        return False
    return None


def format_validation_report(report: ValidationReport) -> None:
    typer.echo(
        f"workspace={report.workspace_name} provider={report.provider} zone={report.zone_name} "
        f"entries={report.entry_count} enabled={report.enabled_entry_count}"
    )
    typer.echo(f"token_file={report.token_file}")


def format_render_report(report: RenderArtifacts) -> None:
    typer.echo(f"workspace={report.workspace_name} rendered={report.workspace_root}")
    typer.echo(f"effective_workspace={report.effective_workspace_file}")
    typer.echo(f"desired_records={report.desired_records_file}")
    typer.echo(f"service_unit={report.service_unit_file}")
    typer.echo(f"timer_unit={report.timer_unit_file}")


def format_apply_report(report: ApplyReport) -> None:
    typer.echo(
        f"workspace={report.workspace_name} service={report.service_name} "
        f"timer={report.timer_name} immediate_sync_ran={report.immediate_sync_ran}"
    )
    typer.echo(f"installed_service={report.installed_service_unit}")
    typer.echo(f"installed_timer={report.installed_timer_unit}")
    if report.sync_report is not None:
        format_run_report(report.sync_report)


def format_status_report(report: WorkspaceStatus) -> None:
    typer.echo(
        f"workspace={report.workspace_name} provider={report.provider} zone={report.zone_name} "
        f"entries={report.entry_count} enabled={report.enabled_entry_count}"
    )
    typer.echo(
        f"runtime_exists={report.runtime_dir_exists} log_exists={report.runtime_log_file_exists}"
    )
    typer.echo(f"log_file={report.runtime_log_file}")
    typer.echo(
        f"managed_active={report.managed_active_count} managed_stale={report.managed_stale_count}"
    )
    typer.echo(
        f"service_status={report.service_status.active_state or 'unknown'} "
        f"timer_status={report.timer_status.active_state or 'unknown'}"
    )
    for warning in report.warnings:
        typer.echo(f"warning={warning}")
    for error in report.errors:
        typer.echo(f"error={error}")


def format_doctor_report(report: DoctorReport) -> None:
    for check in report.checks:
        typer.echo(f"{check.status} name={check.name} message={check.message}")


def format_uninstall_report(report: UninstallReport) -> None:
    typer.echo(
        f"workspace={report.workspace_name} service={report.service_name} "
        f"timer={report.timer_name} purged={report.purged}"
    )
    typer.echo(
        f"service_stopped={report.service_stopped} timer_stopped={report.timer_stopped} "
        f"timer_disabled={report.timer_disabled}"
    )
    typer.echo(
        f"service_unit_removed={report.service_unit_removed} "
        f"timer_unit_removed={report.timer_unit_removed} "
        f"daemon_reloaded={report.daemon_reloaded}"
    )
    typer.echo(
        f"service_reset_failed={report.service_reset_failed} "
        f"timer_reset_failed={report.timer_reset_failed}"
    )
    for removed in report.removed_paths:
        typer.echo(f"removed={removed}")
    for kept in report.kept_paths:
        typer.echo(f"kept={kept}")
    if report.manual_cleanup_hint is not None:
        typer.echo("System installation artifacts have been removed.")
        typer.echo(f"Workspace configuration is still present in {report.workspace_root}.")
        typer.echo(
            "If you no longer need it, you can remove it manually with: "
            f"{report.manual_cleanup_hint}"
        )
    for warning in report.warnings:
        typer.echo(f"warning={warning}")


def format_provider_verification(report: ProviderVerification) -> None:
    typer.echo(
        f"provider={report.provider} zone_id={report.zone_id} "
        f"zone_name={report.zone_name or '-'} token_file={report.token_file}"
    )
    typer.echo(f"record_listing_succeeded={report.record_listing_succeeded}")


def format_run_report(report: WorkspaceRunReport) -> None:
    typer.echo(f"workspace={report.workspace_name} dry_run={report.dry_run}")
    if not report.record_outcomes and not report.prune_outcomes:
        typer.echo("status=no-enabled-entries")
        return
    for outcome in report.record_outcomes:
        actions = "-"
        if outcome.plan is not None:
            actions = ",".join(change.action for change in outcome.plan.changes)
        typer.echo(
            f"entry={outcome.entry_name} source={outcome.source_kind.value}/"
            f"{outcome.source_id if outcome.source_id is not None else '-'} "
            f"fqdn={outcome.fqdn} family={outcome.family.value} type={outcome.record_type} "
            f"value_source={outcome.value_source} status={outcome.status} "
            f"selection={outcome.selection_status or '-'} selected={outcome.selected_value or '-'} "
            f"action={actions} message={outcome.message}"
        )
    for prune_outcome in report.prune_outcomes:
        actions = "-"
        if prune_outcome.plan is not None:
            actions = ",".join(change.action for change in prune_outcome.plan.changes)
        typer.echo(
            f"prune_entry={prune_outcome.entry_name} fqdn={prune_outcome.fqdn} "
            f"type={prune_outcome.record_type} record_id={prune_outcome.record_id or '-'} "
            f"status={prune_outcome.status} action={actions} message={prune_outcome.message}"
        )


def format_entry(entry: WorkspaceEntry) -> str:
    """Return one flat text summary for an entry."""

    static_parts: list[str] = []
    if entry.static_ipv4 is not None:
        static_parts.append(f"ipv4={entry.static_ipv4}")
    if entry.static_ipv6 is not None:
        static_parts.append(f"ipv6={entry.static_ipv6}")
    static_suffix = f" {' '.join(static_parts)}" if static_parts else ""
    return (
        f"name={entry.name} source={entry.source_descriptor} fqdn={entry.fqdn} "
        f"family={entry.family.value} enabled={entry.enabled}{static_suffix}"
    )


def format_entry_mutation(result: EntryMutationResult) -> None:
    """Emit a human-readable entry mutation summary."""

    typer.echo(result.message)
