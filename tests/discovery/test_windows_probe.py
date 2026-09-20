"""Synthetic PVE guest-exec protocol tests; PowerShell is not executed here."""

from __future__ import annotations

import base64
import json
import subprocess
from collections.abc import Sequence

import pytest

from dnsleaf.config.resources import read_text
from dnsleaf.discovery.pve_qga import PVEQGADiscoveryBackend
from dnsleaf.discovery.windows import PROBE_RESOURCE, WindowsMetadataProbe, parse_windows_metadata
from dnsleaf.models import TargetKind, TargetRef
from dnsleaf.util.process import CommandResult, run_command
from tests.windows_fixtures import SyntheticWindowsCommands, metadata_wire, synthetic_metadata


@pytest.mark.parametrize(
    "records", [[], synthetic_metadata()[:1], synthetic_metadata(), synthetic_metadata()[0]]
)
@pytest.mark.parametrize("exited", [True, 1])
def test_zero_one_many_and_single_object_metadata(records, exited) -> None:
    wire = json.loads(metadata_wire(records))
    wire["exited"] = exited
    wire["out-truncated"] = False
    wire["err-truncated"] = 0
    result = parse_windows_metadata(json.dumps(wire))
    assert result.status == "ok"
    assert len(result.addresses) == (1 if isinstance(records, dict) else len(records))


@pytest.mark.parametrize(
    "patch",
    [
        {"exited": False},
        {"exited": 0},
        {"exited": "true"},
        {"exited": 1.0},
        {"exited": 2},
        {"exitcode": None},
        {"exitcode": "0"},
        {"exitcode": False},
        {"exitcode": 1},
        {"signal": 9},
        {"signal": 0},
        {"out-truncated": True},
        {"err-truncated": 1},
        {"out-truncated": "false"},
        {"out-data": None},
        {"out-data": ""},
        {"out-data": "{"},
        {"out-data": "[]"},
        {"out-data": "null"},
        {"out-data": '{"addresses": null}'},
        {"out-data": '{"addresses": 1}'},
        {"out-data": '{"addresses": [1]}'},
        {"out-data": '{"addresses": [], "extra": 1}'},
    ],
)
def test_incomplete_or_malformed_transport_is_rejected(patch) -> None:
    wire = json.loads(metadata_wire(synthetic_metadata()))
    wire.update(patch)
    result = parse_windows_metadata(json.dumps(wire))
    assert result.status == "error" and result.error and result.addresses == []


@pytest.mark.parametrize(
    "wire",
    [
        "{",
        "null",
        "[]",
        "1",
        '"text"',
        '{"pid": 123}',
        '{"exited": true}',
        '{"exited": true, "exited": false, "exitcode": 0}',
        '{"return": {"exited": true, "exitcode": 0, "out-data": "e30="}}',
    ],
)
def test_missing_completion_and_raw_rpc_wrappers_are_not_accepted(wire) -> None:
    assert parse_windows_metadata(wire).status == "error"


def test_ascii_json_survives_simulated_qga_pve_pipeline_and_bom() -> None:
    records = synthetic_metadata()
    records[0]["InterfaceAlias"] = '以太网 Adapter "A" 🖧'
    # PowerShell's fixed probe emits JSON whose non-ASCII UTF-16 code units are escaped.
    powershell_bytes = json.dumps({"addresses": records}, ensure_ascii=True).encode("ascii")
    qga_base64 = base64.b64encode(powershell_bytes)
    # PVE performs this step, not dnsleaf. Outer CLI output is UTF-8 JSON.
    pve_out_data = base64.b64decode(qga_base64).decode("ascii")
    pve_json_bytes = json.dumps(
        {"exited": 1, "exitcode": 0, "out-data": "\ufeff" + pve_out_data}
    ).encode("utf-8")
    parsed = parse_windows_metadata("\ufeff" + pve_json_bytes.decode("utf-8"))
    assert parsed.status == "ok"
    assert parsed.addresses[0].interface_alias == records[0]["InterfaceAlias"]
    # There is no heuristic second Base64 decode for out-data.
    encoded = json.dumps({"exited": 1, "exitcode": 0, "out-data": qga_base64.decode("ascii")})
    assert parse_windows_metadata(encoded).status == "error"


@pytest.mark.parametrize("timeout,pve_wait", [(30, "30"), (0.25, "1"), (1.5, "2")])
def test_fixed_encoded_command_has_finite_host_and_pve_deadlines(timeout, pve_wait) -> None:
    commands = SyntheticWindowsCommands()
    # User-controlled values exist only in returned data, never in executable source.
    commands.records[0]["InterfaceAlias"] = '$(Remove-Item something); " & injected'
    probe = WindowsMetadataProbe(runner=commands)
    result = probe.query(
        TargetRef(kind=TargetKind.VM, id=201), qm_bin="/test/qm", timeout_seconds=timeout
    )
    assert result.status == "ok"
    args = commands.calls[0]
    assert args[:9] == (
        "/test/qm",
        "guest",
        "exec",
        "201",
        "--synchronous",
        "1",
        "--timeout",
        pve_wait,
        "--",
    )
    assert args[9:13] == ("powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand")
    source = base64.b64decode(args[13]).decode("utf-16le")
    assert source == read_text(PROBE_RESOURCE)
    assert commands.records[0]["InterfaceAlias"] not in source
    assert "-ExecutionPolicy" not in args
    assert commands.timeouts == [timeout]


def test_host_subprocess_timeout_does_not_dump_script(monkeypatch) -> None:
    def expired(args, **kwargs):
        assert kwargs["timeout"] == 0.25
        assert "shell" not in kwargs
        raise subprocess.TimeoutExpired(args, kwargs["timeout"])

    monkeypatch.setattr("subprocess.run", expired)
    result = WindowsMetadataProbe(runner=run_command).query(
        TargetRef(kind=TargetKind.VM, id=201),
        qm_bin="qm",
        timeout_seconds=0.25,
    )
    assert result.error_stage == "execution"
    assert result.error and "Guest process may still be running" in result.error
    assert "EncodedCommand" not in result.error


def test_pve_wait_timeout_returns_pid_without_retry() -> None:
    commands = SyntheticWindowsCommands()
    commands.metadata_output = '{"pid": 123}'
    result = WindowsMetadataProbe(runner=commands).query(
        TargetRef(kind=TargetKind.VM, id=201),
        qm_bin="qm",
        timeout_seconds=1,
    )
    assert result.status == "error" and len(commands.calls) == 1


def test_disabled_exec_error_preserves_bounded_context_without_script() -> None:
    def disabled(args: Sequence[str], *, check: bool = True, timeout: float | None = None):
        return CommandResult(tuple(args), 1, "", "guest-exec unavailable " + args[-1] + "x" * 1000)

    result = WindowsMetadataProbe(runner=disabled).query(
        TargetRef(kind=TargetKind.VM, id=201),
        qm_bin="qm",
        timeout_seconds=1,
    )
    assert result.error_stage == "execution"
    assert result.error and "guest-exec unavailable" in result.error and len(result.error) < 500
    assert "[probe]" in result.error


def test_raw_execution_parsing_and_partial_parsing_remain_distinct() -> None:
    def response(output):
        def fake(args: Sequence[str], *, check: bool = True, timeout: float | None = None):
            return CommandResult(tuple(args), 0, output, "")

        return fake

    target = TargetRef(kind=TargetKind.VM, id=201)
    raw = PVEQGADiscoveryBackend(runner=response("{")).discover(target)
    assert raw.error_stage == "parsing"
    raw = PVEQGADiscoveryBackend(runner=response('[{"ip-addresses":[{}]}]')).discover(target)
    assert raw.ok and raw.parsing_issues and raw.candidates == []


def test_guest_exit_failure_reports_execution_stage_with_bounded_context() -> None:
    result = parse_windows_metadata(
        json.dumps(
            {
                "exited": 1,
                "exitcode": 1,
                "err-data": "CIM query failed " + "x" * 1000,
            }
        )
    )
    assert result.error_stage == "execution"
    assert result.error and "CIM query failed" in result.error and len(result.error) < 500


def test_undecodable_command_output_is_a_metadata_failure() -> None:
    def undecodable(args: Sequence[str], *, check: bool = True, timeout: float | None = None):
        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")

    result = WindowsMetadataProbe(runner=undecodable).query(
        TargetRef(kind=TargetKind.VM, id=201),
        qm_bin="qm",
        timeout_seconds=1,
    )
    assert result.error_stage == "execution" and result.error
    assert "could not be decoded" in result.error


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_nonstandard_json_constants_are_rejected_even_in_unused_fields(constant) -> None:
    output = metadata_wire(synthetic_metadata())
    output = output[:-1] + ', "pid": ' + constant + "}"
    result = parse_windows_metadata(output)
    assert result.status == "error" and "invalid JSON constant" in (result.error or "")
