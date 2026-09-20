"""The single current configuration and field-by-field strategy contract."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest
import yaml
from typer.testing import CliRunner

from dnsleaf.cli import app
from dnsleaf.config.strategy import SourceDefault, StrategyDefaults, resolve_strategy
from dnsleaf.models import IPAddressFamily
from dnsleaf.workspace.models import EntriesFile, WorkspaceConfig
from dnsleaf.workspace.renderer import WorkspaceRenderer
from dnsleaf.workspace.storage import WorkspaceLoadError, WorkspaceStorage, dump_yaml_data
from tests.fakes import FakeDNSProvider
from tests.sync.test_windows_dhcpv6_sync import make_runner, run
from tests.windows_fixtures import DHCP, SyntheticWindowsCommands


def group(**patch):
    return dict(
        source_kind="vm",
        source_ids=[201, 202],
        selection_policy="require-dhcpv6",
        evidence="windows-powershell",
        **patch,
    )


def dynamic(**patch):
    return (
        dict(
            name="node",
            source_kind="vm",
            source_id=201,
            family="ipv6",
            fqdn="node.example.com",
            enabled=True,
        )
        | patch
    )


def write_config(root, *, groups=None, entries=None):
    dump_yaml_data(root / "workspace.yaml", {"config_version": 5, "source_defaults": groups or []})
    dump_yaml_data(root / "entries.yaml", {"config_version": 3, "entries": entries or []})
    return WorkspaceStorage().load(root)


@pytest.mark.parametrize("filename,current", [("workspace.yaml", 5), ("entries.yaml", 3)])
@pytest.mark.parametrize("version", [None, 1, 2, 4, 99, True, False, "5", 5.0])
def test_external_versions_fail_before_execution_or_writes(
    workspace_dir, monkeypatch, filename, current, version
):
    document: dict[str, Any] = {"entries": []} if filename == "entries.yaml" else {}
    if version is not None:
        document["config_version"] = version
    path = workspace_dir / filename
    dump_yaml_data(path, document)
    before = {p: p.read_bytes() for p in workspace_dir.rglob("*") if p.is_file()}
    forbidden = Mock(side_effect=AssertionError("must fail before execution"))
    monkeypatch.setattr("dnsleaf.sync.runner.SyncRunner.run", forbidden)
    result = CliRunner().invoke(app, ["plan", "-w", str(workspace_dir), "--json"])
    assert result.exit_code != 0
    assert filename in result.output and f"config_version: {current}" in result.output
    assert not forbidden.called
    assert before == {p: p.read_bytes() for p in workspace_dir.rglob("*") if p.is_file()}


@pytest.mark.parametrize(
    "patch",
    [
        {"source_kind": "lxc"},
        {"source_ids": []},
        {"source_ids": [0]},
        {"source_ids": [-1]},
        {"source_ids": [True]},
        {"source_ids": ["201"]},
        {"source_ids": [201.0]},
        {"source_ids": [201, 201]},
        {"unknown": True},
        {"selection_policy": None, "evidence": None},
        {"selection_policy": ""},
        {"evidence": ""},
        {"selection_policy": "windows-dhcpv6"},
    ],
)
def test_invalid_source_groups(patch):
    with pytest.raises(ValueError):
        WorkspaceConfig.from_mapping({"config_version": 5, "source_defaults": [group() | patch]})


def test_overlapping_groups_even_identical_are_rejected():
    with pytest.raises(ValueError, match="overlap"):
        WorkspaceConfig.from_mapping({"config_version": 5, "source_defaults": [group(), group()]})


@pytest.mark.parametrize(
    "overrides,expected",
    [
        ({}, ("require-dhcpv6", "windows-powershell", "source_default", "source_default")),
        (
            {"selection_policy": None, "evidence": None},
            ("require-dhcpv6", "windows-powershell", "source_default", "source_default"),
        ),
        (
            {"selection_policy": "default"},
            ("default", "windows-powershell", "entry", "source_default"),
        ),
        (
            {"selection_policy": "default", "evidence": "none"},
            ("default", "none", "entry", "entry"),
        ),
    ],
)
def test_field_precedence_and_origins(workspace_dir, overrides, expected):
    loaded = write_config(workspace_dir, groups=[group()], entries=[dynamic(**overrides)])
    strategy = loaded.strategies["node"]
    assert (
        strategy.selection_policy,
        strategy.evidence,
        strategy.selection_policy_origin,
        strategy.evidence_origin,
    ) == expected


def test_partial_defaults_and_builtin_provenance(workspace_dir):
    for partial, override in [
        ({"selection_policy": "require-dhcpv6"}, {"evidence": "windows-powershell"}),
        (
            {"evidence": "none"},
            {"selection_policy": "require-dhcpv6", "evidence": "windows-powershell"},
        ),
    ]:
        loaded = write_config(
            workspace_dir,
            groups=[dict(source_kind="vm", source_ids=[201], **partial)],
            entries=[dynamic(**override)],
        )
        assert loaded.strategies["node"].requires_evidence
    loaded = write_config(workspace_dir, entries=[dynamic()])
    assert loaded.strategies["node"].model_dump() == dict(
        selection_policy="default",
        evidence="none",
        selection_policy_origin="built_in",
        evidence_origin="built_in",
    )
    # A declaration need not be effective until a consumer exists.
    write_config(
        workspace_dir,
        groups=[dict(source_kind="vm", source_ids=[201], selection_policy="require-dhcpv6")],
    )


@pytest.mark.parametrize(
    "patch", [{"evidence": "none"}, {"family": "ipv4"}, {"family": "ipv4", "enabled": False}]
)
def test_invalid_effective_consumers_including_disabled(workspace_dir, patch):
    with pytest.raises(WorkspaceLoadError, match="node.*requires"):
        write_config(workspace_dir, groups=[group()], entries=[dynamic(**patch)])


@pytest.mark.parametrize("kind", ["lxc", "local", "static"])
def test_evidence_only_vm_and_static_has_no_strategy(kind):
    entry = dynamic(source_kind=kind, evidence="windows-powershell")
    if kind != "lxc":
        entry.pop("source_id")
    if kind == "static":
        entry["static_ipv6"] = DHCP
    with pytest.raises(ValueError):
        EntriesFile.from_mapping({"config_version": 3, "entries": [entry]})


@pytest.mark.parametrize(
    "field,value",
    [
        ("selection_policy", "windows-dhcpv6"),
        ("selection_policy", ""),
        ("evidence", ""),
        ("evidence", "typo"),
    ],
)
def test_removed_unknown_and_empty_values_rejected_yaml_and_cli(workspace_dir, field, value):
    with pytest.raises(ValueError):
        EntriesFile.from_mapping({"config_version": 3, "entries": [dynamic(**{field: value})]})
    result = CliRunner().invoke(
        app,
        [
            "discover",
            "vm",
            "201",
            "-w",
            str(workspace_dir),
            "--" + field.replace("_", "-"),
            value,
            "--json",
        ],
    )
    assert result.exit_code != 0 and not result.stdout


def test_entry_inheritance_clear_and_atomic_failures(workspace_dir):
    write_config(workspace_dir, groups=[group()])
    runner = CliRunner()
    root = ["-w", str(workspace_dir)]
    path = workspace_dir / "entries.yaml"
    result = runner.invoke(
        app,
        [
            "entry",
            "add",
            "vm",
            "--id",
            "201",
            "--name",
            "node",
            "--fqdn",
            "node.example.com",
            "--family",
            "ipv6",
            *root,
        ],
    )
    assert result.exit_code == 0, result.output
    raw = yaml.safe_load(path.read_text())["entries"][0]
    assert "selection_policy" not in raw and "evidence" not in raw
    for patch in [
        ["--description", "new description"],
        ["--selection-policy", "default", "--evidence", "none"],
        ["--inherit-selection-policy", "--inherit-evidence"],
    ]:
        result = runner.invoke(app, ["entry", "update", "node", *root, *patch])
        assert result.exit_code == 0, result.output
    raw = yaml.safe_load(path.read_text())["entries"][0]
    assert "selection_policy" not in raw and "evidence" not in raw
    assert WorkspaceStorage().load(workspace_dir).strategies["node"].requires_evidence
    before = path.read_bytes()
    for patch in [
        ["--evidence", "none"],
        ["--family", "ipv4"],
        ["--selection-policy", "default", "--inherit-selection-policy"],
        ["--evidence", "none", "--inherit-evidence"],
    ]:
        result = runner.invoke(app, ["entry", "update", "node", *root, *patch])
        assert result.exit_code != 0 and path.read_bytes() == before


@pytest.mark.parametrize("inherited", [True, False])
def test_explicit_and_inherited_execution_and_render_share_resolved_strategy(
    workspace_dir, monkeypatch, inherited
):
    entry = (
        dynamic()
        if inherited
        else dynamic(selection_policy="require-dhcpv6", evidence="windows-powershell")
    )
    loaded = write_config(workspace_dir, groups=[group()] if inherited else [], entries=[entry])
    # The loading boundary has resolved once; operation and rendering must reuse it.
    monkeypatch.setattr(
        "dnsleaf.workspace.storage.resolve_entry_strategies",
        Mock(side_effect=AssertionError("resolved twice")),
    )
    commands = SyntheticWindowsCommands()
    outcome = run(make_runner(commands, FakeDNSProvider()), loaded).record_outcomes[0]
    assert outcome.selected_value == DHCP and len(commands.calls) == 2
    assert outcome.strategy is loaded.strategies["node"]
    artifacts = WorkspaceRenderer().render(loaded)
    record = json.loads(Path(artifacts.desired_records_file).read_text())["records"][0]
    assert record["strategy"] == loaded.strategies["node"].model_dump()


@pytest.mark.parametrize("case", ["unused", "disabled", "default", "ipv4"])
def test_permission_without_demand_never_probes(workspace_dir, case):
    entries = (
        []
        if case == "unused"
        else [
            dynamic(
                **(
                    {"enabled": False}
                    if case == "disabled"
                    else {
                        "selection_policy": "default",
                        "family": "ipv4" if case == "ipv4" else "ipv6",
                    }
                )
            )
        ]
    )
    loaded = write_config(workspace_dir, groups=[group()], entries=entries)
    commands = SyntheticWindowsCommands()
    run(make_runner(commands, FakeDNSProvider()), loaded)
    assert len(commands.calls) == (0 if case in {"unused", "disabled"} else 1)
    assert all(c[1] == "agent" for c in commands.calls)


@pytest.mark.parametrize("override", [False, True])
def test_discover_inherits_without_enrolling_or_calling_provider(
    workspace_dir, monkeypatch, override
):
    write_config(workspace_dir, groups=[group()], entries=[dynamic()])
    before = (workspace_dir / "entries.yaml").read_bytes()
    commands = SyntheticWindowsCommands()
    runner = make_runner(commands, FakeDNSProvider())
    runner._provider_factory = Mock(side_effect=AssertionError("discovery cannot call DNS"))
    monkeypatch.setattr("dnsleaf.commands.common.debug_runner", lambda ctx: runner)
    args = ["discover", "vm", "201", "-w", str(workspace_dir), "--family", "ipv6", "--json"]
    if override:
        args += ["--selection-policy", "default"]
    result = CliRunner().invoke(app, args)
    assert result.exit_code == int(override), result.output
    payload = json.loads(result.stdout)
    assert payload["strategy"]["selection_policy_origin"] == (
        "cli" if override else "source_default"
    )
    assert payload["enrollment"] == dict(
        local_entries_checked=True, matching_enabled_entries=["node"], dns_publication_checked=False
    )
    assert len(commands.calls) == (1 if override else 2)
    assert (workspace_dir / "entries.yaml").read_bytes() == before


def test_strategy_package_defaults_and_cli_origin(tmp_path):
    path = tmp_path / "strategy.json"
    path.write_text('{"evidence": "windows-powershell"}')
    assert StrategyDefaults.from_file(path) == StrategyDefaults.from_mapping(
        {"evidence": "windows-powershell"}
    )
    strategy = resolve_strategy(
        source_kind="vm",
        source_id=201,
        families=(IPAddressFamily.IPV6,),
        selection_policy="default",
        source_defaults=[SourceDefault.model_validate(group())],
        override_origin="cli",
        builtins=StrategyDefaults.from_defaults(),
    )
    assert strategy.selection_policy_origin == "cli" and not strategy.requires_evidence


def test_add_invalid_inherited_family_is_atomic(workspace_dir):
    write_config(workspace_dir, groups=[group()])
    path = workspace_dir / "entries.yaml"
    before = path.read_bytes()
    result = CliRunner().invoke(
        app,
        [
            "entry",
            "add",
            "vm",
            "--id",
            "201",
            "--name",
            "v4",
            "--fqdn",
            "v4.example.com",
            "--family",
            "ipv4",
            "-w",
            str(workspace_dir),
        ],
    )
    assert result.exit_code != 0 and "requires family" in result.output
    assert path.read_bytes() == before


def test_enable_after_invalid_default_change_never_writes(workspace_dir):
    write_config(workspace_dir, entries=[dynamic(family="ipv4", enabled=False)])
    path = workspace_dir / "entries.yaml"
    before = path.read_bytes()
    dump_yaml_data(
        workspace_dir / "workspace.yaml", {"config_version": 5, "source_defaults": [group()]}
    )
    for args in (["entry", "enable", "node"], ["status"], ["doctor"], ["render"]):
        result = CliRunner().invoke(app, [*args, "-w", str(workspace_dir)])
        assert result.exit_code != 0 and "requires family" in result.output
        assert path.read_bytes() == before
    assert not (workspace_dir / "rendered" / "desired-records.json").exists()
