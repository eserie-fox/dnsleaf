"""Workspace entry CLI commands."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from dnsleaf.commands import common, output
from dnsleaf.models import EntryAddressFamily


def register(app: typer.Typer) -> None:
    """Register `entry` commands."""

    entry_app = typer.Typer(
        help="Manage workspace entries.",
        no_args_is_help=True,
    )
    entry_add_app = typer.Typer(
        help="Add a new workspace entry.",
        no_args_is_help=True,
    )
    entry_app.add_typer(entry_add_app, name="add")
    app.add_typer(entry_app, name="entry")

    @entry_app.command("list")
    def entry_list_command(
        ctx: typer.Context,
        workspace: Path | None = common.WORKSPACE_OPTION,
        json_output: bool = common.JSON_OPTION,
    ) -> None:
        """List workspace entries."""

        try:
            with common.workspace_command_logging(
                ctx, workspace, command_name="entry-list"
            ) as loaded:
                entries = common.entry_service(ctx).list_entries(loaded)
        except Exception as exc:
            output.exit_with_error(exc, json_output=json_output)
        if json_output:
            payload = [entry.model_dump(mode="json", exclude_none=True) for entry in entries]
            typer.echo(output.json_payload(payload))
            return
        if not entries:
            typer.echo("entries=0")
            return
        for entry in entries:
            typer.echo(output.format_entry(entry))

    @entry_app.command("update")
    def entry_update_command(
        ctx: typer.Context,
        name: str,
        workspace: Path | None = common.WORKSPACE_OPTION,
        fqdn: Annotated[str | None, typer.Option("--fqdn")] = None,
        family: EntryAddressFamily | None = None,
        selection_policy: Annotated[str | None, typer.Option("--selection-policy")] = None,
        enabled: Annotated[bool | None, typer.Option("--enabled")] = None,
        ttl: Annotated[str | None, typer.Option("--ttl")] = None,
        proxied: Annotated[
            bool | None,
            typer.Option(
                "--proxied/--no-proxied",
                help="Explicitly manage Cloudflare proxying for this entry.",
            ),
        ] = None,
        inherit_proxied: Annotated[
            bool,
            typer.Option(
                "--inherit-proxied",
                help="Clear the entry-level proxied override and inherit the workspace default.",
            ),
        ] = False,
        source_id: Annotated[int | None, typer.Option("--id")] = None,
        description: Annotated[str | None, typer.Option("--description")] = None,
        static_ipv4: Annotated[str | None, typer.Option("--ipv4")] = None,
        static_ipv6: Annotated[str | None, typer.Option("--ipv6")] = None,
    ) -> None:
        """Update a workspace entry."""

        parsed_ttl = common.parse_ttl_option(ttl)
        if proxied is not None and inherit_proxied:
            raise typer.BadParameter(
                "cannot pass both --proxied/--no-proxied and --inherit-proxied"
            )
        try:
            with common.workspace_command_logging(
                ctx, workspace, command_name="entry-update"
            ) as loaded:
                result = common.entry_service(ctx).update_entry(
                    loaded,
                    name=name,
                    fqdn=fqdn,
                    family=family.value if family is not None else None,
                    selection_policy=selection_policy,
                    enabled=enabled,
                    ttl=parsed_ttl,
                    proxied=proxied,
                    inherit_proxied=inherit_proxied,
                    source_id=source_id,
                    description=description,
                    static_ipv4=static_ipv4,
                    static_ipv6=static_ipv6,
                )
        except Exception as exc:
            output.exit_with_error(exc)
        output.format_entry_mutation(result)

    @entry_app.command("remove")
    def entry_remove_command(
        ctx: typer.Context,
        name: str,
        workspace: Path | None = common.WORKSPACE_OPTION,
    ) -> None:
        """Remove a workspace entry."""

        try:
            with common.workspace_command_logging(
                ctx, workspace, command_name="entry-remove"
            ) as loaded:
                result = common.entry_service(ctx).remove_entry(loaded, name=name)
        except Exception as exc:
            output.exit_with_error(exc)
        output.format_entry_mutation(result)

    @entry_app.command("enable")
    def entry_enable_command(
        ctx: typer.Context,
        name: str,
        workspace: Path | None = common.WORKSPACE_OPTION,
    ) -> None:
        """Enable a workspace entry."""

        try:
            with common.workspace_command_logging(
                ctx, workspace, command_name="entry-enable"
            ) as loaded:
                result = common.entry_service(ctx).set_enabled(loaded, name=name, enabled=True)
        except Exception as exc:
            output.exit_with_error(exc)
        output.format_entry_mutation(result)

    @entry_app.command("disable")
    def entry_disable_command(
        ctx: typer.Context,
        name: str,
        workspace: Path | None = common.WORKSPACE_OPTION,
    ) -> None:
        """Disable a workspace entry."""

        try:
            with common.workspace_command_logging(
                ctx, workspace, command_name="entry-disable"
            ) as loaded:
                result = common.entry_service(ctx).set_enabled(
                    loaded,
                    name=name,
                    enabled=False,
                )
        except Exception as exc:
            output.exit_with_error(exc)
        output.format_entry_mutation(result)

    @entry_add_app.command("lxc")
    def entry_add_lxc(
        ctx: typer.Context,
        source_id: Annotated[int, typer.Option("--id")],
        fqdn: Annotated[str, typer.Option("--fqdn")],
        name: Annotated[str, typer.Option("--name")],
        family: EntryAddressFamily = common.FAMILY_OPTION,
        workspace: Path | None = common.WORKSPACE_OPTION,
        selection_policy: Annotated[str, typer.Option("--selection-policy")] = "default",
        ttl: Annotated[str | None, typer.Option("--ttl")] = None,
        proxied: Annotated[
            bool | None,
            typer.Option(
                "--proxied/--no-proxied",
                help="Explicitly manage Cloudflare proxying for this entry.",
            ),
        ] = None,
        description: Annotated[str | None, typer.Option("--description")] = None,
    ) -> None:
        """Add a dynamic LXC entry."""

        parsed_ttl = common.parse_ttl_option(ttl)
        try:
            with common.workspace_command_logging(
                ctx, workspace, command_name="entry-add-lxc"
            ) as loaded:
                result = common.entry_service(ctx).add_entry(
                    loaded,
                    name=name,
                    source_kind="lxc",
                    source_id=source_id,
                    fqdn=fqdn,
                    family=family.value,
                    selection_policy=selection_policy,
                    ttl=parsed_ttl,
                    proxied=proxied,
                    description=description,
                )
        except Exception as exc:
            output.exit_with_error(exc)
        output.format_entry_mutation(result)

    @entry_add_app.command("vm")
    def entry_add_vm(
        ctx: typer.Context,
        source_id: Annotated[int, typer.Option("--id")],
        fqdn: Annotated[str, typer.Option("--fqdn")],
        name: Annotated[str, typer.Option("--name")],
        family: EntryAddressFamily = common.FAMILY_OPTION,
        workspace: Path | None = common.WORKSPACE_OPTION,
        selection_policy: Annotated[str, typer.Option("--selection-policy")] = "default",
        ttl: Annotated[str | None, typer.Option("--ttl")] = None,
        proxied: Annotated[
            bool | None,
            typer.Option(
                "--proxied/--no-proxied",
                help="Explicitly manage Cloudflare proxying for this entry.",
            ),
        ] = None,
        description: Annotated[str | None, typer.Option("--description")] = None,
    ) -> None:
        """Add a dynamic VM entry."""

        parsed_ttl = common.parse_ttl_option(ttl)
        try:
            with common.workspace_command_logging(
                ctx, workspace, command_name="entry-add-vm"
            ) as loaded:
                result = common.entry_service(ctx).add_entry(
                    loaded,
                    name=name,
                    source_kind="vm",
                    source_id=source_id,
                    fqdn=fqdn,
                    family=family.value,
                    selection_policy=selection_policy,
                    ttl=parsed_ttl,
                    proxied=proxied,
                    description=description,
                )
        except Exception as exc:
            output.exit_with_error(exc)
        output.format_entry_mutation(result)

    @entry_add_app.command("local")
    def entry_add_local(
        ctx: typer.Context,
        fqdn: Annotated[str, typer.Option("--fqdn")],
        name: Annotated[str, typer.Option("--name")],
        family: EntryAddressFamily = common.FAMILY_OPTION,
        workspace: Path | None = common.WORKSPACE_OPTION,
        selection_policy: Annotated[str, typer.Option("--selection-policy")] = "default",
        ttl: Annotated[str | None, typer.Option("--ttl")] = None,
        proxied: Annotated[
            bool | None,
            typer.Option(
                "--proxied/--no-proxied",
                help="Explicitly manage Cloudflare proxying for this entry.",
            ),
        ] = None,
        description: Annotated[str | None, typer.Option("--description")] = None,
    ) -> None:
        """Add a dynamic local-host entry."""

        parsed_ttl = common.parse_ttl_option(ttl)
        try:
            with common.workspace_command_logging(
                ctx, workspace, command_name="entry-add-local"
            ) as loaded:
                result = common.entry_service(ctx).add_entry(
                    loaded,
                    name=name,
                    source_kind="local",
                    fqdn=fqdn,
                    family=family.value,
                    selection_policy=selection_policy,
                    ttl=parsed_ttl,
                    proxied=proxied,
                    description=description,
                )
        except Exception as exc:
            output.exit_with_error(exc)
        output.format_entry_mutation(result)

    @entry_add_app.command("static")
    def entry_add_static(
        ctx: typer.Context,
        fqdn: Annotated[str, typer.Option("--fqdn")],
        name: Annotated[str, typer.Option("--name")],
        family: EntryAddressFamily = common.FAMILY_OPTION,
        workspace: Path | None = common.WORKSPACE_OPTION,
        static_ipv4: Annotated[str | None, typer.Option("--ipv4")] = None,
        static_ipv6: Annotated[str | None, typer.Option("--ipv6")] = None,
        ttl: Annotated[str | None, typer.Option("--ttl")] = None,
        proxied: Annotated[
            bool | None,
            typer.Option(
                "--proxied/--no-proxied",
                help="Explicitly manage Cloudflare proxying for this entry.",
            ),
        ] = None,
        description: Annotated[str | None, typer.Option("--description")] = None,
    ) -> None:
        """Add a static IP entry."""

        parsed_ttl = common.parse_ttl_option(ttl)
        try:
            with common.workspace_command_logging(
                ctx, workspace, command_name="entry-add-static"
            ) as loaded:
                result = common.entry_service(ctx).add_entry(
                    loaded,
                    name=name,
                    source_kind="static",
                    fqdn=fqdn,
                    family=family.value,
                    ttl=parsed_ttl,
                    proxied=proxied,
                    description=description,
                    static_ipv4=static_ipv4,
                    static_ipv6=static_ipv6,
                )
        except Exception as exc:
            output.exit_with_error(exc)
        output.format_entry_mutation(result)
