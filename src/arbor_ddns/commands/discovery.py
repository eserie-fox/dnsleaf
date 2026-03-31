"""Low-level discovery debug commands."""

from __future__ import annotations

from pathlib import Path

import typer

from arbor_ddns.commands import common
from arbor_ddns.models import EntryAddressFamily, TargetKind, TargetRef


def register(app: typer.Typer) -> None:
    """Register `discover` commands."""

    discover_app = typer.Typer(help="Run low-level discovery/debug commands.")
    app.add_typer(discover_app, name="discover")

    @discover_app.command("lxc")
    def discover_lxc_command(
        target_id: int,
        family: EntryAddressFamily = common.FAMILY_BOTH_OPTION,
        json_output: bool = common.JSON_OPTION,
        config: Path | None = common.CONFIG_OPTION,
    ) -> None:
        """Discover IP candidates for an LXC guest."""

        _run_discover(
            TargetKind.LXC,
            target_id,
            family,
            json_output=json_output,
            config_path=config,
        )

    @discover_app.command("vm")
    def discover_vm_command(
        target_id: int,
        family: EntryAddressFamily = common.FAMILY_BOTH_OPTION,
        json_output: bool = common.JSON_OPTION,
        config: Path | None = common.CONFIG_OPTION,
    ) -> None:
        """Discover IP candidates for a VM guest."""

        _run_discover(TargetKind.VM, target_id, family, json_output=json_output, config_path=config)


def _run_discover(
    kind: TargetKind,
    target_id: int,
    family: EntryAddressFamily,
    *,
    json_output: bool,
    config_path: Path | None,
) -> None:
    target = TargetRef(kind=kind, id=target_id)
    runner = common.debug_runner(config_path)
    discovery, selections = runner.discover_target_families(
        target,
        families=family.concrete_families(),
        policy="default",
    )

    if json_output:
        typer.echo(
            common.json_payload(
                {
                    "target": target.model_dump(mode="json"),
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

    typer.echo(f"target={kind.value}/{target_id} backend={discovery.backend}")
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
