"""Shared CLI helpers."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import typer

from dnsleaf.config.outside_workspace import OutsideWorkspaceConfig
from dnsleaf.dns.models import TTLSetting, normalize_ttl_setting
from dnsleaf.logging.runtime import workspace_logging_context
from dnsleaf.models import EntryAddressFamily
from dnsleaf.sync.runner import SyncRunner, build_runner
from dnsleaf.util.privilege import require_root as require_root
from dnsleaf.workspace.entries import EntryService
from dnsleaf.workspace.locator import locate_workspace
from dnsleaf.workspace.service import WorkspaceService
from dnsleaf.workspace.storage import LoadedWorkspace, WorkspaceStorage

WORKSPACE_OPTION = typer.Option(
    None,
    "--workspace",
    "-w",
    help="Workspace directory; overrides DNSLEAF_WORKSPACE and automatic search.",
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
OUTSIDE_WORKSPACE_CONFIG_CONTEXT_KEY = "outside_workspace_config"


def outside_workspace_config_from_ctx(ctx: typer.Context) -> OutsideWorkspaceConfig:
    """Return the outside-workspace config from the current Typer context."""

    ctx.ensure_object(dict)
    config = ctx.obj.get(OUTSIDE_WORKSPACE_CONFIG_CONTEXT_KEY)
    if not isinstance(config, OutsideWorkspaceConfig):
        config = OutsideWorkspaceConfig.from_defaults()
        ctx.obj[OUTSIDE_WORKSPACE_CONFIG_CONTEXT_KEY] = config
    return config


def workspace_service(ctx: typer.Context) -> WorkspaceService:
    """Build the workspace facade."""

    _ = ctx
    return WorkspaceService()


def entry_service(ctx: typer.Context) -> EntryService:
    """Build the entry facade."""

    _ = ctx
    return EntryService()


def debug_runner(ctx: typer.Context) -> SyncRunner:
    """Build the low-level debug runner."""

    return build_runner(outside_workspace_config=outside_workspace_config_from_ctx(ctx))


@contextmanager
def workspace_command_logging(
    ctx: typer.Context,
    workspace: Path | None,
    *,
    command_name: str,
    loaded_workspace: LoadedWorkspace | None = None,
) -> Iterator[LoadedWorkspace]:
    """Select and load once, then share this snapshot with logging and the operation."""

    _ = ctx
    loaded = loaded_workspace
    if loaded is None:
        loaded = WorkspaceStorage().load(locate_workspace(workspace))
    with workspace_logging_context(
        loaded.paths.root, command_name=command_name, loaded_workspace=loaded
    ):
        yield loaded


def resolve_bool_override(yes: bool, no: bool, label: str) -> bool | None:
    """Resolve mutually exclusive boolean CLI flags."""

    if yes and no:
        raise typer.BadParameter(f"cannot pass both --{label} and --no-{label}")
    if yes:
        return True
    if no:
        return False
    return None


def parse_ttl_option(value: str | None) -> TTLSetting | None:
    """Parse a CLI TTL option as seconds or `auto`."""

    if value is None:
        return None
    try:
        return normalize_ttl_setting(value)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
