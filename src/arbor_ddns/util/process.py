"""Centralized subprocess helpers."""

from __future__ import annotations

import json
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


class ProcessRunner(Protocol):
    """Callable protocol used by discovery backends for testability."""

    def __call__(self, args: Sequence[str]) -> CommandResult:
        """Run a command and return captured output."""


def run_command(args: Sequence[str]) -> CommandResult:
    """Run a command and raise on non-zero exit status."""

    completed = subprocess.run(
        list(args),
        capture_output=True,
        check=False,
        text=True,
    )
    result = CommandResult(
        args=tuple(str(part) for part in args),
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )
    if result.returncode != 0:
        raise CommandExecutionError(result)
    return result


def run_json_command(args: Sequence[str]) -> Any:
    """Run a command and parse its stdout as JSON."""

    result = run_command(args)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(f"command did not return valid JSON: {' '.join(result.args)}") from exc
