"""Low-level discovery debug commands."""

from __future__ import annotations

from pathlib import Path

import typer

from arbor_ddns.commands import _privilege_analysis as privilege_analysis
from arbor_ddns.commands import common
from arbor_ddns.models import EntryAddressFamily, TargetKind, TargetRef
from arbor_ddns.workspace.storage import LoadedWorkspace, WorkspaceStorage

DISCOVER_WORKSPACE_OPTION = typer.Option(
    None,
    "--workspace",
    "-w",
    help=(
        "Optional workspace directory. Defaults to the current directory "
        "when it is a valid workspace."
    ),
)


def register(app: typer.Typer) -> None:
    """Register `discover` commands."""

    discover_app = typer.Typer(
        help="Run low-level discovery/debug commands.",
        no_args_is_help=True,
    )
    app.add_typer(discover_app, name="discover")

    @discover_app.command("lxc")
    def discover_lxc_command(
        ctx: typer.Context,
        target_id: int,
        family: EntryAddressFamily = common.FAMILY_BOTH_OPTION,
        workspace: Path | None = DISCOVER_WORKSPACE_OPTION,
        json_output: bool = common.JSON_OPTION,
        sudo: bool = common.SUDO_OPTION,
    ) -> None:
        """Discover IP candidates for an LXC guest."""

        try:
            if common.enforce_root_privileges(
                ctx,
                reasons=privilege_analysis.analyze_discover_root_requirements(
                    TargetKind.LXC,
                    workspace=workspace,
                ),
                sudo_requested=sudo,
            ):
                return
            _run_discover(
                ctx,
                TargetKind.LXC,
                target_id,
                family,
                workspace=workspace,
                json_output=json_output,
            )
        except Exception as exc:
            common.exit_with_error(exc, json_output=json_output)

    @discover_app.command("vm")
    def discover_vm_command(
        ctx: typer.Context,
        target_id: int,
        family: EntryAddressFamily = common.FAMILY_BOTH_OPTION,
        workspace: Path | None = DISCOVER_WORKSPACE_OPTION,
        json_output: bool = common.JSON_OPTION,
        sudo: bool = common.SUDO_OPTION,
    ) -> None:
        """Discover IP candidates for a VM guest."""

        try:
            if common.enforce_root_privileges(
                ctx,
                reasons=privilege_analysis.analyze_discover_root_requirements(
                    TargetKind.VM,
                    workspace=workspace,
                ),
                sudo_requested=sudo,
            ):
                return
            _run_discover(
                ctx,
                TargetKind.VM,
                target_id,
                family,
                workspace=workspace,
                json_output=json_output,
            )
        except Exception as exc:
            common.exit_with_error(exc, json_output=json_output)

    @discover_app.command("local")
    def discover_local_command(
        ctx: typer.Context,
        family: EntryAddressFamily = common.FAMILY_BOTH_OPTION,
        workspace: Path | None = DISCOVER_WORKSPACE_OPTION,
        json_output: bool = common.JSON_OPTION,
        sudo: bool = common.SUDO_OPTION,
    ) -> None:
        """Discover IP candidates for the local host."""

        try:
            if common.enforce_root_privileges(
                ctx,
                reasons=privilege_analysis.analyze_discover_root_requirements(
                    TargetKind.LOCAL,
                    workspace=workspace,
                ),
                sudo_requested=sudo,
            ):
                return
            _run_discover(
                ctx,
                TargetKind.LOCAL,
                None,
                family,
                workspace=workspace,
                json_output=json_output,
            )
        except Exception as exc:
            common.exit_with_error(exc, json_output=json_output)


def _run_discover(
    ctx: typer.Context,
    kind: TargetKind,
    target_id: int | None,
    family: EntryAddressFamily,
    *,
    workspace: Path | None,
    json_output: bool,
) -> None:
    target = TargetRef(kind=kind, id=target_id)
    loaded_workspace = _resolve_workspace_for_discovery(workspace)
    runner = common.debug_runner(ctx)

    if loaded_workspace is None:
        discovery, selections = runner.discover_target_families(
            target,
            families=family.concrete_families(),
            policy="default",
        )
    else:
        with common.workspace_command_logging(
            ctx,
            loaded_workspace.paths.root,
            command_name=f"discover-{kind.value}",
            loaded_workspace=loaded_workspace,
        ):
            discovery, selections = runner.discover_target_families(
                target,
                families=family.concrete_families(),
                policy="default",
                loaded_workspace=loaded_workspace,
            )

    if json_output:
        typer.echo(
            common.json_payload(
                {
                    "target": target.model_dump(mode="json", exclude_none=True),
                    "backend": discovery.backend,
                    "error": discovery.error,
                    "candidates": [
                        candidate.model_dump(mode="json", exclude_none=True)
                        for candidate in discovery.candidates
                    ],
                    "selections": {
                        family_name.value: selection.model_dump(mode="json", exclude_none=True)
                        for family_name, selection in selections.items()
                    },
                }
            )
        )
        if discovery.error is not None or any(
            selection.status != "selected" for selection in selections.values()
        ):
            raise typer.Exit(code=1)
        return

    typer.echo(f"target={target.descriptor} backend={discovery.backend}")
    if discovery.error is not None:
        typer.echo(f"status=error reason={discovery.error}")
        raise typer.Exit(code=1)

    for candidate in discovery.candidates:
        typer.echo(
            f"candidate family={candidate.family.value} interface={candidate.interface} "
            f"cidr={candidate.cidr}"
        )

    exit_code = 0
    for concrete_family in family.concrete_families():
        selection = selections[concrete_family]
        typer.echo(
            f"family={concrete_family.value} status={selection.status} reason={selection.reason}"
        )
        if selection.selected is not None:
            typer.echo(
                f"selected family={concrete_family.value} "
                f"cidr={selection.selected.address}/{selection.selected.prefix_length} "
                f"interface={selection.selected.interface}"
            )
        for rejected in selection.filtered_out:
            typer.echo(
                f"filtered family={concrete_family.value} interface={rejected.candidate.interface} "
                f"cidr={rejected.candidate.cidr} reason={rejected.reason}"
            )
        for skipped in selection.not_selected:
            typer.echo(
                f"not_selected family={concrete_family.value} "
                f"interface={skipped.candidate.interface} "
                f"cidr={skipped.candidate.cidr} reason={skipped.reason}"
            )
        if selection.status != "selected":
            exit_code = 1
    if exit_code:
        raise typer.Exit(code=exit_code)


def _resolve_workspace_for_discovery(workspace: Path | None) -> LoadedWorkspace | None:
    storage = WorkspaceStorage()
    if workspace is not None:
        return storage.load(workspace)

    try:
        return storage.load(Path("."))
    except Exception:
        return None
