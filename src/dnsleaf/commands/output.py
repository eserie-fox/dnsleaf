"""CLI report presentation and error output."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, TypeVar

import typer
from pydantic import BaseModel

from dnsleaf.dns.models import ProviderVerification
from dnsleaf.models import EntrySourceKind
from dnsleaf.util.privilege import permission_hint
from dnsleaf.workspace.models import WorkspaceEntry
from dnsleaf.workspace.reports import (
    ApplyReport,
    DoctorReport,
    EntryMutationResult,
    RenderArtifacts,
    UninstallReport,
    ValidationReport,
    WorkspaceRunReport,
    WorkspaceStatus,
)

Report = TypeVar("Report", bound=BaseModel)


def echo_model_or_text(
    model: Report,
    json_output: bool,
    formatter: Callable[[Report], None],
) -> None:
    """Emit JSON or formatted text."""

    if json_output:
        typer.echo(json_payload(model.model_dump(mode="json", exclude_none=True)))
        return
    formatter(model)


def json_payload(payload: Any) -> str:
    """Return pretty JSON output."""

    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def exit_with_error(exc: Exception, *, json_output: bool = False) -> None:
    """Emit a CLI error and exit."""

    message = str(exc)
    cause: BaseException | None = exc
    while cause is not None:
        if isinstance(cause, PermissionError):
            message = f"{message}\n{permission_hint()}"
            break
        cause = cause.__cause__
    if json_output:
        typer.echo(json_payload({"ok": False, "error": message}), err=True)
    else:
        typer.echo(f"error={message}", err=True)
    raise typer.Exit(code=1)


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
    if report.runtime_log_symlink_target is not None:
        typer.echo(f"log_target={report.runtime_log_symlink_target}")
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
        source_descriptor = (
            outcome.source_kind.value
            if outcome.source_kind in {EntrySourceKind.STATIC, EntrySourceKind.LOCAL}
            else f"{outcome.source_kind.value}/{outcome.source_id}"
        )
        typer.echo(
            f"entry={outcome.entry_name} source={source_descriptor} "
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
