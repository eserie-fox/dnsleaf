"""CLI entrypoint."""

from __future__ import annotations

import logging

import typer

from dnsleaf.commands import discovery, entry, provider, workspace
from dnsleaf.commands.common import OUTSIDE_WORKSPACE_CONFIG_CONTEXT_KEY
from dnsleaf.config.outside_workspace import OutsideWorkspaceConfig
from dnsleaf.logging.runtime import configure_default_logging
from dnsleaf.version import __version__

app = typer.Typer(
    add_completion=False,
    help=(
        "Manage workspace-driven Cloudflare DDNS for PVE guests, "
        "the local host, and static IP targets."
    ),
    no_args_is_help=True,
    invoke_without_command=True,
)
VERSION_OPTION = typer.Option(
    False,
    "--version",
    help="Show version and exit",
    is_eager=True,
)


@app.callback()
def callback(
    ctx: typer.Context,
    version: bool = VERSION_OPTION,
) -> None:
    """Top-level CLI callback."""

    ctx.ensure_object(dict)
    if version:
        typer.echo(__version__)
        raise typer.Exit()

    outside_workspace_config = OutsideWorkspaceConfig.from_defaults()
    configure_default_logging(
        stream_name=outside_workspace_config.dnsleaf_logging.stream,
        level=outside_workspace_config.dnsleaf_logging.resolved_level(),
        fmt=outside_workspace_config.dnsleaf_logging.format,
    )
    ctx.obj[OUTSIDE_WORKSPACE_CONFIG_CONTEXT_KEY] = outside_workspace_config
    logging.getLogger(__name__).debug("starting CLI command: %s", ctx.invoked_subcommand)


for module in (workspace, entry, provider, discovery):
    module.register(app)


def main() -> None:
    """Console-script entrypoint."""

    app()
