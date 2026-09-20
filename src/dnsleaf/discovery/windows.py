"""One fixed read-only Windows metadata probe via synchronous PVE guest exec."""

from __future__ import annotations

import base64
import json
import math
from typing import Any, NoReturn

from pydantic import ValidationError

from dnsleaf.config.resources import read_text
from dnsleaf.discovery.models import WindowsAddressEvidence, WindowsMetadataResult
from dnsleaf.models import TargetKind, TargetRef
from dnsleaf.util.process import (
    CommandExecutionError,
    CommandTimeoutError,
    ProcessRunner,
    run_command,
)

PROBE_RESOURCE = "pkg://dnsleaf/probes/windows_ipv6.ps1"


def _excerpt(value: str) -> str:
    return " ".join(value.split())[:400]


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object field")
        result[key] = value
    return result


def _invalid_json_constant(value: str) -> NoReturn:
    raise ValueError(f"invalid JSON constant: {value}")


def _json_document(value: str) -> Any:
    # A single leading BOM is permitted; no lossy decoding or encoding guesses.
    return json.loads(
        value.removeprefix("\ufeff"),
        object_pairs_hook=_unique_object,
        parse_constant=_invalid_json_constant,
    )


def _pve_boolean(value: object, field: str) -> bool:
    if type(value) is bool:
        return bool(value)
    if type(value) is int and value in (0, 1):
        return value == 1
    raise ValueError(f"qm guest exec {field} must be a boolean or integer 0/1")


def parse_windows_metadata(output: str) -> WindowsMetadataResult:
    """Validate qm's unwrapped, already-decoded execution result and probe JSON."""

    try:
        result = _json_document(output)
        if not isinstance(result, dict):
            raise ValueError("qm guest exec result must be an object")
        if "exited" not in result:
            raise ValueError(
                "qm guest exec has no completed status (possibly PID-only after its wait); "
                "no metadata accepted"
            )
        if not _pve_boolean(result["exited"], "exited"):
            raise ValueError("qm guest exec did not complete within its wait; no metadata accepted")
        if "signal" in result:
            return WindowsMetadataResult(
                status="error",
                error_stage="execution",
                error="Windows metadata probe ended with a signal",
            )
        for field in ("out-truncated", "err-truncated"):
            if field in result and _pve_boolean(result[field], field):
                raise ValueError(f"qm guest exec {field}: metadata output was truncated")
        if type(result.get("exitcode")) is not int:
            raise ValueError("qm guest exec is missing an integer Guest exitcode")
        if result["exitcode"] != 0:
            detail = result.get("err-data")
            excerpt = _excerpt(detail) if isinstance(detail, str) else ""
            return WindowsMetadataResult(
                status="error",
                error_stage="execution",
                error=f"Windows metadata probe Guest exitcode={result['exitcode']}: {excerpt}",
            )
        stdout = result.get("out-data")
        if not isinstance(stdout, str) or not stdout.strip():
            raise ValueError("qm guest exec is missing probe out-data")
        envelope = _json_document(stdout)
        if not isinstance(envelope, dict) or set(envelope) != {"addresses"}:
            raise ValueError("Windows metadata must be an object with an addresses array")
        records = envelope["addresses"]
        # Accommodate PowerShell's single-object serialization, but never scalar roots.
        if isinstance(records, dict):
            records = [records]
        if not isinstance(records, list):
            raise ValueError("Windows metadata addresses must be an array or one address object")
        addresses = [WindowsAddressEvidence.model_validate(record) for record in records]
        return WindowsMetadataResult(status="ok", addresses=addresses)
    except ValidationError as exc:
        fields = "; ".join(
            f"{'.'.join(map(str, error['loc']))}: {error['type']}"
            for error in exc.errors(include_input=False)[:8]
        )
        message = f"invalid Windows address evidence ({fields})"
    except json.JSONDecodeError as exc:
        message = f"invalid metadata JSON at line {exc.lineno}, column {exc.colno}"
    except ValueError as exc:
        message = str(exc)
    return WindowsMetadataResult(status="error", error_stage="protocol", error=message)


class WindowsMetadataProbe:
    """Acquire evidence without selecting an address or changing Guest configuration."""

    def __init__(self, *, runner: ProcessRunner = run_command) -> None:
        self._runner = runner

    def query(
        self, target: TargetRef, *, qm_bin: str, timeout_seconds: float
    ) -> WindowsMetadataResult:
        if target.kind is not TargetKind.VM or target.id is None:
            raise ValueError("Windows metadata requires a VM target")
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("Windows metadata timeout must be finite and positive")
        encoded = base64.b64encode(read_text(PROBE_RESOURCE).encode("utf-16le")).decode("ascii")
        args = [
            qm_bin,
            "guest",
            "exec",
            str(target.id),
            "--synchronous",
            "1",
            "--timeout",
            str(max(1, math.ceil(timeout_seconds))),
            "--",
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-EncodedCommand",
            encoded,
        ]
        try:
            result = self._runner(args, check=False, timeout=timeout_seconds)
            if result.returncode != 0:
                raise CommandExecutionError(result)
        except CommandTimeoutError:
            message = (
                f"Windows metadata qm guest exec timed out after {timeout_seconds:g} seconds; "
                "check guest-exec availability and discovery.timeout_seconds; "
                "the Guest process may still be running"
            )
        except CommandExecutionError as exc:
            # Never render the command exception: it contains the encoded script.
            detail = exc.result.stderr.replace(encoded, "[probe]")
            message = (
                f"qm guest exec failed (host exit {exc.result.returncode}): {_excerpt(detail)}"
            )
        except UnicodeError:
            message = "qm guest exec output could not be decoded; no metadata accepted"
        except (OSError, RuntimeError) as exc:
            message = f"qm guest exec unavailable: {_excerpt(str(exc).replace(encoded, '[probe]'))}"
        else:
            return parse_windows_metadata(result.stdout)
        return WindowsMetadataResult(status="error", error_stage="execution", error=message)
