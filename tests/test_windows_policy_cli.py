"""Public opt-in validation and JSON diagnostics, using only synthetic transports."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from dnsleaf.cli import app
from dnsleaf.discovery.models import AddressCandidate
from dnsleaf.discovery.pve_qga import PVEQGADiscoveryBackend
from dnsleaf.discovery.windows import WindowsMetadataProbe
from dnsleaf.models import IPAddressFamily
from dnsleaf.sync.runner import SyncRunner
from dnsleaf.workspace.models import EntriesFile
from dnsleaf.workspace.storage import WorkspaceStorage
from tests.fakes import FakeDNSProvider
from tests.windows_fixtures import DHCP, SyntheticWindowsCommands


@pytest.mark.parametrize("workspace", [False, True])
@pytest.mark.parametrize("case", ["ipv6", "both_private_ipv4", "both_metadata_failure", "default"])
def test_discover_policy_workspace_and_outside_json(
    workspace_dir, tmp_path, monkeypatch, workspace, case
):
    commands = SyntheticWindowsCommands()
    commands.raw.candidates.append(
        AddressCandidate(
            family=IPAddressFamily.IPV4,
            interface="Ethernet",
            prefix_length=24,
            source="pve_qga",
            address="8.8.8.8" if case == "both_metadata_failure" else "192.168.1.10",
        )
    )
    if case == "both_metadata_failure":
        commands.metadata_output = '{"pid": 123}'
    sync = SyncRunner(
        provider_factory=lambda _: FakeDNSProvider(),
        discovery_backends={"vm": PVEQGADiscoveryBackend(runner=commands)},
        windows_probe=WindowsMetadataProbe(runner=commands),
    )
    monkeypatch.setattr("dnsleaf.commands.common.debug_runner", lambda ctx: sync)
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.chdir(outside)
    args = [
        "discover",
        "vm",
        "201",
        "--json",
        "--family",
        "both" if case.startswith("both") else "ipv6",
    ]
    if case != "default":
        args += ["--selection-policy", "windows-dhcpv6"]
    if workspace:
        args += ["--workspace", str(workspace_dir)]
        (workspace_dir / "workspace.yaml").write_text(
            "paths:\n  qm_bin: /test/configured-qm\ndiscovery:\n  timeout_seconds: 0.25\n"
        )
    result = CliRunner().invoke(app, args)
    assert result.exit_code == (0 if case == "ipv6" else 1), result.output
    payload = json.loads(result.stdout)  # Exactly one JSON document, even on intentional exits.
    assert payload["backend"] == "pve_qga" and payload["error"] is None
    v6 = payload["selections"]["ipv6"]
    if case == "default":
        assert len(commands.calls) == 1 and v6["status"] == "ambiguous"
        assert "supplementary" not in v6
    else:
        assert len(commands.calls) == 2
        if workspace:
            assert commands.calls[1][0] == "/test/configured-qm"
            assert commands.timeouts[1] == 0.25
        if case == "both_metadata_failure":
            assert v6["supplementary"]["status"] == "error"
            assert payload["selections"]["ipv4"]["selected"]["address"] == "8.8.8.8"
        else:
            assert v6["selected"]["address"] == DHCP
            assert v6["supplementary"]["addresses"][0]["prefix_origin"] == "Dhcp"
            if case == "both_private_ipv4":
                assert payload["selections"]["ipv4"]["status"] == "no_candidate"
    assert "error:" not in result.stderr.lower()


@pytest.mark.parametrize("policy,family", [("typo", "ipv6"), ("windows-dhcpv6", "ipv4")])
def test_invalid_discover_policy_never_executes(workspace_dir, policy, family, monkeypatch):
    commands = SyntheticWindowsCommands()
    sync = SyncRunner(
        provider_factory=lambda _: FakeDNSProvider(),
        discovery_backends={"vm": PVEQGADiscoveryBackend(runner=commands)},
        windows_probe=WindowsMetadataProbe(runner=commands),
    )
    monkeypatch.setattr("dnsleaf.commands.common.debug_runner", lambda ctx: sync)
    result = CliRunner().invoke(
        app,
        [
            "discover",
            "vm",
            "201",
            "--workspace",
            str(workspace_dir),
            "--selection-policy",
            policy,
            "--family",
            family,
            "--json",
        ],
    )
    assert result.exit_code != 0 and commands.calls == []
    assert "policy" in result.output or "requires" in result.output


@pytest.mark.parametrize(
    "kind,family,policy",
    [
        ("lxc", "ipv6", "windows-dhcpv6"),
        ("local", "both", "windows-dhcpv6"),
        ("static", "ipv6", "windows-dhcpv6"),
        ("vm", "ipv4", "windows-dhcpv6"),
        ("vm", "ipv6", "typo"),
        ("lxc", "ipv4", "typo"),
    ],
)
def test_entries_reject_invalid_source_family_policy(kind, family, policy):
    entry = dict(
        name="test",
        source_kind=kind,
        family=family,
        fqdn="test.example.com",
        selection_policy=policy,
        enabled=True,
    )
    if kind in {"lxc", "vm"}:
        entry["source_id"] = 201
    if kind == "static":
        entry["static_ipv6"] = DHCP
    with pytest.raises(ValidationError, match="selection_policy|selection policy|requires"):
        EntriesFile.from_mapping({"entries": [entry]})


def test_entry_cli_policy_edits_and_collisions_are_atomic(workspace_dir):
    runner = CliRunner()
    workspace = ["--workspace", str(workspace_dir)]
    add = [
        "entry",
        "add",
        "vm",
        "--id",
        "201",
        "--fqdn",
        "windows.example.com",
        "--name",
        "windows",
        "--family",
        "ipv6",
        *workspace,
    ]
    result = runner.invoke(app, [*add, "--selection-policy", "windows-dhcpv6"])
    assert result.exit_code == 0, result.output
    path = workspace_dir / "entries.yaml"
    original = path.read_bytes()
    for patch in (["--family", "ipv4"], ["--selection-policy", "typo"]):
        result = runner.invoke(app, ["entry", "update", "windows", *workspace, *patch])
        assert result.exit_code != 0 and path.read_bytes() == original
    result = runner.invoke(
        app,
        [
            "entry",
            "add",
            "vm",
            "--id",
            "202",
            "--name",
            "collision",
            "--family",
            "ipv6",
            "--fqdn",
            "WINDOWS.EXAMPLE.COM.",
            "--selection-policy",
            "windows-dhcpv6",
            *workspace,
        ],
    )
    assert result.exit_code != 0 and path.read_bytes() == original
    for policy in ("default", "windows-dhcpv6"):
        result = runner.invoke(
            app, ["entry", "update", "windows", *workspace, "--selection-policy", policy]
        )
        assert result.exit_code == 0, result.output
        loaded = WorkspaceStorage().load(workspace_dir)
        assert loaded.entries_file.entries[0].selection_policy == policy
    result = runner.invoke(app, ["entry", "update", "windows", *workspace, "--family", "both"])
    assert result.exit_code == 0, result.output
