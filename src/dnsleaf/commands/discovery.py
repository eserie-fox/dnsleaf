"""Low-level discovery debug commands."""

from __future__ import annotations

from pathlib import Path

import typer

from dnsleaf.commands import common, output
from dnsleaf.config.strategy import StrategyDefaults, StrategyOverrides, resolve_strategy
from dnsleaf.models import EntryAddressFamily, TargetKind, TargetRef
from dnsleaf.workspace.locator import WorkspaceNotFoundError, locate_workspace
from dnsleaf.workspace.storage import LoadedWorkspace, WorkspaceStorage


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
        workspace: Path | None = common.WORKSPACE_OPTION,
        json_output: bool = common.JSON_OPTION,
    ) -> None:
        """Discover IP candidates for an LXC guest."""

        try:
            exit_code = _run_discover(
                ctx,
                TargetKind.LXC,
                target_id,
                family,
                workspace=workspace,
                json_output=json_output,
            )
        except Exception as exc:
            output.exit_with_error(exc, json_output=json_output)
        raise typer.Exit(code=exit_code)

    @discover_app.command("vm")
    def discover_vm_command(
        ctx: typer.Context,
        target_id: int,
        family: EntryAddressFamily = common.FAMILY_BOTH_OPTION,
        selection_policy: str | None = typer.Option(
            None,
            "--selection-policy",
            help="default or require-dhcpv6; omission inherits source defaults.",
        ),
        evidence: str | None = typer.Option(
            None, "--evidence", help="none or windows-powershell; omission inherits."
        ),
        workspace: Path | None = common.WORKSPACE_OPTION,
        json_output: bool = common.JSON_OPTION,
    ) -> None:
        """Discover IP candidates for a VM guest."""

        try:
            exit_code = _run_discover(
                ctx,
                TargetKind.VM,
                target_id,
                family,
                workspace=workspace,
                json_output=json_output,
                selection_policy=selection_policy,
                evidence=evidence,
            )
        except Exception as exc:
            output.exit_with_error(exc, json_output=json_output)
        raise typer.Exit(code=exit_code)

    @discover_app.command("local")
    def discover_local_command(
        ctx: typer.Context,
        family: EntryAddressFamily = common.FAMILY_BOTH_OPTION,
        workspace: Path | None = common.WORKSPACE_OPTION,
        json_output: bool = common.JSON_OPTION,
    ) -> None:
        """Discover IP candidates for the local host."""

        try:
            exit_code = _run_discover(
                ctx,
                TargetKind.LOCAL,
                None,
                family,
                workspace=workspace,
                json_output=json_output,
            )
        except Exception as exc:
            output.exit_with_error(exc, json_output=json_output)
        raise typer.Exit(code=exit_code)


def _run_discover(
    ctx: typer.Context,
    kind: TargetKind,
    target_id: int | None,
    family: EntryAddressFamily,
    *,
    workspace: Path | None,
    json_output: bool,
    selection_policy: str | None = None,
    evidence: str | None = None,
) -> int:
    target = TargetRef(kind=kind, id=target_id)
    loaded_workspace = _resolve_workspace_for_discovery(workspace)
    overrides = StrategyOverrides.model_validate(
        {"selection_policy": selection_policy, "evidence": evidence}
    )
    strategy = resolve_strategy(
        source_kind=kind.value,
        source_id=target_id,
        families=family.concrete_families(),
        selection_policy=overrides.selection_policy,
        evidence=overrides.evidence,
        source_defaults=loaded_workspace.workspace_config.source_defaults
        if loaded_workspace
        else (),
        override_origin="cli",
        builtins=StrategyDefaults.from_defaults(),
    )
    enrollment = {
        "local_entries_checked": loaded_workspace is not None,
        "matching_enabled_entries": [
            entry.name
            for entry in loaded_workspace.enabled_entries()
            if entry.source_kind.value == kind.value and entry.source_id == target_id
        ]
        if loaded_workspace
        else [],
        "dns_publication_checked": False,
    }
    runner = common.debug_runner(ctx)

    if loaded_workspace is None:
        discovery, selections = runner.discover_target_families(
            target,
            families=family.concrete_families(),
            strategy=strategy,
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
                strategy=strategy,
                loaded_workspace=loaded_workspace,
            )

    if json_output:
        typer.echo(
            output.json_payload(
                {
                    "target": target.model_dump(mode="json", exclude_none=True),
                    "backend": discovery.backend,
                    "strategy": strategy.model_dump(mode="json"),
                    "enrollment": enrollment,
                    "error": discovery.error,
                    "error_stage": discovery.error_stage,
                    "parsing_issues": discovery.parsing_issues,
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
            return 1
        return 0

    typer.echo(f"target={target.descriptor} backend={discovery.backend}")
    typer.echo(
        f"policy={strategy.selection_policy} origin={strategy.selection_policy_origin} "
        f"evidence_permission={strategy.evidence} origin={strategy.evidence_origin}"
    )
    typer.echo(
        "discovery does not enroll an entry or check/publish DNS; "
        + (
            f"matching enabled local entries={enrollment['matching_enabled_entries']}"
            if loaded_workspace
            else "local enrollment unknown outside a workspace"
        )
    )
    if discovery.error is not None:
        typer.echo(f"status=error reason={discovery.error}")
        return 1

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
    return exit_code


def _resolve_workspace_for_discovery(workspace: Path | None) -> LoadedWorkspace | None:
    try:
        root = locate_workspace(workspace)
    except WorkspaceNotFoundError as exc:
        if exc.incomplete:
            raise
        return None
    return WorkspaceStorage().load(root)
