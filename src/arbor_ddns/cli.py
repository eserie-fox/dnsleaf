"""Typer CLI entrypoint."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from arbor_ddns.config import AppConfig
from arbor_ddns.models import TargetKind, TargetRef
from arbor_ddns.sync.runner import EntrySyncOutcome, RunReport, SyncRunner, build_runner

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Discover IPv6 addresses from PVE guests and synchronize DNS AAAA records.",
)
discover_app = typer.Typer(help="Discover IPv6 candidate addresses for a target.")
app.add_typer(discover_app, name="discover")

ConfigPathOption = Annotated[
    Path | None,
    typer.Option("--config", "-c", help="Optional JSON config path."),
]
ApplyModeOption = Annotated[
    bool,
    typer.Option(
        "--apply/--dry-run",
        help="Apply changes instead of printing a dry-run report.",
    ),
]


def _load_config(config_path: Path | None) -> AppConfig:
    return AppConfig.from_file(config_path)


def _build_runner(config: AppConfig) -> SyncRunner:
    return build_runner(config)


@discover_app.command("lxc")
def discover_lxc(
    target_id: int,
    config: ConfigPathOption = None,
) -> None:
    """Discover IPv6 candidates for an LXC guest."""

    _run_discover(TargetRef(kind=TargetKind.LXC, id=target_id), config_path=config)


@discover_app.command("vm")
def discover_vm(
    target_id: int,
    config: ConfigPathOption = None,
) -> None:
    """Discover IPv6 candidates for a VM guest via QGA."""

    _run_discover(TargetRef(kind=TargetKind.VM, id=target_id), config_path=config)


@app.command("plan")
def plan_command(
    config: ConfigPathOption = None,
) -> None:
    """Plan synchronization for all enabled inventory entries."""

    runner = _build_runner(_load_config(config))
    report = runner.plan_inventory()
    _echo_report(report, heading="Plan")
    if report.has_errors():
        raise typer.Exit(code=1)


@app.command("sync-once")
def sync_once_command(
    config: ConfigPathOption = None,
    apply: ApplyModeOption = False,
) -> None:
    """Plan and optionally apply synchronization once."""

    runner = _build_runner(_load_config(config))
    report = runner.sync_once(apply=apply)
    heading = "Apply" if apply else "Dry Run"
    _echo_report(report, heading=heading)
    if report.has_errors():
        raise typer.Exit(code=1)


def _run_discover(target: TargetRef, *, config_path: Path | None) -> None:
    runner = _build_runner(_load_config(config_path))
    discovery, selection = runner.discover_target(target, policy="default")

    typer.echo(f"target={target.kind.value}/{target.id} backend={discovery.backend}")
    if discovery.error is not None:
        typer.echo(f"status=error reason={discovery.error}")
        raise typer.Exit(code=1)

    typer.echo(f"status={selection.status} reason={selection.reason}")
    if selection.selected is not None:
        typer.echo(
            "selected="
            f"{selection.selected.address}/{selection.selected.prefix_length} "
            f"interface={selection.selected.interface}"
        )
    for candidate in selection.remaining_candidates:
        typer.echo(f"candidate={candidate.interface} {candidate.cidr}")
    for rejected in selection.filtered_out:
        typer.echo(
            f"filtered={rejected.candidate.interface} "
            f"{rejected.candidate.cidr} reason={rejected.reason}"
        )
    for skipped in selection.not_selected:
        typer.echo(
            f"not-selected={skipped.candidate.interface} "
            f"{skipped.candidate.cidr} reason={skipped.reason}"
        )


def _echo_report(report: RunReport, *, heading: str) -> None:
    typer.echo(heading)
    if not report.outcomes:
        typer.echo("status=no-enabled-entries")
        return
    for outcome in report.outcomes:
        typer.echo(_format_outcome(outcome))
        if outcome.selection.selected is not None:
            typer.echo(
                "selected="
                f"{outcome.selection.selected.address}/{outcome.selection.selected.prefix_length} "
                f"fqdn={outcome.entry.fqdn if outcome.entry is not None else 'unknown'}"
            )
        if outcome.plan is None:
            continue
        for change in outcome.plan.changes:
            target_value = change.desired.value if change.desired is not None else "-"
            current_value = change.current.value if change.current is not None else "-"
            typer.echo(
                f"change={change.action} fqdn={change.fqdn} "
                f"current={current_value} desired={target_value} "
                f"reason={change.reason}"
            )


def _format_outcome(outcome: EntrySyncOutcome) -> str:
    if outcome.entry is not None:
        fqdn = outcome.entry.fqdn
    else:
        fqdn = f"{outcome.discovery.target.kind.value}/{outcome.discovery.target.id}"
    return f"status={outcome.status} fqdn={fqdn} message={outcome.message}"


def main() -> None:
    """Console-script entrypoint."""

    app()
