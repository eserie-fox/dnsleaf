"""CLI entrypoint."""

from __future__ import annotations

import typer

from arbor_ddns import __version__
from arbor_ddns.commands import discovery, entry, provider, workspace

app = typer.Typer(
    add_completion=False,
    help="Manage workspace-driven Cloudflare DDNS for PVE guests and static IP entries.",
    invoke_without_command=True,
)


@app.callback()
def callback(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", help="Show version and exit", is_eager=True),
) -> None:
    """Top-level CLI callback."""

    if version:
        typer.echo(__version__)
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()


for module in (workspace, entry, provider, discovery):
    module.register(app)


def main() -> None:
    """Console-script entrypoint."""

    app()
