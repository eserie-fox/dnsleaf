"""DNS provider CLI commands."""

from __future__ import annotations

from pathlib import Path

import typer

from dnsleaf.commands import common


def register(app: typer.Typer) -> None:
    """Register `provider` commands."""

    provider_app = typer.Typer(
        help="Provider-specific operations.",
        no_args_is_help=True,
    )
    app.add_typer(provider_app, name="provider")

    @provider_app.command("verify")
    def provider_verify_command(
        ctx: typer.Context,
        workspace: Path = common.WORKSPACE_OPTION,
        json_output: bool = common.JSON_OPTION,
    ) -> None:
        """Verify the Cloudflare provider configuration and API access."""

        try:
            with common.workspace_command_logging(ctx, workspace, command_name="provider-verify"):
                report = common.workspace_service(ctx).provider_verify(workspace)
        except Exception as exc:
            common.exit_with_error(exc, json_output=json_output)
        common.echo_model_or_text(report, json_output, common.format_provider_verification)
