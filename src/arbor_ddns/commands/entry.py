"""Workspace entry CLI commands."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from arbor_ddns.commands import common
from arbor_ddns.models import EntryAddressFamily


def register(app: typer.Typer) -> None:
    """Register `entry` commands."""

    entry_app = typer.Typer(help="Manage workspace entries.")
    entry_add_app = typer.Typer(help="Add a new workspace entry.")
    entry_app.add_typer(entry_add_app, name="add")
    app.add_typer(entry_app, name="entry")

    @entry_app.command("list")
    def entry_list_command(
        workspace: Path = common.WORKSPACE_OPTION,
        json_output: bool = common.JSON_OPTION,
        config: Path | None = common.CONFIG_OPTION,
    ) -> None:
        """List workspace entries."""

        try:
            entries = common.entry_service(config).list_entries(workspace)
        except Exception as exc:
            common.exit_with_error(exc, json_output=json_output)
        if json_output:
            payload = [entry.model_dump(mode="json", exclude_none=True) for entry in entries]
            typer.echo(common.json_payload(payload))
            return
        if not entries:
            typer.echo("entries=0")
            return
        for entry in entries:
            typer.echo(common.format_entry(entry))

    @entry_app.command("update")
    def entry_update_command(
        name: str,
        workspace: Path = common.WORKSPACE_OPTION,
        fqdn: Annotated[str | None, typer.Option("--fqdn")] = None,
        family: EntryAddressFamily | None = None,
        selection_policy: Annotated[str | None, typer.Option("--selection-policy")] = None,
        enabled: Annotated[bool | None, typer.Option("--enabled")] = None,
        ttl: Annotated[int | None, typer.Option("--ttl")] = None,
        proxied: Annotated[bool | None, typer.Option("--proxied")] = None,
        source_id: Annotated[int | None, typer.Option("--id")] = None,
        description: Annotated[str | None, typer.Option("--description")] = None,
        static_ipv4: Annotated[str | None, typer.Option("--ipv4")] = None,
        static_ipv6: Annotated[str | None, typer.Option("--ipv6")] = None,
        config: Path | None = common.CONFIG_OPTION,
    ) -> None:
        """Update a workspace entry."""

        try:
            result = common.entry_service(config).update_entry(
                workspace,
                name=name,
                fqdn=fqdn,
                family=family.value if family is not None else None,
                selection_policy=selection_policy,
                enabled=enabled,
                ttl=ttl,
                proxied=proxied,
                source_id=source_id,
                description=description,
                static_ipv4=static_ipv4,
                static_ipv6=static_ipv6,
            )
        except Exception as exc:
            common.exit_with_error(exc)
        common.format_entry_mutation(result)

    @entry_app.command("remove")
    def entry_remove_command(
        name: str,
        workspace: Path = common.WORKSPACE_OPTION,
        config: Path | None = common.CONFIG_OPTION,
    ) -> None:
        """Remove a workspace entry."""

        try:
            result = common.entry_service(config).remove_entry(workspace, name=name)
        except Exception as exc:
            common.exit_with_error(exc)
        common.format_entry_mutation(result)

    @entry_app.command("enable")
    def entry_enable_command(
        name: str,
        workspace: Path = common.WORKSPACE_OPTION,
        config: Path | None = common.CONFIG_OPTION,
    ) -> None:
        """Enable a workspace entry."""

        try:
            result = common.entry_service(config).set_enabled(workspace, name=name, enabled=True)
        except Exception as exc:
            common.exit_with_error(exc)
        common.format_entry_mutation(result)

    @entry_app.command("disable")
    def entry_disable_command(
        name: str,
        workspace: Path = common.WORKSPACE_OPTION,
        config: Path | None = common.CONFIG_OPTION,
    ) -> None:
        """Disable a workspace entry."""

        try:
            result = common.entry_service(config).set_enabled(workspace, name=name, enabled=False)
        except Exception as exc:
            common.exit_with_error(exc)
        common.format_entry_mutation(result)

    @entry_add_app.command("lxc")
    def entry_add_lxc(
        source_id: Annotated[int, typer.Option("--id")],
        fqdn: Annotated[str, typer.Option("--fqdn")],
        name: Annotated[str, typer.Option("--name")],
        family: EntryAddressFamily = common.FAMILY_OPTION,
        workspace: Path = common.WORKSPACE_OPTION,
        selection_policy: Annotated[str, typer.Option("--selection-policy")] = "default",
        ttl: Annotated[int | None, typer.Option("--ttl")] = None,
        proxied: Annotated[bool | None, typer.Option("--proxied")] = None,
        description: Annotated[str | None, typer.Option("--description")] = None,
        config: Path | None = common.CONFIG_OPTION,
    ) -> None:
        """Add a dynamic LXC entry."""

        try:
            result = common.entry_service(config).add_entry(
                workspace,
                name=name,
                source_kind="lxc",
                source_id=source_id,
                fqdn=fqdn,
                family=family.value,
                selection_policy=selection_policy,
                ttl=ttl,
                proxied=proxied,
                description=description,
            )
        except Exception as exc:
            common.exit_with_error(exc)
        common.format_entry_mutation(result)

    @entry_add_app.command("vm")
    def entry_add_vm(
        source_id: Annotated[int, typer.Option("--id")],
        fqdn: Annotated[str, typer.Option("--fqdn")],
        name: Annotated[str, typer.Option("--name")],
        family: EntryAddressFamily = common.FAMILY_OPTION,
        workspace: Path = common.WORKSPACE_OPTION,
        selection_policy: Annotated[str, typer.Option("--selection-policy")] = "default",
        ttl: Annotated[int | None, typer.Option("--ttl")] = None,
        proxied: Annotated[bool | None, typer.Option("--proxied")] = None,
        description: Annotated[str | None, typer.Option("--description")] = None,
        config: Path | None = common.CONFIG_OPTION,
    ) -> None:
        """Add a dynamic VM entry."""

        try:
            result = common.entry_service(config).add_entry(
                workspace,
                name=name,
                source_kind="vm",
                source_id=source_id,
                fqdn=fqdn,
                family=family.value,
                selection_policy=selection_policy,
                ttl=ttl,
                proxied=proxied,
                description=description,
            )
        except Exception as exc:
            common.exit_with_error(exc)
        common.format_entry_mutation(result)

    @entry_add_app.command("static")
    def entry_add_static(
        fqdn: Annotated[str, typer.Option("--fqdn")],
        name: Annotated[str, typer.Option("--name")],
        family: EntryAddressFamily = common.FAMILY_OPTION,
        workspace: Path = common.WORKSPACE_OPTION,
        static_ipv4: Annotated[str | None, typer.Option("--ipv4")] = None,
        static_ipv6: Annotated[str | None, typer.Option("--ipv6")] = None,
        ttl: Annotated[int | None, typer.Option("--ttl")] = None,
        proxied: Annotated[bool | None, typer.Option("--proxied")] = None,
        description: Annotated[str | None, typer.Option("--description")] = None,
        config: Path | None = common.CONFIG_OPTION,
    ) -> None:
        """Add a static IP entry."""

        try:
            result = common.entry_service(config).add_entry(
                workspace,
                name=name,
                source_kind="static",
                fqdn=fqdn,
                family=family.value,
                ttl=ttl,
                proxied=proxied,
                description=description,
                static_ipv4=static_ipv4,
                static_ipv6=static_ipv6,
            )
        except Exception as exc:
            common.exit_with_error(exc)
        common.format_entry_mutation(result)
