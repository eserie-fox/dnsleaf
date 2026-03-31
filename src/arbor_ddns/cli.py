"""Typer CLI entrypoint."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

import typer

from arbor_ddns.config import AppConfig
from arbor_ddns.dns.models import ProviderVerification
from arbor_ddns.models import TargetKind, TargetRef
from arbor_ddns.sync.runner import SyncRunner, WorkspaceRunReport, build_runner
from arbor_ddns.workspace.entries import EntryService
from arbor_ddns.workspace.models import (
    DoctorReport,
    RenderArtifacts,
    ValidationReport,
    WorkspaceStatus,
)
from arbor_ddns.workspace.service import ApplyReport
from arbor_ddns.workspace.service import WorkspaceService

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Manage workspace-driven PVE IPv6 discovery and Cloudflare DNS synchronization.",
)
discover_app = typer.Typer(help="Run low-level discovery/debug commands.")
entry_app = typer.Typer(help="Manage workspace entries.")
provider_app = typer.Typer(help="Provider-specific operations.")
entry_add_app = typer.Typer(help="Add a workspace entry.")
app.add_typer(discover_app, name="discover")
app.add_typer(entry_app, name="entry")
app.add_typer(provider_app, name="provider")
entry_app.add_typer(entry_add_app, name="add")

ConfigPathOption = Annotated[
    Path | None,
    typer.Option("--config", "-c", help="Optional app runtime JSON override."),
]
WorkspaceOption = Annotated[
    Path,
    typer.Option("--workspace", "-w", help="Workspace directory."),
]
JsonOption = Annotated[
    bool,
    typer.Option("--json", help="Emit machine-friendly JSON."),
]


def _load_config(config_path: Path | None) -> AppConfig:
    return AppConfig.from_file(config_path)


def _workspace_service(config_path: Path | None) -> WorkspaceService:
    return WorkspaceService(app_config=_load_config(config_path))


def _entry_service(config_path: Path | None) -> EntryService:
    from arbor_ddns.workspace.storage import WorkspaceStorage

    return EntryService(storage=WorkspaceStorage(_load_config(config_path)))


def _debug_runner(config_path: Path | None) -> SyncRunner:
    return build_runner(_load_config(config_path))


@app.command("init")
def init_command(
    directory: Path,
    config: ConfigPathOption = None,
) -> None:
    """Initialize a new workspace directory."""

    service = _workspace_service(config)
    try:
        created = service.init_workspace(directory)
    except Exception as exc:
        _exit_with_error(exc)
    typer.echo(f"workspace={created}")


@app.command("validate")
def validate_command(
    workspace: WorkspaceOption,
    json_output: JsonOption = False,
    config: ConfigPathOption = None,
) -> None:
    """Validate a workspace."""

    try:
        report = _workspace_service(config).validate_workspace(workspace)
    except Exception as exc:
        _exit_with_error(exc, json_output=json_output)
    _echo_model_or_text(report, json_output, _format_validation_report)


@app.command("render")
def render_command(
    workspace: WorkspaceOption,
    json_output: JsonOption = False,
    config: ConfigPathOption = None,
) -> None:
    """Render workspace artifacts without applying them."""

    try:
        report = _workspace_service(config).render_workspace(workspace)
    except Exception as exc:
        _exit_with_error(exc, json_output=json_output)
    _echo_model_or_text(report, json_output, _format_render_report)


@app.command("apply")
def apply_command(
    workspace: WorkspaceOption,
    json_output: JsonOption = False,
    prune_managed: Annotated[
        bool,
        typer.Option("--prune-managed", help="Override the workspace default and allow prune."),
    ] = False,
    no_prune_managed: Annotated[
        bool,
        typer.Option(
            "--no-prune-managed",
            help="Override the workspace default and disable prune.",
        ),
    ] = False,
    run_sync: Annotated[
        bool,
        typer.Option("--run-sync", help="Run one immediate sync after apply."),
    ] = False,
    no_run_sync: Annotated[
        bool,
        typer.Option("--no-run-sync", help="Skip immediate sync after apply."),
    ] = False,
    config: ConfigPathOption = None,
) -> None:
    """Validate, render, install units, and optionally sync once."""

    prune_override = _resolve_bool_override(prune_managed, no_prune_managed, "prune")
    run_sync_override = _resolve_bool_override(run_sync, no_run_sync, "run-sync")
    try:
        report = _workspace_service(config).apply_workspace(
            workspace,
            prune_managed=prune_override,
            run_sync=run_sync_override,
        )
    except Exception as exc:
        _exit_with_error(exc, json_output=json_output)
    _echo_model_or_text(report, json_output, _format_apply_report)
    if report.sync_report is not None and report.sync_report.has_errors():
        raise typer.Exit(code=1)


@app.command("status")
def status_command(
    workspace: WorkspaceOption,
    json_output: JsonOption = False,
    config: ConfigPathOption = None,
) -> None:
    """Show aggregated workspace status."""

    try:
        report = _workspace_service(config).status_workspace(workspace)
    except Exception as exc:
        _exit_with_error(exc, json_output=json_output)
    _echo_model_or_text(report, json_output, _format_status_report)
    if report.errors:
        raise typer.Exit(code=1)


@app.command("doctor")
def doctor_command(
    workspace: WorkspaceOption,
    json_output: JsonOption = False,
    config: ConfigPathOption = None,
) -> None:
    """Run non-destructive workspace health checks."""

    report = _workspace_service(config).doctor_workspace(workspace)
    _echo_model_or_text(report, json_output, _format_doctor_report)
    if not report.ok:
        raise typer.Exit(code=1)


@app.command("plan")
def plan_command(
    workspace: WorkspaceOption,
    json_output: JsonOption = False,
    prune_managed: Annotated[
        bool,
        typer.Option("--prune-managed", help="Include prune planning."),
    ] = False,
    no_prune_managed: Annotated[
        bool,
        typer.Option("--no-prune-managed", help="Disable prune planning."),
    ] = False,
    config: ConfigPathOption = None,
) -> None:
    """Run a live DNS plan against the configured provider."""

    prune_override = _resolve_bool_override(prune_managed, no_prune_managed, "prune")
    try:
        report = _workspace_service(config).plan_workspace(
            workspace,
            prune_managed=prune_override,
        )
    except Exception as exc:
        _exit_with_error(exc, json_output=json_output)
    _echo_model_or_text(report, json_output, _format_run_report)
    if report.has_errors():
        raise typer.Exit(code=1)


@app.command("sync-once")
def sync_once_command(
    workspace: WorkspaceOption,
    json_output: JsonOption = False,
    apply: Annotated[
        bool,
        typer.Option("--apply", help="Apply changes instead of printing a dry-run report."),
    ] = False,
    prune_managed: Annotated[
        bool,
        typer.Option("--prune-managed", help="Include prune changes."),
    ] = False,
    no_prune_managed: Annotated[
        bool,
        typer.Option("--no-prune-managed", help="Disable prune changes."),
    ] = False,
    config: ConfigPathOption = None,
) -> None:
    """Run one live workspace sync cycle."""

    prune_override = _resolve_bool_override(prune_managed, no_prune_managed, "prune")
    try:
        report = _workspace_service(config).sync_once(
            workspace,
            apply=apply,
            prune_managed=prune_override,
        )
    except Exception as exc:
        _exit_with_error(exc, json_output=json_output)
    _echo_model_or_text(report, json_output, _format_run_report)
    if report.has_errors():
        raise typer.Exit(code=1)


@provider_app.command("verify")
def provider_verify_command(
    workspace: WorkspaceOption,
    json_output: JsonOption = False,
    config: ConfigPathOption = None,
) -> None:
    """Verify the Cloudflare provider configuration and API access."""

    try:
        report = _workspace_service(config).provider_verify(workspace)
    except Exception as exc:
        _exit_with_error(exc, json_output=json_output)
    _echo_model_or_text(report, json_output, _format_provider_verification)


@entry_app.command("list")
def entry_list_command(
    workspace: WorkspaceOption,
    json_output: JsonOption = False,
    config: ConfigPathOption = None,
) -> None:
    """List workspace entries."""

    try:
        entries = _entry_service(config).list_entries(workspace)
    except Exception as exc:
        _exit_with_error(exc, json_output=json_output)
    if json_output:
        payload = [entry.model_dump(mode="json", exclude_none=True) for entry in entries]
        typer.echo(_json_payload(payload))
        return
    if not entries:
        typer.echo("entries=0")
        return
    for entry in entries:
        typer.echo(
            f"name={entry.name} source={entry.source_kind.value}/{entry.source_id} "
            f"fqdn={entry.fqdn} type={entry.record_type} enabled={entry.enabled}"
        )


@entry_app.command("update")
def entry_update_command(
    name: str,
    workspace: WorkspaceOption,
    fqdn: Annotated[str | None, typer.Option("--fqdn")] = None,
    selection_policy: Annotated[str | None, typer.Option("--selection-policy")] = None,
    enabled: Annotated[bool | None, typer.Option("--enabled")] = None,
    ttl: Annotated[int | None, typer.Option("--ttl")] = None,
    proxied: Annotated[bool | None, typer.Option("--proxied")] = None,
    source_id: Annotated[int | None, typer.Option("--id")] = None,
    description: Annotated[str | None, typer.Option("--description")] = None,
    config: ConfigPathOption = None,
) -> None:
    """Update a workspace entry."""

    try:
        result = _entry_service(config).update_entry(
            workspace,
            name=name,
            fqdn=fqdn,
            selection_policy=selection_policy,
            enabled=enabled,
            ttl=ttl,
            proxied=proxied,
            source_id=source_id,
            description=description,
        )
    except Exception as exc:
        _exit_with_error(exc)
    typer.echo(result.message)


@entry_app.command("remove")
def entry_remove_command(
    name: str,
    workspace: WorkspaceOption,
    config: ConfigPathOption = None,
) -> None:
    """Remove a workspace entry."""

    try:
        result = _entry_service(config).remove_entry(workspace, name=name)
    except Exception as exc:
        _exit_with_error(exc)
    typer.echo(result.message)


@entry_app.command("enable")
def entry_enable_command(
    name: str,
    workspace: WorkspaceOption,
    config: ConfigPathOption = None,
) -> None:
    """Enable a workspace entry."""

    try:
        result = _entry_service(config).set_enabled(workspace, name=name, enabled=True)
    except Exception as exc:
        _exit_with_error(exc)
    typer.echo(result.message)


@entry_app.command("disable")
def entry_disable_command(
    name: str,
    workspace: WorkspaceOption,
    config: ConfigPathOption = None,
) -> None:
    """Disable a workspace entry."""

    try:
        result = _entry_service(config).set_enabled(workspace, name=name, enabled=False)
    except Exception as exc:
        _exit_with_error(exc)
    typer.echo(result.message)


@entry_add_app.command("lxc")
def entry_add_lxc(
    workspace: WorkspaceOption,
    source_id: Annotated[int, typer.Option("--id")],
    fqdn: Annotated[str, typer.Option("--fqdn")],
    name: Annotated[str, typer.Option("--name")],
    selection_policy: Annotated[str, typer.Option("--selection-policy")] = "default",
    ttl: Annotated[int | None, typer.Option("--ttl")] = None,
    proxied: Annotated[bool | None, typer.Option("--proxied")] = None,
    description: Annotated[str | None, typer.Option("--description")] = None,
    config: ConfigPathOption = None,
) -> None:
    """Add an LXC-backed `AAAA` entry."""

    try:
        result = _entry_service(config).add_entry(
            workspace,
            name=name,
            source_kind="lxc",
            source_id=source_id,
            fqdn=fqdn,
            selection_policy=selection_policy,
            ttl=ttl,
            proxied=proxied,
            description=description,
        )
    except Exception as exc:
        _exit_with_error(exc)
    typer.echo(result.message)


@entry_add_app.command("vm")
def entry_add_vm(
    workspace: WorkspaceOption,
    source_id: Annotated[int, typer.Option("--id")],
    fqdn: Annotated[str, typer.Option("--fqdn")],
    name: Annotated[str, typer.Option("--name")],
    selection_policy: Annotated[str, typer.Option("--selection-policy")] = "default",
    ttl: Annotated[int | None, typer.Option("--ttl")] = None,
    proxied: Annotated[bool | None, typer.Option("--proxied")] = None,
    description: Annotated[str | None, typer.Option("--description")] = None,
    config: ConfigPathOption = None,
) -> None:
    """Add a VM-backed `AAAA` entry."""

    try:
        result = _entry_service(config).add_entry(
            workspace,
            name=name,
            source_kind="vm",
            source_id=source_id,
            fqdn=fqdn,
            selection_policy=selection_policy,
            ttl=ttl,
            proxied=proxied,
            description=description,
        )
    except Exception as exc:
        _exit_with_error(exc)
    typer.echo(result.message)


@discover_app.command("lxc")
def discover_lxc_command(
    target_id: int,
    config: ConfigPathOption = None,
) -> None:
    """Discover IPv6 candidates for an LXC guest."""

    _run_discover(TargetKind.LXC, target_id, config)


@discover_app.command("vm")
def discover_vm_command(
    target_id: int,
    config: ConfigPathOption = None,
) -> None:
    """Discover IPv6 candidates for a VM guest."""

    _run_discover(TargetKind.VM, target_id, config)


def _run_discover(kind: TargetKind, target_id: int, config_path: Path | None) -> None:
    target = TargetRef(kind=kind, id=target_id)
    runner = _debug_runner(config_path)
    discovery, selection = runner.discover_target(target, policy="default")
    typer.echo(f"target={kind.value}/{target_id} backend={discovery.backend}")
    if discovery.error is not None:
        typer.echo(f"status=error reason={discovery.error}")
        raise typer.Exit(code=1)
    typer.echo(f"status={selection.status} reason={selection.reason}")
    if selection.selected is not None:
        typer.echo(
            "selected="
            f"{selection.selected.address}/{selection.selected.prefix_length} "
            f"interface={selection.selected.interface}"
        )
    for candidate in selection.remaining_candidates:
        typer.echo(f"candidate={candidate.interface} {candidate.cidr}")
    for rejected in selection.filtered_out:
        typer.echo(
            f"filtered={rejected.candidate.interface} "
            f"{rejected.candidate.cidr} reason={rejected.reason}"
        )
    for skipped in selection.not_selected:
        typer.echo(
            f"not-selected={skipped.candidate.interface} "
            f"{skipped.candidate.cidr} reason={skipped.reason}"
        )


def _echo_model_or_text(
    model: Any,
    json_output: bool,
    formatter: Callable[[Any], None],
) -> None:
    if json_output:
        if hasattr(model, "model_dump"):
            typer.echo(_json_payload(model.model_dump(mode="json", exclude_none=True)))
            return
        typer.echo(_json_payload(model))
        return
    formatter(model)


def _format_validation_report(report: ValidationReport) -> None:
    typer.echo(
        f"workspace={report.workspace_name} provider={report.provider} zone={report.zone_name} "
        f"entries={report.entry_count} enabled={report.enabled_entry_count}"
    )
    typer.echo(f"token_file={report.token_file}")


def _format_render_report(report: RenderArtifacts) -> None:
    typer.echo(f"workspace={report.workspace_name} rendered={report.workspace_root}")
    typer.echo(f"effective_workspace={report.effective_workspace_file}")
    typer.echo(f"desired_records={report.desired_records_file}")
    typer.echo(f"service_unit={report.service_unit_file}")
    typer.echo(f"timer_unit={report.timer_unit_file}")


def _format_apply_report(report: ApplyReport) -> None:
    typer.echo(
        f"workspace={report.workspace_name} service={report.service_name} "
        f"timer={report.timer_name} "
        f"immediate_sync_ran={report.immediate_sync_ran}"
    )
    typer.echo(f"installed_service={report.installed_service_unit}")
    typer.echo(f"installed_timer={report.installed_timer_unit}")
    if report.sync_report is not None:
        _format_run_report(report.sync_report)


def _format_status_report(report: WorkspaceStatus) -> None:
    typer.echo(
        f"workspace={report.workspace_name} provider={report.provider} zone={report.zone_name} "
        f"entries={report.entry_count} enabled={report.enabled_entry_count}"
    )
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


def _format_doctor_report(report: DoctorReport) -> None:
    for check in report.checks:
        typer.echo(f"{check.status} name={check.name} message={check.message}")


def _format_provider_verification(report: ProviderVerification) -> None:
    typer.echo(
        f"provider={report.provider} zone_id={report.zone_id} "
        f"zone_name={report.zone_name or '-'} token_file={report.token_file}"
    )
    typer.echo(f"record_listing_succeeded={report.record_listing_succeeded}")


def _format_run_report(report: WorkspaceRunReport) -> None:
    typer.echo(f"workspace={report.workspace_name} dry_run={report.dry_run}")
    if not report.entry_outcomes and not report.prune_outcomes:
        typer.echo("status=no-enabled-entries")
        return
    for outcome in report.entry_outcomes:
        actions = "-"
        if outcome.plan is not None:
            actions = ",".join(change.action for change in outcome.plan.changes)
        typer.echo(
            f"entry={outcome.entry_name} source={outcome.source_kind.value}/{outcome.source_id} "
            f"fqdn={outcome.fqdn} type={outcome.record_type} status={outcome.status} "
            f"selection={outcome.selection_status} selected={outcome.selected_value or '-'} "
            f"action={actions} message={outcome.message}"
        )
    for prune_outcome in report.prune_outcomes:
        actions = "-"
        if prune_outcome.plan is not None:
            actions = ",".join(change.action for change in prune_outcome.plan.changes)
        typer.echo(
            f"prune_entry={prune_outcome.entry_name} fqdn={prune_outcome.fqdn} "
            f"type={prune_outcome.record_type} record_id={prune_outcome.record_id or '-'} "
            f"status={prune_outcome.status} action={actions} "
            f"message={prune_outcome.message}"
        )


def _resolve_bool_override(yes: bool, no: bool, label: str) -> bool | None:
    if yes and no:
        raise typer.BadParameter(f"cannot pass both --{label} and --no-{label}")
    if yes:
        return True
    if no:
        return False
    return None


def _json_payload(payload: Any) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _exit_with_error(exc: Exception, *, json_output: bool = False) -> None:
    if json_output:
        typer.echo(_json_payload({"ok": False, "error": str(exc)}), err=True)
    else:
        typer.echo(f"error={exc}", err=True)
    raise typer.Exit(code=1)


def main() -> None:
    """Console-script entrypoint."""

    app()
