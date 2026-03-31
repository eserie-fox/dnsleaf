"""Centralized subprocess helpers."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class CommandResult:
    """Captured command output."""

    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


class CommandExecutionError(RuntimeError):
    """Raised when an external command fails."""

    def __init__(self, result: CommandResult):
        message = (
            f"command failed with exit code {result.returncode}: {' '.join(result.args)}"
        )
        if result.stderr.strip():
            message = f"{message}: {result.stderr.strip()}"
        super().__init__(message)
        self.result = result


class CommandNotFoundError(RuntimeError):
    """Raised when an executable cannot be found."""

    def __init__(self, command: str):
        super().__init__(f"command not found: {command}")
        self.command = command


class ProcessRunner(Protocol):
    """Callable protocol used by discovery backends for testability."""

    def __call__(self, args: Sequence[str], *, check: bool = True) -> CommandResult:
        """Run a command and return captured output."""


def run_command(args: Sequence[str], *, check: bool = True) -> CommandResult:
    """Run a command and optionally raise on non-zero exit status."""

    try:
        completed = subprocess.run(
            list(args),
            capture_output=True,
            check=False,
            text=True,
        )
    except FileNotFoundError as exc:
        raise CommandNotFoundError(str(args[0])) from exc
    result = CommandResult(
        args=tuple(str(part) for part in args),
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )
    if check and result.returncode != 0:
        raise CommandExecutionError(result)
    return result


def run_json_command(args: Sequence[str]) -> Any:
    """Run a command and parse its stdout as JSON."""

    result = run_command(args)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(f"command did not return valid JSON: {' '.join(result.args)}") from exc


def command_available(command: str) -> bool:
    """Return whether a command is available for execution."""

    if os.sep in command:
        return os.access(command, os.X_OK)
    return shutil.which(command) is not None
