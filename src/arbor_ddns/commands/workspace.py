"""Workspace-oriented CLI commands."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from arbor_ddns.commands import common


def register(app: typer.Typer) -> None:
    """Register workspace lifecycle commands."""

    @app.command("init")
    def init_command(
        directory: Path,
        config: Path | None = common.CONFIG_OPTION,
    ) -> None:
        """Initialize a new workspace directory."""

        try:
            created = common.workspace_service(config).init_workspace(directory)
        except Exception as exc:
            common.exit_with_error(exc)
        typer.echo(f"workspace={created}")

    @app.command("validate")
    def validate_command(
        workspace: Path = common.WORKSPACE_OPTION,
        json_output: bool = common.JSON_OPTION,
        config: Path | None = common.CONFIG_OPTION,
    ) -> None:
        """Validate a workspace."""

        try:
            report = common.workspace_service(config).validate_workspace(workspace)
        except Exception as exc:
            common.exit_with_error(exc, json_output=json_output)
        common.echo_model_or_text(report, json_output, common.format_validation_report)

    @app.command("render")
    def render_command(
        workspace: Path = common.WORKSPACE_OPTION,
        json_output: bool = common.JSON_OPTION,
        config: Path | None = common.CONFIG_OPTION,
    ) -> None:
        """Render workspace artifacts without applying them."""

        try:
            report = common.workspace_service(config).render_workspace(workspace)
        except Exception as exc:
            common.exit_with_error(exc, json_output=json_output)
        common.echo_model_or_text(report, json_output, common.format_render_report)

    @app.command("apply")
    def apply_command(
        workspace: Path = common.WORKSPACE_OPTION,
        json_output: bool = common.JSON_OPTION,
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
        config: Path | None = common.CONFIG_OPTION,
    ) -> None:
        """Validate, render, install units, and optionally sync once."""

        prune_override = common.resolve_bool_override(prune_managed, no_prune_managed, "prune")
        run_sync_override = common.resolve_bool_override(run_sync, no_run_sync, "run-sync")
        try:
            report = common.workspace_service(config).apply_workspace(
                workspace,
                prune_managed=prune_override,
                run_sync=run_sync_override,
            )
        except Exception as exc:
            common.exit_with_error(exc, json_output=json_output)
        common.echo_model_or_text(report, json_output, common.format_apply_report)
        if report.sync_report is not None and report.sync_report.has_errors():
            raise typer.Exit(code=1)

    @app.command("uninstall")
    def uninstall_command(
        workspace: Path = common.WORKSPACE_OPTION,
        json_output: bool = common.JSON_OPTION,
        purge: Annotated[
            bool,
            typer.Option("--purge", help="Delete the entire workspace directory after uninstall."),
        ] = False,
        config: Path | None = common.CONFIG_OPTION,
    ) -> None:
        """Remove installed units and generated artifacts for a workspace."""

        try:
            report = common.workspace_service(config).uninstall_workspace(workspace, purge=purge)
        except Exception as exc:
            common.exit_with_error(exc, json_output=json_output)
        common.echo_model_or_text(report, json_output, common.format_uninstall_report)

    @app.command("status")
    def status_command(
        workspace: Path = common.WORKSPACE_OPTION,
        json_output: bool = common.JSON_OPTION,
        config: Path | None = common.CONFIG_OPTION,
    ) -> None:
        """Show aggregated workspace status."""

        try:
            report = common.workspace_service(config).status_workspace(workspace)
        except Exception as exc:
            common.exit_with_error(exc, json_output=json_output)
        common.echo_model_or_text(report, json_output, common.format_status_report)
        if report.errors:
            raise typer.Exit(code=1)

    @app.command("doctor")
    def doctor_command(
        workspace: Path = common.WORKSPACE_OPTION,
        json_output: bool = common.JSON_OPTION,
        config: Path | None = common.CONFIG_OPTION,
    ) -> None:
        """Run non-destructive workspace health checks."""

        report = common.workspace_service(config).doctor_workspace(workspace)
        common.echo_model_or_text(report, json_output, common.format_doctor_report)
        if not report.ok:
            raise typer.Exit(code=1)

    @app.command("plan")
    def plan_command(
        workspace: Path = common.WORKSPACE_OPTION,
        json_output: bool = common.JSON_OPTION,
        prune_managed: Annotated[
            bool,
            typer.Option("--prune-managed", help="Include prune planning."),
        ] = False,
        no_prune_managed: Annotated[
            bool,
            typer.Option("--no-prune-managed", help="Disable prune planning."),
        ] = False,
        config: Path | None = common.CONFIG_OPTION,
    ) -> None:
        """Run a live DNS plan against the configured provider."""

        prune_override = common.resolve_bool_override(prune_managed, no_prune_managed, "prune")
        try:
            report = common.workspace_service(config).plan_workspace(
                workspace,
                prune_managed=prune_override,
            )
        except Exception as exc:
            common.exit_with_error(exc, json_output=json_output)
        common.echo_model_or_text(report, json_output, common.format_run_report)
        if report.has_errors():
            raise typer.Exit(code=1)

    @app.command("sync-once")
    def sync_once_command(
        workspace: Path = common.WORKSPACE_OPTION,
        json_output: bool = common.JSON_OPTION,
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
        config: Path | None = common.CONFIG_OPTION,
    ) -> None:
        """Run one live workspace sync cycle."""

        prune_override = common.resolve_bool_override(prune_managed, no_prune_managed, "prune")
        try:
            report = common.workspace_service(config).sync_once(
                workspace,
                apply=apply,
                prune_managed=prune_override,
            )
        except Exception as exc:
            common.exit_with_error(exc, json_output=json_output)
        common.echo_model_or_text(report, json_output, common.format_run_report)
        if report.has_errors():
            raise typer.Exit(code=1)
