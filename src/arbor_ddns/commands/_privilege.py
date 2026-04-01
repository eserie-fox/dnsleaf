"""CLI privilege checks and sudo re-exec helpers."""

from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path
from typing import Any

import click
import typer
from click.core import ParameterSource

from arbor_ddns.util.process import command_available


class PermissionOperationError(RuntimeError):
    """Raised when the current user lacks privileges for one CLI operation."""


class UnsupportedSudoReexecParameterError(RuntimeError):
    """Raised when one CLI parameter cannot be reconstructed safely for `--sudo`."""


def current_user_is_root() -> bool:
    """Return whether the current process is running as root."""

    geteuid = getattr(os, "geteuid", None)
    if geteuid is None:
        return False
    return geteuid() == 0


def command_args_from_ctx(ctx: typer.Context) -> list[str]:
    """Reconstruct equivalent CLI arguments for the active command context.

    Supported shapes are intentionally narrow:
    - single-value positional arguments
    - single-value options
    - simple boolean flags
    - paired boolean flags with `secondary_opts`

    Unsupported Click/Typer parameter shapes fail fast so `--sudo` re-exec
    cannot silently drift away from the original command semantics.
    """

    command_args = ctx.command_path.split()[1:]
    for param in ctx.command.params:
        if param.name is None or param.name not in ctx.params:
            continue
        value = ctx.params[param.name]
        source = ctx.get_parameter_source(param.name)
        if isinstance(param, click.Argument):
            command_args.extend(_argument_tokens(param, value))
            continue
        if not isinstance(param, click.Option):
            continue
        if source is ParameterSource.DEFAULT:
            continue
        command_args.extend(_option_tokens(param, value, source=source))
    return command_args


def ensure_root_privileges(
    *,
    operation: str,
    reasons: list[str],
    sudo_requested: bool,
    command_args: list[str],
) -> bool:
    """Fail fast or re-exec through sudo when root privileges are required."""

    base_command_args = [arg for arg in command_args if arg != "--sudo"]
    if current_user_is_root() or not reasons:
        return False

    if not sudo_requested:
        raise PermissionOperationError(
            _format_privilege_message(operation, reasons, base_command_args)
        )

    if not command_available("sudo"):
        raise PermissionOperationError(
            _format_privilege_message(
                operation,
                reasons,
                base_command_args,
                sudo_requested=True,
                sudo_available=False,
            )
        )

    _exec_with_sudo(_sudo_exec_args(base_command_args))
    return True


def format_unsupported_sudo_reexec_message(
    *,
    operation: str,
    detail: str,
    command_args: list[str],
) -> str:
    """Format a fail-fast error for unsupported `--sudo` argument reconstruction."""

    manual_command = _display_command([arg for arg in command_args if arg != "--sudo"])
    return "\n".join(
        [
            f"{operation} cannot be safely re-executed via --sudo:",
            f"- {detail}",
            f"Run this command as root instead: sudo {manual_command}",
        ]
    )


def _argument_tokens(param: click.Argument, value: Any) -> list[str]:
    _validate_supported_param_shape(param)
    if value is None:
        return []
    return [*_flatten_tokens((value,))]


def _option_tokens(
    param: click.Option,
    value: Any,
    *,
    source: ParameterSource,
) -> list[str]:
    _validate_supported_param_shape(param)
    option_name = param.opts[0]
    if param.is_flag:
        if not isinstance(value, bool):
            raise UnsupportedSudoReexecParameterError(
                f"option {option_name} uses an unsupported non-boolean flag shape"
            )
        if value:
            return [option_name]
        if param.secondary_opts:
            if source is not ParameterSource.COMMANDLINE:
                raise UnsupportedSudoReexecParameterError(
                    f"option {option_name} was set false via {source.name.lower()}, "
                    "which cannot be reconstructed safely for --sudo"
                )
            return [param.secondary_opts[0]]
        return []
    if value is None:
        return []
    return [option_name, *_flatten_tokens((value,))]


def _flatten_tokens(values: tuple[Any, ...]) -> list[str]:
    tokens: list[str] = []
    for value in values:
        if value is None:
            continue
        if isinstance(value, tuple):
            tokens.extend(_flatten_tokens(value))
            continue
        if hasattr(value, "value") and not isinstance(value, (str, bytes, Path)):
            tokens.append(str(value.value))
            continue
        tokens.append(str(value))
    return tokens


def _format_privilege_message(
    operation: str,
    reasons: list[str],
    command_args: list[str],
    *,
    sudo_requested: bool = False,
    sudo_available: bool = True,
) -> str:
    manual_command = _display_command(command_args)
    retry_command = _display_command([*command_args, "--sudo"])
    lines = [f"{operation} requires elevated privileges:"]
    lines.extend(f"- {reason}" for reason in reasons)
    if sudo_requested and not sudo_available:
        lines.append("`--sudo` was requested, but `sudo` is not available in PATH.")
        lines.append(f"Run this command as root instead: {manual_command}")
    else:
        lines.append(f"Retry with: {retry_command}")
        lines.append(f"Or run manually: sudo {manual_command}")
    return "\n".join(lines)


def _display_command(command_args: list[str]) -> str:
    return shlex.join(["arbor-ddns", *command_args])


def _sudo_exec_args(command_args: list[str]) -> list[str]:
    cli_path = Path(sys.executable).resolve().with_name("arbor-ddns")
    if cli_path.exists() and os.access(cli_path, os.X_OK):
        return ["sudo", str(cli_path), *command_args, "--sudo"]
    return ["sudo", sys.executable, "-m", "arbor_ddns", *command_args, "--sudo"]


def _exec_with_sudo(args: list[str]) -> None:
    os.execvp(args[0], args)


def _validate_supported_param_shape(param: click.Parameter) -> None:
    label = _param_label(param)
    if getattr(param, "multiple", False):
        raise UnsupportedSudoReexecParameterError(
            f"{label} uses multiple=True, which is not supported by --sudo re-exec"
        )
    if getattr(param, "count", False):
        raise UnsupportedSudoReexecParameterError(
            f"{label} uses count=True, which is not supported by --sudo re-exec"
        )
    if getattr(param, "nargs", 1) != 1:
        raise UnsupportedSudoReexecParameterError(
            f"{label} uses nargs={param.nargs}, which is not supported by --sudo re-exec"
        )


def _param_label(param: click.Parameter) -> str:
    if isinstance(param, click.Option) and param.opts:
        return f"option {param.opts[0]}"
    if isinstance(param, click.Argument):
        return f"argument {param.human_readable_name}"
    return "parameter"
